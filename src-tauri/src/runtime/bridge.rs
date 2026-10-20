use super::allowed_command;
use serde_json::{json, Value};
use std::{collections::HashMap, path::Path, sync::{Arc, atomic::{AtomicBool, Ordering}}, time::Duration};
use tokio::{io::{AsyncBufReadExt, AsyncWriteExt, BufReader}, process::{Child, ChildStdin, Command}, sync::{Mutex, oneshot}};

pub struct Bridge {
    input: Mutex<ChildStdin>,
    child: Mutex<Child>,
    pending: Arc<Mutex<HashMap<String, oneshot::Sender<Value>>>>,
    closed: Arc<AtomicBool>,
}

impl Bridge {
    pub async fn spawn(executable: &Path, args: &[String], cwd: Option<&Path>, emit: Arc<dyn Fn(Value) + Send + Sync>) -> Result<Self, String> {
        let mut command = Command::new(executable);
        command.args(args).stdin(std::process::Stdio::piped()).stdout(std::process::Stdio::piped()).stderr(std::process::Stdio::null()).kill_on_drop(true);
        if let Some(cwd) = cwd { command.current_dir(cwd); }
        #[cfg(windows)]
        { command.creation_flags(0x08000000); }
        let mut child = command.spawn().map_err(|e| format!("bridge-start: {e}"))?;
        let input = child.stdin.take().ok_or("bridge-stdin")?;
        let output = child.stdout.take().ok_or("bridge-stdout")?;
        let pending: Arc<Mutex<HashMap<String, oneshot::Sender<Value>>>> = Default::default();
        let closed = Arc::new(AtomicBool::new(false));
        let queue = pending.clone();
        let ended = closed.clone();
        tokio::spawn(async move {
            let mut reader = BufReader::new(output).lines();
            while let Ok(Some(line)) = reader.next_line().await {
                if line.len() > 16_000_000 { break; }
                if let Ok(value) = serde_json::from_str::<Value>(&line) {
                    if let Some(id) = value.get("id").and_then(Value::as_str) {
                        if let Some(sender) = queue.lock().await.remove(id) { let _ = sender.send(value); }
                    } else if value.get("event").is_some() { emit(value); }
                }
            }
            ended.store(true, Ordering::SeqCst);
            queue.lock().await.clear();
        });
        Ok(Self { input: Mutex::new(input), child: Mutex::new(child), pending, closed })
    }

    pub async fn request(&self, command: &str, payload: Value) -> Result<Value, String> {
        if !allowed_command(command) { return Err("unknown-command".into()); }
        if self.closed.load(Ordering::SeqCst) { return Err("bridge-closed".into()); }
        let id = uuid::Uuid::new_v4().to_string();
        let (sender, receiver) = oneshot::channel();
        self.pending.lock().await.insert(id.clone(), sender);
        let serialized = json!({"id":id,"command":command,"payload":payload}).to_string() + "\n";
        if serialized.len() > 16_000_000 { self.pending.lock().await.remove(&id); return Err("message-too-large".into()); }
        let write = self.input.lock().await.write_all(serialized.as_bytes()).await;
        if let Err(error) = write { self.pending.lock().await.remove(&id); return Err(error.to_string()); }
        let response = tokio::time::timeout(Duration::from_secs(30), receiver).await;
        self.pending.lock().await.remove(&id);
        let value = response.map_err(|_| "bridge-timeout")?.map_err(|_| "bridge-disconnected")?;
        if value["ok"].as_bool() == Some(true) { Ok(value["result"].clone()) }
        else { Err(value["error"]["message"].as_str().or(value["error"]["code"].as_str()).unwrap_or("runtime-error").to_string()) }
    }

    pub async fn shutdown(&self, deadline: Duration) {
        let _ = self.request("shutdown", json!({})).await;
        self.closed.store(true, Ordering::SeqCst);
        let mut child = self.child.lock().await;
        if tokio::time::timeout(deadline, child.wait()).await.is_err() { let _ = child.kill().await; }
        self.pending.lock().await.clear();
    }
}
