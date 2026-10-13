"""Shared logic of the gow3-dev-guard hooks.

Deterministic only: every decision is a regex/path/git-query evaluated in code.
No LLM, no network, no file writes (except the Stop hook's loop-counter state file).

I/O contract with the ZCode hook runner (see AGENTS.md and the plugin README):
  - stdin:  the event payload as JSON (invalid JSON => fail-open, exit 0, warning on stderr)
  - stdout: empty (we deliberately rely on exit codes; stdout would be parsed as a
            strict JSON schema and a wrong key would mark the hook as failed)
  - exit 0: pass;  exit 2: deliberate block (reason on stderr);  other: never raised
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

PASS = 0
BLOCK = 2

# Paths inside the repository that a UI/harness task must never modify (AGENTS.md rules 2, 4, 5).
# Relative POSIX prefixes; the plugin's own directory, docs/, launcher/, tests/, packaging/ and
# gpu/shim/gow3_overlay.cpp (approved save-screen scope) stay writable.
PROTECTED_PREFIXES = (
    "src/",                # runtime C (PS4 service emulation, loader)
    "gpu/shadps4/",        # shadPS4 video core and recompiler
    "gpu/patches/",        # patches applied to the FSR-Vulkan submodule
    "gpu/dlss_bridge/",    # NVIDIA DLSS bridge
    "gpu/shim/gow3gpu.cpp",# C bridge between runtime and overlay
    "patches/",            # built-in patch XMLs (eboot byte patches)
    "scripts/",            # game orchestration incl. the patch whitelist (patches.py)
    "third_party/",        # pinned dependencies
    "gpu/third_party/",    # pinned submodules
    "run.py", "run.sh",    # game start contracts (restart, environment)
    ".git/",               # repository integrity
)

# Proprietary game files: never written, never versioned (AGENTS.md rule 4).
PROPRIETARY_PATTERNS = (
    re.compile(r"(^|/)eboot\.bin$", re.IGNORECASE),
    re.compile(r"(^|/)sce_module(/|$)", re.IGNORECASE),
    re.compile(r"(^|/)sce_sys(/|$)", re.IGNORECASE),
    re.compile(r"\.pkg$", re.IGNORECASE),
    re.compile(r"\.prx$", re.IGNORECASE),
    re.compile(r"\.sprx$", re.IGNORECASE),
    re.compile(r"(^|/)savedata(/|$)", re.IGNORECASE),
)

# Destructive shell commands. Each entry: (compiled regex, block reason).
_DESTRUCTIVE = [
    (re.compile(r"git\s+push[^|;&>]*\s(--force\b|-f\b|--force-with-lease)", re.IGNORECASE),
     "force-push is destructive (AGENTS.md rule 1)"),
    (re.compile(r"git\s+push[^|;&>]*\bmain\b", re.IGNORECASE),
     "pushing directly to main is forbidden (AGENTS.md rule 1)"),
    (re.compile(r"git\s+(checkout|switch)\s+(-\S+\s+)*main\b", re.IGNORECASE),
     "switching to main is forbidden; work on feat/*, fix/* or chore/* branches"),
    (re.compile(r"git\s+reset\s+--hard", re.IGNORECASE),
     "git reset --hard is destructive (AGENTS.md rule 1)"),
    (re.compile(r"git\s+clean\s+[^|;&]*-f", re.IGNORECASE),
     "git clean -f deletes untracked work (AGENTS.md rule 1)"),
    (re.compile(r"git\s+branch\s+(?:[^|;&]*\s)?-D\b", re.IGNORECASE),
     "git branch -D force-deletes branches (AGENTS.md rule 1)"),
    (re.compile(r"git\s+add\s+[^|;&]*\s-f\b|^git\s+add\s+-f\b|\bgit\s+add\s+-f\b", re.IGNORECASE),
     "git add -f bypasses .gitignore (AGENTS.md 'Engenharia de UI'); never force-add"),
    (re.compile(r"git\s+add[^|;&]*(eboot\.bin|sce_module|sce_sys|\.pkg\b|\.prx\b|\.sprx\b|savedata)", re.IGNORECASE),
     "versioning proprietary game files is forbidden (AGENTS.md rule 4)"),
    (re.compile(r"GOW3_FORCE_PATCHES\s*=\s*[1-9a-zA-Z_\"']", re.IGNORECASE),
     "GOW3_FORCE_PATCHES relaxes patch validation (AGENTS.md rule 3)"),
    (re.compile(r":\(\)\s*\{"), "fork bomb"),
    (re.compile(r"(?<!-)\bformat\b(?!-patch)\s+[a-zA-Z]:", re.IGNORECASE), "formatting a drive"),
    (re.compile(r"\b(mkfs(\.\w+)?|shutdown\b|restart-computer|diskpart)", re.IGNORECASE),
     "system-level destructive command"),
    (re.compile(r"\brd\s+/s\b|\bdel\s+/[sq]\b", re.IGNORECASE), "recursive Windows delete"),
    (re.compile(r"remove-item[^|;&]*-recurse[^|;&]*(force|src|gpu|scripts|patches|user|home|\$HOME|~)", re.IGNORECASE),
     "recursive Remove-Item on protected paths"),
    (re.compile(r"(taskkill|stop-process)[^|;&]*(gow3-probe|god of war)", re.IGNORECASE),
     "killing the game process (AGENTS.md rule 7: only processes started by the agent)"),
]

# Targets that make an "rm -rf" (or rm -fr) forbidden, matched against whole path arguments:
# the argument equals a protected name or lives under it. Rebuildable outputs (out/, dist/,
# temp directories) stay allowed.
_RMRF_CMD = re.compile(r"(?:^|[;&|]\s*|\bsudo\s+)rm\s+(?:-[a-zA-Z]*[rf][a-zA-Z]*\s+)+", re.IGNORECASE)
_RMRF_PROTECTED_TOPS = ("src", "gpu", "scripts", "patches", "launcher", "docs", "zcode", "tests",
                        "user", "sce_module", "sce_sys", "savedata", "eboot.bin", "gow3.ini",
                        "mods.json", "patches.json")

# Git commands that mutate history: blocked while HEAD is on main. Searched at the start of the
# command or after a command separator, so compound commands cannot smuggle one through.
_GIT_MUTATION = re.compile(
    r"(?:^|[;&|(]\s*)git\s+(commit|merge|rebase|reset|revert|cherry-pick|tag|push|pull)\b",
    re.IGNORECASE)


def _rmrf_argument_blocked(argument: str) -> bool:
    """Whether one rm argument targets protected work or user data."""
    token = argument.strip().strip('"\'').replace("\\", "/").rstrip("/")
    if not token or token == ".":
        return False
    if token.startswith("~") or token.startswith("$HOME") or token in ("/", "C:", "C:/", "C:*",
                                                                       "C:/*"):
        return True
    if re.search(r"(^|/)windows(/|$)", token, re.IGNORECASE):
        return True
    name = token.lstrip("./")
    top = name.split("/", 1)[0].lower()
    return top in _RMRF_PROTECTED_TOPS


def warn(message: str) -> None:
    print(f"gow3-dev-guard: {message}", file=sys.stderr)


def read_payload() -> dict | None:
    """The event payload from stdin; None when it is not valid JSON (fail-open upstream)."""
    try:
        raw = sys.stdin.buffer.read()
    except OSError:
        return None
    try:
        data = json.loads(raw.decode("utf-8", errors="replace"))
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def pass_hook(payload: dict | None = None) -> int:
    return PASS


def block(reason: str) -> int:
    warn(f"BLOCK: {reason}")
    return BLOCK


def project_root(payload: dict | None) -> Path:
    """Repository root: host-provided dir, else derived from this file's location
    (<repo>/zcode/gow3-dev-guard/hooks/guard_common.py)."""
    for key in ("ZCODE_PROJECT_DIR", "CLAUDE_PROJECT_DIR"):
        value = os.environ.get(key)
        if value:
            return Path(value).resolve()
    if payload:
        cwd = payload.get("cwd")
        if cwd:
            return Path(cwd).resolve()
    return Path(__file__).resolve().parents[3]


def git_branch(root: Path) -> str | None:
    """Current branch name, or None when root is not a git repository (fail-open)."""
    try:
        done = subprocess.run(["git", "-C", str(root), "rev-parse", "--abbrev-ref", "HEAD"],
                              capture_output=True, text=True, timeout=5,
                              creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.SubprocessError):
        return None
    return done.stdout.strip() if done.returncode == 0 else None


def repo_rel(path: str, root: Path) -> str | None:
    """A path as a POSIX repo-relative string ('src/x.c'), None when outside the repo."""
    try:
        rel = Path(path).resolve().relative_to(root).as_posix()
    except (ValueError, OSError):
        return None
    return rel


def proprietary(path: str) -> bool:
    posix = Path(path).as_posix()
    return any(p.search(posix) for p in PROPRIETARY_PATTERNS)


def write_violation(rel: str | None, raw_path: str) -> str | None:
    """Block reason for an Edit/Write to a file, or None when allowed."""
    if proprietary(raw_path):
        return f"proprietary game file/directory: {raw_path} (AGENTS.md rule 4)"
    if rel is not None:
        posix = rel if not rel.startswith("./") else rel[2:]
        for prefix in PROTECTED_PREFIXES:
            if posix == prefix.rstrip("/") or posix.startswith(prefix):
                return f"protected engine/contract path: {posix} (AGENTS.md rules 2-4)"
    return None


def bash_violation(command: str, root: Path) -> str | None:
    """Block reason for a Bash command, or None when allowed."""
    command = command.strip()
    for pattern, reason in _DESTRUCTIVE:
        if pattern.search(command):
            return reason
    for match in _RMRF_CMD.finditer(command):
        tail = command[match.end():match.end() + 400].split(";")[0].split("&")[0].split("|")[0]
        if any(_rmrf_argument_blocked(argument) for argument in tail.split()):
            return "rm with -r/-f on a protected or user-data path (AGENTS.md rule 5)"
    if _GIT_MUTATION.search(command) and git_branch(root) == "main":
        return "mutating git while HEAD is on main (AGENTS.md rule 1)"
    return None


def stop_state_file(payload: dict | None) -> Path:
    """Per-session Stop-block counter, under the plugin data dir (or temp)."""
    base = os.environ.get("ZCODE_PLUGIN_DATA") or os.environ.get("CLAUDE_PLUGIN_DATA")
    session = "unknown"
    if payload:
        for key in ("session_id", "sessionId"):
            value = payload.get(key)
            if isinstance(value, str) and re.fullmatch(r"[\w.-]{1,80}", value):
                session = value
                break
    root = Path(base) if base else Path(os.environ.get("TEMP") or ".")
    return root / "gow3-dev-guard" / f"stop-{session}.count"
