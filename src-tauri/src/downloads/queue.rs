use super::{resolve_manifest,transfer_file,TransferControl,ModelManifest};
use super::transfer::atomic_json;
use serde::{Serialize,Deserialize};
use std::{path::PathBuf,sync::{Arc,Mutex},time::{Duration,Instant}};
#[derive(Clone,Serialize,Deserialize)]pub struct DownloadSnapshot{pub id:String,pub model:String,pub state:String,pub bytes_done:u64,pub total_bytes:Option<u64>,pub speed_bps:Option<f64>,pub eta_seconds:Option<u64>,pub error:Option<String>}
struct Inner{snapshot:Option<DownloadSnapshot>,control:TransferControl,active:bool}
pub struct DownloadManager{root:PathBuf,record:PathBuf,inner:Mutex<Inner>,emit:Arc<dyn Fn(Vec<DownloadSnapshot>)+Send+Sync>}
impl DownloadManager{
 pub fn new(root:PathBuf,record:PathBuf,emit:Arc<dyn Fn(Vec<DownloadSnapshot>)+Send+Sync>)->Arc<Self>{let snapshot=std::fs::read(&record).ok().and_then(|v|serde_json::from_slice::<DownloadSnapshot>(&v).ok()).map(|mut s|{if !["ready","cancelled","error"].contains(&s.state.as_str()){s.state="paused".into();}s.speed_bps=None;s.eta_seconds=None;s});Arc::new(Self{root,record,inner:Mutex::new(Inner{snapshot,control:TransferControl::default(),active:false}),emit})}
 pub fn snapshot(&self)->Vec<DownloadSnapshot>{self.inner.lock().unwrap().snapshot.clone().into_iter().collect()}
 fn update(&self,apply:impl FnOnce(&mut DownloadSnapshot)){let values={let mut inner=self.inner.lock().unwrap();if let Some(s)=inner.snapshot.as_mut(){apply(s);if let Some(parent)=self.record.parent(){let _=std::fs::create_dir_all(parent);}let _=atomic_json(&self.record,s);}inner.snapshot.clone().into_iter().collect()};(self.emit)(values);}
 pub fn stop(&self,cancel:bool){let inner=self.inner.lock().unwrap();if cancel{inner.control.cancel()}else{inner.control.pause()}}
 pub fn action(self:&Arc<Self>,action:&str,id:Option<&str>)->Result<(),String>{
  if !["enqueue","resume","retry","pause","cancel"].contains(&action){return Err("invalid-download-action".into());}
  {let inner=self.inner.lock().unwrap();if let Some(id)=id{if inner.snapshot.as_ref().map(|s|s.id.as_str())!=Some(id){return Err("unknown-download".into());}}}
  if action=="pause"||action=="cancel"{self.stop(action=="cancel");let active=self.inner.lock().unwrap().active;if !active{self.update(|s|{s.state=if action=="pause"{"paused"}else{"cancelled"}.into();s.speed_bps=None;s.eta_seconds=None;});}return Ok(());}
  {let mut inner=self.inner.lock().unwrap();if inner.active{return Err("download-already-active".into());}if action!="enqueue"&&inner.snapshot.is_none(){return Err("unknown-download".into());}inner.active=true;inner.control=TransferControl::default();if inner.snapshot.is_none(){inner.snapshot=Some(DownloadSnapshot{id:uuid::Uuid::new_v4().to_string(),model:"Qwen3-TTS-12Hz-0.6B-Base".into(),state:"queued".into(),bytes_done:0,total_bytes:None,speed_bps:None,eta_seconds:None,error:None});}}
  let manager=self.clone();tokio::spawn(async move{manager.update(|s|{s.state="preparing".into();s.error=None;s.speed_bps=None;s.eta_seconds=None;});let result=manager.run().await;manager.inner.lock().unwrap().active=false;manager.update(|s|{s.speed_bps=None;s.eta_seconds=None;match result{Ok(())=>s.state="ready".into(),Err(ref e)if e=="paused"||e=="cancelled"=>s.state=e.clone(),Err(ref e)=>{s.state="error".into();s.error=Some(e.clone());}}});});Ok(())
 }
 async fn run(self:&Arc<Self>)->Result<(),String>{
  let manifest=resolve_manifest().await?;let root=self.root.join("models/Qwen3-TTS-12Hz-0.6B-Base");std::fs::create_dir_all(&root).map_err(|e|e.to_string())?;
  let pinned=root.join(".narrator-manifest.json");if let Ok(bytes)=std::fs::read(&pinned){if let Ok(old)=serde_json::from_slice::<ModelManifest>(&bytes){if old.revision!=manifest.revision{self.update(|s|s.bytes_done=0);}}}atomic_json(&pinned,&manifest)?;
  let total=manifest.files.iter().try_fold(0u64,|sum,f|f.bytes.and_then(|size|sum.checked_add(size)));self.update(|s|{s.total_bytes=total;s.state="downloading".into();});
  let client=reqwest::Client::builder().https_only(true).connect_timeout(Duration::from_secs(20)).read_timeout(Duration::from_secs(60)).build().map_err(|e|e.to_string())?;
  let control=self.inner.lock().unwrap().control.clone();let mut complete=0u64;
  for file in &manifest.files{control.status()?;let url=format!("https://huggingface.co/{}/resolve/{}/{}",manifest.repo,manifest.revision,file.relative_path);let manager=self.clone();let base=complete;let started=Instant::now();let measurement=Arc::new(Mutex::new((Instant::now()-Duration::from_secs(1),None::<u64>)));let meter=measurement.clone();transfer_file(&client,&url,&root,file,&manifest.revision,&control,Arc::new(move|n|{let mut last=meter.lock().unwrap();let initial=*last.1.get_or_insert(n);if last.0.elapsed()>Duration::from_millis(250){last.0=Instant::now();let elapsed=started.elapsed().as_secs_f64();let speed=if elapsed>2.0{Some(n.saturating_sub(initial)as f64/elapsed)}else{None};manager.update(|s|{s.bytes_done=base+n;s.speed_bps=speed;s.eta_seconds=match(s.total_bytes,speed){(Some(total),Some(speed))if speed>0.0=>Some((total.saturating_sub(base+n)as f64/speed)as u64),_=>None};});}})).await?;complete+=std::fs::metadata(root.join(&file.relative_path)).map_err(|e|e.to_string())?.len();self.update(|s|s.bytes_done=complete);}
  self.update(|s|s.state="verifying".into());for file in &manifest.files{control.status()?;super::verify_file(&root.join(&file.relative_path),file)?;}Ok(())
 }
}
