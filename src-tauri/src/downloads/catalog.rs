use super::ModelManifest;
use serde_json::Value;
use std::time::Duration;

pub async fn resolve_manifest()->Result<ModelManifest,String>{
    let client=reqwest::Client::builder().timeout(Duration::from_secs(40)).https_only(true).user_agent("NarratorStudio/2.0").build().map_err(|e|e.to_string())?;
    let value=client.get("https://huggingface.co/api/models/Qwen/Qwen3-TTS-12Hz-0.6B-Base/revision/main?blobs=true").send().await.map_err(|e|e.to_string())?.error_for_status().map_err(|e|e.to_string())?.json::<Value>().await.map_err(|e|e.to_string())?;
    let manifest=ModelManifest::from_api(&value)?;
    if !manifest.files.iter().any(|f|f.relative_path=="config.json") || !manifest.files.iter().any(|f|f.relative_path.ends_with(".safetensors")){return Err("incomplete-model-manifest".into());}
    Ok(manifest)
}
