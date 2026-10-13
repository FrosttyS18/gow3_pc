#!/usr/bin/env python3
"""SessionStart hook of gow3-dev-guard.

Injects project context into the conversation (recognized-key JSON on stdout) and touches
nothing on disk: it only runs read-only git queries.

Emitted context: repository, branch, HEAD, baseline reference and the critical restrictions
of the current scope (AGENTS.md)."""
import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import guard_common as g  # noqa: E402

BASELINE_BRANCH = "chore/zcode-baseline"


def git(root: Path, *args: str) -> str:
    try:
        done = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True,
                              timeout=5, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.SubprocessError):
        return "?"
    return done.stdout.strip() if done.returncode == 0 else "?"


def main() -> int:
    payload = g.read_payload() or {}
    root = g.project_root(payload)
    branch = g.git_branch(root) or "?"
    origin = git(root, "remote", "get-url", "origin")
    repo = re.sub(r"\.git$", "", origin.replace("\\", "/").rstrip("/").rsplit("/", 1)[-1]) \
        if origin not in ("", "?") else "?"
    head = git(root, "rev-parse", "--short", "HEAD")
    baseline = git(root, "rev-parse", "--short", BASELINE_BRANCH) if branch != BASELINE_BRANCH else head

    context = "\n".join([
        f"[gow3-dev-guard] Repositório: {repo} · branch: {branch} · HEAD: {head}",
        f"[gow3-dev-guard] Baseline de referência: {BASELINE_BRANCH}@{baseline}"
        " (docs/DEV-BASELINE.md — use-a como referência de não-regressão).",
        "[gow3-dev-guard] Restrições críticas (AGENTS.md):",
        "  - NUNCA modifique main; trabalhe em feat/*, fix/* ou chore/*. Sem force-push.",
        "  - NUNCA altere src/, gpu/shadps4/, gpu/patches/, gpu/dlss_bridge/,"
        " gpu/shim/gow3gpu.cpp, patches/, scripts/, run.py, run.sh, third_party/ nem .git/.",
        "  - NUNCA versione arquivos proprietários (eboot.bin, sce_module/, sce_sys/,"
        " *.pkg/*.prx/*.sprx, savedata/) nem use git add -f ou GOW3_FORCE_PATCHES.",
        "  - Escopo de UI: launcher Windows (redesign pt-BR, paridade total) e tela de saves"
        " (gpu/shim/gow3_overlay.cpp, apenas visual). O menu Insert/R3+L2 está FORA do escopo.",
        "  - Toda tarefa termina com o bloco 'GOW3 — ZCODE REPORT' em um único bloco ```text"
        " (contrato completo no AGENTS.md).",
    ])
    # Recognized hook-output key only (strict schema; extra keys fail host validation).
    print(json.dumps({"additionalContext": context}, ensure_ascii=False))
    return g.PASS


if __name__ == "__main__":
    sys.exit(main())
