use super::{validate_relative, verify_file, ModelFile};
use futures_util::StreamExt;
use std::{
    path::{Path, PathBuf},
    sync::{
        atomic::{AtomicU8, Ordering},
        Arc,
    },
};
use tokio::io::AsyncWriteExt;
#[derive(Clone, Default)]
pub struct TransferControl(Arc<AtomicU8>);
impl TransferControl {
    pub fn pause(&self) {
        self.0.store(1, Ordering::SeqCst);
    }
    pub fn cancel(&self) {
        self.0.store(2, Ordering::SeqCst);
    }
    pub fn status(&self) -> Result<(), String> {
        match self.0.load(Ordering::SeqCst) {
            1 => Err("paused".into()),
            2 => Err("cancelled".into()),
            _ => Ok(()),
        }
    }
}
pub fn atomic_json(path: &Path, value: &impl serde::Serialize) -> Result<(), String> {
    let temp = path.with_extension(format!("{}.tmp", uuid::Uuid::new_v4()));
    std::fs::write(
        &temp,
        serde_json::to_vec_pretty(value).map_err(|e| e.to_string())?,
    )
    .map_err(|e| e.to_string())?;
    let file = std::fs::OpenOptions::new()
        .write(true)
        .open(&temp)
        .map_err(|e| e.to_string())?;
    file.sync_all().map_err(|e| e.to_string())?;
    drop(file);
    std::fs::rename(temp, path).map_err(|e| e.to_string())
}
pub fn safe_target(root: &Path, name: &str) -> Result<PathBuf, String> {
    validate_relative(name)?;
    std::fs::create_dir_all(root).map_err(|e| e.to_string())?;
    let root = root.canonicalize().map_err(|e| e.to_string())?;
    let mut parent = root.clone();
    let parts: Vec<_> = name.split('/').collect();
    for part in &parts[..parts.len() - 1] {
        parent.push(part);
        if parent.exists() {
            if std::fs::symlink_metadata(&parent)
                .map_err(|e| e.to_string())?
                .file_type()
                .is_symlink()
            {
                return Err("model-symlink".into());
            }
        } else {
            std::fs::create_dir(&parent).map_err(|e| e.to_string())?;
        }
        if !parent
            .canonicalize()
            .map_err(|e| e.to_string())?
            .starts_with(&root)
        {
            return Err("model-path-escape".into());
        }
    }
    let target = parent.join(parts.last().unwrap());
    for path in [
        target.clone(),
        PathBuf::from(format!("{}.part", target.display())),
        PathBuf::from(format!("{}.part.json", target.display())),
    ] {
        if path.exists()
            && std::fs::symlink_metadata(path)
                .map_err(|e| e.to_string())?
                .file_type()
                .is_symlink()
        {
            return Err("model-symlink".into());
        }
    }
    Ok(target)
}
pub async fn transfer_file(
    client: &reqwest::Client,
    url: &str,
    root: &Path,
    spec: &ModelFile,
    revision: &str,
    control: &TransferControl,
    progress: Arc<dyn Fn(u64) + Send + Sync>,
) -> Result<(), String> {
    control.status()?;
    let target = safe_target(root, &spec.relative_path)?;
    if target.is_file() && verify_file(&target, spec).is_ok() {
        progress(target.metadata().map_err(|e| e.to_string())?.len());
        return Ok(());
    }
    let part = PathBuf::from(format!("{}.part", target.display()));
    let metadata = PathBuf::from(format!("{}.part.json", target.display()));
    let previous: serde_json::Value = std::fs::read(&metadata)
        .ok()
        .and_then(|b| serde_json::from_slice(&b).ok())
        .unwrap_or_default();
    let mut offset = if previous["revision"] == revision {
        std::fs::metadata(&part).map(|m| m.len()).unwrap_or(0)
    } else {
        0
    };
    if offset > spec.bytes.unwrap_or(u64::MAX) {
        offset = 0;
    }
    if spec.bytes == Some(offset) && offset > 0 {
        if verify_file(&part, spec).is_ok() {
            tokio::fs::rename(&part, &target)
                .await
                .map_err(|e| e.to_string())?;
            let _ = tokio::fs::remove_file(&metadata).await;
            progress(offset);
            return Ok(());
        }
        offset = 0;
    }
    if let Some(total) = spec.bytes {
        if fs2::available_space(root).map_err(|e| e.to_string())?
            < total
                .saturating_sub(offset)
                .saturating_add(16 * 1024 * 1024)
        {
            return Err("insufficient-disk-space".into());
        }
    }
    atomic_json(&metadata, &serde_json::json!({"revision":revision}))?;
    let mut request = client.get(url);
    if offset > 0 {
        request = request.header(reqwest::header::RANGE, format!("bytes={offset}-"));
    }
    let response = tokio::select! {result=request.send()=>result.map_err(|e|e.to_string())?,_=async{loop{if control.status().is_err(){break;}tokio::time::sleep(std::time::Duration::from_millis(100)).await;}}=>return control.status()};
    let status = response.status();
    if !status.is_success() {
        return Err(format!("download-http-{status}"));
    }
    if offset > 0 && status == reqwest::StatusCode::PARTIAL_CONTENT {
        let expected = format!("bytes {offset}-");
        if !response
            .headers()
            .get(reqwest::header::CONTENT_RANGE)
            .and_then(|s| s.to_str().ok())
            .is_some_and(|s| s.starts_with(&expected))
        {
            return Err("invalid-content-range".into());
        }
    } else {
        offset = 0;
    }
    let mut file = tokio::fs::OpenOptions::new()
        .create(true)
        .write(true)
        .append(offset > 0)
        .truncate(offset == 0)
        .open(&part)
        .await
        .map_err(|e| e.to_string())?;
    let mut stream = response.bytes_stream();
    let mut received = offset;
    progress(received);
    loop {
        control.status()?;
        let next = tokio::select! {chunk=stream.next()=>chunk,_=tokio::time::sleep(std::time::Duration::from_millis(100))=>continue};
        match next {
            Some(chunk) => {
                let chunk = chunk.map_err(|e| e.to_string())?;
                file.write_all(&chunk).await.map_err(|e| e.to_string())?;
                received += chunk.len() as u64;
                if spec.bytes.is_some_and(|size| received > size) {
                    return Err("size-overflow".into());
                }
                progress(received);
            }
            None => break,
        }
    }
    file.flush().await.map_err(|e| e.to_string())?;
    file.sync_all().await.map_err(|e| e.to_string())?;
    drop(file);
    control.status()?;
    verify_file(&part, spec)?;
    tokio::fs::rename(&part, &target)
        .await
        .map_err(|e| e.to_string())?;
    let _ = tokio::fs::remove_file(metadata).await;
    Ok(())
}
