#!/usr/bin/env python3
"""PreToolUse hook of gow3-dev-guard (hardened after the independent audit of 7e85be1).

The matcher routes only write-capable tools here — Bash, Edit, Write, ApplyPatch (alias of
Write/Edit), MultiEdit — so the policy is FAIL-CLOSED: an invalid payload, an
unidentifiable target, an unresolvable repository/branch or an unverifiable write BLOCKS
with a specific reason. Read-only tools never reach this hook.

Blocks, by deterministic rules (guard_common.py):
  - destructive shell/git operations (force-push, reset --hard, clean -f, checkout --/restore,
    stash, rm -rf outside authorized rebuildable/temporary locations, worktree discards,
    drive formatting, killing the game process, ...);
  - direct changes to main (switching to it, pushing it, any git mutation — including via
    git -C or compound commands — and any in-repo write while HEAD sits on it);
  - writes to the game engine and its safety contracts (src/, gpu/shadps4/, gpu/patches/,
    gpu/dlss_bridge/, gpu/shim/gow3gpu.cpp, patches/, scripts/, run.py, run.sh, third_party/,
    .git) and proprietary game files, wherever they live;
  - bash/PowerShell write operators (redirections, tee, cp/mv/dd/sed -i, Set-Content and
    friends) whose destination resolves to a protected path — or whose destination cannot
    be verified at all;
  - staging or committing protected/proprietary files (git add --dry-run inspection plus a
    staged-files gate at commit time), and GOW3_FORCE_PATCHES.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import guard_common as g  # noqa: E402

WRITE_TOOLS = {"Edit", "Write", "ApplyPatch", "MultiEdit"}


def main() -> int:
    payload = g.read_payload()
    if payload is None:
        return g.block("PreToolUse: invalid or missing JSON payload — cannot evaluate a"
                       " write-capable tool call (fail-closed)")

    tool = payload.get("tool_name") or payload.get("toolName") or ""
    tool_input = payload.get("tool_input") or payload.get("toolInput") or {}
    if not isinstance(tool, str) or not tool:
        return g.block("PreToolUse: no tool_name — cannot determine the tool (fail-closed)")
    if not isinstance(tool_input, dict):
        return g.block(f"PreToolUse({tool}): tool_input is missing or not an object"
                       " (fail-closed)")

    root = g.repo_root(payload)

    if tool == "Bash":
        command = tool_input.get("command")
        if not isinstance(command, str) or not command.strip():
            return g.block("PreToolUse(Bash): no command to evaluate (fail-closed)")
        cwd = root
        if isinstance(payload.get("cwd"), str) and payload["cwd"].strip():
            cwd = Path(payload["cwd"])
        reason = g.bash_violation(command, cwd, root)
        if reason:
            return g.block(f"Bash: {reason}. Ask the maintainer if this operation is"
                           " really needed.")
        return g.PASS

    if tool in WRITE_TOOLS:
        paths = g.write_tool_paths(tool_input)
        if not paths:
            return g.block(f"PreToolUse({tool}): write operation without any identifiable"
                           " target file (fail-closed)")
        inside_repo = False
        for raw in paths:
            path = Path(raw)
            if not path.is_absolute():
                path = Path(root / raw)
            rel = g.repo_rel(path, root)
            reason = g.write_violation(rel, raw)
            if reason:
                return g.block(f"{tool}: {reason}. UI work may touch launcher/, docs/,"
                               " tests/, zcode/, packaging/ and the save screen in"
                               " gpu/shim/gow3_overlay.cpp.")
            inside_repo = inside_repo or rel is not None
        if inside_repo:
            branch = g.git_branch(root)
            if branch is None:
                return g.block(f"{tool} inside the repository, but the current branch cannot"
                               " be determined (fail-closed)")
            if branch in g.MAIN_BRANCHES:
                return g.block(f"{tool} inside the repository while HEAD is on {branch}"
                               " (AGENTS.md rule 1). Create a feat/*, fix/* or chore/*"
                               " branch first.")
        return g.PASS

    # Any other tool is read-only and never blocked (the matcher already filters).
    return g.PASS


if __name__ == "__main__":
    sys.exit(main())
