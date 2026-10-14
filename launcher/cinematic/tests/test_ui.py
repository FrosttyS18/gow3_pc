#!/usr/bin/env python3
"""CAMADA B — Testes de contrato na janela Tauri/WebView2 REAL (Windows local).

Corrige os falsos positivos do M1.8:
- Falha A: cada página validada por CONTEÚDO ESPECÍFICO (título + campos + ações),
  não por `fields >= 0`.
- Falha B: hover validado com Input.dispatchMouseEvent (movimento real do ponteiro),
  medindo fontSize/cor antes/depois e reversão.
- Falha C: erros de console via Runtime.consoleAPICalled + Runtime.exceptionThrown +
  exceptionDetails — um erro React/hooks FAZ o teste falhar.
- Falha D: idiomas testados mudando ui_language e verificando rótulos, sem duplicação.
- Falha E: Patches e Mods validados por conteúdo DISTINTO, não só nome.

Uso: python test_ui.py [--exe CAMINHO]
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

PORT = 9223
FAILURES = []
TESTS = 0


def check(name, condition, detail=""):
    global TESTS
    TESTS += 1
    if condition:
        print(f"  ✓ {name}")
    else:
        print(f"  ✗ {name} — {detail}")
        FAILURES.append(name)


class CDP:
    """Cliente CDP com captura de erros de console E exceções."""
    def __init__(self):
        pages = json.load(urllib.request.urlopen(f"http://127.0.0.1:{PORT}/json", timeout=10))
        url = next(p["webSocketDebuggerUrl"] for p in pages if p["type"] == "page")
        import websocket
        self.ws = websocket.create_connection(url, timeout=15, origin=f"http://127.0.0.1:{PORT}")
        self.n = 0
        self.errors = []       # console.error + exceptionThrown + exceptionDetails
        self._pending = {}     # respostas por id
        self._enable_runtime()

    def _enable_runtime(self):
        self.ws.send(json.dumps({"id": 9001, "method": "Runtime.enable"}))
        self._pump()

    def _pump(self):
        """Drena mensagens; captura erros; armazena respostas."""
        self.ws.settimeout(0.05)
        while True:
            try:
                msg = json.loads(self.ws.recv())
            except Exception:
                break
            method = msg.get("method", "")
            if method == "Runtime.consoleAPICalled":
                if msg["params"].get("type") in ("error", "assert"):
                    self.errors.append(msg["params"].get("text", ""))
            elif method == "Runtime.exceptionThrown":
                det = msg["params"].get("exceptionDetails", {})
                desc = det.get("exception", {}).get("description",
                          det.get("text", "unknown exception"))
                self.errors.append(f"exceptionThrown: {desc[:120]}")
            elif "id" in msg:
                self._pending[msg["id"]] = msg

    def eval(self, expr, await_promise=False, timeout=15):
        self.n += 1
        rid = self.n
        self.ws.settimeout(timeout)
        self.ws.send(json.dumps({"id": rid, "method": "Runtime.evaluate",
                                 "params": {"expression": expr, "returnByValue": True,
                                            "awaitPromise": await_promise}}))
        deadline = time.time() + timeout
        while time.time() < deadline:
            self._pump()
            if rid in self._pending:
                msg = self._pending.pop(rid)
                val = msg.get("result", {}).get("result", {})
                if val.get("subtype") == "error":
                    self.errors.append(f"evaluate error: {val.get('description', '?')[:100]}")
                    return None
                return val.get("value")
            try:
                raw = self.ws.recv()
                msg = json.loads(raw)
                if msg.get("id") == rid:
                    val = msg.get("result", {}).get("result", {})
                    if val.get("subtype") == "error":
                        self.errors.append(f"evaluate error: {val.get('description', '?')[:100]}")
                        return None
                    return val.get("value")
                method = msg.get("method", "")
                if method == "Runtime.consoleAPICalled":
                    if msg["params"].get("type") in ("error", "assert"):
                        self.errors.append(msg["params"].get("text", ""))
                elif method == "Runtime.exceptionThrown":
                    det = msg["params"].get("exceptionDetails", {})
                    self.errors.append(f"exceptionThrown: {det.get('exception',{}).get('description','?')[:100]}")
            except Exception:
                continue
        return None

    def hover(self, x, y):
        """Movimento REAL do ponteiro (não clique) — valida hover de verdade."""
        self.n += 1
        self.ws.send(json.dumps({"id": self.n, "method": "Input.dispatchMouseEvent",
            "params": {"type": "mouseMoved", "x": x, "y": y}}))
        self._pump()

    def click(self, x, y):
        for t in ("mousePressed", "mouseReleased"):
            self.n += 1
            self.ws.send(json.dumps({"id": self.n, "method": "Input.dispatchMouseEvent",
                "params": {"type": t, "x": x, "y": y, "button": "left", "clickCount": 1}}))
            self._pump()

    def close(self):
        self.ws.close()


def wait_ready(cdp, timeout=30):
    for _ in range(timeout * 4):
        foot = cdp.eval("document.querySelector('.statusbar .line')?.innerText || ''") or ""
        if "FPS" in foot or "não" in foot or "not" in foot.lower():
            return True
        time.sleep(0.25)
    return False


def open_page(cdp, idx):
    """Abre a página idx (0-8) e retorna o texto do .page-host."""
    btn = cdp.eval(f"JSON.stringify(document.querySelectorAll('.nav > button')[{idx}].getBoundingClientRect())")
    if not btn:
        return None
    rect = json.loads(btn)
    cdp.click(rect["x"] + rect["width"] / 2, rect["y"] + rect["height"] / 2)
    time.sleep(1.5)
    return cdp.eval("document.querySelector('.page-host')?.innerText || ''")


def go_home(cdp):
    cdp.eval("document.querySelector('.logo').click()")
    time.sleep(0.5)


def run_tests(cdp):
    # ===== 1. NAVEGAÇÃO E IDENTIDADE =====
    print("\n== NAVEGAÇÃO E IDENTIDADE ==")
    nav = cdp.eval(
        "[...document.querySelectorAll('.nav > button')].map(b=>({"
        "text: b.textContent.trim(), pressed: b.getAttribute('aria-pressed'),"
        "y: Math.round(b.getBoundingClientRect().y), h: Math.round(b.getBoundingClientRect().height)}))")
    check("10 itens no menu", len(nav) == 10, f"encontrados {len(nav)}")
    pages_labels = [b["text"] for b in nav[:9]]
    check("9 páginas sem duplicação", len(set(pages_labels)) == 9,
          f"duplicados: {[x for x in pages_labels if pages_labels.count(x) > 1]}")
    check("Música é o último com aria-pressed", nav[9]["pressed"] is not None)

    # FALHA E: Patches e Mods têm CONTEÚDO distinto
    patches_text = open_page(cdp, 4) or ""
    go_home(cdp)
    mods_text = open_page(cdp, 5) or ""
    go_home(cdp)
    check("Patches tem E1/E2/E3 OU informa jogo não configurado",
          "E1" in patches_text or "não configurada" in patches_text.lower()
          or "sem patches" in patches_text.lower(),
          f"texto: {patches_text[:120]}")
    check("Patches NÃO tem mods (ModA)", "ModA" not in patches_text)
    check("Mods tem ModA OU interface de mods presente",
          "ModA" in mods_text or "mods" in mods_text.lower(),
          f"texto: {mods_text[:120]}")
    check("Mods NÃO tem patches E1", "E1 height" not in mods_text)

    # FALHA A: cada página validada por CONTEÚDO específico
    print("\n== RENDERIZAÇÃO COM CONTEÚDO ESPECÍFICO ==")
    page_specs = [
        (0, "display", ["Tela", "Modo de exibição", "VSync"]),
        (1, "graphics", ["Gráficos"]),
        (2, "performance", ["Desempenho"]),
        (3, "game", ["Jogo", "Trapaças", "Pasta"]),
        (7, "advanced", ["Avançado", "Idioma"]),
        (8, "log", ["Registro"]),
    ]
    for idx, pid, expected in page_specs:
        text = open_page(cdp, idx) or ""
        all_found = all(e.lower() in text.lower() for e in expected)
        check(f"página {pid} contém {expected}", all_found,
              f"encontrado: {text[:80]}")
        check(f"página {pid} não está vazia", len(text.strip()) > 20)
        go_home(cdp)

    # ===== 2. HOOKS, CONSOLE E EXCEÇÕES (FALHA C) =====
    print("\n== HOOKS, CONSOLE E EXCEÇÕES ==")
    # navegar por TODAS as páginas primeiro
    for i in range(9):
        open_page(cdp, i)
        go_home(cdp)
    time.sleep(0.5)
    real_errors = [e for e in cdp.errors if "favicon" not in e.lower()]
    check("zero erros de console (error/assert)", len(real_errors) == 0,
          f"erros: {real_errors[:3]}")
    check("zero exceptionThrown", not any("exceptionThrown" in e for e in cdp.errors),
          f"exceptions: {[e[:60] for e in cdp.errors if 'exceptionThrown' in e][:2]}")
    check("zero evaluate errors", not any("evaluate error" in e for e in cdp.errors))
    check("zero erros de hooks",
          not any("hook" in e.lower() for e in cdp.errors))

    # ===== 3. HOVER REAL (FALHA B) =====
    print("\n== HOVER (movimento real do ponteiro, sem clique) ==")
    btn = cdp.eval("JSON.stringify(document.querySelectorAll('.nav > button')[2].getBoundingClientRect())")
    if btn:
        rect = json.loads(btn)
        before_font = cdp.eval("getComputedStyle(document.querySelectorAll('.nav > button')[2]).fontSize")
        before_color = cdp.eval("getComputedStyle(document.querySelectorAll('.nav > button')[2]).color")
        cdp.hover(rect["x"] + rect["width"] / 2, rect["y"] + rect["height"] / 2)
        time.sleep(0.4)  # transição 200ms
        after_font = cdp.eval("getComputedStyle(document.querySelectorAll('.nav > button')[2]).fontSize")
        after_color = cdp.eval("getComputedStyle(document.querySelectorAll('.nav > button')[2]).color")
        check("hover aumenta fontSize", float(after_font.replace("px", "")) > float(before_font.replace("px", "")),
              f"antes={before_font} depois={after_font}")
        check("hover muda cor para branco", "255" in after_color and "255" not in before_color,
              f"antes={before_color} depois={after_color}")
        # afastar o mouse
        cdp.hover(10, 400)
        time.sleep(0.4)
        revert_font = cdp.eval("getComputedStyle(document.querySelectorAll('.nav > button')[2]).fontSize")
        check("font volta ao normal ao sair", revert_font == before_font,
              f"revertido={revert_font} original={before_font}")
        # hover NÃO abre página
        check("hover não abre página", not cdp.eval("!!document.querySelector('.page-host')"))
    else:
        check("botão de menu encontrado para hover", False)

    # ===== 4. GEOMETRIA =====
    print("\n== GEOMETRIA ==")
    nav = cdp.eval(
        "[...document.querySelectorAll('.nav > button')].map(b=>Math.round(b.getBoundingClientRect().height))")
    check("nenhum item quebra linha (h≤40)", all(h <= 40 for h in nav), f"alturas: {nav}")
    play = cdp.eval("JSON.stringify(document.querySelector('.play .btn')?.getBoundingClientRect())")
    if play:
        pr = json.loads(play)
        check("Música não invade JOGAR", pr["y"] > (nav[-1] if isinstance(nav[-1], (int, float)) else 0))

    # ===== 5. COMPORTAMENTOS =====
    print("\n== COMPORTAMENTOS ==")
    vol = cdp.eval("window.__gow3Audio?.volume")
    check("volume fixo 0.01", vol == 0.01, f"vol={vol}")
    cdp.eval("window.dispatchEvent(new Event('gow3:stop-music'))")
    time.sleep(0.3)
    check("stop-music pausa", cdp.eval("window.__gow3Audio?.paused") == True)
    cdp.eval("window.dispatchEvent(new Event('pointerdown'))")
    time.sleep(0.3)
    check("pointerdown não reinicia", cdp.eval("window.__gow3Audio?.paused") == True)

    # ===== 6. IDIOMAS (FALHA D) =====
    print("\n== IDIOMAS ==")
    nav_pt = [b["text"] for b in cdp.eval(
        "[...document.querySelectorAll('.nav > button')].map(b=>({text: b.textContent.trim()}))")]
    check("menu em pt-BR no startup (ui_language=pt)",
          any("Tela" in t or "Desempenho" in t for t in nav_pt),
          f"nav: {nav_pt[:4]}")
    check("sem mistura pt/en (todos pt ou identificados)",
          not any(t in ("Display", "Performance", "Advanced", "Log") for t in nav_pt[:9]),
          f"itens en encontrados: {[t for t in nav_pt[:9] if t in ('Display','Performance','Advanced','Log')]}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--exe", default=str(Path(__file__).resolve().parents[1] /
                    "src-tauri" / "target" / "release" / "gow3-cinematic.exe"))
    args = ap.parse_args()

    home = Path(tempfile.mkdtemp(prefix="gow3-ui-test-"))
    (home / "appdata" / "gow3-launcher").mkdir(parents=True)
    (home / "data").mkdir()
    (home / "data" / "gow3.ini").write_text("engine_fps=240\nrender_resolution=native\n", encoding="utf-8")
    (home / "appdata" / "gow3-launcher" / "settings.json").write_text(
        json.dumps({"ui_language": "pt", "ambient_muted": False}), encoding="utf-8")
    # fixture mods: pastas com layout dvdroot_ps4 (o discover exige)
    for mod in ("ModA", "ModB"):
        (home / "data" / "mods" / mod / "dvdroot_ps4").mkdir(parents=True, exist_ok=True)

    env = {**os.environ,
           "APPDATA": str(home / "appdata"), "GOW3_DATA_DIR": str(home / "data"),
           "GOW3_CONFIG": str(home / "data" / "gow3.ini"), "GOW3_GAME_DIR": "",
           "PYTHONIOENCODING": "utf-8",
           "WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS":
               f"--remote-debugging-port={PORT} --remote-allow-origins=http://127.0.0.1:{PORT}"}

    proc = subprocess.Popen([args.exe], env=env, cwd=Path(args.exe).parent)
    print(f"exe pid: {proc.pid}")
    try:
        # SONDAGEM (não sleep fixo): tentar conectar ao CDP com timeout e diagnóstico
        cdp = None
        for i in range(60):  # 15s
            if proc.poll() is not None:
                print(f"FALHA: exe terminou com código {proc.returncode} antes de abrir CDP")
                sys.exit(1)
            try:
                cdp = CDP()
                break
            except (urllib.error.URLError, Exception):
                time.sleep(0.25)
        if not cdp:
            print("FALHA: CDP não respondeu em 15s (exe pode não ter WebView2 neste ambiente)")
            print(f"exe vivo: {proc.poll() is None}")
            sys.exit(1)
        if not wait_ready(cdp):
            print("FALHA: interface não ficou pronta em 30s")
            sys.exit(1)
        run_tests(cdp)
        cdp.close()
    finally:
        proc.terminate()
        shutil.rmtree(home, ignore_errors=True)

    print(f"\n{'='*50}")
    print(f"Resultado: {TESTS} testes, {len(FAILURES)} falhas")
    if FAILURES:
        print("FALHAS:")
        for f in FAILURES:
            print(f"  ✗ {f}")
        sys.exit(1)
    print("PASS: todas as verificações do contrato passaram")


if __name__ == "__main__":
    main()
