#!/usr/bin/env python3
"""TESTES NEGATIVOS — provar que os testes de contrato detectam regressões.

LIMITAÇÃO COMPROVADA: o exe Tauri EMBUTE o frontend no build (dist/ é copiado
para dentro do binário). Mudanças no dist/ APÓS o build não afetam o exe em
execução — os testes negativos por injeção de CSS/JS no dist/ não funcionam
na Camada B (Tauri real).

Os testes negativos são executados na CAMADA A (CI/dev server) onde o
dist/ é servido do disco. Na Camada B, a prova de detecção de regressão
é a validação REAL de conteúdo (34 verificações com conteúdo específico,
hover com movimento de ponteiro, exceções capturadas, etc.) que já reprovou
os falsos positivos do M1.8.

Uso: rodar no CI (Layer A) onde o dev server serve dist/ do disco.
"""
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(r"C:/gow3/wt-m1/launcher/cinematic")
DIST = ROOT / "dist" / "assets"
TEST = ROOT / "tests" / "test_ui.py"
BACKUP = DIST.parent / ".backup-negative"

# cada defeito: (nome, arquivo_alvo, substring_antes, substring_depois, teste_esperado)
DEFECTS = [
    ("nome_duplicado_patches_mods",
     None, None, None, "9 páginas sem duplicação"),
    ("hover_sem_crescimento",
     None, "25.65px", "18.49px", "hover aumenta fontSize"),
    ("volume_errado",
     None, "0.01", "0.05", "volume fixo"),
]


def run_test_ui():
    """Roda test_ui.py e retorna (exit_code, stdout)."""
    r = subprocess.run([sys.executable, str(TEST)],
                       capture_output=True, text=True, timeout=120,
                       cwd=str(ROOT.parents[1]))
    return r.returncode, r.stdout


def inject_css_defect(css_file, old, new):
    """Substitui no CSS compilado (dist/assets/*.css)."""
    for f in DIST.glob("*.css"):
        text = f.read_text(encoding="utf-8")
        if old in text:
            f.write_text(text.replace(old, new), encoding="utf-8")
            return True
    return False


def inject_js_defect(js_file, old, new):
    """Substitui no JS compilado (dist/assets/*.js)."""
    for f in DIST.glob("*.js"):
        text = f.read_text(encoding="utf-8")
        if old in text:
            f.write_text(text.replace(old, new, 1), encoding="utf-8")
            return True
    return False


def restore():
    """Restaura o dist do backup."""
    if BACKUP.exists():
        shutil.rmtree(DIST.parent / "assets", ignore_errors=True)
        shutil.copytree(BACKUP, DIST.parent / "assets")
        print("  [restaurado]")


def main():
    # backup do dist original
    if BACKUP.exists():
        shutil.rmtree(BACKUP)
    shutil.copytree(DIST.parent / "assets", BACKUP)
    print("backup do dist/ criado")

    results = []

    # ===== DEFECT 1: hover sem crescimento (fontSize do hover = fontSize normal) =====
    print("\n== DEFEITO 1: hover sem crescimento ==")
    restore()
    ok = inject_css_defect(None, "25.65px", "18.49px")
    if ok:
        rc, out = run_test_ui()
        detected = "hover aumenta fontSize" in out and rc != 0
        results.append(("hover_sem_crescimento", detected))
        print(f"  {'✓ DETECTADO' if detected else '✗ NÃO DETECTADO'} (rc={rc})")
    else:
        results.append(("hover_sem_crescimento", False))
        print("  ✗ não foi possível injetar")

    # ===== DEFECT 2: volume errado (0.05 em vez de 0.01) =====
    print("\n== DEFEITO 2: volume 0.05 em vez de 0.01 ==")
    restore()
    ok = inject_js_defect(None, "0.01", "0.05")
    if ok:
        rc, out = run_test_ui()
        detected = "volume fixo" in out and rc != 0
        results.append(("volume_errado", detected))
        print(f"  {'✓ DETECTADO' if detected else '✗ NÃO DETECTADO'} (rc={rc})")
    else:
        results.append(("volume_errado", False))
        print("  ✗ não foi possível injetar")

    # ===== DEFECT 3: música reinicia durante pausa (remove o guarda mayPlay) =====
    print("\n== DEFEITO 3: música reinicia (remove guarda) ==")
    restore()
    # injetar: fazer pointerdown sempre chamar play()
    ok = inject_js_defect(None,
        "if(window.__gow3Audio&&window.__gow3Audio.src&&mayPlay())",
        "if(window.__gow3Audio&&window.__gow3Audio.src)")
    if not ok:
        # tentar padrão alternativo
        ok = inject_js_defect(None, "!mutedRef.current", "true")
    if ok:
        rc, out = run_test_ui()
        detected = "pointerdown não reinicia" in out and rc != 0
        results.append(("musica_reinicia", detected))
        print(f"  {'✓ DETECTADO' if detected else '✗ NÃO DETECTADO'} (rc={rc})")
    else:
        results.append(("musica_reinicia", False))
        print("  ✗ não foi possível injetar (padrão não encontrado no bundle)")

    # ===== CONTROLE: restaurar e passar =====
    print("\n== CONTROLE: build original ==")
    restore()
    rc, out = run_test_ui()
    control_pass = rc == 0
    results.append(("controle_pass", control_pass))
    print(f"  {'✓ PASS' if control_pass else '✗ FALHA INESPERADA'} (rc={rc})")

    # ===== RESUMO =====
    print(f"\n{'='*50}")
    print("RESULTADO DOS TESTES NEGATIVOS:")
    all_ok = control_pass
    for name, detected in results[:-1]:
        status = "DETECTADO ✓" if detected else "NÃO DETECTADO ✗"
        print(f"  {name}: {status}")
        if not detected:
            all_ok = False
    print(f"  controle_pass: {'SIM' if control_pass else 'NÃO'}")

    if all_ok and all(d for _, d in results[:-1]):
        print("\nPASS: todos os defeitos foram detectados e o controle passou")
        sys.exit(0)
    else:
        print("\nFAIL: algum defeito passou sem ser detectado")
        sys.exit(1)


if __name__ == "__main__":
    main()
