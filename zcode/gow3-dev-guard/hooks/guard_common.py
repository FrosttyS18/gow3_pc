"""Shared logic of the gow3-dev-guard hooks (hardened after the independent audit of 7e85be1).

Deterministic only: every decision is a resolved path, a regex or a read-only git query
evaluated in code. No LLM, no network, no writes (except the Stop hook's loop counter).

I/O contract with the ZCode hook runner:
  - stdin:  the event payload as JSON.
  - stdout: empty for PreToolUse/Stop (exit codes carry the decision); SessionStart prints
            the recognized-key JSON {"additionalContext": ...}.
  - exit 0: pass; exit 2: deliberate block (reason on stderr); no other exit code is raised.

Fail policy (audit item 4): PreToolUse is fail-CLOSED — it only ever sees write-capable
tools (matcher Bash|Edit|Write|ApplyPatch|MultiEdit), so an invalid payload, an
unidentifiable target or an undeterminable branch BLOCKS with a specific reason. Safe
reads never reach this hook, and SessionStart/Stop stay fail-open (they cannot write and
must not trap the session).
"""
from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path, PurePosixPath

PASS = 0
BLOCK = 2

# --------------------------------------------------------------------------------------------
# Protected / proprietary / authorized locations (AGENTS.md rules 1-5).

# Repository paths a UI/harness task must never modify. POSIX prefixes relative to the
# repository root. Writable scope stays: docs/, launcher/, tests/, zcode/, packaging/,
# tools/ and gpu/shim/gow3_overlay.cpp (approved save-screen work).
PROTECTED_PREFIXES = (
    "src/",                 # runtime C (PS4 service emulation, loader)
    "gpu/shadps4/",         # shadPS4 video core and recompiler
    "gpu/patches/",         # patches applied to the FSR-Vulkan submodule
    "gpu/dlss_bridge/",     # NVIDIA DLSS bridge
    "gpu/shim/gow3gpu.cpp", # C bridge between runtime and overlay
    "patches/",             # built-in patch XMLs (eboot byte patches)
    "scripts/",             # game orchestration incl. the patch whitelist (patches.py)
    "third_party/",         # pinned dependencies
    "gpu/third_party/",     # pinned submodules
    "run.py", "run.sh",     # game start contracts (restart, environment)
    ".git",                 # repository integrity (dir and any path under it)
)

# Proprietary game material: never written, never staged, wherever it lives.
PROPRIETARY_PATTERNS = (
    re.compile(r"(^|/)eboot\.bin$", re.IGNORECASE),
    re.compile(r"(^|/)sce_module(/|$)", re.IGNORECASE),
    re.compile(r"(^|/)sce_sys(/|$)", re.IGNORECASE),
    re.compile(r"\.pkg$", re.IGNORECASE),
    re.compile(r"\.prx$", re.IGNORECASE),
    re.compile(r"\.sprx$", re.IGNORECASE),
    re.compile(r"(^|/)savedata(/|$)", re.IGNORECASE),
)

# "rm -rf" inside the repository is allowed ONLY under these rebuildable/temporary roots.
TOP_AUTHORIZED_RM = ("out", "dist", "__pycache__", ".pytest_cache", "node_modules", "target",
                     "tmp", "temp")
NESTED_AUTHORIZED_RM = ("__pycache__", ".pytest_cache", "node_modules", "target", "tmp", "temp")

MAIN_BRANCHES = ("main", "master")

# --------------------------------------------------------------------------------------------
# Small helpers.


def warn(message: str) -> None:
    print(f"gow3-dev-guard: {message}", file=sys.stderr)


def read_payload() -> dict | None:
    """The event payload from stdin; None when it is not a JSON object."""
    try:
        raw = sys.stdin.buffer.read()
    except OSError:
        return None
    try:
        data = json.loads(raw.decode("utf-8", errors="replace"))
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def block(reason: str) -> int:
    warn(f"BLOCK: {reason}")
    return BLOCK


def _git(root: Path, *args: str) -> subprocess.CompletedProcess | None:
    try:
        return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True,
                              timeout=8, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.SubprocessError):
        return None


def _derived_root() -> Path:
    return Path(__file__).resolve().parents[3]


def repo_root(payload: dict | None) -> Path:
    """The repository root that governs protection, resolved from the event's own directory
    first (audit item 4): payload cwd → host env, escalated through `git rev-parse
    --show-toplevel`. When the event points somewhere that is not a repository, that
    directory itself governs (no silent fallback to another repository — only when the
    event supplies no directory at all is this file's repository used)."""
    event_starts: list[Path] = []
    if payload:
        cwd = payload.get("cwd")
        if isinstance(cwd, str) and cwd.strip():
            event_starts.append(Path(cwd))
    for key in ("ZCODE_PROJECT_DIR", "CLAUDE_PROJECT_DIR"):
        value = os.environ.get(key)
        if value:
            event_starts.append(Path(value))
    starts = event_starts or [_derived_root()]
    for start in starts:
        done = _git(start, "rev-parse", "--show-toplevel")
        if done is not None and done.returncode == 0 and done.stdout.strip():
            return Path(done.stdout.strip().replace("\\", "/"))
    return starts[0]


def git_branch(root: Path) -> str | None:
    done = _git(root, "rev-parse", "--abbrev-ref", "HEAD")
    return done.stdout.strip() if done is not None and done.returncode == 0 else None


def repo_rel(path: Path | str, root: Path) -> str | None:
    """A path as a POSIX repo-relative string, or None when outside the repository."""
    path = Path(os.path.normpath(str(path)))
    try:
        rel = path.resolve().relative_to(Path(root).resolve())
    except (ValueError, OSError):
        return None
    return rel.as_posix()


def proprietary(path: str) -> bool:
    posix = PurePosixPath(str(path).replace("\\", "/")).as_posix()
    return any(p.search(posix) for p in PROPRIETARY_PATTERNS)


def write_violation(rel: str | None, raw_path: str) -> str | None:
    """Block reason for writing to a path (Edit/Write/staged/bash target), or None."""
    if proprietary(raw_path):
        return f"proprietary game file/directory: {raw_path} (AGENTS.md rule 4)"
    if rel is not None:
        posix = rel if not rel.startswith("./") else rel[2:]
        for prefix in PROTECTED_PREFIXES:
            if prefix.endswith("/"):
                if posix.startswith(prefix) or posix == prefix[:-1]:
                    return f"protected engine/contract path: {posix} (AGENTS.md rules 2-4)"
            elif posix == prefix or posix.startswith(prefix + "/"):
                return f"protected engine/contract path: {posix} (AGENTS.md rules 2-4)"
    return None


def resolve_token(token: str, base: Path) -> Path:
    """A shell path token resolved against the directory the command runs in."""
    token = token.strip().strip("\"'")
    expanded = os.path.expandvars(os.path.expanduser(token))
    path = Path(expanded)
    return path if path.is_absolute() else Path(os.path.normpath(str(base / path)))


# --------------------------------------------------------------------------------------------
# Audit item 1 — destructive deletes with resolved, normalized paths.

_RMRF_CMD = re.compile(r"(?:^\s*|[;&|]\s*|\bsudo\s+)rm\s+(?:-{1,2}[a-zA-Z]*[rf][a-zA-Z]*\s+)+",
                       re.IGNORECASE)


def _rmrf_argument_reason(argument: str, cwd: Path, root: Path) -> str | None:
    token = argument.strip().strip("\"'")
    if not token:
        return None
    if token in (".", "..", "./", "../", ".\\", "..\\"):
        return "deleting the current or parent directory"
    path = resolve_token(token, cwd)
    posix = path.as_posix()
    if proprietary(posix):
        return f"proprietary game data: {token}"
    try:
        root_resolved = root.resolve()
        path_resolved = path.resolve()
    except OSError:
        return f"cannot resolve rm target {token!r} (fail-closed)"
    if path_resolved == root_resolved:
        return "deleting the repository root"
    if path_resolved in root_resolved.parents:
        return f"deleting {token} would remove the repository itself"
    rel = repo_rel(path, root)
    if rel is not None:
        parts = PurePosixPath(rel).parts
        top = parts[0] if parts else ""
        if top == ".git":
            return "deleting .git (repository integrity)"
        if top in TOP_AUTHORIZED_RM or any(part in NESTED_AUTHORIZED_RM for part in parts[1:]):
            return None  # explicitly authorized rebuildable/temporary location
        reason = write_violation(rel, posix)
        return reason or (f"inside the repository but not an authorized rebuildable/temporary"
                          f" location: {rel}")
    # Outside the repository: temporary locations are fine, home/system are not.
    lowered = [part.lower() for part in path.parts]
    if any(part in ("temp", "tmp") for part in lowered[:-1]):
        return None
    home = Path.home()
    try:
        if path_resolved == home or home in path_resolved.parents:
            return "deleting inside the user home directory"
    except OSError:
        pass
    if "windows" in lowered:
        return "deleting a Windows system directory"
    if path_resolved.parent == path_resolved:
        return "deleting a filesystem root"
    return None


def rmrf_violation(command: str, cwd: Path, root: Path) -> str | None:
    for match in _RMRF_CMD.finditer(command):
        tail = command[match.end():match.end() + 400]
        tail = re.split(r"[;&|]", tail)[0]
        for argument in shlex.split(tail) if _quote_balanced(tail) else tail.split():
            reason = _rmrf_argument_reason(argument, cwd, root)
            if reason:
                return reason
    return None


def _quote_balanced(text: str) -> bool:
    return text.count('"') % 2 == 0 and text.count("'") % 2 == 0


# --------------------------------------------------------------------------------------------
# Audit item 3 — bash write policy: resolved targets, PowerShell, git staging.

_REDIRECTION = re.compile(r"(?:^|[\s;|&])(?:\d)?>{1,2}\s*([^\s;|&]+)")
_TEE = re.compile(r"\btee\s+((?:-{1,2}\S+\s+)*)(.+?)(?=[;&|]|$)", re.IGNORECASE)
_LASTARG_TOOLS = re.compile(
    r"\b(?:cp|mv|install|rsync|shred)\b.*?(\S+)\s*$", re.IGNORECASE | re.DOTALL)
_DD_OF = re.compile(r"\bof=(\"[^\"]+\"|\S+)", re.IGNORECASE)
_SED_INPLACE = re.compile(r"\bsed\s+((?:\s|[^;|&])*?)\s(\S+)\s*$")
_PS_EXEC = re.compile(r"\b(powershell|pwsh)\b", re.IGNORECASE)
_PS_WRITE = re.compile(
    r"\b(Set-Content|Add-Content|Out-File|New-Item|Remove-Item|Move-Item|Copy-Item|"
    r"Clear-Content|Set-Item|Tee-Object|Export-Csv|Export-Clixml)\b", re.IGNORECASE)
_PS_PATH_FLAG = re.compile(
    r"(?:-Path|-FilePath|-Destination|-LiteralPath)\s+(?:'([^']+)'|\"([^\"]+)\"|(\S+))",
    re.IGNORECASE)
_UNRESOLVABLE = re.compile(r"\$[A-Za-z_{(]")


def _skip_target(token: str) -> bool:
    token = token.strip("\"'")
    return (not token or token.startswith("&") or token.startswith("/dev/")
            or token in ("&1", "&2", "-", "/dev/null", "/dev/stdout", "/dev/stderr"))


def _segment_targets(segment: str) -> list[str]:
    """Path tokens this command segment writes to (redirections, tee, last-argument copy
    tools, in-place sed, dd of=)."""
    candidates: list[str] = []
    for match in _REDIRECTION.finditer(segment):
        token = match.group(1)
        if not _skip_target(token):
            candidates.append(token)
    match = _TEE.search(segment)
    if match:
        for token in re.split(r"\s+", match.group(2).strip()):
            if token and not token.startswith("-"):
                candidates.append(token)
    match = _LASTARG_TOOLS.search(segment)
    if match and not _skip_target(match.group(1)):
        candidates.append(match.group(1))
    match = _SED_INPLACE.search(segment)
    if match and not _skip_target(match.group(2)):
        candidates.append(match.group(2))
    if re.search(r"\btruncate\b", segment, re.IGNORECASE):
        tokens = segment.split()
        if tokens and not _skip_target(tokens[-1]) and tokens[-1] != "truncate":
            candidates.append(tokens[-1])
    for match in _DD_OF.finditer(segment):
        candidates.append(match.group(1))
    return candidates


def _powershell_violation(command: str, cwd: Path, root: Path) -> str | None:
    """A PowerShell write cmdlet must name a verifiable destination (fail-closed) and the
    destination must not be protected."""
    if not (_PS_EXEC.search(command) and _PS_WRITE.search(command)):
        return None
    ps_targets: list[str] = []
    for match in _PS_PATH_FLAG.finditer(command):
        ps_targets.append(next(group for group in match.groups() if group is not None))
    for pair in re.findall(r"'([^']+)'|\"([^\"]+)\"", command):
        value = next((group for group in pair if group), None)
        if value:
            ps_targets.append(value)
    if not ps_targets or any(_UNRESOLVABLE.search(token) for token in ps_targets):
        return ("PowerShell write cmdlet without a verifiable destination "
                "(fail-closed); write with the Edit/Write tools instead")
    for token in ps_targets:
        path = resolve_token(token, cwd)
        reason = write_violation(repo_rel(path, root), str(path))
        if reason:
            return f"PowerShell writes to {reason}"
    return None


# Git plumbing for staging integrity.

_GIT_COMMIT = re.compile(r"\bgit\s+(?:-C\s+(\"[^\"]+\"|\S+)\s+)?commit\b", re.IGNORECASE)
_GIT_ADD = re.compile(r"\bgit\s+add\b\s*(.*)$", re.IGNORECASE)
_GIT_RM = re.compile(r"\bgit\s+rm\b\s*(.*)$", re.IGNORECASE)
_GIT_MUTATION = re.compile(
    r"(?:^|[;&|(]\s*)git\s+(?:-C\s+\S+\s+)?(commit|merge|rebase|reset|revert|cherry-pick|"
    r"tag|push|pull|stash(?!\s+(list|show)))\b", re.IGNORECASE)


def _git_dir_of(command: str, cwd: Path, root: Path) -> Path:
    match = _GIT_COMMIT.search(command)
    if match and match.group(1):
        return resolve_token(match.group(1).strip("\"'"), cwd)
    return root


def staged_violation(root: Path) -> str | None:
    """Files already staged for commit must not include protected/proprietary paths."""
    done = _git(root, "diff", "--cached", "--name-only", "-z")
    if done is None or done.returncode != 0:
        return "cannot inspect staged files (git failed — fail-closed)"
    for name in done.stdout.split("\0"):
        if not name:
            continue
        reason = write_violation(name.replace("\\", "/"), name)
        if reason:
            return f"git commit would persist {reason}"
    return None


def worktree_violation(root: Path) -> str | None:
    """Tracked files modified but not staged — what `git commit -a/--all` would commit."""
    done = _git(root, "diff", "--name-only", "-z", "HEAD")
    if done is None or done.returncode != 0:
        return "cannot inspect worktree changes (git failed — fail-closed)"
    for name in done.stdout.split("\0"):
        if not name:
            continue
        reason = write_violation(name.replace("\\", "/"), name)
        if reason:
            return f"git commit -a would commit {reason}"
    return None


def git_violation(command: str, cwd: Path, root: Path) -> str | None:
    """Deterministic git policy: branch fail-closed on mutations, main protection,
    worktree discards, staging inspection at add/commit time."""
    mutation = _GIT_MUTATION.search(command)
    if mutation:
        branch = git_branch(root)
        if branch is None:
            return "cannot determine the current branch for a git mutation (fail-closed)"
        if branch in MAIN_BRANCHES:
            return f"mutating git while HEAD is on {branch} (AGENTS.md rule 1)"

    match = _GIT_ADD.search(command)
    if match:
        args = re.split(r"[;&|]", match.group(1))[0].strip()
        if "-f" in args.split() or "--force" in args.split():
            return "git add -f bypasses .gitignore (AGENTS.md 'Engenharia de UI')"
        if args:
            if _quote_balanced(args):
                try:
                    argv = shlex.split(args, posix="\\" not in args)
                except ValueError:
                    argv = args.split()
            else:
                argv = args.split()
            # The pathspec itself decides: adding an engine/proprietary path is blocked
            # even when the file is tracked and unchanged (dry-run would list nothing).
            for token in argv:
                if token.startswith("-") or token in (".", "..", ":/", "-A", "-a", "-u"):
                    continue
                path = resolve_token(token, cwd)
                reason = write_violation(repo_rel(path, root), str(path))
                if reason:
                    return f"git add stages {reason}"
            # Expand what would really enter the index (globs, -A, .): dry-run never writes.
            dry = _git(root, "add", "--dry-run", *argv)
        else:  # bare `git add -A` / `git add .`: enumerate everything it would stage
            dry = _git(root, "add", "--dry-run", "-A")
        if dry is not None and dry.returncode == 0:
            for line in dry.stdout.splitlines():
                found = re.search(r"'([^']+)'", line)
                if found:
                    reason = write_violation(found.group(1), found.group(1))
                    if reason:
                        return f"git add stages {reason}"
        elif dry is not None:
            return "git add --dry-run failed: pathspec invalid or inaccessible (fail-closed)"

    match = _GIT_RM.search(command)
    if match:
        for token in re.split(r"[;&|]", match.group(1))[0].split():
            if token.startswith("-"):
                continue
            path = resolve_token(token, cwd)
            reason = write_violation(repo_rel(path, root), str(path)) or \
                proprietary(str(path)) and f"git rm of proprietary file {token}"
            if reason:
                return f"git rm: {reason}"

    if _GIT_COMMIT.search(command):
        commit_dir = _git_dir_of(command, cwd, root)
        reason = staged_violation(commit_dir)
        if reason:
            return reason
        # `commit -a/-am/--all/--include` also commits tracked modifications that were
        # never staged — inspect the worktree against HEAD too.
        if re.search(r"(?:\s|^)(?:-am|-a\b|--all|--include)(?=\s|$)", command):
            reason = worktree_violation(commit_dir)
            if reason:
                return reason
    return None


# Declarative destructive patterns (kept from phase 1, plus worktree discards).
_DESTRUCTIVE = [
    (re.compile(r"git\s+(?:-C\s+\S+\s+)?push[^|;&>]*\s(--force\b|-f\b|--force-with-lease)",
                re.IGNORECASE),
     "force-push is destructive (AGENTS.md rule 1)"),
    (re.compile(r"git\s+(?:-C\s+\S+\s+)?push[^|;&>]*\bmain\b", re.IGNORECASE),
     "pushing directly to main is forbidden (AGENTS.md rule 1)"),
    (re.compile(r"git\s+(?:-C\s+\S+\s+)?(checkout|switch)\s+(-\S+\s+)*main\b", re.IGNORECASE),
     "switching to main is forbidden; work on feat/*, fix/* or chore/* branches"),
    (re.compile(r"git\s+reset\s+--hard", re.IGNORECASE),
     "git reset --hard is destructive (AGENTS.md rule 1)"),
    (re.compile(r"git\s+clean\s+[^|;&]*-f", re.IGNORECASE),
     "git clean -f deletes untracked work (AGENTS.md rule 1)"),
    (re.compile(r"git\s+branch\s+(?:[^|;&]*\s)?-D\b", re.IGNORECASE),
     "git branch -D force-deletes branches (AGENTS.md rule 1)"),
    (re.compile(r"git\s+checkout\s+--(\s|$)|git\s+restore\b", re.IGNORECASE),
     "discarding working-tree changes (checkout --/restore) is destructive"),
    (re.compile(r"git\s+stash(?!\s+(list|show))\b", re.IGNORECASE),
     "git stash mutates the working tree; only list/show are safe"),
    (re.compile(r"GOW3_FORCE_PATCHES\s*=\s*[1-9a-zA-Z_\"']", re.IGNORECASE),
     "GOW3_FORCE_PATCHES relaxes patch validation (AGENTS.md rule 3)"),
    (re.compile(r":\(\)\s*\{"), "fork bomb"),
    (re.compile(r"(?<!-)\bformat\b(?!-patch)\s+[a-zA-Z]:", re.IGNORECASE), "formatting a drive"),
    (re.compile(r"\b(mkfs(\.\w+)?|shutdown\b|restart-computer|diskpart)", re.IGNORECASE),
     "system-level destructive command"),
    (re.compile(r"\brd\s+/s\b|\bdel\s+/[sq]\b", re.IGNORECASE), "recursive Windows delete"),
    (re.compile(r"(taskkill|stop-process)[^|;&]*(gow3-probe|god of war)", re.IGNORECASE),
     "killing the game process (AGENTS.md rule 7: only processes started by the agent)"),
]


_CD_SEGMENT = re.compile(r"^\s*cd\s+(.+?)\s*$")


def effective_cwds(command: str, cwd: Path) -> list[tuple[str, Path, bool]]:
    """(segment, cwd-in-effect, cwd-unresolvable) per segment, walking `cd` commands so a
    write after `cd <dir>` resolves against the directory the shell would be in."""
    out: list[tuple[str, Path, bool]] = []
    current, unresolvable = cwd, False
    for segment in re.split(r"[;&|]", command):
        match = _CD_SEGMENT.match(segment)
        if match:
            token = match.group(1).strip("\"'")
            if token == "-":
                unresolvable = True
            else:
                expanded = os.path.expandvars(os.path.expanduser(token))
                if "$" in expanded or "`" in expanded or "$(" in token:
                    unresolvable = True
                else:
                    candidate = Path(expanded)
                    current = candidate if candidate.is_absolute() else \
                        Path(os.path.normpath(str(current / candidate)))
        out.append((segment, current, unresolvable))
    return out


def bash_violation(command: str, cwd: Path, root: Path) -> str | None:
    command = command.strip()
    for pattern, reason in _DESTRUCTIVE:
        if pattern.search(command):
            return reason

    wrote_in_repo = False
    for segment, seg_cwd, cwd_lost in effective_cwds(command, cwd):
        reason = rmrf_violation(segment, seg_cwd, root)
        if reason:
            return reason
        for token in _segment_targets(segment):
            expanded = os.path.expandvars(token.strip("\"'"))
            if "$" in expanded or "`" in token or "$(" in token:
                return (f"bash write destination {token!r} cannot be resolved safely"
                        " (fail-closed); use an explicit path or the Edit/Write tools")
            if cwd_lost:
                return ("bash writes after an unresolvable `cd` cannot be verified"
                        " (fail-closed)")
            path = resolve_token(token, seg_cwd)
            rel = repo_rel(path, root)
            reason = write_violation(rel, str(path))
            if reason:
                return f"bash writes to {reason}"
            wrote_in_repo = wrote_in_repo or rel is not None

    if wrote_in_repo:
        branch = git_branch(root)
        if branch is None:
            return ("cannot determine the current branch for a bash write inside the"
                    " repository (fail-closed)")
        if branch in MAIN_BRANCHES:
            return (f"bash writes inside the repository while HEAD is on {branch}"
                    " (AGENTS.md rule 1)")

    reason = _powershell_violation(command, cwd, root)
    if reason:
        return reason
    return git_violation(command, cwd, root)


# --------------------------------------------------------------------------------------------
# Audit item 2 — extract every file a write-capable tool may touch.

_APPLY_PATCH_FILE = re.compile(
    r"^\*\*\*\s+(?:(?:Update|Add|Delete)\s+File:|Move\s+to:)\s+(\S+)",
    re.IGNORECASE | re.MULTILINE)
_DIFF_FILE = re.compile(r"^(?:\+\+\+ b/|diff --git a/\S+ b/)(\S+)", re.MULTILINE)


def write_tool_paths(tool_input: dict) -> list[str]:
    """All destination paths an Edit/Write/ApplyPatch/MultiEdit payload can name."""
    paths: list[str] = []

    def add(value):
        if isinstance(value, str) and value.strip() and value not in paths:
            paths.append(value)

    for key in ("file_path", "path", "notebook_path", "filePath"):
        add(tool_input.get(key))
    for key in ("files", "patches", "edits", "operations"):
        items = tool_input.get(key)
        if isinstance(items, list):
            for item in items:
                if isinstance(item, str):
                    add(item)
                elif isinstance(item, dict):
                    for sub in ("file_path", "path", "filePath", "new_path", "dest_path",
                                "to"):
                        add(item.get(sub))
    for key in ("patch", "diff"):
        text = tool_input.get(key)
        if isinstance(text, str):
            for match in _APPLY_PATCH_FILE.finditer(text):
                add(match.group(1))
            for match in _DIFF_FILE.finditer(text):
                add(match.group(1))
    return paths


# --------------------------------------------------------------------------------------------
# Stop-hook loop counter.

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
