use base64::Engine;
use std::fs;
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};
use std::sync::OnceLock;
use std::time::Instant;

// ============================ SUPERVISÃO NATIVA (Job Objects) ============================
// Regra definitiva do mantenedor (M1.6): TODO processo do jogo iniciado pelo launcher
// morre junto com ele — X, Alt+F4, Gerenciador de Tarefas ou crash. Implementado com
// um Windows Job Object com JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE de propriedade do
// processo principal do Tauri: quando o processo morre (de qualquer forma), o kernel
// fecha o handle e encerra a árvore inteira. Sem taskkill, sem nomes — só identidade
// (processos que nós mesmos criamos e associamos).
//
// Cobertura da árvore: cada processo Python da ponte é associado ao Job LOGO APÓS o
// spawn e ANTES de escrevermos o pedido no stdin — o monitor (e portanto run.py,
// gow3-probe e TODOS os filhos, inclusive reinícios via GOW3_RESTART_COMMAND) só
// nasce quando a ponte processa o pedido, ou seja, JÁ DENTRO do Job (filhos de um
// membro herdam o Job automaticamente). A associação não usa CREATE_SUSPENDED
// porque a sincronização é garantida pelo gating de stdin: a ponte não executa
// nada antes de receber o request, que só é escrito após AssignProcessToJobObject.
// Processos independentes (outros jogos, Pythons alheios, Explorer/Steam) nunca são
// associados e nunca são tocados.

/// Handle (como isize) do Job Object vitalício do launcher. Nunca é fechado em
/// tempo de vida: o kernel fecha quando o processo morre → KILL_ON_JOB_CLOSE.
static JOB: OnceLock<usize> = OnceLock::new();  // HANDLE (ponteiros não são Send/Sync)

fn job_handle() -> Result<windows_sys::Win32::Foundation::HANDLE, String> {
    if let Some(handle) = JOB.get() {
        return Ok(*handle as windows_sys::Win32::Foundation::HANDLE);
    }
    unsafe {
        let handle = windows_sys::Win32::System::JobObjects::CreateJobObjectW(
            std::ptr::null(), std::ptr::null());
        if handle.is_null() {
            return Err("CreateJobObjectW falhou".into());
        }
        let mut info: windows_sys::Win32::System::JobObjects::
            JOBOBJECT_EXTENDED_LIMIT_INFORMATION = std::mem::zeroed();
        info.BasicLimitInformation.LimitFlags =
            windows_sys::Win32::System::JobObjects::JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
        let ok = windows_sys::Win32::System::JobObjects::SetInformationJobObject(
            handle,
            windows_sys::Win32::System::JobObjects::JobObjectExtendedLimitInformation,
            &mut info as *mut _ as *mut core::ffi::c_void,
            std::mem::size_of::<
                windows_sys::Win32::System::JobObjects::JOBOBJECT_EXTENDED_LIMIT_INFORMATION>()
                as u32,
        );
        if ok == 0 {
            return Err("SetInformationJobObject (KILL_ON_JOB_CLOSE) falhou".into());
        }
        let _ = JOB.set(handle as usize);
        Ok(handle)
    }
}

fn assign_to_job(child: &std::process::Child) -> Result<(), String> {
    use std::os::windows::io::AsRawHandle;
    let job = job_handle()?;
    let ok = unsafe {
        windows_sys::Win32::System::JobObjects::AssignProcessToJobObject(
            job,
            child.as_raw_handle(),
        )
    };
    if ok == 0 {
        Err(format!("AssignProcessToJobObject falhou (erro {})",
                    unsafe { windows_sys::Win32::Foundation::GetLastError() }))
    } else {
        Ok(())
    }
}

// =============================== PONTE (AGORA ASSÍNCRONA) ================================
// P0 (travamento): bridge_call era síncrona e rodava NA THREAD PRINCIPAL do Tauri;
// a ponte Python valida o jogo e executa gow3-gpu-capabilities (segundos) — a
// janela congelava ("Não está respondendo"). Agora o trabalho bloqueante roda em
// spawn_blocking (pool dedicado) e o comando é async: a interface permanece
// responsiva durante TODA a inicialização. Durações instrumentadas via
// GOW3_CINEMATIC_TRACE=1 (sem poluição de log por padrão).

fn bridge_call_blocking(request: String) -> Result<String, String> {
    let began = Instant::now();
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
    // Associa a ponte ao Job ANTES de enviar o pedido (ver gating acima).
    if let Err(error) = assign_to_job(&child) {
        let _ = child.kill();
        let _ = child.wait();
        return Err(error);
    }
    use std::io::Write;
    if let Some(stdin) = child.stdin.as_mut() {
        stdin.write_all(request.as_bytes()).map_err(|e| format!("stdin: {e}"))?;
    }
    let output = child.wait_with_output().map_err(|e| format!("bridge: {e}"))?;
    let elapsed = began.elapsed().as_millis();
    if std::env::var("GOW3_CINEMATIC_TRACE").ok().as_deref() == Some("1") {
        eprintln!("[gow3-cinematic] bridge_call {} ms ({} bytes)", elapsed, request.len());
    }
    if output.stdout.is_empty() {
        return Err(format!(
            "bridge sem resposta: {}",
            String::from_utf8_lossy(&output.stderr).chars().take(400).collect::<String>()
        ));
    }
    Ok(String::from_utf8_lossy(&output.stdout).trim().to_string())
}

#[tauri::command]
async fn bridge_call(request: String) -> Result<String, String> {
    tauri::async_runtime::spawn_blocking(move || bridge_call_blocking(request))
        .await
        .map_err(|e| format!("task join: {e}"))?
}

/// The maintainer picks a FOLDER (game/update/mods/patches/saves) with the native dialog.
#[tauri::command]
async fn pick_folder(app: tauri::AppHandle) -> Option<String> {
    use tauri_plugin_dialog::DialogExt;
    let picked = app.dialog().file().blocking_pick_folder();
    picked
        .and_then(|path| path.into_path().ok())
        .map(|p| p.to_string_lossy().into_owned())
}

/// Opens a path in Windows Explorer (the port folder, gow3.ini, mods…).
#[tauri::command]
async fn open_in_explorer(path: String) -> Result<(), String> {
    tauri::async_runtime::spawn_blocking(move || -> Result<(), String> {
        Command::new("explorer").arg(&path).spawn().map_err(|e| format!("explorer: {e}"))?;
        Ok(())
    })
    .await
    .map_err(|e| format!("task join: {e}"))?
}

/// Reads the ambient MP3 as a data URL (bounded) so <audio> plays a local file
/// without granting the webview any filesystem scope. Async: ler ~6 MB na thread
/// principal também causava engasgos.
#[tauri::command]
async fn music_data_url(path: String) -> Result<Option<String>, String> {
    tauri::async_runtime::spawn_blocking(move || {
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
    })
    .await
    .map_err(|e| format!("task join: {e}"))?
}

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

#[allow(unused)]
fn _path_helper(_p: &Path) {}

// ============================ TESTES DE CICLO DE VIDA (M1.6 §3) ============================
// Fixtures descartáveis (python sleep), NUNCA o jogo real. Validam o mecanismo
// nativo do kernel do qual o launcher depende: KILL_ON_JOB_CLOSE mata a árvore
// quando o DONO do Job morre (simulando crash/Alt+F4/taskkill do launcher) e
// processos INDEPENDENTES fora do Job sobrevivem.

#[cfg(test)]
mod lifecycle_tests {
    use super::*;
    use std::process::{Command, Stdio};

    fn python() -> Command {
        let mut command = Command::new("python");
        command.stdin(Stdio::null()).stdout(Stdio::piped()).stderr(Stdio::null());
        command
    }

    fn pid_alive(pid: u32) -> bool {
        unsafe {
            let handle = windows_sys::Win32::System::Threading::OpenProcess(
                windows_sys::Win32::System::Threading::PROCESS_QUERY_LIMITED_INFORMATION,
                0, pid);
            if handle.is_null() { return false; }
            let mut code: u32 = 0;
            let ok = windows_sys::Win32::System::Threading::GetExitCodeProcess(
                handle, &mut code);
            windows_sys::Win32::Foundation::CloseHandle(handle);
            ok != 0 && code == 259 // STILL_ACTIVE
        }
    }

    fn kill_hard(pid: u32) {
        unsafe {
            let handle = windows_sys::Win32::System::Threading::OpenProcess(
                windows_sys::Win32::System::Threading::PROCESS_TERMINATE, 0, pid);
            if !handle.is_null() {
                windows_sys::Win32::System::Threading::TerminateProcess(handle, 1);
                windows_sys::Win32::Foundation::CloseHandle(handle);
            }
        }
    }

    /// Helper "launcher de brinquedo": cria o PRÓPRIO Job (kill-on-close, como o nosso),
    /// associa a si mesmo, gera um FILHO sleep e imprime o pid do filho — simula a
    /// árvore launcher→ponte→monitor→jogo sem tocar em nada real.
    const SUPERVISOR_HELPER: &str = r#"
import ctypes, subprocess, sys, time
import ctypes.wintypes as wt
k32 = ctypes.windll.kernel32
job = k32.CreateJobObjectW(None, None)
class IO(ctypes.Structure):
    _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64),
                ("PerJobUserTimeLimit", ctypes.c_int64),
                ("LimitFlags", ctypes.c_uint32), ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", ctypes.c_uint32),
                ("Affinity", ctypes.c_void_p), ("PriorityClass", ctypes.c_uint32),
                ("SchedulingClass", ctypes.c_uint32)]
class XI(ctypes.Structure):
    _fields_ = [("BasicLimitInformation", IO), ("IoInfo", ctypes.c_int64*6),
                ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t)]
info = XI(); info.BasicLimitInformation.LimitFlags = 0x2000  # KILL_ON_JOB_CLOSE
rc = k32.SetInformationJobObject(job, 9, ctypes.byref(info), ctypes.sizeof(XI))
child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
# espelha o launcher: associa o FILHO recem-criado (handle aberto por pid)
import os
ch = k32.OpenProcess(0x0100 | 0x0001, 0, child.pid)  # PROCESS_SET_QUOTA | PROCESS_TERMINATE
arc = k32.AssignProcessToJobObject(job, ch)
k32.CloseHandle(ch)
with open(os.environ["GOW3_TEST_OUT"], "w") as f:
    f.write(str(child.pid) if (rc == 1 and arc != 0) else "SETFAIL rc=%d arc=%d err=%d" % (rc, arc, k32.GetLastError()))
if rc != 1 or arc == 0:
    child.kill(); sys.exit(3)
time.sleep(60)
"#;

    #[test]
    fn force_killed_owner_kills_whole_tree_no_orphans() {
        let out = std::env::temp_dir().join(format!("gow3-job-test-{}.pid", std::process::id()));
        let mut supervisor = python();
        supervisor.arg("-c").arg(SUPERVISOR_HELPER)
            .env("GOW3_TEST_OUT", &out)
            .stderr(Stdio::null());
        let mut child = supervisor.spawn().expect("helper");
        let mut grandchild: u32 = 0;
        for _ in 0..100 {
            std::thread::sleep(std::time::Duration::from_millis(50));
            if let Ok(text) = fs::read_to_string(&out) {
                if let Ok(pid) = text.trim().parse::<u32>() { grandchild = pid; break; }
            }
        }
        assert!(grandchild != 0, "helper deve reportar o pid do neto");
        assert!(pid_alive(grandchild), "neto deve estar vivo antes do kill");
        kill_hard(child.id()); // encerramento FORÇADO do "launcher" (taskkill /F)
        let _ = child.wait();
        std::thread::sleep(std::time::Duration::from_millis(800));
        assert!(!pid_alive(grandchild),
                "neto deve morrer com o dono do Job (KILL_ON_JOB_CLOSE) — sem órfãos");
    }

    #[test]
    fn independent_process_survives_job_owner_death() {
        let mut outsider = python();
        outsider.arg("-c").arg("import time; time.sleep(60)");
        let mut outsider = outsider.spawn().expect("forasteiro");
        // um Job qualquer nasce e MORRE (handle fechado pelo processo-teste ao sair do escopo)
        {
            let _guard = job_handle().unwrap();
            // nada a fazer: apenas garantir que criar o Job do launcher não afeta ninguém
        }
        // agora um dono de Job morre: o forasteiro NÃO pode ser afetado
        let out = std::env::temp_dir().join(format!("gow3-job-test2-{}.pid", std::process::id()));
        let mut supervisor = python();
        supervisor.arg("-c").arg(SUPERVISOR_HELPER)
            .env("GOW3_TEST_OUT", &out)
            .stderr(Stdio::null());
        let mut child = supervisor.spawn().expect("helper");
        let mut grandchild: u32 = 0;
        for _ in 0..100 {
            std::thread::sleep(std::time::Duration::from_millis(50));
            if let Ok(text) = fs::read_to_string(&out) {
                if let Ok(pid) = text.trim().parse::<u32>() { grandchild = pid; break; }
            }
        }
        assert!(grandchild != 0);
        kill_hard(child.id());
        let _ = child.wait();
        std::thread::sleep(std::time::Duration::from_millis(500));
        assert!(!pid_alive(grandchild));
        assert!(pid_alive(outsider.id()), "processo INDEPENDENTE deve sobreviver");
        kill_hard(outsider.id());
        let _ = outsider.wait();
    }

    #[test]
    fn bridge_processes_can_be_assigned_and_job_is_created() {
        // o Job vitalício do launcher cria e associa processos python descartáveis
        let mut probe = python();
        probe.arg("-c").arg("import time; time.sleep(30)");
        let mut child = probe.spawn().expect("probe");
        assign_to_job(&child).expect("associação ao Job deve funcionar");
        kill_hard(child.id());
        let _ = child.wait();
    }
}

