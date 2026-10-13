#!/usr/bin/env python3
"""PreToolUse hook of gow3-dev-guard.

Blocks, by deterministic rules only (guard_common.py):
  - destructive shell/git operations (force-push, reset --hard, clean -f, rm -rf on protected
    or user-data paths, drive formatting, killing the game process, ...);
  - direct changes to main (switching to it, pushing it, or any git mutation / in-repo file
    write while HEAD sits on it);
  - writes to the game engine and its safety contracts (src/, gpu/shadps4/, gpu/patches/,
    gpu/dlss_bridge/, gpu/shim/gow3gpu.cpp, patches/, scripts/, run.py, run.sh, third_party/,
    .git/) and to proprietary game files (eboot.bin, sce_module/, sce_sys/, *.pkg/*.prx/*.sprx,
    savedata/);
  - GOW3_FORCE_PATCHES and `git add -f`.

Everything else — reads, searches, builds, tests, edits in docs/, launcher/, tests/, zcode/,
packaging/ and gpu/shim/gow3_overlay.cpp (approved save-screen scope) — passes.
Fail-open on malformed input (exit 0 + warning), so a bad payload never breaks a session.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import guard_common as g  # noqa: E402

WRITE_TOOLS = {"Edit", "Write", "ApplyPatch", "MultiEdit"}


def main() -> int:
    payload = g.read_payload()
    if payload is None:
        g.warn("invalid or missing JSON payload; failing open")
        return g.PASS

    tool = payload.get("tool_name") or payload.get("toolName") or ""
    tool_input = payload.get("tool_input") or payload.get("toolInput") or {}
    if not isinstance(tool_input, dict):
        g.warn("tool_input is not an object; failing open")
        return g.PASS
    root = g.project_root(payload)

    if tool == "Bash":
        command = str(tool_input.get("command") or "")
        if not command.strip():
            return g.PASS
        reason = g.bash_violation(command, root)
        if reason:
            return g.block(f"Bash: {reason}. Ask the maintainer if this operation is really needed.")
        return g.PASS

    if tool in WRITE_TOOLS:
        raw_path = str(tool_input.get("file_path") or tool_input.get("path") or "")
        if not raw_path.strip():
            return g.PASS  # nothing identifiable to check
        rel = g.repo_rel(raw_path, root)
        reason = g.write_violation(rel, raw_path)
        if reason:
            return g.block(f"{tool}: {reason}. UI work may touch launcher/, docs/, tests/, zcode/,"
                           " packaging/ and the save screen in gpu/shim/gow3_overlay.cpp.")
        if rel is not None and g.git_branch(root) == "main":
            return g.block(f"{tool} inside the repository while HEAD is on main"
                           " (AGENTS.md rule 1). Create a feat/*, fix/* or chore/* branch first.")
        return g.PASS

    return g.PASS  # reads, searches and other tools are never blocked


if __name__ == "__main__":
    sys.exit(main())
