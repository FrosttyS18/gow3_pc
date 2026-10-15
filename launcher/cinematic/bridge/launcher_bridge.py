#!/usr/bin/env python3
"""Typed JSON bridge between the cinematic launcher (Tauri/React) and the port's real logic.

The Python layer stays the single owner of the port's rules: this module only imports
gow3_launcher_win as a library (import-safe: the Tkinter classes receive the tk modules
as arguments) and exposes a request/response protocol — one JSON object on stdin, one
JSON object on stdout, ALWAYS UTF-8 (stdout is reconfigured; the Rust side spawns this
process with PYTHONIOENCODING=utf-8 as well).

Commands (M1.2):
  state                       -> everything the UI needs: settings, ini, choices (all real
                                  option lists), game status, music, mods, patches (built-in
                                  and external), backups, controls, presets, version
  set_ini {values} / set_app {values}
  set_game_patches {names[]}            (settings.json game_patches[title_id])
  set_external_patches {enabled[], disabled[]}
  mods_set {order[], disabled[]}        (mods.json)
  preset_save {name} / preset_load {name} / preset_delete {name}
  backups_list / backup_restore {name}  (save_backup; refuses while the game runs)
  controls_set {key{}, pad{}, pad_style}
  clear_cache                           (user/cache; refuses while the game runs)
  update_check                          (latest_release vs VERSION — check only)
  log_read                              (real run log; sources reported honestly)
  play / play_status                    (unchanged contract)

No Tkinter window is ever created; user data is only touched through the port's own
functions, and destructive ops (restore/clear) guard on the game not running.
"""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # launcher/ on the path
import gow3_launcher_win as L  # noqa: E402  (the port's launcher, as a library)
sys.path.insert(0, str(L.PORT_DIR / "scripts"))  # mods/save_backup/patches live here

MUSIC_KEYS = ("ambient_volume", "ambient_muted", "ambient_file")
RUN_LOG = Path(tempfile.gettempdir()) / "gow3-cinematic-run.log"
RUN_PID = Path(tempfile.gettempdir()) / "gow3-cinematic-run.pid"


def _out(values):
    sys.stdout.flush()
    return values


def choice_labels(pairs):
    return [{"value": value, "label": texts[0]} for value, texts in pairs]


def app_settings() -> dict:
    return {**L.APP_DEFAULTS, **L.load_json(L.CONFIG_FILE, {})}


def game_running() -> bool:
    try:
        pid = int(RUN_PID.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return False
    return pid_alive(pid)


def pid_alive(pid: int) -> bool:
    """Read-only liveness check (OpenProcess QUERY + GetExitCodeProcess): never signals."""
    if pid <= 0:
        return False
    try:
        import ctypes
        from ctypes import wintypes
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return False
        try:
            code = wintypes.DWORD()
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
                return False
            return code.value == 259  # STILL_ACTIVE (ambiguity documented)
        finally:
            kernel32.CloseHandle(handle)
    except Exception:
        return False


def meta_dir(app: dict) -> Path:
    return L.meta_folder(app.get("game_dir") or ".", app.get("update_dir") or "")


def game_state(app: dict, ini: dict) -> dict:
    folder = meta_dir(app)
    info = L.game_info(folder) if folder else None
    title_id, profile = L.game_profile_of(folder)
    names = app.get("game_patches", {}).get(title_id) or []
    resolution = dict((v, t[0]) for v, t in L.RESOLUTION_CHOICES).get(ini.get("render_resolution"), "?")
    if info is None:
        summary = "Pasta do jogo não configurada"
    elif not profile:
        summary = f"{resolution} · 60 FPS engine · sem patches para este jogo"
    else:
        summary = f"{resolution} · {ini.get('engine_fps', '60')} FPS engine · {len(names)} patches"
    missing = []
    try:
        if info:
            missing = [str(m[0] if isinstance(m, tuple) else m)
                       for m in (L.missing_game_files(folder) or [])][:8]
    except Exception:
        missing = []
    return {"found": bool(info), "folder": str(folder), "title_id": title_id,
            "patch_profile": bool(profile), "summary": summary, "missing_files": missing}


def music_state(app: dict) -> dict:
    art = L.DATA_DIR / "launcher" / "cinematic" / "public" / "art"
    default = next((str(p) for name in ("ambient.mp3", "intro_launcher.mp3")
                    for p in [art / name] if p.is_file()), None)
    return {"default_path": default, "file": app.get("ambient_file") or "",
            "volume": float(app.get("ambient_volume", 0.55)),
            "muted": bool(app.get("ambient_muted", False))}


GPU_CACHE_FILE = Path(tempfile.gettempdir()) / "gow3-cinematic-gpus.json"


def cached_gpus():
    """list_gpus executa gow3-gpu-capabilities (segundos) e cada ponte é um processo
    NOVO: o cache precisa persistir em ARQUIVO para valer entre chamadas (5 min)."""
    import time
    try:
        data = json.loads(GPU_CACHE_FILE.read_text(encoding="utf-8"))
        if time.time() - data.get("when", 0) < 300:
            return [tuple(row) for row in data["rows"]]
    except (OSError, ValueError, KeyError):
        pass
    rows = L.list_gpus()
    try:
        GPU_CACHE_FILE.write_text(json.dumps(
            {"when": time.time(), "rows": [list(row) for row in rows]}), encoding="utf-8")
    except OSError:
        pass
    return rows


def all_choices(app: dict) -> dict:
    gpus = cached_gpus()
    c = {
        "display_mode": choice_labels(L.DISPLAY_MODES),
        "render_resolution": choice_labels(L.RESOLUTION_CHOICES),
        "engine_fps": choice_labels(L.ENGINE_FPS_CHOICES),
        "fps_limit": choice_labels(L.FPS_LIMITS),
        "upscaler": choice_labels(L.UPSCALERS),
        "preset": choice_labels(L.PRESETS),
        "output_res": choice_labels(L.OUTPUTS),
        "live_resolution": choice_labels(L.LIVE),
        "frames_queued": choice_labels(L.FRAMES_QUEUED),
        "stream_memory": choice_labels(L.STREAM_MEMORY),
        "draw_pipe": choice_labels(L.DRAW_PIPE),
        "readbacks": choice_labels(L.READBACKS),
        "language": choice_labels(L.LANGUAGES),
        "ui_language": choice_labels(L.UI_LANGUAGES),
        "video_backend": choice_labels(L.VIDEO_BACKENDS),
        "glyph_style": choice_labels(L.GLYPH_STYLES),
        "anisotropy": choice_labels(L.ANISOTROPY),
        "gpu_id": [{"value": "", "label": "Automático"}] + [
            {"value": row[0], "label": row[1]} for row in gpus],
        "no_msaa": choice_labels(L.no_msaa_options(gpus, app.get("gpu_id", ""))),
    }
    return c


def _resolve_patches_dir(app: dict) -> Path:
    """Fonte ÚNICA de verdade: a MESMA resolução de game_environment() para
    GOW3_PATCHES_DIR. Se o usuário configurar patches_dir no backend (ex.: apontando
    para a pasta do pacote), AMBOS (UI e runtime) usam o mesmo diretório automaticamente.
    O fallback anterior para Downloads foi removido porque criava divergência: a UI
    listava patches que o runtime não carregava. Para usar os patches do pacote, o
    usuário deve configurar patches_dir na página Patches (mesma ação do Tkinter)."""
    return Path(app.get("patches_dir") or "") if app.get("patches_dir") else L.DATA_DIR / "patches"


def patches_state(app: dict) -> dict:
    import xml.etree.ElementTree as ET
    from patches import ALWAYS_ON, EXCLUSIVE_PREFIX
    folder = meta_dir(app)
    title_id, profile = L.game_profile_of(folder)
    builtin = []
    if profile:
        _ids, xml, version = profile[:3]
        metas = [m for m in ET.parse(xml).getroot().iter("Metadata") if m.get("AppVer") == version]
        chosen = app.get("game_patches", {}).get(title_id)
        on = set(chosen) if chosen is not None else {m.get("Name") for m in metas
                                                     if m.get("isEnabled", "false").lower() == "true"}
        for meta in metas:
            name = meta.get("Name")
            if name.startswith(EXCLUSIVE_PREFIX) or name.startswith("Frame Rate Patch") or name in ALWAYS_ON:
                continue  # ALWAYS_ON (v2.2.0): correções sem escolha, aplicadas sempre — inclusive com listas salvas antigas
            builtin.append({"name": name, "author": meta.get("Author"),
                            "note": meta.get("Note"), "enabled": name in on})
    from patches import external_patches
    ext = []
    if profile:
        root = _resolve_patches_dir(app)
        chosen = L.load_json(L.DATA_DIR / "patches.json", {})
        builtin_xml = profile[1].name if profile else ""  # não listar o XML interno como "externo"
        for key, _path, meta in external_patches(root, profile[2], profile[1], profile[0]):
            if _path.name == builtin_xml:
                continue  # cópia do XML interno na pasta de patches: o Tkinter só lista terceiros
            on = key in chosen.get("enabled", []) or (key not in chosen.get("disabled", [])
                                                      and meta.get("isEnabled", "false").lower() == "true")
            ext.append({"key": key, "author": meta.get("Author"), "enabled": on})
    return {"title_id": title_id, "version": (profile[2] if profile else None),
            "builtin": builtin, "external": ext,
            "patches_dir_resolved": str(root) if profile else None}


def mods_state(app: dict) -> dict:
    from mods import discover, conflicts
    root = Path(app.get("mods_dir") or L.DATA_DIR / "mods")
    available = discover(root)
    saved = L.load_json(L.DATA_DIR / "mods.json", {})
    order = [n for n in saved.get("order", []) if n in available] + \
            [n for n in available if n not in saved.get("order", [])]
    disabled = [n for n in saved.get("disabled", []) if n in available]
    enabled_now = [n for n in order if n not in disabled]
    return {"available": available, "order": order, "disabled": disabled,
            "conflicts": conflicts(root, enabled_now),
            "presets": sorted(L.load_json(L.MOD_PRESETS, {}))}


def backups_state(app: dict) -> dict:
    import save_backup
    user = Path(app.get("user_dir") or L.DATA_DIR / "user")
    return {"keep": save_backup.KEEP, "names": save_backup.list_backups(user)}


def controls_state(app: dict) -> dict:
    saved = {kind: L.control_values(app.get("controls"), kind) for kind in ("key", "pad")}
    style = app.get("pad_style") if app.get("pad_style") in L.PAD_STYLES else "playstation"
    rows = []
    for button, key, pad in L.CONTROLS:
        rows.append({"button": button, "ps_name": L.PS_BUTTON_NAMES[button],
                     "default_key": key, "default_pad": pad or "",
                     "key": saved.get("key", {}).get(button) or key,
                     "pad": saved.get("pad", {}).get(button) or pad or "",
                     "remappable": bool(pad)})
    return {"style": style, "styles": {s: dict(v) for s, v in L.PAD_STYLES.items()},
            "rows": rows}


def translations_state() -> dict:
    """Tabelas de tradução oficiais (gow3_lang.table) por idioma — EN é a chave."""
    import gow3_lang
    tables = {}
    for code, _names in gow3_lang.LANGUAGE_NAMES:
        if not code:
            continue
        try:
            tables[code] = gow3_lang.table(code)
        except ValueError:
            pass  # idioma incompleto no upstream: não expõe tabela parcial
    return tables


def cmd_state() -> dict:
    app = app_settings()
    ini, _lines = L.load_ini()
    return {
        "version": L.VERSION,
        "app": {k: app[k] for k in sorted(app) if isinstance(app[k], (str, int, float, bool))},
        "controls_cfg": {"controls": app.get("controls", {}), "pad_style": app.get("pad_style", "playstation")},
        "game_patches_cfg": app.get("game_patches", {}),
        "ini": dict(sorted(ini.items())),
        "game": game_state(app, ini),
        "music": music_state(app),
        "choices": all_choices(app),
        "patches": patches_state(app),
        "mods": mods_state(app),
        "backups": backups_state(app),
        "controls": controls_state(app),
        "running": game_running(),
        "translations": translations_state(),
    }


def save_app(app: dict) -> None:
    """Writes settings.json in the launcher's own format (dir ensured)."""
    L.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    L.CONFIG_FILE.write_text(json.dumps(app, indent=2, ensure_ascii=False), encoding="utf-8")


def cmd_set_ini(values: dict) -> dict:
    """Grava SOMENTE as chaves pedidas (v2.2.0: preserva alterações feitas dentro do jogo
    e chaves legadas fsr1/rcas/sharpen/sharpness — removidas do contrato do port — porque
    nenhuma outra chave é relida/regravada)."""
    ini, lines = L.load_ini()
    for key, value in values.items():
        if key not in L.INI_DEFAULTS:
            return {"error": f"gow3.ini key not part of the port contract: {key}"}
        if key in L.INI_FLAGS:
            ini[key] = "1" if value in (True, "1", 1) else "0"
        else:
            ini[key] = str(value)
    L.save_ini({key: ini[key] for key in values}, lines)
    return {"ok": True, "ini": dict(sorted(L.load_ini()[0].items()))}


def cmd_set_app(values: dict) -> dict:
    app = app_settings()
    for key, value in values.items():
        if key in MUSIC_KEYS or key in L.APP_DEFAULTS:
            app[key] = value
        else:
            return {"error": f"settings.json key not part of the launcher contract: {key}"}
    save_app(app)
    return {"ok": True}


def cmd_set_game_patches(names: list) -> dict:
    app = app_settings()
    title_id, profile = L.game_profile_of(meta_dir(app))
    if not title_id:
        return {"error": "Pasta do jogo não configurada."}
    app.setdefault("game_patches", {})[title_id] = [str(n) for n in names]
    save_app(app)
    return {"ok": True}


def cmd_set_external_patches(enabled: list, disabled: list) -> dict:
    """Atualiza SÓ as chaves visíveis na versão atual do jogo, preservando as
    seleções de outras versões/arquivos (mesma semântica do Tkinter collect())."""
    chosen = L.load_json(L.DATA_DIR / "patches.json", {})
    visible = set(str(k) for k in enabled) | set(str(k) for k in disabled)
    old_enabled = set(chosen.get("enabled", []))
    old_disabled = set(chosen.get("disabled", []))
    chosen["enabled"] = sorted((set(str(k) for k in enabled) | (old_enabled - visible))
                               & (old_enabled | set(str(k) for k in enabled)))
    chosen["disabled"] = sorted((set(str(k) for k in disabled) | (old_disabled - visible))
                                & (old_disabled | set(str(k) for k in disabled)))
    (L.DATA_DIR / "patches.json").write_text(json.dumps(chosen, indent=2), encoding="utf-8")
    return {"ok": True}


def cmd_mods_set(order: list, disabled: list) -> dict:
    (L.DATA_DIR / "mods.json").write_text(json.dumps(
        {"order": [str(n) for n in order], "disabled": [str(n) for n in disabled]}, indent=2),
        encoding="utf-8")
    return {"ok": True}


def cmd_preset(name: str, op: str) -> dict:
    name = str(name).strip()
    presets = L.load_json(L.MOD_PRESETS, {})
    if op == "save":
        if not name:
            return {"error": "Dê um nome ao preset."}
        saved = L.load_json(L.DATA_DIR / "mods.json", {})
        presets[name] = saved
        L.MOD_PRESETS.write_text(json.dumps(presets, indent=2), encoding="utf-8")
        return {"ok": True, "presets": sorted(presets)}
    if op == "delete":
        presets.pop(name, None)
        L.MOD_PRESETS.write_text(json.dumps(presets, indent=2), encoding="utf-8")
        return {"ok": True, "presets": sorted(presets)}
    if op == "load":
        from mods import apply_preset
        preset = presets.get(name)
        if not isinstance(preset, dict):
            return {"error": "Preset não encontrado."}
        app = app_settings()
        from mods import discover
        available = discover(Path(app.get("mods_dir") or L.DATA_DIR / "mods"))
        order, disabled = apply_preset(preset, list(available))
        return cmd_mods_set(order, disabled)
    return {"error": f"unknown preset op: {op}"}


def cmd_backup_restore(name: str) -> dict:
    import save_backup
    if game_running():
        return {"error": "Feche o jogo antes de restaurar saves."}
    name = str(name)
    app = app_settings()
    user = Path(app.get("user_dir") or L.DATA_DIR / "user")
    names = save_backup.list_backups(user)
    if name not in names:
        return {"error": "Backup não encontrado."}
    try:
        safety = save_backup.restore(user, name)
    except (OSError, ValueError) as error:
        return {"error": f"Não foi possível restaurar: {error}"}
    return {"ok": True, "safety": safety.name if safety else None,
            "names": save_backup.list_backups(user)}


def cmd_controls_set(key: dict, pad: dict, pad_style: str) -> dict:
    """Mesma semântica do Tkinter control_changes(): casefold() para comparação,
    só botões previstos em CONTROLS, só valores que diferem do padrão, e o
    mapeamento vazio é preservado para botões fixos (touchpad_left, L2, R2)."""
    app = app_settings()
    if pad_style not in L.PAD_STYLES:
        return {"error": "pad_style inválido"}
    app["pad_style"] = pad_style
    controls = {"key": {}, "pad": {}}
    valid_buttons = {b.casefold(): (b, k, p) for b, k, p in L.CONTROLS}
    for kind, values in (("key", key), ("pad", pad)):
        if not isinstance(values, dict):
            continue
        column = 1 if kind == "key" else 2
        for button, value in values.items():
            value = str(value).strip()
            if not value:
                continue
            lookup = valid_buttons.get(str(button).casefold())
            if lookup is None:
                continue  # botão não previsto em CONTROLS: ignora
            _, default_key, default_pad = lookup
            default_value = default_key if kind == "key" else default_pad
            if not default_value:
                continue  # botão fixo (sem mapeamento nesta coluna): não grava
            if value.casefold() != default_value.casefold():
                controls[kind][lookup[0]] = value  # grava o nome canônico do botão
    app["controls"] = controls
    save_app(app)
    return {"ok": True}


def cmd_clear_cache() -> dict:
    import shutil
    if game_running():
        return {"error": "Feche o jogo antes de limpar o cache."}
    app = app_settings()
    cache = Path(app.get("user_dir") or L.DATA_DIR / "user") / "cache"
    shutil.rmtree(cache, ignore_errors=True)
    return {"ok": True}


def cmd_update_check() -> dict:
    try:
        version, url, page = L.latest_release()
    except (OSError, ValueError, KeyError) as error:
        return {"error": f"Não foi possível verificar atualizações: {error}"}
    newer = L.version_tuple(version) > L.version_tuple(L.VERSION)
    return {"current": L.VERSION, "latest": version, "url": url, "page": page, "newer": newer}


def cmd_resolve_path(name: str) -> dict:
    """Resolve um nome relativo para o caminho real usado pelo backend
    (gow3.ini → GOW3_CONFIG; user → DATA_DIR/user; port → PORT_DIR)."""
    name = name.strip().lower()
    if name in ("gow3.ini", "ini"):
        return {"path": str(L.ini_path())}
    if name in ("user", "user_dir", "saves", "saves folder"):
        return {"path": str(L.DATA_DIR / "user")}
    if name in ("port", "port folder", "root"):
        return {"path": str(L.PORT_DIR)}
    if name in ("mods", "mods folder"):
        return {"path": str(L.DATA_DIR / "mods")}
    if name in ("patches", "patches folder"):
        return {"path": str(_resolve_patches_dir(app_settings()))}
    return {"path": str(L.DATA_DIR)}


def cmd_log_read() -> dict:
    sources = []
    for label, path in (("execução", RUN_LOG),):
        try:
            text = Path(path).read_text(encoding="utf-8", errors="replace")
            sources.append({"name": label, "path": str(path), "text": text[-12000:]})
        except OSError:
            pass
    return {"sources": sources, "running": game_running()}


def _check_play_prerequisites(app: dict) -> str | None:
    """As validações que o Tkinter faz antes de iniciar (Launcher.play), com mensagens
    acionáveis em pt-BR. Retorna None quando pode iniciar."""
    import os as _os
    if _os.environ.get("GOW3_CINEMATIC_SKIP_GAME_CHECK") == "1":
        return None  # apenas para testes de integração com processo substituto
    folder = meta_dir(app)
    if not L.game_info(folder):
        return "Pasta do jogo não configurada ou sem eboot.bin válido (configure na página Jogo)."
    try:
        source = L.system_files_beside(folder)
        if source:
            return (f"Arquivos de sistema de uma extração PKG encontrados em {source}, "
                    "fora de sce_sys. Copie-os para a pasta sce_sys do jogo "
                    "(o launcher Tkinter faz esta adoção automaticamente).")
    except Exception:
        pass
    missing = L.missing_game_files(app.get("game_dir") or ".")
    if missing:
        listed = '\n'.join(str(m[0] if isinstance(m, tuple) else m) for m in missing[:10])
        return ("O dump do jogo está incompleto — arquivos ausentes ou vazios:"
                + '\n' + listed)
    update_dir = app.get("update_dir") or ""
    if update_dir:
        if L.same_folder(update_dir, app.get("game_dir") or "."):
            return ("Use pastas separadas para o jogo e para a atualização, "
                    "ou deixe a atualização vazia.")
        missing = L.missing_game_files(update_dir, L.REQUIRED_UPDATE_FILES)
        if missing:
            listed = ", ".join(str(m[0] if isinstance(m, tuple) else m) for m in missing[:8])
            return (f"A pasta da atualização está incompleta (faltam: {listed}). "
                    "Ela precisa de eboot.bin e sce_sys.")
    if not L.find_tool("gow3-probe.exe"):
        return ("gow3-probe.exe não encontrado em out/ ou bin/ do port — "
                "compile o port (bash build.sh) ou use uma build empacotada.")
    return None


def prepare_play() -> dict:
    """Valida os pré-requisitos e devolve a ESPECIFICAÇÃO de execução (comando, cwd,
    env, arquivos de ciclo) para o RUST spawnar e supervisionar por eventos. A ponte
    NÃO cria mais processos aqui: um único worker persistente atende este pedido e o
    acompanhamento do fim da sessão é orientado a eventos (Job Object de sessão)."""
    import os
    app = app_settings()
    problem = _check_play_prerequisites(app)
    if problem:
        return {"error": problem}
    # comando real do port — ou substituto declarado por teste de integração
    if os.environ.get("GOW3_CINEMATIC_RUN_CMD"):
        command = json.loads(os.environ["GOW3_CINEMATIC_RUN_CMD"])
        cwd = os.environ.get("GOW3_CINEMATIC_RUN_CWD") or str(L.PORT_DIR)
        env = dict(os.environ)
    else:
        command = L.run_command()
        cwd = str(L.PORT_DIR)
        env = L.game_environment(app)
    # Discord Rich Presence: decisão DEFINITIVA do mantenedor — desativado neste
    # launcher EM TODA partida, mesmo que um settings.json legado traga
    # discord_rpc=true (a preferência NÃO é apagada nem reescrita; só o ambiente
    # desta sessão é forçado — o discord_presence.py OFICIAL se autodesativa
    # com GOW3_DISCORD='0', sem tocar em arquivo oficial).
    env["GOW3_DISCORD"] = "0"
    exit_file = RUN_PID.with_name("gow3-cinematic-run.exit")
    for stale in (RUN_PID, exit_file):
        try:
            stale.unlink()
        except OSError:
            pass
    return {"ok": True,
            "command": [str(part) for part in command],
            "cwd": cwd,
            "env": {str(k): str(v) for k, v in env.items()},
            "pid_file": str(RUN_PID),
            "exit_file": str(exit_file),
            "log_file": str(RUN_LOG)}


def cmd_play_status() -> dict:
    """Status da sessão (leitura de arquivos apenas — SEM processos): o Rust grava o
    pid ao iniciar e o código de saída quando o kernel anuncia o fim da sessão."""
    exit_file = RUN_PID.with_name("gow3-cinematic-run.exit")
    try:
        pid = int(RUN_PID.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        pid = 0
    running = pid_alive(pid)
    exit_code = None
    try:
        exit_code = int(exit_file.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        pass
    tail = ""
    try:
        text = RUN_LOG.read_text(encoding="utf-8", errors="replace")
        lines = [line for line in text.splitlines() if line.strip()]
        tail = '\n'.join(lines[-12:])
    except OSError:
        pass
    outcome = None
    last_line = tail.splitlines()[-1] if tail else ""
    if not running:
        if exit_code is None:
            outcome = "unknown"          # monitor não registrou (reinício/limpeza)
        elif exit_code == 0:
            outcome = "finished"
        else:
            outcome = "error"
    return {"running": running, "pid": pid or None, "exit_code": exit_code,
            "outcome": outcome, "last_line": last_line, "tail": tail}


def dispatch(request: dict) -> dict:
    """Um pedido → uma resposta. Compartilhado pelo modo single-shot e pelo worker
    persistente (serialização natural: o loop atende um pedido por vez, então
    escritas de settings.json/gow3.ini nunca correm entre si)."""
    cmd = request.get("cmd")
    try:
        if cmd == "state":
            response = cmd_state()
        elif cmd == "set_ini":
            response = cmd_set_ini(request.get("values") or {})
        elif cmd == "set_app":
            response = cmd_set_app(request.get("values") or {})
        elif cmd == "set_game_patches":
            response = cmd_set_game_patches(request.get("names") or [])
        elif cmd == "set_external_patches":
            response = cmd_set_external_patches(request.get("enabled") or [],
                                                request.get("disabled") or [])
        elif cmd == "mods_set":
            response = cmd_mods_set(request.get("order") or [], request.get("disabled") or [])
        elif cmd == "preset":
            response = cmd_preset(request.get("name", ""), request.get("op", ""))
        elif cmd == "backups_list":
            response = {"names": backups_state(app_settings())["names"]}
        elif cmd == "backup_restore":
            response = cmd_backup_restore(request.get("name", ""))
        elif cmd == "controls_set":
            response = cmd_controls_set(request.get("key") or {}, request.get("pad") or {},
                                        request.get("pad_style", "playstation"))
        elif cmd == "clear_cache":
            response = cmd_clear_cache()
        elif cmd == "update_check":
            response = cmd_update_check()
        elif cmd == "resolve_path":
            response = cmd_resolve_path(request.get("name", ""))
        elif cmd == "log_read":
            response = cmd_log_read()
        elif cmd == "prepare_play":
            response = prepare_play()
        elif cmd == "play_status":
            response = cmd_play_status()
        elif cmd == "test_sleep":
            # APENAS para testes automatizados (cargo): dorme N segundos (máx 600)
            # para exercitar o TIMEOUT do worker sem repetição de efeitos.
            import time
            seconds = min(max(float(request.get("seconds", 1)), 0.0), 600.0)
            time.sleep(seconds)
            response = {"ok": True, "slept": seconds}
        else:
            response = {"error": f"unknown command: {cmd!r}"}
    except Exception as error:  # fail loud, never half-written state
        response = {"error": f"{type(error).__name__}: {error}"}
    return response


def run_persistent() -> int:
    """Modo worker (P0): UM processo por launcher atende muitos pedidos — linha JSON
    {'seq': N, 'req': {...}} no stdin, linha {'seq': N, 'resp': {...}} no stdout, até
    o EOF. Ocioso (bloqueado no read) quando não há pedidos; o Rust reinicia apenas
    de forma limitada se morrer. Mantém a compatibilidade: sem a variável de ambiente
    o bridge continua single-shot (um pedido por processo, como nos testes)."""
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            envelope = json.loads(line)
            seq = envelope.get("seq")
            response = dispatch(envelope.get("req") or {})
        except ValueError as error:
            seq = None
            response = {"error": f"invalid JSON envelope: {error}"}
        print(json.dumps({"seq": seq, "resp": response}, ensure_ascii=False), flush=True)
    return 0


def main() -> int:
    # UTF-8 de ponta a ponta: o processo roda com pipes; sem isto o Windows usa cp1252 e
    # caracteres como '·', 'ã', 'ç' viram bytes inválidos que o Rust converte em U+FFFD.
    import os
    if os.environ.get("GOW3_BRIDGE_PERSISTENT") == "1":
        return run_persistent()
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    try:
        request = json.loads(sys.stdin.read() or "{}")
    except ValueError:
        print(json.dumps({"error": "invalid JSON request"}, ensure_ascii=False))
        return 2
    response = dispatch(request)
    print(json.dumps(response, ensure_ascii=False))
    return 2 if "error" in response else 0


if __name__ == "__main__":
    sys.exit(main())
