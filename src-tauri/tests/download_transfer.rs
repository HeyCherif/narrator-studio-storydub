use narrator_studio::downloads::{transfer_file, Integrity, ModelFile, TransferControl};
use std::{
    io::{Read, Write},
    net::TcpListener,
    sync::{Arc, Mutex},
};
#[tokio::test]
async fn resume_sends_range_and_appends_only_matching_content() {
    let dir = tempfile::tempdir().unwrap();
    std::fs::write(dir.path().join("config.json.part"), b"he").unwrap();
    std::fs::write(
        dir.path().join("config.json.part.json"),
        r#"{"revision":"revision"}"#,
    )
    .unwrap();
    let socket = TcpListener::bind("127.0.0.1:0").unwrap();
    let address = socket.local_addr().unwrap();
    let server = std::thread::spawn(move || {
        let (mut stream, _) = socket.accept().unwrap();
        let mut request = [0u8; 4096];
        let n = stream.read(&mut request).unwrap();
        assert!(String::from_utf8_lossy(&request[..n])
            .to_lowercase()
            .contains("range: bytes=2-"));
        stream.write_all(b"HTTP/1.1 206 Partial Content\r\nContent-Range: bytes 2-4/5\r\nContent-Length: 3\r\nConnection: close\r\n\r\nllo").unwrap();
    });
    transfer_file(
        &reqwest::Client::new(),
        &format!("http://{address}/file"),
        dir.path(),
        &file(),
        "revision",
        &TransferControl::default(),
        Arc::new(|_| {}),
    )
    .await
    .unwrap();
    server.join().unwrap();
    assert_eq!(
        std::fs::read(dir.path().join("config.json")).unwrap(),
        b"hello"
    );
}

#[tokio::test]
async fn insufficient_space_prevents_any_http_transfer() {
    let dir = tempfile::tempdir().unwrap();
    let mut spec = file();
    spec.bytes = Some(u64::MAX);
    let error = transfer_file(
        &reqwest::Client::new(),
        "http://127.0.0.1:1",
        dir.path(),
        &spec,
        "revision",
        &TransferControl::default(),
        Arc::new(|_| {}),
    )
    .await
    .unwrap_err();
    assert_eq!(error, "insufficient-disk-space");
}

#[tokio::test]
async fn pause_flushes_partial_and_complete_valid_partial_promotes_without_network() {
    let dir = tempfile::tempdir().unwrap();
    let control = TransferControl::default();
    let trigger = control.clone();
    let error = transfer_file(
        &reqwest::Client::new(),
        &server(b"hello", "200 OK"),
        dir.path(),
        &file(),
        "revision",
        &control,
        Arc::new(move |n| {
            if n > 0 {
                trigger.pause();
            }
        }),
    )
    .await
    .unwrap_err();
    assert_eq!(error, "paused");
    assert_eq!(
        std::fs::read(dir.path().join("config.json.part")).unwrap(),
        b"hello"
    );
    transfer_file(
        &reqwest::Client::new(),
        "http://127.0.0.1:1",
        dir.path(),
        &file(),
        "revision",
        &TransferControl::default(),
        Arc::new(|_| {}),
    )
    .await
    .unwrap();
    assert_eq!(
        std::fs::read(dir.path().join("config.json")).unwrap(),
        b"hello"
    );
}

#[tokio::test]
async fn one_active_download_is_enforced() {
    let dir = tempfile::tempdir().unwrap();
    let manager = narrator_studio::downloads::DownloadManager::new(
        dir.path().into(),
        dir.path().join("queue.json"),
        Arc::new(|_| {}),
    );
    manager.action("enqueue", None).unwrap();
    assert_eq!(
        manager.action("enqueue", None).unwrap_err(),
        "download-already-active"
    );
    manager.stop(true);
}

fn file() -> ModelFile {
    ModelFile {
        relative_path: "config.json".into(),
        bytes: Some(5),
        integrity: Integrity::Sha256(
            "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824".into(),
        ),
    }
}
fn server(body: &'static [u8], status: &'static str) -> String {
    let socket = TcpListener::bind("127.0.0.1:0").unwrap();
    let address = socket.local_addr().unwrap();
    std::thread::spawn(move || {
        let (mut stream, _) = socket.accept().unwrap();
        let mut request = [0u8; 4096];
        let _ = stream.read(&mut request);
        write!(
            stream,
            "HTTP/1.1 {status}\r\nContent-Length: {}\r\nConnection: close\r\n\r\n",
            body.len()
        )
        .unwrap();
        stream.write_all(body).unwrap();
    });
    format!("http://{address}/file")
}
#[tokio::test]
async fn progress_uses_received_bytes_and_verifies() {
    let dir = tempfile::tempdir().unwrap();
    let seen = Arc::new(Mutex::new(Vec::new()));
    let copy = seen.clone();
    transfer_file(
        &reqwest::Client::new(),
        &server(b"hello", "200 OK"),
        dir.path(),
        &file(),
        "revision",
        &TransferControl::default(),
        Arc::new(move |n| copy.lock().unwrap().push(n)),
    )
    .await
    .unwrap();
    assert_eq!(
        std::fs::read(dir.path().join("config.json")).unwrap(),
        b"hello"
    );
    assert_eq!(seen.lock().unwrap().last(), Some(&5));
}
#[tokio::test]
async fn checksum_failure_never_marks_ready() {
    let dir = tempfile::tempdir().unwrap();
    assert_eq!(
        transfer_file(
            &reqwest::Client::new(),
            &server(b"wrong", "200 OK"),
            dir.path(),
            &file(),
            "revision",
            &TransferControl::default(),
            Arc::new(|_| {})
        )
        .await
        .unwrap_err(),
        "checksum-mismatch"
    );
    assert!(!dir.path().join("config.json").exists());
}
#[tokio::test]
async fn range_ignored_restarts_without_append() {
    let dir = tempfile::tempdir().unwrap();
    std::fs::write(dir.path().join("config.json.part"), b"he").unwrap();
    std::fs::write(
        dir.path().join("config.json.part.json"),
        r#"{"revision":"revision"}"#,
    )
    .unwrap();
    transfer_file(
        &reqwest::Client::new(),
        &server(b"hello", "200 OK"),
        dir.path(),
        &file(),
        "revision",
        &TransferControl::default(),
        Arc::new(|_| {}),
    )
    .await
    .unwrap();
    assert_eq!(
        std::fs::read(dir.path().join("config.json")).unwrap(),
        b"hello"
    );
}
#[tokio::test]
async fn cancel_preserves_partial() {
    let dir = tempfile::tempdir().unwrap();
    let control = TransferControl::default();
    control.pause();
    assert_eq!(
        transfer_file(
            &reqwest::Client::new(),
            "http://127.0.0.1:1",
            dir.path(),
            &file(),
            "revision",
            &control,
            Arc::new(|_| {})
        )
        .await
        .unwrap_err(),
        "paused"
    );
}
#[tokio::test]
async fn corrupt_complete_partial_retries_from_zero() {
    let dir = tempfile::tempdir().unwrap();
    std::fs::write(dir.path().join("config.json.part"), b"wrong").unwrap();
    std::fs::write(
        dir.path().join("config.json.part.json"),
        r#"{"revision":"revision"}"#,
    )
    .unwrap();
    let socket = TcpListener::bind("127.0.0.1:0").unwrap();
    let address = socket.local_addr().unwrap();
    let server = std::thread::spawn(move || {
        let (mut stream, _) = socket.accept().unwrap();
        let mut request = [0u8; 4096];
        let n = stream.read(&mut request).unwrap();
        let range = String::from_utf8_lossy(&request[..n])
            .to_lowercase()
            .contains("range:");
        let response = if range {
            "HTTP/1.1 416 Range Not Satisfiable\r\nContent-Length: 0\r\nConnection: close\r\n\r\n"
        } else {
            "HTTP/1.1 200 OK\r\nContent-Length: 5\r\nConnection: close\r\n\r\nhello"
        };
        stream.write_all(response.as_bytes()).unwrap();
    });
    let result = transfer_file(
        &reqwest::Client::new(),
        &format!("http://{address}/file"),
        dir.path(),
        &file(),
        "revision",
        &TransferControl::default(),
        Arc::new(|_| {}),
    )
    .await;
    server.join().unwrap();
    result.unwrap();
    assert_eq!(
        std::fs::read(dir.path().join("config.json")).unwrap(),
        b"hello"
    );
}
