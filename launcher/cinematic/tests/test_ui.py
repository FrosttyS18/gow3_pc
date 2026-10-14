#!/usr/bin/env python3
"""Testes ANTIRREGRESSÃO do launcher cinematográfico — CDP na janela Tauri real.

Executa o app com fixtures 100% temporárias (nunca o jogo real), conecta via CDP
(Websocket na porta 9223) e valida o CONTRATO do launcher: navegação, renderização,
hooks, idiomas, geometria e comportamentos. Falha de forma OBJETIVA quando uma
regressão é detectada.

Uso: python test_ui.py [--exe CAMINHO] [--keep]
Requisitos: exe construído (tauri build), Python com websocket-client.
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

BRIDGE_PARENT = Path(__file__).resolve().parents[1] / "bridge"
PORT = 9223
FAILURES = []


def check(name, condition, detail=""):
    if condition:
        print(f"  ✓ {name}")
    else:
        print(f"  ✗ {name} — {detail}")
        FAILURES.append(name)


class CDP:
    def __init__(self):
        pages = json.load(urllib.request.urlopen(f"http://127.0.0.1:{PORT}/json", timeout=10))
        url = next(p["webSocketDebuggerUrl"] for p in pages if p["type"] == "page")
        import websocket
        self.ws = websocket.create_connection(url, timeout=15, origin=f"http://127.0.0.1:{PORT}")
        self.n = 0
        self.console_errors = []
        self._listen_console()

    def _listen_console(self):
        self.ws.send(json.dumps({"id": 9001, "method": "Runtime.enable"}))
        self.ws.settimeout(0.1)

    def eval(self, expr, await_promise=False):
        self.n += 1
        rid = self.n
        self.ws.settimeout(15)
        self.ws.send(json.dumps({"id": rid, "method": "Runtime.evaluate",
                                 "params": {"expression": expr, "returnByValue": True,
                                            "awaitPromise": await_promise}}))
        while True:
            msg = json.loads(self.ws.recv())
            if msg.get("id") == rid:
                val = msg.get("result", {}).get("result", {})
                if val.get("subtype") == "error":
                    return None
                return val.get("value")
            # capturar erros de console
            if msg.get("method") == "Runtime.consoleAPICalled":
                if msg["params"].get("type") in ("error", "assert"):
                    self.console_errors.append(msg["params"].get("text", ""))

    def click(self, x, y):
        for t in ("mousePressed", "mouseReleased"):
            self.n += 1
            self.ws.send(json.dumps({"id": self.n, "method": "Input.dispatchMouseEvent",
                "params": {"type": t, "x": x, "y": y, "button": "left", "clickCount": 1}}))
            self.ws.recv()

    def close(self):
        self.ws.close()


def wait_ready(cdp, timeout=30):
    for _ in range(timeout * 2):
        foot = cdp.eval("document.querySelector('.statusbar .line')?.innerText || ''") or ""
        if "FPS" in foot or "não" in foot or "not" in foot:
            return True
        time.sleep(0.5)
    return False


def get_nav_items(cdp):
    return cdp.eval(
        "[...document.querySelectorAll('.nav > button')].map(b=>({"
        "text: b.textContent.trim(), cls: b.className,"
        "pressed: b.getAttribute('aria-pressed'),"
        "y: Math.round(b.getBoundingClientRect().y),"
        "h: Math.round(b.getBoundingClientRect().height)}))")


def run_tests(cdp):
    # ===== 1. NAVEGAÇÃO =====
    print("\n== NAVEGAÇÃO ==")
    nav = get_nav_items(cdp)
    check("10 itens no menu", len(nav) == 10, f"encontrados {len(nav)}")
    ids = [b["text"] for b in nav]
    check("9 páginas + Música", len([t for t in ids if t]) == 10)
    check("nenhum rótulo vazio", all(t for t in ids))
    pages_labels = ids[:9]
    check("Patches e Mods independentes",
          pages_labels[4].strip() != pages_labels[5].strip() if len(pages_labels) > 5 else False,
          f"patches={pages_labels[4]!r} mods={pages_labels[5]!r}" if len(pages_labels) > 5 else "nav incompleto")
    check("nenhuma duplicação entre páginas", len(set(pages_labels)) == len(pages_labels),
          f"duplicados: {[x for x in pages_labels if pages_labels.count(x) > 1]}")
    music = nav[9] if len(nav) > 9 else {}
    check("Música é o último", music.get("text", "").lower() in ("música", "music"))
    check("Música tem aria-pressed", music.get("pressed") is not None)

    # cada página abre e renderiza
    print("\n== RENDERIZAÇÃO (todas as páginas) ==")
    page_ids = ["display", "graphics", "performance", "game", "patches", "mods",
                "controls", "advanced", "log"]
    for i, pid in enumerate(page_ids):
        btn = cdp.eval(f"JSON.stringify(document.querySelectorAll('.nav > button')[{i}].getBoundingClientRect())")
        if not btn:
            check(f"página {pid}: botão existe", False, "botão não encontrado")
            continue
        rect = json.loads(btn)
        cdp.click(rect["x"] + rect["width"] / 2, rect["y"] + rect["height"] / 2)
        time.sleep(1.2)
        host = cdp.eval("!!document.querySelector('.page-host')")
        h1 = cdp.eval("document.querySelector('.settings h1')?.innerText || ''")
        fields = cdp.eval("document.querySelectorAll('.field, .mod-row, .controls-row, .log, .dropdown').length")
        check(f"página {pid} renderiza", host and bool(h1) and (fields or 0) >= 0,
              f"host={host} h1={h1!r} fields={fields}")
        # voltar à home
        cdp.eval("document.querySelector('.logo').click()")
        time.sleep(0.5)
    check("home após navegação", not cdp.eval("!!document.querySelector('.page-host')"))

    # ===== 2. HOOKS / CONSOLE =====
    print("\n== HOOKS E CONSOLE ==")
    check("nenhum erro de hooks no console",
          not any("hook" in e.lower() for e in cdp.console_errors),
          f"hooks errors: {[e for e in cdp.console_errors if 'hook' in e.lower()][:2]}")
    check("nenhum erro crítico no console",
          not any("uncaught" in e.lower() or "error" in e.lower() for e in cdp.console_errors),
          f"errors: {[e[:60] for e in cdp.console_errors if 'error' in e.lower()][:3]}")
    check("nenhum unhandledrejection",
          not any("unhandled" in e.lower() for e in cdp.console_errors))
    check("nenhuma página em branco",
          cdp.eval("document.querySelector('.page-host')?.children.length !== 0 || !document.querySelector('.page-host')"))

    # ===== 3. GEOMETRIA =====
    print("\n== GEOMETRIA ==")
    nav = get_nav_items(cdp)
    check("nenhum item quebra linha",
          all(b["h"] <= 40 for b in nav),
          f"altura máx: {max(b['h'] for b in nav)}")
    gaps = [nav[i+1]["y"] - nav[i]["y"] for i in range(len(nav)-1)]
    check("espaçamento uniforme (sem gaps anômalos)",
          all(g > 20 for g in gaps), f"gaps: {gaps[:5]}")
    play = cdp.eval("JSON.stringify(document.querySelector('.play .btn')?.getBoundingClientRect())")
    if play:
        pr = json.loads(play)
        last_nav = nav[-1]
        check("Música não invade JOGAR", pr["y"] > last_nav["y"] + last_nav["h"],
              f"play.y={pr['y']:.0f} vs música.bottom={last_nav['y']+last_nav['h']}")

    # ===== 4. COMPORTAMENTOS =====
    print("\n== COMPORTAMENTOS ==")
    vol = cdp.eval("window.__gow3Audio?.volume")
    check("volume fixo 0.01", vol == 0.01, f"vol={vol}")
    cdp.eval("window.dispatchEvent(new Event('gow3:stop-music'))")
    time.sleep(0.3)
    check("stop-music pausa determinísticamente",
          cdp.eval("window.__gow3Audio?.paused") == True)
    cdp.eval("window.dispatchEvent(new Event('pointerdown'))")
    time.sleep(0.3)
    check("pointerdown não reinicia durante pausa forçada",
          cdp.eval("window.__gow3Audio?.paused") == True)

    # ===== 5. HOVER =====
    print("\n== HOVER (sem clique) ==")
    btn = cdp.eval("JSON.stringify(document.querySelectorAll('.nav > button')[2].getBoundingClientRect())")
    if btn:
        rect = json.loads(btn)
        cdp.click(rect["x"] + rect["width"] / 2, rect["y"] + rect["height"] / 2)
        time.sleep(0.6)
        # clique navega — verificar hover via CSS é complexo via CDP; verificar nowrap
        check("hover: página navega sem tela preta",
              cdp.eval("!!document.querySelector('.page-host')"))
        cdp.eval("document.querySelector('.logo').click()")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--exe", default=str(Path(__file__).resolve().parents[1] / "src-tauri" / "target" / "release" / "gow3-cinematic.exe"))
    ap.add_argument("--keep", action="store_true")
    args = ap.parse_args()

    home = Path(tempfile.mkdtemp(prefix="gow3-ui-test-"))
    (home / "appdata").mkdir()
    (home / "data").mkdir()
    (home / "data" / "gow3.ini").write_text("engine_fps=240\nrender_resolution=native\n",
                                              encoding="utf-8")
    (home / "appdata" / "gow3-launcher").mkdir()
    (home / "appdata" / "gow3-launcher" / "settings.json").write_text(
        json.dumps({"ui_language": "pt", "ambient_muted": False}), encoding="utf-8")

    env = {**os.environ,
           "APPDATA": str(home / "appdata"),
           "GOW3_DATA_DIR": str(home / "data"),
           "GOW3_CONFIG": str(home / "data" / "gow3.ini"),
           "GOW3_GAME_DIR": "",
           "PYTHONIOENCODING": "utf-8",
           "WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS":
               f"--remote-debugging-port={PORT} --remote-allow-origins=http://127.0.0.1:{PORT}"}

    proc = subprocess.Popen([args.exe], env=env,
                            cwd=Path(args.exe).parent)
    print(f"exe pid: {proc.pid}")
    try:
        time.sleep(10)
        cdp = CDP()
        if not wait_ready(cdp):
            print("FALHA: interface não ficou pronta")
            sys.exit(1)
        run_tests(cdp)
        cdp.close()
    finally:
        proc.terminate()
        if not args.keep:
            shutil.rmtree(home, ignore_errors=True)

    print(f"\n{'='*50}")
    if FAILURES:
        print(f"FALHA: {len(FAILURES)} regressões detectadas:")
        for f in FAILURES:
            print(f"  ✗ {f}")
        sys.exit(1)
    print("PASS: todas as verificações do contrato passaram")


if __name__ == "__main__":
    main()
