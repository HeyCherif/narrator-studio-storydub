use crate::{runtime::{Bridge,resolve_audio},downloads::{DownloadManager,DownloadSnapshot}};
use serde_json::{Value,json};
use std::{path::{Path,PathBuf},sync::{Arc,Mutex},time::Duration};
use tauri::{Manager,Emitter,State};
use tauri_plugin_dialog::DialogExt;
use tauri_plugin_opener::OpenerExt;
struct DesktopState{root:Mutex<PathBuf>,settings:PathBuf,bridge:tokio::sync::Mutex<Option<Bridge>>,downloads:Mutex<Arc<DownloadManager>>}
async fn request(app:&tauri::AppHandle,state:&DesktopState,command:&str,payload:Value)->Result<Value,String>{
 let mut bridge=state.bridge.lock().await;
 if bridge.is_none(){let root=state.root.lock().unwrap().clone();let exe=std::env::current_exe().map_err(|e|e.to_string())?.parent().ok_or("executable-path")?.join("narrator-bridge.exe");let app=app.clone();let emit=Arc::new(move|value:Value|{let _=app.emit("runtime:event",value);});
  #[cfg(debug_assertions)]let (exe,args,cwd)=if exe.exists(){(exe,vec!["--library".into(),root.to_string_lossy().into_owned()],None)}else{let cwd=PathBuf::from(env!("CARGO_MANIFEST_DIR")).parent().unwrap().to_path_buf();(PathBuf::from("python"),vec!["-m".into(),"backend.bridge".into(),"--library".into(),root.to_string_lossy().into_owned()],Some(cwd))};
  #[cfg(not(debug_assertions))]let (exe,args,cwd)=(exe,vec!["--library".into(),root.to_string_lossy().into_owned()],None::<PathBuf>);
  *bridge=Some(Bridge::spawn(&exe,&args,cwd.as_deref(),emit).await?);
 }
 bridge.as_ref().unwrap().request(command,payload).await
}
#[tauri::command]async fn runtime_request(app:tauri::AppHandle,state:State<'_,DesktopState>,command:String,payload:Value)->Result<Value,String>{request(&app,&state,&command,payload).await}
#[tauri::command]fn audio_path(app:tauri::AppHandle,state:State<'_,DesktopState>,filename:String)->Result<String,String>{let path=resolve_audio(&state.root.lock().unwrap(),&filename)?;app.asset_protocol_scope().allow_file(&path).map_err(|e|e.to_string())?;Ok(path.to_string_lossy().into_owned())}
#[tauri::command]async fn export_audio(app:tauri::AppHandle,state:State<'_,DesktopState>,filename:String)->Result<bool,String>{let path=resolve_audio(&state.root.lock().unwrap(),&filename)?;let destination=app.dialog().file().set_file_name(&filename).blocking_save_file();if let Some(dest)=destination{let dest=dest.into_path().map_err(|e|e.to_string())?;tokio::fs::copy(path,dest).await.map_err(|e|e.to_string())?;Ok(true)}else{Ok(false)}}
#[tauri::command]fn open_history_folder(app:tauri::AppHandle,state:State<'_,DesktopState>)->Result<(),String>{let root=state.root.lock().unwrap().join("history");std::fs::create_dir_all(&root).map_err(|e|e.to_string())?;app.opener().open_path(root.to_string_lossy(),None::<&str>).map_err(|e|e.to_string())}
#[tauri::command]async fn choose_path(app:tauri::AppHandle,kind:String)->Result<Option<String>,String>{let selected=match kind.as_str(){"runtime_python"|"qwen_runtime_python"|"qc_runtime_python"=>app.dialog().file().add_filter("Python",&["exe"]).blocking_pick_file(),"model_path"|"qwen_model_path"|"qc_model_path"=>app.dialog().file().blocking_pick_folder(),_=>return Err("invalid-path-kind".into())};selected.map(|v|v.into_path().map(|p|p.to_string_lossy().into_owned()).map_err(|e|e.to_string())).transpose()}
fn manager(app:&tauri::AppHandle,root:PathBuf,settings:&Path)->Arc<DownloadManager>{let handle=app.clone();DownloadManager::new(root,settings.with_file_name("downloads.json"),Arc::new(move|values|{let _=handle.emit("downloads:changed",values);}))}
#[tauri::command]async fn adopt_library(app:tauri::AppHandle,state:State<'_,DesktopState>)->Result<bool,String>{
 let values=request(&app,&state,"bootstrap",json!({})).await?;if values["job"]["running"]==true{return Err("operation-in-progress".into());}
 if state.downloads.lock().unwrap().snapshot().iter().any(|s|["preparing","downloading","verifying"].contains(&s.state.as_str())){return Err("download-in-progress".into());}
 let Some(folder)=app.dialog().file().blocking_pick_folder()else{return Ok(false)};let root=folder.into_path().map_err(|e|e.to_string())?.canonicalize().map_err(|e|e.to_string())?;
 for(name,object)in[("config.json",true),("history.json",false)]{let file=root.join(name);if file.exists(){let value:Value=serde_json::from_slice(&std::fs::read(&file).map_err(|e|e.to_string())?).map_err(|e|e.to_string())?;if if object{!value.is_object()}else{!value.is_array()}{return Err(format!("invalid-library-{name}"));}}}
 let confirmed=app.dialog().message("Utiliser cette bibliothèque ? Les petits index seront sauvegardés. Aucun modèle ni audio ne sera déplacé. / Use this library? Indexes will be backed up; models and audio stay in place.").title("Narrator Studio").buttons(tauri_plugin_dialog::MessageDialogButtons::OkCancel).blocking_show();if !confirmed{return Ok(false);}
 let backup=root.join(".narrator-backups").join(uuid::Uuid::new_v4().to_string());std::fs::create_dir_all(&backup).map_err(|e|e.to_string())?;for name in ["config.json","history.json"]{if root.join(name).is_file(){std::fs::copy(root.join(name),backup.join(name)).map_err(|e|e.to_string())?;}}
 if let Some(bridge)=state.bridge.lock().await.take(){bridge.shutdown(Duration::from_secs(5)).await;}
 let temp=state.settings.with_extension("tmp");std::fs::write(&temp,json!({"schema_version":1,"library_root":root}).to_string()).map_err(|e|e.to_string())?;std::fs::rename(temp,&state.settings).map_err(|e|e.to_string())?;
 *state.root.lock().unwrap()=root.clone();*state.downloads.lock().unwrap()=manager(&app,root,&state.settings);Ok(true)
}
#[tauri::command]fn download_snapshot(state:State<'_,DesktopState>)->Vec<DownloadSnapshot>{state.downloads.lock().unwrap().snapshot()}
#[tauri::command]fn download_action(state:State<'_,DesktopState>,action:String,id:Option<String>)->Result<(),String>{state.downloads.lock().unwrap().action(&action,id.as_deref())}
pub fn run(){
 let app=tauri::Builder::default().plugin(tauri_plugin_single_instance::init(|app,_,_|{if let Some(window)=app.get_webview_window("main"){let _=window.show();let _=window.set_focus();}})).plugin(tauri_plugin_dialog::init()).plugin(tauri_plugin_opener::init())
 .setup(|app|{let data=app.path().app_data_dir()?;std::fs::create_dir_all(&data)?;let settings=data.join("settings.json");let saved:Value=std::fs::read(&settings).ok().and_then(|b|serde_json::from_slice(&b).ok()).unwrap_or_default();let root=std::env::var_os("NARRATOR_LIBRARY").map(PathBuf::from).or_else(||saved["library_root"].as_str().map(PathBuf::from)).unwrap_or_else(||data.join("library"));std::fs::create_dir_all(&root)?;let downloads=manager(app.handle(),root.clone(),&settings);app.manage(DesktopState{root:Mutex::new(root),settings,bridge:tokio::sync::Mutex::new(None),downloads:Mutex::new(downloads)});Ok(())})
 .invoke_handler(tauri::generate_handler![runtime_request,audio_path,export_audio,open_history_folder,choose_path,adopt_library,download_snapshot,download_action]).build(tauri::generate_context!()).expect("Unable to start Narrator Studio");
 app.run(|handle,event|{if let tauri::RunEvent::ExitRequested{..}=event{let state=handle.state::<DesktopState>();state.downloads.lock().unwrap().stop(false);tauri::async_runtime::block_on(async{if let Some(bridge)=state.bridge.lock().await.take(){bridge.shutdown(Duration::from_secs(5)).await;}});}});
}
