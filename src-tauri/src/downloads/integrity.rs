use super::{ModelFile,Integrity};
use sha2::{Sha256,Digest};
use sha1::Sha1;
use std::{path::Path,fs::File,io::{Read,BufReader}};

pub fn verify_file(path:&Path,spec:&ModelFile)->Result<(),String>{
    let file=File::open(path).map_err(|e|e.to_string())?;
    let size=file.metadata().map_err(|e|e.to_string())?.len();
    if spec.bytes.is_some_and(|expected|expected!=size){return Err("size-mismatch".into());}
    let mut reader=BufReader::new(file);
    let mut sha256=Sha256::new();
    let mut sha1=Sha1::new();
    sha1.update(format!("blob {size}\0").as_bytes());
    let mut buffer=[0u8;64*1024];
    loop {let count=reader.read(&mut buffer).map_err(|e|e.to_string())?;if count==0{break;}sha256.update(&buffer[..count]);sha1.update(&buffer[..count]);}
    let (actual,expected)=match &spec.integrity {Integrity::Sha256(expected)=>(hex::encode(sha256.finalize()),expected),Integrity::GitBlobSha1(expected)=>(hex::encode(sha1.finalize()),expected)};
    if actual!=expected.to_lowercase(){return Err("checksum-mismatch".into());}
    Ok(())
}
