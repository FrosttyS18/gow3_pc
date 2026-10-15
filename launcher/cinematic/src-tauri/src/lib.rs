use base64::Engine;
use std::collections::HashMap;
use std::fs;
use std::io::{BufRead, BufReader, Write};
use std::os::windows::process::CommandExt;
use std::path::{Path, PathBuf};
use std::process::{ChildStdin, Command, Stdio};
use std::sync::mpsc::{channel, Sender};
use std::sync::{Arc, Mutex, OnceLock};
use std::time::{Duration, Instant};

/// CREATE_NO_WINDOW: nenhum processo de console criado pelo launcher abre janela.
const CREATE_NO_WINDOW: u32 = 0x0800_0000;

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

/// Verdadeiro quando o launcher conseguiu se AUTO-associar ao próprio Job: todo
/// processo criado pelo Rust já nasce dentro dele (herança na CRIAÇÃO — sem
/// corrida). Falso quando o shell já o impõe outro Job: a adesão explícita por
/// filho acontece então dentro da janela SUSPENSA do spawn da sessão.
static JOB_SELF_ASSIGNED: OnceLock<bool> = OnceLock::new();

fn job_self_assigned() -> bool {
    // job_handle() preenche na primeira criação; default false se ainda não rolou.
    *JOB_SELF_ASSIGNED.get().unwrap_or(&false)
}

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
        // Auto-adesão (quando possível): sendo o launcher MEMBRO do próprio Job, todo
        // processo que o Rust criar nasce DENTRO dele por herança — janela de corrida
        // zero na adesão. Falha silenciosa se o launcher já estiver no Job de um shell
        // (não pode pertencer a dois), e então vale a adesão por filho na janela
        // SUSPENSA do spawn (ver spawn_game_session_inner).
        let self_process = windows_sys::Win32::System::Threading::GetCurrentProcess();
        let self_ok = windows_sys::Win32::System::JobObjects::AssignProcessToJobObject(
            handle, self_process);
        let _ = JOB_SELF_ASSIGNED.set(self_ok != 0);
        let _ = JOB.set(handle as usize);
        Ok(handle)
    }
}

fn assign_to_job(child: &std::process::Child) -> Result<(), String> {
    let job = job_handle()?;
    assign_process_to(job, child)
}

fn assign_process_to(job: windows_sys::Win32::Foundation::HANDLE,
                     child: &std::process::Child) -> Result<(), String> {
    use std::os::windows::io::AsRawHandle;
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

// ======================= PONTE PERSISTENTE (HOTFIX P0) =======================
// ANTES: cada operação da ponte iniciava um python.exe novo (e o React consultava
// play_status a cada 1,5 s enquanto o jogo rodava — dezenas de processos por minuto,
// cada um abrindo uma janela de console). AGORA: UM worker Python por launcher atende
// TODAS as operações por uma conexão stdin/stdout com envelopes {"seq","req"} →
// {"seq","resp"} (serialização natural: o worker atende um pedido por vez, então
// escritas de settings.json/gow3.ini nunca correm entre si). O worker é associado ao
// Job ANTES do primeiro pedido (mesmo gating de stdin da M1.6), fica OCIOSO bloqueado
// na leitura quando não há pedidos e morre junto com o launcher (Job). Recuperação
// LIMITADA: se cair, renasce na próxima chamada, no máximo 3 vezes por minuto — após
// isso a ponte recusa até o launcher reiniciar (sem loops de reinicialização).
// Modo single-shot preservado sem GOW3_BRIDGE_PERSISTENT=1 (testes e compat).

struct WorkerHandle {
    stdin: ChildStdin,
    next_seq: u64,
    generation: u64,
    #[cfg_attr(not(test), allow(dead_code))] // lido apenas por testes/diagnóstico
    pid: u32,
    pending: Arc<Mutex<HashMap<u64, Sender<String>>>>,
}

struct WorkerSlot {
    worker: Option<WorkerHandle>,
    generation: u64,
    restarts: Vec<Instant>,
    broken: Option<String>,
    stderr_tail: Arc<Mutex<String>>,
}

static WORKER: OnceLock<Mutex<WorkerSlot>> = OnceLock::new();

fn worker_slot() -> &'static Mutex<WorkerSlot> {
    WORKER.get_or_init(|| Mutex::new(WorkerSlot {
        worker: None,
        generation: 0,
        restarts: Vec::new(),
        broken: None,
        stderr_tail: Arc::new(Mutex::new(String::new())),
    }))
}

fn spawn_worker(slot_generation: u64, stderr_tail: &Arc<Mutex<String>>)
                -> Result<WorkerHandle, String> {
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
        .env("PYTHONUNBUFFERED", "1")
        .env("GOW3_BRIDGE_PERSISTENT", "1")
        .creation_flags(CREATE_NO_WINDOW)
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .map_err(|e| format!("python não pôde iniciar: {e}"))?;
    // Associa ao Job ANTES de qualquer pedido (gating por stdin: o worker só age
    // depois de ler a primeira linha, que só é escrita após esta adesão).
    if let Err(error) = assign_to_job(&child) {
        let _ = child.kill();
        let _ = child.wait();
        return Err(error);
    }
    let stdin = child.stdin.take()
        .ok_or("stdin do worker indisponível")?;
    let stdout = child.stdout.take()
        .ok_or("stdout do worker indisponível")?;
    let stderr = child.stderr.take();
    let pending: Arc<Mutex<HashMap<u64, Sender<String>>>> =
        Arc::new(Mutex::new(HashMap::new()));
    let reader_pending = Arc::clone(&pending);
    // Leitor: despacha respostas pelo seq; no EOF marca o worker morto (limitado).
    std::thread::spawn(move || {
        let reader = BufReader::new(stdout);
        for line in reader.lines() {
            let line = match line {
                Ok(line) => line,
                Err(_) => break,
            };
            if let Ok(envelope) = serde_json::from_str::<serde_json::Value>(&line) {
                if let Some(seq) = envelope.get("seq").and_then(|v| v.as_u64()) {
                    if let Some(sender) = reader_pending.lock().unwrap().remove(&seq) {
                        let _ = sender.send(envelope.get("resp").cloned()
                            .unwrap_or(serde_json::Value::Null).to_string());
                    }
                }
            }
        }
        // Worker morreu: falha todos os pendentes e registra a queda para a política
        // de recuperação limitada. Guard de geração para não derrubar um worker NOVO.
        let mut slot = worker_slot().lock().unwrap();
        for (_seq, sender) in reader_pending.lock().unwrap().drain() {
            let _ = sender.send(String::from("{\"error\":\"worker encerrou\"}"));
        }
        if slot.generation == slot_generation {
            slot.worker = None;
            slot.restarts.push(Instant::now());
        }
    });
    if let Some(stderr) = stderr {
        let tail = Arc::clone(stderr_tail);
        std::thread::spawn(move || {
            let mut buffer = BufReader::new(stderr).lines();
            while let Some(Ok(line)) = buffer.next() {
                let mut tail = tail.lock().unwrap();
                tail.push_str(&line);
                tail.push('\n');
                let length = tail.len();
                if length > 4096 {
                    let cut = length - 4096;
                    *tail = tail[cut.max(tail.len() - tail.chars().rev().take_while(|c| (*c as u32) < 0x80).count())..].to_string();
                }
            }
        });
    }
    Ok(WorkerHandle {
        stdin,
        next_seq: 1,
        generation: slot_generation,
        pid: child.id(),
        pending,
    })
}

/// PID do worker vivo (para testes e diagnóstico); 0 se não há worker.
#[cfg(test)]
fn worker_pid_for_tests() -> u32 {
    worker_slot().lock().unwrap().worker.as_ref().map(|w| w.pid).unwrap_or(0)
}

/// Encerra o worker da geração indicada (usado no timeout: um worker vivo mas mudo
/// não pode ficar preso com pedidos pendurados). O leitor registra a queda e a
/// política de recuperação limitada passa a valer.
fn kill_current_worker(generation: u64) {
    let slot = worker_slot();
    let mut guard = slot.lock().unwrap();
    if let Some(worker) = guard.worker.take() {
        if worker.generation == generation {
            unsafe {
                let handle = windows_sys::Win32::System::Threading::OpenProcess(
                    windows_sys::Win32::System::Threading::PROCESS_TERMINATE, 0, worker.pid);
                if !handle.is_null() {
                    windows_sys::Win32::System::Threading::TerminateProcess(handle, 1);
                    windows_sys::Win32::Foundation::CloseHandle(handle);
                }
            }
            drop(worker); // fecha stdin: o leitor detecta o EOF e registra a queda
        } else {
            guard.worker = Some(worker); // outro worker já nasceu: não mexe
        }
    }
}

/// Uma chamada completa à ponte pelo worker persistente (renascendo se preciso).
fn bridge_roundtrip_blocking(request: &str) -> Result<String, String> {
    let began = Instant::now();
    let parsed: serde_json::Value = serde_json::from_str(request)
        .map_err(|e| format!("pedido inválido: {e}"))?;
    let mut attempts = 0;
    loop {
        attempts += 1;
        if attempts > 4 {
            return Err("worker da ponte não respondeu após reinícios limitados".into());
        }
        let (receiver, generation) = {
            let mut slot = worker_slot().lock().unwrap();
            if let Some(reason) = slot.broken.clone() {
                return Err(reason);
            }
            if slot.worker.is_none() {
                slot.restarts.retain(|at| at.elapsed() < Duration::from_secs(60));
                if slot.restarts.len() >= 3 {
                    let reason = "worker da ponte caiu 3× no último minuto — \
                                  reinicie o launcher (sem loops de reinicialização)".to_string();
                    slot.broken = Some(reason.clone());
                    return Err(reason);
                }
                slot.generation += 1;
                let generation = slot.generation;
                let stderr_tail = Arc::clone(&slot.stderr_tail);
                match spawn_worker(generation, &stderr_tail) {
                    Ok(worker) => slot.worker = Some(worker),
                    Err(error) => {
                        return Err(format!("{error}{}", {
                            let tail = stderr_tail.lock().unwrap().clone();
                            if tail.is_empty() { String::new() }
                            else { format!(" — stderr: {}", tail.chars().rev().take(400).collect::<String>().chars().rev().collect::<String>()) }
                        }));
                    }
                }
            }
            let handle = slot.worker.as_mut().unwrap();
            let seq = handle.next_seq;
            handle.next_seq += 1;
            let (sender, receiver) = channel();
            handle.pending.lock().unwrap().insert(seq, sender);
            let envelope = serde_json::json!({"seq": seq, "req": parsed});
            let mut line = envelope.to_string();
            line.push('\n');
            if handle.stdin.write_all(line.as_bytes()).is_err()
                || handle.stdin.flush().is_err() {
                handle.pending.lock().unwrap().remove(&seq);
                slot.worker = None; // morto no meio do envio: o leitor registra a queda
                continue;
            }
            (receiver, handle.generation)
        };
        // Espera COM PRAZO: um worker vivo mas mudo (ex.: travado em I/O) não pode
        // prender a chamada para sempre. Vencido o prazo, o worker é ENCERRADO e a
        // chamada falha — NUNCA é repetida automaticamente: o pedido pode já ter
        // sido aplicado (set_ini/set_app têm efeito em arquivo), repetir seria
        // duplicar efeitos ou corromper preferências. Quem decide repetir é o usuário.
        let timeout = Duration::from_millis(
            std::env::var("GOW3_BRIDGE_TIMEOUT_MS").ok()
                .and_then(|v| v.parse().ok()).unwrap_or(120_000));
        match receiver.recv_timeout(timeout) {
            Ok(response) => {
                let elapsed = began.elapsed().as_millis();
                if std::env::var("GOW3_CINEMATIC_TRACE").ok().as_deref() == Some("1") {
                    eprintln!("[gow3-cinematic] bridge_roundtrip {} ms", elapsed);
                }
                return Ok(response);
            }
            Err(std::sync::mpsc::RecvTimeoutError::Timeout) => {
                kill_current_worker(generation);
                return Err(format!(
                    "worker da ponte não respondeu em {} ms — chamada descartada sem \
                     repetição (operação pode ter sido aplicada; verifique e repita se \
                     quiser); o worker foi reiniciado",
                    timeout.as_millis()));
            }
            Err(std::sync::mpsc::RecvTimeoutError::Disconnected) => {
                // o worker morreu no meio: mesmo raciocínio — o pedido PODE ter sido
                // aplicado antes da morte; sem repetição automática.
                return Err("worker da ponte encerrou durante a chamada — resultado \
                            incerto, nada foi repetido automaticamente".into());
            }
        }
    }
}

#[tauri::command]
async fn bridge_call(request: String) -> Result<String, String> {
    tauri::async_runtime::spawn_blocking(move || bridge_roundtrip_blocking(&request))
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
/// Abre um caminho no Explorer. Caminhos RELATIVOS são resolvidos pela ponte Python
/// (ex.: "gow3.ini" vira o caminho de GOW3_CONFIG; "" vira DATA_DIR/user).
#[tauri::command]
async fn open_in_explorer(path: String) -> Result<(), String> {
    tauri::async_runtime::spawn_blocking(move || -> Result<(), String> {
        let is_absolute = path.contains('/') || path.contains('\\') || path.contains(':');
        let resolved = if is_absolute {
            path
        } else {
            let req = format!("{{\"cmd\":\"resolve_path\",\"name\":\"{}\"}}", path);
            match bridge_roundtrip_blocking(&req) {
                Ok(resp) => match serde_json::from_str::<serde_json::Value>(&resp) {
                    Ok(v) => v.get("path").and_then(|p| p.as_str()).unwrap_or("").to_string(),
                    Err(_) => path.clone(),
                },
                Err(_) => path.clone(),
            }
        };
        if resolved.is_empty() {
            return Err("caminho não resolvido".into());
        }
        Command::new("explorer").arg(&resolved).spawn().map_err(|e| format!("explorer: {e}"))?;
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

// ==================== SESSÃO DO JOGO ORIENTADA A EVENTOS (HOTFIX P0) ====================
// ANTES: um monitor Python detached esperava o run.py e gravava código de saída num
// arquivo; o React fazia polling de play_status a cada 1,5 s — cada consulta era um
// python.exe NOVO (~40/min só para saber se o jogo continuava aberto).
// AGORA: o Rust recebe da ponte (prepare_play) apenas a ESPECIFICAÇÃO de execução e
// ele mesmo inicia o run.py (CREATE_NO_WINDOW, stdout/stderr direto no log). O fim
// VERDADEIRO da sessão vem de um Job Object de SESSÃO dedicado com porta de conclusão
// (IOCP): o kernel posta JOB_OBJECT_MSG_ACTIVE_PROCESS_ZERO quando o ÚLTIMO processo
// da árvore morre — cobre também os reinícios internos ("Apply and restart" faz o
// probe gerar um novo run.py --after: o run.py original sai, a sessão continua). Zero
// processos e zero consultas enquanto o jogo roda. O handle do run.py original dá o
// código de saída (mesma semântica do monitor antigo); o evento "gow3://game-end"
// atualiza o launcher UMA vez, sem polling.

/// Cria o Job de sessão (sem limites: só rastreio) e a porta de conclusão.
fn create_session_objects() -> Result<(windows_sys::Win32::Foundation::HANDLE,
                                       windows_sys::Win32::Foundation::HANDLE), String> {
    unsafe {
        let job = windows_sys::Win32::System::JobObjects::CreateJobObjectW(
            std::ptr::null(), std::ptr::null());
        if job.is_null() {
            return Err("CreateJobObjectW (sessão) falhou".into());
        }
        let port = windows_sys::Win32::System::IO::CreateIoCompletionPort(
            windows_sys::Win32::Foundation::INVALID_HANDLE_VALUE,
            std::ptr::null_mut(), 0, 1);
        if port.is_null() {
            return Err("CreateIoCompletionPort falhou".into());
        }
        Ok((job, port))
    }
}

/// Associa a porta de conclusão ao Job — só DEPOIS de o primeiro processo estar no
/// Job (evita um ACTIVE_PROCESS_ZERO espúrio de Job vazio).
fn associate_port(job: windows_sys::Win32::Foundation::HANDLE,
                  port: windows_sys::Win32::Foundation::HANDLE) -> Result<(), String> {
    unsafe {
        let mut assoc: windows_sys::Win32::System::JobObjects::
            JOBOBJECT_ASSOCIATE_COMPLETION_PORT = std::mem::zeroed();
        assoc.CompletionKey = job as *mut core::ffi::c_void;
        assoc.CompletionPort = port;
        let ok = windows_sys::Win32::System::JobObjects::SetInformationJobObject(
            job,
            windows_sys::Win32::System::JobObjects::
                JobObjectAssociateCompletionPortInformation,
            &mut assoc as *mut _ as *mut core::ffi::c_void,
            std::mem::size_of::<windows_sys::Win32::System::JobObjects::
                JOBOBJECT_ASSOCIATE_COMPLETION_PORT>() as u32,
        );
        if ok == 0 {
            return Err("SetInformationJobObject (porta de conclusão) falhou".into());
        }
        Ok(())
    }
}

/// Inicia o processo da sessão (run.py ou substituto de teste) SEM CORRIDA: o
/// processo nasce SUSPENSO (CREATE_SUSPENDED), é associado aos Jobs de sessão e
/// principal ANTES de executar QUALQUER código, só então ganha CPU (ResumeThread).
/// Hierarquia de Jobs aninhados (Win8+): o filho pode pertencer ao Job de sessão E
/// ao principal simultaneamente; se o launcher não pôde se auto-associar (shell o
/// impõe outro Job), a adesão explícita ao principal acontece aqui — na mesma
/// janela suspensa. Falha em qualquer passo = terminação + fechamento de TODOS os
/// handles (criação, associação ou retomada parciais não vazam recursos).
struct GameSession {
    process: usize, // HANDLE do processo raiz (run.py) — fonte do código de saída
    job: usize,     // HANDLE do Job de sessão — fechado ao FIM da vigília
    port: usize,    // HANDLE da porta de conclusão — fechado ao FIM da vigília
    pid: u32,
}

/// Citação de argumento na linha de comando do Windows (regras MSVCRT).
fn quote_arg(arg: &str) -> String {
    if arg.is_empty() {
        return "\"\"".into();
    }
    if !arg.chars().any(|c| c == ' ' || c == '\t' || c == '"') {
        return arg.into();
    }
    let mut out = String::with_capacity(arg.len() + 2);
    out.push('"');
    let mut backslashes = 0;
    for ch in arg.chars() {
        match ch {
            '\\' => backslashes += 1,
            '"' => {
                out.push_str(&"\\".repeat(backslashes * 2 + 1));
                out.push('"');
                backslashes = 0;
            }
            _ => {
                out.push_str(&"\\".repeat(backslashes));
                backslashes = 0;
                out.push(ch);
            }
        }
    }
    out.push_str(&"\\".repeat(backslashes * 2));
    out.push('"');
    out
}

/// Bloco de ambiente UNICODE ("K=V\0...\0\0") para CreateProcessW.
fn environment_block(envs: &HashMap<String, String>) -> Vec<u16> {
    let mut block: Vec<u16> = Vec::new();
    for (key, value) in envs {
        let entry = format!("{key}={value}\0");
        block.extend(entry.encode_utf16());
    }
    block.push(0);
    block
}

fn spawn_game_session(command: &[String], cwd: &str, envs: &HashMap<String, String>,
                      log_file: &Path) -> Result<GameSession, String> {
    spawn_game_session_inner(command, cwd, envs, log_file, true)
}

fn spawn_game_session_inner(command: &[String], cwd: &str, envs: &HashMap<String, String>,
                            log_file: &Path, associate: bool) -> Result<GameSession, String> {
    use windows_sys::Win32::System::Threading::{
        CreateProcessW, ResumeThread, STARTUPINFOW, PROCESS_INFORMATION,
        CREATE_SUSPENDED, CREATE_UNICODE_ENVIRONMENT, STARTF_USESTDHANDLES,
    };
    if command.is_empty() {
        return Err("comando da sessão vazio".into());
    }
    // log: um handle, tornado herdável para stdout/stderr do filho
    let log = fs::File::create(log_file)
        .map_err(|e| format!("log da sessão: {e}"))?;
    let log_err = log.try_clone()
        .map_err(|e| format!("log da sessão (stderr): {e}"))?;
    use std::os::windows::io::AsRawHandle;
    unsafe {
        for handle in [log.as_raw_handle(), log_err.as_raw_handle()] {
            if windows_sys::Win32::Foundation::SetHandleInformation(
                handle, windows_sys::Win32::Foundation::HANDLE_FLAG_INHERIT,
                windows_sys::Win32::Foundation::HANDLE_FLAG_INHERIT) == 0 {
                return Err("log da sessão não pôde ser herdado".into());
            }
        }
    }
    let (session_job, port) = create_session_objects()?;
    unsafe {
        let mut command_line: Vec<u16> = command.iter().map(|a| quote_arg(a))
            .collect::<Vec<String>>().join(" ").encode_utf16().collect();
        command_line.push(0);
        let mut cwd_w: Vec<u16> = cwd.encode_utf16().collect();
        cwd_w.push(0);
        let env_block = environment_block(envs);
        let mut startup: STARTUPINFOW = std::mem::zeroed();
        startup.cb = std::mem::size_of::<STARTUPINFOW>() as u32;
        startup.dwFlags = STARTF_USESTDHANDLES;
        startup.hStdInput = std::ptr::null_mut();
        startup.hStdOutput = log.as_raw_handle();
        startup.hStdError = log_err.as_raw_handle();
        let mut info: PROCESS_INFORMATION = std::mem::zeroed();
        let created = CreateProcessW(
            std::ptr::null(),                       // aplicativo vem da linha de comando
            command_line.as_mut_ptr(),
            std::ptr::null(), std::ptr::null(),     // atributos padrão
            1,                                      // bInheritHandles: log herdável
            CREATE_SUSPENDED | CREATE_NO_WINDOW | CREATE_UNICODE_ENVIRONMENT,
            if env_block.is_empty() { std::ptr::null() }
            else { env_block.as_ptr() as *const core::ffi::c_void },
            cwd_w.as_ptr(),
            &startup, &mut info);
        if created == 0 {
            let error = windows_sys::Win32::Foundation::GetLastError();
            windows_sys::Win32::Foundation::CloseHandle(port);
            windows_sys::Win32::Foundation::CloseHandle(session_job);
            return Err(format!("não foi possível iniciar: erro {error}"));
        }
        // A partir daqui o processo existe SUSPENSO: toda falha = terminar + fechar tudo.
        let fail = |message: String, info: &PROCESS_INFORMATION| -> String {
            windows_sys::Win32::System::Threading::TerminateProcess(info.hProcess, 1);
            windows_sys::Win32::System::Threading::WaitForSingleObject(info.hProcess, 5000);
            windows_sys::Win32::Foundation::CloseHandle(info.hThread);
            windows_sys::Win32::Foundation::CloseHandle(info.hProcess);
            windows_sys::Win32::Foundation::CloseHandle(port);
            windows_sys::Win32::Foundation::CloseHandle(session_job);
            message
        };
        if windows_sys::Win32::System::JobObjects::AssignProcessToJobObject(
            session_job, info.hProcess) == 0 {
            return Err(fail("associação ao Job de sessão falhou".into(), &info));
        }
        // Job principal: só adesão explícita quando o launcher NÃO se auto-associou
        // (se auto-associou, o filho SUSPENSO já herdou o Job por criação — sem corrida).
        if !job_self_assigned() {
            let main_job = match job_handle() {
                Ok(handle) => handle,
                Err(error) => return Err(fail(error, &info)),
            };
            if windows_sys::Win32::System::JobObjects::AssignProcessToJobObject(
                main_job, info.hProcess) == 0 {
                return Err(fail("associação ao Job principal falhou".into(), &info));
            }
        }
        if associate {
            if let Err(error) = associate_port(session_job, port) {
                return Err(fail(error, &info));
            }
        }
        if ResumeThread(info.hThread) == u32::MAX {
            return Err(fail("ResumeThread falhou".into(), &info));
        }
        let pid = info.dwProcessId;
        windows_sys::Win32::Foundation::CloseHandle(info.hThread);
        Ok(GameSession {
            process: info.hProcess as usize,
            job: session_job as usize,
            port: port as usize,
            pid,
        })
    }
}

/// Consulta NATIVA de autoridade: processos ativos no Job de sessão (kernel).
fn session_active_processes(job: windows_sys::Win32::Foundation::HANDLE) -> Option<u32> {
    unsafe {
        let mut accounting: windows_sys::Win32::System::JobObjects::
            JOBOBJECT_BASIC_ACCOUNTING_INFORMATION = std::mem::zeroed();
        let ok = windows_sys::Win32::System::JobObjects::QueryInformationJobObject(
            job,
            windows_sys::Win32::System::JobObjects::JobObjectBasicAccountingInformation,
            &mut accounting as *mut _ as *mut core::ffi::c_void,
            std::mem::size_of::<windows_sys::Win32::System::JobObjects::
                JOBOBJECT_BASIC_ACCOUNTING_INFORMATION>() as u32,
            std::ptr::null_mut());
        if ok == 0 { None } else { Some(accounting.ActiveProcesses) }
    }
}

/// Espera o fim VERDADEIRO da sessão e devolve o código de saída da raiz (run.py).
/// Prioritariamente orientada a eventos, SEM espera infinita cega e SEM polling de
/// processos: (1) o handle do processo RAIZ é o gatilho confiável — a raiz só sai
/// no fim real OU num reinício interno (run.py --after), e enquanto o jogo roda a
/// espera é um único bloqueio de custo zero; (2) após a saída da raiz, o caminho
/// rápido é a mensagem do kernel (ACTIVE_PROCESS_ZERO, se entregue — o Windows NÃO
/// garante a entrega) e o fallback é a consulta de autoridade
/// QueryInformationJobObject(ActiveProcesses), ~1 consulta/s apenas na janela pós-
/// raiz (reinício), sem busy-wait, sem processos; (3) todos os handles (processo,
/// Job de sessão, porta) são fechados exatamente uma vez, aqui. O Job PRINCIPAL é
/// vitalício e intocável. Não confunde fim da raiz com fim da árvore: a raiz sair
/// com processos ativos no Job = reinício → continua esperando.
fn wait_session_end(session: GameSession) -> u32 {
    use windows_sys::Win32::System::Threading::WaitForSingleObject;
    let GameSession { process, job, port, pid: _ } = session;
    let process = process as windows_sys::Win32::Foundation::HANDLE;
    let job = job as windows_sys::Win32::Foundation::HANDLE;
    let port = port as windows_sys::Win32::Foundation::HANDLE;
    unsafe {
        // (1) gatilho confiável: saída da raiz (custo zero enquanto o jogo roda)
        WaitForSingleObject(process, u32::MAX);
        let mut code: u32 = 0;
        windows_sys::Win32::System::Threading::GetExitCodeProcess(process, &mut code);
        // (2) fim da ÁRVORE: evento do kernel (rápido) + consulta de autoridade (fallback)
        let mut query_failures: u32 = 0;
        loop {
            let mut message: u32 = 0;
            let mut key: usize = 0;
            let mut overlapped: *mut windows_sys::Win32::System::IO::OVERLAPPED =
                std::ptr::null_mut();
            let delivered = windows_sys::Win32::System::IO::GetQueuedCompletionStatus(
                port, &mut message, &mut key, &mut overlapped, 0);
            if delivered != 0 {
                if message == windows_sys::Win32::System::SystemServices::
                    JOB_OBJECT_MSG_ACTIVE_PROCESS_ZERO {
                    break; // evento entregue: fim da árvore
                }
                continue; // EXIT_PROCESS etc.: drena e segue
            }
            // fila vazia (WAIT_TIMEOUT) ou erro: consulta de autoridade do kernel
            match session_active_processes(job) {
                Some(0) => break,                       // fim confirmado nativamente
                Some(_alive) => query_failures = 0,     // reinício em andamento: espera
                None => {
                    query_failures += 1;
                    if query_failures > 120 {
                        break; // raiz morta + Job inobservável por ~90 s: encerra a vigília
                    }
                }
            }
            std::thread::sleep(std::time::Duration::from_millis(750));
        }
        // (3) gerenciamento determinístico: cada handle fechado exatamente uma vez
        windows_sys::Win32::Foundation::CloseHandle(port);
        windows_sys::Win32::Foundation::CloseHandle(job);
        windows_sys::Win32::Foundation::CloseHandle(process);
        code
    }
}

/// JOGAR (novo fluxo): validações e especificação vêm da ponte (worker persistente,
/// NENHUM processo novo), o spawn e a vigília são do Rust, o fim da sessão chega por
/// evento do kernel e vira UM evento Tauri ("gow3://game-end") — sem polling algum.
#[tauri::command]
async fn game_start(app: tauri::AppHandle) -> Result<serde_json::Value, String> {
    tauri::async_runtime::spawn_blocking(move || {
        use tauri::Emitter;
        let spec_text = bridge_roundtrip_blocking("{\"cmd\":\"prepare_play\"}")?;
        let spec: serde_json::Value = serde_json::from_str(&spec_text)
            .map_err(|e| format!("resposta de prepare_play inválida: {e}"))?;
        if let Some(error) = spec.get("error").and_then(|v| v.as_str()) {
            return Err(error.to_string());
        }
        let command: Vec<String> = spec.get("command").and_then(|v| v.as_array())
            .map(|a| a.iter().filter_map(|x| x.as_str().map(String::from)).collect())
            .ok_or("prepare_play sem command")?;
        let cwd = spec.get("cwd").and_then(|v| v.as_str())
            .ok_or("prepare_play sem cwd")?.to_string();
        let envs: HashMap<String, String> = spec.get("env").and_then(|v| v.as_object())
            .map(|o| o.iter().filter_map(|(k, v)| v.as_str()
                .map(|s| (k.clone(), s.to_string()))).collect())
            .ok_or("prepare_play sem env")?;
        let log_file = spec.get("log_file").and_then(|v| v.as_str())
            .ok_or("prepare_play sem log_file")?.to_string();
        let pid_file = spec.get("pid_file").and_then(|v| v.as_str())
            .ok_or("prepare_play sem pid_file")?.to_string();
        let exit_file = spec.get("exit_file").and_then(|v| v.as_str())
            .ok_or("prepare_play sem exit_file")?.to_string();
        let session = spawn_game_session(&command, &cwd, &envs, Path::new(&log_file))?;
        let pid = session.pid;
        let _ = fs::write(&pid_file, pid.to_string());
        std::thread::spawn(move || {
            let exit_code = wait_session_end(session);
            let _ = fs::write(&exit_file, exit_code.to_string());
            let _ = app.emit("gow3://game-end",
                serde_json::json!({"pid": pid, "exit_code": exit_code}));
        });
        Ok(serde_json::json!({"ok": true, "pid": pid, "log": log_file}))
    })
    .await
    .map_err(|e| format!("task join: {e}"))?
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .invoke_handler(tauri::generate_handler![
            bridge_call,
            pick_folder,
            open_in_explorer,
            music_data_url,
            game_start
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


// ===================== TESTES DO HOTFIX P0 (worker + sessão) =====================
// Fixtures: python sleep e o próprio worker da ponte — NUNCA o jogo real.

#[cfg(test)]
mod p0_tests {
    use super::*;
    use std::sync::Mutex as TestMutex;
    use std::time::Duration;

    /// O worker é UM static compartilhado: os testes que o matam precisam rodar
    /// em série (o cargo paraleliza testes por padrão).
    static WORKER_TEST_LOCK: TestMutex<()> = TestMutex::new(());

    /// Estado do worker é compartilhado entre testes do MESMO binary (broken/restarts
    /// persistem): cada teste do worker começa do zero — mata o atual e limpa a política.
    fn reset_worker_for_tests() {
        {
            let slot = worker_slot();
            let mut guard = slot.lock().unwrap();
            if let Some(worker) = guard.worker.take() {
                kill_hard(worker.pid);
            }
        }
        std::thread::sleep(Duration::from_millis(300)); // leitor registra a queda
        let slot = worker_slot();
        let mut guard = slot.lock().unwrap();
        guard.restarts.clear();
        guard.broken = None;
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

    fn pid_alive(pid: u32) -> bool {
        unsafe {
            let handle = windows_sys::Win32::System::Threading::OpenProcess(
                windows_sys::Win32::System::Threading::PROCESS_QUERY_LIMITED_INFORMATION,
                0, pid);
            if handle.is_null() { return false; }
            let mut code: u32 = 0;
            let ok = windows_sys::Win32::System::Threading::GetExitCodeProcess(handle, &mut code);
            windows_sys::Win32::Foundation::CloseHandle(handle);
            ok != 0 && code == 259
        }
    }

    /// A ponte atende MUITAS requisições (sequenciais E concorrentes) com UM só
    /// processo — o PID do worker não muda entre chamadas.
    #[test]
    fn worker_serves_many_requests_as_one_process() {
        let _guard = WORKER_TEST_LOCK.lock().unwrap_or_else(|e| e.into_inner());
        reset_worker_for_tests();
        let first = bridge_roundtrip_blocking("{\"cmd\":\"resolve_path\",\"name\":\"gow3.ini\"}")
            .expect("primeira chamada");
        assert!(first.contains("gow3.ini"), "resposta: {first}");
        let pid_before = worker_pid_for_tests();
        assert!(pid_before != 0, "worker deve existir");
        for i in 0..5 {
            let response = bridge_roundtrip_blocking(
                &format!("{{\"cmd\":\"resolve_path\",\"name\":\"user\",\"marca\":{i}}}"))
                .expect("chamada sequencial");
            assert!(response.contains("user"), "resposta {i}: {response}");
        }
        // concorrentes: 5 threads ao mesmo tempo pela MESMA conexão (seq distintos)
        let mut joins = Vec::new();
        for _ in 0..5 {
            joins.push(std::thread::spawn(|| {
                bridge_roundtrip_blocking("{\"cmd\":\"resolve_path\",\"name\":\"user\"}")
            }));
        }
        for join in joins {
            join.join().expect("thread").expect("chamada concorrente");
        }
        assert_eq!(worker_pid_for_tests(), pid_before,
                   "o MESMO worker atendeu todas as chamadas (sem respawn)");
    }

    /// Recuperação LIMITADA: worker morto renasce na chamada seguinte (pid muda);
    /// após 3 quedas no minuto a ponte recusa em vez de reiniciar em loop.
    #[test]
    fn worker_recovery_is_bounded_not_a_loop() {
        let _guard = WORKER_TEST_LOCK.lock().unwrap_or_else(|e| e.into_inner());
        reset_worker_for_tests();
        let _ = bridge_roundtrip_blocking("{\"cmd\":\"resolve_path\",\"name\":\"user\"}")
            .expect("aquece o worker");
        // queda 1 → renasce
        kill_hard(worker_pid_for_tests());
        std::thread::sleep(Duration::from_millis(300));
        let revived = bridge_roundtrip_blocking("{\"cmd\":\"resolve_path\",\"name\":\"user\"}");
        assert!(revived.is_ok(), "deve renascer uma vez: {revived:?}");
        // queda 2 (última dentro da política) → ainda renasce
        kill_hard(worker_pid_for_tests());
        std::thread::sleep(Duration::from_millis(300));
        assert!(bridge_roundtrip_blocking("{\"cmd\":\"resolve_path\",\"name\":\"user\"}").is_ok());
        // queda 3 dentro do minuto → RECUSA (sem loop de reinicialização)
        kill_hard(worker_pid_for_tests());
        std::thread::sleep(Duration::from_millis(300));
        let refused = bridge_roundtrip_blocking("{\"cmd\":\"resolve_path\",\"name\":\"user\"}");
        assert!(refused.is_err(), "deve recusar após 2 renascimentos no minuto: {refused:?}");
    }

    /// Reinício interno (probe gera novo run.py): a raiz SAI e a sessão CONTINUA —
    /// ACTIVE_PROCESS_ZERO só chega quando o ÚLTIMO processo da árvore morre.
    #[test]
    fn session_survives_root_exit_restart_chain() {
        // o "run.py" de mentira gera um filho sleep 20 e sai 0 logo (pid do filho em arquivo)
        let out = std::env::temp_dir().join(format!("gow3-sess-restart-{}.txt", std::process::id()));
        let script = format!(
            "import subprocess,sys;f=open(r'{}','w');c=subprocess.Popen([sys.executable,'-c','import time; time.sleep(20)']);f.write(str(c.pid));f.close()",
            out.display());
        let log = std::env::temp_dir().join(format!("gow3-sess-restart-{}.log", std::process::id()));
        let mut envs = HashMap::new();
        envs.insert("PATH".to_string(), std::env::var("PATH").unwrap_or_default());
        let command = vec!["python".to_string(), "-c".to_string(), script];
        let session = spawn_game_session(&command, ".", &envs, &log).expect("sessão");
        let root_pid = session.pid;
        let watcher = std::thread::spawn(move || wait_session_end(session));
        // espera a raiz sair e o filho nascer
        let mut child_pid: u32 = 0;
        for _ in 0..100 {
            std::thread::sleep(Duration::from_millis(50));
            if let Ok(text) = fs::read_to_string(&out) {
                if let Ok(parsed) = text.trim().parse::<u32>() { child_pid = parsed; break; }
            }
        }
        assert!(child_pid != 0, "raiz deve gerar o filho do reinício");
        assert!(!pid_alive(root_pid), "raiz saiu (reinício interno)");
        std::thread::sleep(Duration::from_millis(1500));
        assert!(!watcher.is_finished(),
                "sessão NÃO pode terminar com a raiz: o filho do reinício continua");
        assert!(pid_alive(child_pid), "filho do reinício vivo");
        kill_hard(child_pid); // fim real da sessão
        let code = watcher.join().expect("vigília");
        assert_eq!(code, 0, "código da raiz (saída limpa do reinício)");
        assert!(!pid_alive(child_pid), "nenhum órfão");
    }

    // ================== CORREÇÕES DA AUDITORIA INDEPENDENTE (PR #10) ==================

    fn handle_count() -> u32 {
        unsafe {
            let mut count: u32 = 0;
            windows_sys::Win32::System::Threading::GetProcessHandleCount(
                windows_sys::Win32::System::Threading::GetCurrentProcess(), &mut count);
            count
        }
    }

    fn tiny_envs() -> HashMap<String, String> {
        let mut envs = HashMap::new();
        envs.insert("PATH".to_string(), std::env::var("PATH").unwrap_or_default());
        envs.insert("SYSTEMROOT".to_string(),
                    std::env::var("SYSTEMROOT").unwrap_or_else(|_| r"C:\Windows".into()));
        envs
    }

    /// Processo que TERMINA IMEDIATAMENTE: spawn suspenso→jobs→resume→saída em
    /// milissegundos; o fim é detectado e o código de saída chega intacto.
    #[test]
    fn session_immediate_exit_is_detected() {
        let log = std::env::temp_dir().join(format!("gow3-sess-fast-{}.log", std::process::id()));
        let command = vec!["python".to_string(), "-c".to_string(),
                           "print('sessao curta')".to_string()];
        let began = Instant::now();
        let session = spawn_game_session(&command, ".", &tiny_envs(), &log).expect("sessão");
        let code = wait_session_end(session);
        assert_eq!(code, 0, "saída limpa");
        assert!(began.elapsed() < Duration::from_secs(10),
                "detecção rápida (levou {:?})", began.elapsed());
        let text = fs::read_to_string(&log).unwrap_or_default();
        assert!(text.contains("sessao curta"), "log da sessão capturado: {text}");
    }

    /// Notificação de conclusão PERDIDA/indisponível (o Windows não garante a
    /// entrega): sem porta associada, a consulta de autoridade do kernel
    /// (QueryInformationJobObject) ainda detecta o fim — sem espera infinita.
    #[test]
    fn session_end_detected_without_completion_port() {
        let log = std::env::temp_dir().join(format!("gow3-sess-noport-{}.log", std::process::id()));
        let command = vec!["python".to_string(), "-c".to_string(),
                           "import time; time.sleep(2); print('fim')".to_string()];
        // associate=false: NENHUMA mensagem chegará — só o fallback nativo
        let session = spawn_game_session_inner(&command, ".", &tiny_envs(), &log, false)
            .expect("sessão");
        let began = Instant::now();
        let code = wait_session_end(session);
        assert_eq!(code, 0);
        // raiz dorme 2 s + fallback consulta ~1/s → alguns segundos no máximo
        assert!(began.elapsed() < Duration::from_secs(15),
                "fallback deve detectar sem porta (levou {:?})", began.elapsed());
    }

    /// Falha na CRIAÇÃO do processo (binário inexistente): erro claro, sem
    /// processos e sem handles vazados.
    #[test]
    fn session_spawn_failure_is_clean() {
        let log = std::env::temp_dir().join(format!("gow3-sess-fail-{}.log", std::process::id()));
        let before = handle_count();
        let command = vec!["binario_inexistente_xyz_123456".to_string()];
        let result = spawn_game_session(&command, ".", &tiny_envs(), &log);
        assert!(result.is_err(), "deve falhar na criação do processo inexistente");
        std::thread::sleep(Duration::from_millis(200));
        let after = handle_count();
        assert!(after <= before + 1,
                "handles não podem vazar na falha (antes {before}, depois {after})");
    }

    /// Sessões CONSECUTIVAS sem crescimento indevido de handles: 5 sessões
    /// completas (spawn→fim→fechamento) e o total de handles do processo volta
    /// ao patamar inicial.
    #[test]
    fn consecutive_sessions_do_not_leak_handles() {
        let before = handle_count();
        for index in 0..5 {
            let log = std::env::temp_dir()
                .join(format!("gow3-sess-leak-{}-{}.log", std::process::id(), index));
            let command = vec!["python".to_string(), "-c".to_string(),
                               "import time; time.sleep(0.3)".to_string()];
            let session = spawn_game_session(&command, ".", &tiny_envs(), &log)
                .expect("sessão");
            let code = wait_session_end(session);
            assert_eq!(code, 0);
        }
        std::thread::sleep(Duration::from_millis(300));
        let after = handle_count();
        assert!(after <= before + 2,
                "5 sessões não podem vazar handles (antes {before}, depois {after})");
    }

    /// Worker VIVO MAS MUDO (test_sleep no bridge): o prazo vence, a chamada falha
    /// SEM repetição automática, nada é aplicado duas vezes e o worker renasce
    /// limpo para a chamada seguinte.
    #[test]
    fn worker_timeout_discards_call_without_side_effects() {
        let _guard = WORKER_TEST_LOCK.lock().unwrap_or_else(|e| e.into_inner());
        reset_worker_for_tests();
        std::env::set_var("GOW3_BRIDGE_TIMEOUT_MS", "3000");
        // linha de base gravada com sucesso
        let baseline = bridge_roundtrip_blocking(
            "{\"cmd\":\"set_ini\",\"values\":{\"vsync\":\"1\"}}").expect("baseline");
        assert!(baseline.contains("\"ok\""), "baseline: {baseline}");
        // chamada que trava o worker por 60 s (comando SÓ de teste)
        let began = Instant::now();
        let stuck = bridge_roundtrip_blocking(
            "{\"cmd\":\"test_sleep\",\"seconds\":60}");
        std::env::remove_var("GOW3_BRIDGE_TIMEOUT_MS");
        assert!(stuck.is_err(), "deve falhar por prazo: {stuck:?}");
        assert!(began.elapsed() < Duration::from_secs(15),
                "prazo deve vencer rápido (levou {:?})", began.elapsed());
        assert!(stuck.unwrap_err().contains("sem"), "mensagem documenta a ausência de repetição");
        // o pedido travado NÃO foi aplicado fora de ordem: estado coerente
        let state = bridge_roundtrip_blocking("{\"cmd\":\"state\"}").expect("estado");
        assert!(state.contains("\"version\""), "worker renasceu e responde");
        assert!(state.contains("\"vsync\":\"1\""), "valor de base intacto: {state}");
        // a escrita presa nunca chegou a rodar (worker foi morto antes) — o arquivo
        // continua com o valor da baseline, sem duplicação de efeito
        let set_again = bridge_roundtrip_blocking(
            "{\"cmd\":\"set_ini\",\"values\":{\"vsync\":\"0\"}}");
        assert!(set_again.is_ok(), "chamada posterior funciona: {set_again:?}");
    }

    /// Raiz morta com FILHO vivo (reinício) e porta PERDIDA: o fallback de
    /// autoridade mantém a vigília até o último processo — o contrário de
    /// encerrar cedo demais.
    #[test]
    fn session_restart_without_port_waits_for_last_process() {
        let out = std::env::temp_dir()
            .join(format!("gow3-sess-rst-noport-{}.txt", std::process::id()));
        let script = format!(
            "import subprocess,sys;f=open(r'{}','w');c=subprocess.Popen([sys.executable,'-c','import time; time.sleep(15)']);f.write(str(c.pid));f.close()",
            out.display());
        let log = std::env::temp_dir()
            .join(format!("gow3-sess-rst-noport-{}.log", std::process::id()));
        let command = vec!["python".to_string(), "-c".to_string(), script];
        let session = spawn_game_session_inner(&command, ".", &tiny_envs(), &log, false)
            .expect("sessão");
        let root_pid = session.pid;
        let watcher = std::thread::spawn(move || wait_session_end(session));
        let mut child_pid: u32 = 0;
        for _ in range0(100) {
            std::thread::sleep(Duration::from_millis(50));
            if let Ok(text) = fs::read_to_string(&out) {
                if let Ok(parsed) = text.trim().parse::<u32>() { child_pid = parsed; break; }
            }
        }
        assert!(child_pid != 0);
        assert!(!pid_alive(root_pid), "raiz saiu");
        std::thread::sleep(Duration::from_millis(2500));
        assert!(!watcher.is_finished(),
                "sem porta e com filho vivo, a sessão NÃO pode encerrar com a raiz");
        kill_hard(child_pid);
        let code = watcher.join().expect("vigília");
        assert_eq!(code, 0);
    }
}

/// range0: helper minúsculo (0..n) usado apenas nos testes.
#[cfg(test)]
fn range0(n: usize) -> std::ops::Range<usize> { 0..n }
