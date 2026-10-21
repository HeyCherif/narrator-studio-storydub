use narrator_studio::runtime::{allowed_command, resolve_audio};
use tempfile::tempdir;

#[test]
fn rejects_unknown_commands() {
    assert!(!allowed_command("__getattribute__"));
    assert!(!allowed_command("shell"));
    assert!(allowed_command("bootstrap"));
    assert!(allowed_command("cancel_generate"));
}

#[test]
fn rejects_foreign_output_paths() {
    let root = tempdir().unwrap();
    std::fs::create_dir(root.path().join("history")).unwrap();
    std::fs::write(root.path().join("history/test.wav"), b"RIFF").unwrap();
    assert!(resolve_audio(root.path(), "test.wav").is_ok());
    for path in [
        "../test.wav",
        "..\\test.wav",
        "C:\\private.wav",
        "/private.wav",
        "missing.wav",
    ] {
        assert!(resolve_audio(root.path(), path).is_err(), "{path}");
    }
}
