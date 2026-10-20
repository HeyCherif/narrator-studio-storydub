use narrator_studio::downloads::{ModelManifest, Integrity, ModelFile, verify_file};
use serde_json::json;
use tempfile::tempdir;

#[test]
fn pins_revision_and_rejects_missing_integrity() {
    let source = json!({"sha":"1111111111111111111111111111111111111111", "siblings":[{"rfilename":"config.json","size":5,"blobId":"b6fc4c620b67d95f953a5c1c1230aaab5db5a1b0"}]});
    let manifest = ModelManifest::from_api(&source).unwrap();
    assert_eq!(manifest.revision, "1111111111111111111111111111111111111111");
    assert!(ModelManifest::from_api(&json!({"sha":"main","siblings":[]})).is_err());
    assert!(ModelManifest::from_api(&json!({"sha":"1111111111111111111111111111111111111111","siblings":[{"rfilename":"config.json"}]})).is_err());
}

#[test]
fn rejects_traversal_and_absolute_paths() {
    for name in ["../weights.bin", "C:/weights.bin", "/weights.bin", "a\\b.bin", "a/../../weights.bin", "CON", "a//b", "a/./b", "a:stream"] {
        assert!(narrator_studio::downloads::validate_relative(name).is_err(), "{name}");
    }
    assert!(narrator_studio::downloads::validate_relative("tokenizer/config.json").is_ok());
}

#[test]
fn verifies_lfs_sha256_and_git_blob_header_hash() {
    let tmp = tempdir().unwrap();
    let file = tmp.path().join("sample");
    std::fs::write(&file,b"hello").unwrap();
    let mut spec = ModelFile{relative_path:"sample".into(),bytes:Some(5),integrity:Integrity::Sha256("2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824".into())};
    assert!(verify_file(&file,&spec).is_ok());
    spec.integrity=Integrity::GitBlobSha1("b6fc4c620b67d95f953a5c1c1230aaab5db5a1b0".into());
    assert!(verify_file(&file,&spec).is_ok());
    std::fs::write(&file,b"other").unwrap();
    assert!(verify_file(&file,&spec).is_err());
}
