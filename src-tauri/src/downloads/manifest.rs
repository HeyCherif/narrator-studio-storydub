use serde::{Deserialize, Serialize};
use serde_json::Value;

pub const QWEN_REPO: &str = "Qwen/Qwen3-TTS-12Hz-0.6B-Base";
#[derive(Clone, Debug, Serialize, Deserialize)]
pub enum Integrity {
    Sha256(String),
    GitBlobSha1(String),
}
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct ModelFile {
    pub relative_path: String,
    pub bytes: Option<u64>,
    pub integrity: Integrity,
}
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct ModelManifest {
    pub repo: String,
    pub revision: String,
    pub files: Vec<ModelFile>,
}

pub fn validate_relative(name: &str) -> Result<(), String> {
    if name.is_empty() || name.starts_with('/') || name.contains(['\\', ':', '\0', '?', '#']) {
        return Err("invalid-model-path".into());
    }
    for part in name.split('/') {
        let stem = part.split('.').next().unwrap_or("").to_uppercase();
        if part.is_empty()
            || part == "."
            || part == ".."
            || part.ends_with([' ', '.'])
            || [
                "CON", "PRN", "AUX", "NUL", "COM1", "COM2", "COM3", "COM4", "COM5", "COM6", "COM7",
                "COM8", "COM9", "LPT1", "LPT2", "LPT3", "LPT4", "LPT5", "LPT6", "LPT7", "LPT8",
                "LPT9",
            ]
            .contains(&stem.as_str())
        {
            return Err("invalid-model-path".into());
        }
    }
    Ok(())
}

impl ModelManifest {
    pub fn from_api(value: &Value) -> Result<Self, String> {
        let revision = value["sha"].as_str().ok_or("missing-revision")?;
        if revision.len() != 40 || !revision.bytes().all(|b| b.is_ascii_hexdigit()) {
            return Err("unpinned-revision".into());
        }
        let siblings = value["siblings"].as_array().ok_or("missing-files")?;
        let mut files = Vec::new();
        let mut seen = std::collections::HashSet::new();
        for item in siblings {
            let name = item["rfilename"].as_str().ok_or("invalid-file")?;
            validate_relative(name)?;
            if !seen.insert(name.to_lowercase()) {
                return Err("duplicate-model-path".into());
            }
            if name == ".gitattributes" || name.ends_with(".md") {
                continue;
            }
            let (integrity, size) = if let Some(sha) = item["lfs"]["sha256"].as_str() {
                if sha.len() != 64 || !sha.bytes().all(|b| b.is_ascii_hexdigit()) {
                    return Err("invalid-sha256".into());
                }
                (
                    Integrity::Sha256(sha.to_lowercase()),
                    item["lfs"]["size"].as_u64().or(item["size"].as_u64()),
                )
            } else if let Some(blob) = item["blobId"].as_str() {
                if blob.len() != 40 || !blob.bytes().all(|b| b.is_ascii_hexdigit()) {
                    return Err("invalid-blob-id".into());
                }
                (
                    Integrity::GitBlobSha1(blob.to_lowercase()),
                    item["size"].as_u64(),
                )
            } else {
                return Err(format!("missing-integrity: {name}"));
            };
            files.push(ModelFile {
                relative_path: name.into(),
                bytes: size,
                integrity,
            });
        }
        if files.is_empty() {
            return Err("empty-manifest".into());
        }
        Ok(Self {
            repo: QWEN_REPO.into(),
            revision: revision.into(),
            files,
        })
    }
}
