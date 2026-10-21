pub mod bridge;
pub use bridge::Bridge;
use std::path::{Path, PathBuf};

pub fn allowed_command(command: &str) -> bool {
    matches!(
        command,
        "bootstrap"
            | "set_engine"
            | "generate"
            | "cancel_generate"
            | "voices"
            | "clone_voice"
            | "history"
            | "configure"
            | "shutdown"
    )
}

pub fn resolve_audio(root: &Path, name: &str) -> Result<PathBuf, String> {
    if name.is_empty() || name.contains(['/', '\\', ':']) {
        return Err("invalid-audio-id".into());
    }
    let directory = root
        .join("history")
        .canonicalize()
        .map_err(|_| "audio-folder-missing")?;
    let file = directory
        .join(name)
        .canonicalize()
        .map_err(|_| "audio-missing")?;
    if file.parent() != Some(directory.as_path()) || !file.is_file() {
        return Err("invalid-audio-path".into());
    }
    let extension = file
        .extension()
        .and_then(|s| s.to_str())
        .unwrap_or("")
        .to_lowercase();
    if !["wav", "mp3", "flac", "ogg", "m4a"].contains(&extension.as_str()) {
        return Err("not-audio".into());
    }
    Ok(file)
}
