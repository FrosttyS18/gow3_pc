#!/usr/bin/env python3
"""Typed JSON bridge between the cinematic launcher (Tauri/React) and the port's real logic.

The Python layer stays the single owner of the port's rules: this module only imports
gow3_launcher_win as a library (it is import-safe: the Tkinter classes receive the tk
modules as arguments and nothing graphical happens at import time) and exposes a small
request/response protocol — one JSON object on stdin, one JSON object on stdout.

Commands:
  state                -> app settings, gow3.ini values, real game status and the footer summary
  set_ini  {values}    -> writes gow3.ini through save_ini (comments/unknown keys preserved)
  set_app  {values}    -> merges keys into settings.json (launcher format preserved)
  play                -> starts run.py exactly like the Tkinter PLAY button (same env/cwd)
  play_status {log}    -> is the started process still running / exit code / output tail

No Tkinter window is ever created; no user data is touched beyond the launcher's own
configuration files, and those only through the same functions the Tkinter launcher uses.
"""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # launcher/ on the path
import gow3_launcher_win as L  # noqa: E402  (the port's launcher, as a library)

MUSIC_KEYS = ("ambient_volume", "ambient_muted", "ambient_file")
RUN_LOG = Path(tempfile.gettempdir()) / "gow3-cinematic-run.log"
RUN_PID = Path(tempfile.gettempdir()) / "gow3-cinematic-run.pid"


def choice_labels(pairs):
    return [{"value": value, "label": texts[0]} for value, texts in pairs]


def app_settings() -> dict:
    return {**L.APP_DEFAULTS, **L.load_json(L.CONFIG_FILE, {})}


def game_state(app: dict, ini: dict) -> dict:
    folder = L.meta_folder(app.get("game_dir") or ".", app.get("update_dir") or "")
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
            missing = [m[0] if isinstance(m, tuple) else str(m)
                       for m in (L.missing_game_files(folder) or [])][:8]
    except Exception:
        missing = []
    return {
        "found": bool(info),
        "folder": folder,
        "title_id": title_id,
        "patch_profile": bool(profile),
        "summary": summary,
        "missing_files": missing,
    }


def music_state(app: dict) -> dict:
    art = L.DATA_DIR / "launcher" / "cinematic" / "public" / "art"
    default = next((str(p) for name in ("ambient.mp3", "intro_launcher.mp3")
                    for p in [art / name] if p.is_file()), None)
    return {
        "default_path": default,
        "file": app.get("ambient_file") or "",
        "volume": float(app.get("ambient_volume", 0.55)),
        "muted": bool(app.get("ambient_muted", False)),
    }


def cmd_state() -> dict:
    app, (ini, _lines) = app_settings(), L.load_ini()
    return {
        "app": {k: app[k] for k in sorted(app) if isinstance(app[k], (str, int, float, bool))},
        "ini": dict(sorted(ini.items())),
        "game": game_state(app, ini),
        "music": music_state(app),
        "choices": {
            "display_mode": choice_labels(L.DISPLAY_MODES),
            "render_resolution": choice_labels(L.RESOLUTION_CHOICES),
            "engine_fps": choice_labels(L.ENGINE_FPS_CHOICES),
            "fps_limit": choice_labels(L.FPS_LIMITS),
        },
    }


def cmd_set_ini(values: dict) -> dict:
    ini, lines = L.load_ini()
    for key, value in values.items():
        if key not in L.INI_DEFAULTS:
            return {"error": f"gow3.ini key not part of the port contract: {key}"}
        if key in L.INI_FLAGS:
            ini[key] = "1" if value in (True, "1", 1) else "0"
        elif key == "sharpness":
            ini[key] = f"{float(value):.2f}"
        else:
            ini[key] = str(value)
    L.save_ini({key: ini[key] for key in L.INI_DEFAULTS}, lines)
    return {"ok": True, "ini": dict(sorted(L.load_ini()[0].items()))}


def cmd_set_app(values: dict) -> dict:
    app = app_settings()
    for key, value in values.items():
        if key in MUSIC_KEYS or key in L.APP_DEFAULTS:
            app[key] = value
        else:
            return {"error": f"settings.json key not part of the launcher contract: {key}"}
    L.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    L.CONFIG_FILE.write_text(json.dumps(app, indent=2, ensure_ascii=False), encoding="utf-8")
    return {"ok": True}


def cmd_play() -> dict:
    app = app_settings()
    if not L.game_info(L.meta_folder(app.get("game_dir") or ".", app.get("update_dir") or "")):
        return {"error": "Pasta do jogo não configurada ou sem eboot.bin válido."}
    try:
        log = open(RUN_LOG, "w", encoding="utf-8", errors="replace")
    except OSError as error:
        return {"error": f"Não foi possível abrir o log de execução: {error}"}
    try:
        # Detached: the game outlives this bridge process exactly as it outlives the
        # Tkinter launcher (which also never keeps run.py in a Windows Job Object).
        process = subprocess.Popen(L.run_command(), cwd=str(L.PORT_DIR),
                                   env=L.game_environment(app), stdin=subprocess.DEVNULL,
                                   stdout=log, stderr=subprocess.STDOUT,
                                   creationflags=getattr(subprocess, "DETACHED_PROCESS", 0)
                                   | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
    except OSError as error:
        log.close()
        return {"error": f"Não foi possível iniciar: {error}"}
    log.close()  # the child holds its own inherited handle
    RUN_PID.write_text(str(process.pid), encoding="utf-8")
    return {"ok": True, "pid": process.pid, "log": str(RUN_LOG)}


def cmd_play_status() -> dict:
    """Cross-process liveness (the play came from a previous, already-exited bridge run):
    the PID file plus the run log; a finished run is classified by its log's tail."""
    try:
        pid = int(RUN_PID.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        pid = 0
    running = False
    if pid:
        try:
            os.kill(pid, 0)  # signal 0 on Windows: probes liveness only
            running = True
        except OSError:
            running = False
    tail = ""
    try:
        tail = RUN_LOG.read_text(encoding="utf-8", errors="replace")[-2000:]
    except OSError:
        pass
    outcome = None
    if not running and tail:
        lowered = tail.lower()
        if "traceback" in lowered or "não foi possível" in lowered or "could not" in lowered:
            outcome = "error"
        elif pid:
            outcome = "finished"
    return {"running": running, "pid": pid or None, "outcome": outcome, "tail": tail}


def main() -> int:
    try:
        request = json.loads(sys.stdin.read() or "{}")
    except ValueError:
        print(json.dumps({"error": "invalid JSON request"}))
        return 2
    cmd = request.get("cmd")
    try:
        if cmd == "state":
            response = cmd_state()
        elif cmd == "set_ini":
            response = cmd_set_ini(request.get("values") or {})
        elif cmd == "set_app":
            response = cmd_set_app(request.get("values") or {})
        elif cmd == "play":
            response = cmd_play()
        elif cmd == "play_status":
            response = cmd_play_status()
        else:
            response = {"error": f"unknown command: {cmd!r}"}
    except Exception as error:  # fail loud to the caller, never half-written state
        response = {"error": f"{type(error).__name__}: {error}"}
    print(json.dumps(response, ensure_ascii=False))
    return 2 if "error" in response else 0


if __name__ == "__main__":
    sys.exit(main())
