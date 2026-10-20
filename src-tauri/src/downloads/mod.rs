mod manifest;
mod integrity;
mod catalog;
pub use manifest::{ModelManifest, ModelFile, Integrity, validate_relative};
pub use integrity::verify_file;
pub use catalog::resolve_manifest;
