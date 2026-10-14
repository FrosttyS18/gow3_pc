use base64::Engine;
use std::fs;
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};

/// Locates launcher/cinematic/bridge/launcher_bridge.py by walking up from the
/// executable and the working directory (dev: target/release; test build: repo tree).
fn bridge_path() -> Result<PathBuf, String> {
    if let Ok(from_env) = std::env::var("GOW3_CINEMATIC_BRIDGE") {
        let path = PathBuf::from(from_env);
        if path.is_file() {
            return Ok(path);
        }
    }
    let mut roots: Vec<PathBuf> = Vec::new();
    if let Ok(exe) = std::env::current_exe() {
        roots.extend(exe.ancestors().map(Path::to_path_buf));
    }
    if let Ok(cwd) = std::env::current_dir() {
        roots.extend(cwd.ancestors().map(Path::to_path_buf));
    }
    for root in roots {
        for launcher in ["launcher/cinematic/bridge/launcher_bridge.py", "cinematic/bridge/launcher_bridge.py"] {
            let candidate = root.join(launcher);
            if candidate.is_file() {
                return Ok(candidate);
            }
        }
    }
    Err("launcher_bridge.py não encontrado (defina GOW3_CINEMATIC_BRIDGE)".into())
}

/// One JSON request in, one JSON response out — every port rule stays in Python.
/// The child runs with UTF-8 pipes (PYTHONIOENCODING) so '·', 'ã', 'ç' survive the trip.
#[tauri::command]
fn bridge_call(request: String) -> Result<String, String> {
    let bridge = bridge_path()?;
    let port_dir = bridge
        .ancestors()
        .nth(3)
        .ok_or("port directory not resolvable")?
        .to_path_buf();
    let mut child = Command::new("python")
        .arg(&bridge)
        .current_dir(port_dir)
        .env("PYTHONIOENCODING", "utf-8")
        .env("PYTHONUTF8", "1")
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .map_err(|e| format!("python não pôde iniciar: {e}"))?;
    use std::io::Write;
    if let Some(stdin) = child.stdin.as_mut() {
        stdin
            .write_all(request.as_bytes())
            .map_err(|e| format!("stdin: {e}"))?;
    }
    let output = child
        .wait_with_output()
        .map_err(|e| format!("bridge: {e}"))?;
    if output.stdout.is_empty() {
        return Err(format!(
            "bridge sem resposta: {}",
            String::from_utf8_lossy(&output.stderr).chars().take(400).collect::<String>()
        ));
    }
    Ok(String::from_utf8_lossy(&output.stdout).trim().to_string())
}

/// The maintainer picks a FOLDER (game/update/mods/patches/saves) with the native dialog.
#[tauri::command]
async fn pick_folder(app: tauri::AppHandle) -> Option<String> {
    use tauri_plugin_dialog::DialogExt;
    let (sender, receiver) = std::sync::mpsc::channel::<Option<String>>();
    let picked = app.dialog().file().blocking_pick_folder();
    picked
        .and_then(|path| path.into_path().ok())
        .map(|p| p.to_string_lossy().into_owned())
}

/// Opens a path in Windows Explorer (the port folder, gow3.ini, mods…).
#[tauri::command]
fn open_in_explorer(path: String) -> Result<(), String> {
    Command::new("explorer")
        .arg(&path)
        .spawn()
        .map_err(|e| format!("explorer: {e}"))?;
    Ok(())
}

/// Reads the ambient MP3 as a data URL (bounded) so <audio> plays a local file
/// without granting the webview any filesystem scope.
#[tauri::command]
fn music_data_url(path: String) -> Result<Option<String>, String> {
    let path = PathBuf::from(path);
    if path.extension().and_then(|e| e.to_str()).map(|e| e.eq_ignore_ascii_case("mp3")) != Some(true) {
        return Ok(None);
    }
    let bytes = fs::read(&path).map_err(|e| format!("leitura do arquivo: {e}"))?;
    if bytes.len() > 48 * 1024 * 1024 {
        return Err("arquivo muito grande (limite 48 MB)".into());
    }
    let encoded = base64::engine::general_purpose::STANDARD.encode(&bytes);
    Ok(Some(format!("data:audio/mpeg;base64,{encoded}")))
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .invoke_handler(tauri::generate_handler![
            bridge_call,
            pick_folder,
            open_in_explorer,
            music_data_url
        ])
        .run(tauri::generate_context!())
        .expect("erro ao executar o launcher cinematográfico");
}
