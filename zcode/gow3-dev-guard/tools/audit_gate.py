#!/usr/bin/env python3
"""gow3-dev-guard — Audit Gate (integrity layer 2).

An independent, deterministic verifier of the repository's REAL changes — it reads git
itself (committed, staged, worktree and untracked state), never the LLM's interpretation
and never the text of the commands that produced the changes.

  layer 1 (PreToolUse hooks) : block identifiable dangerous operations before they run
  layer 2 (this gate)        : verify what actually changed against a trusted reference

Usage (CLI or CI):
  python zcode/gow3-dev-guard/tools/audit_gate.py [--repo DIR] [--ref REF]
                                                  [--allow-path PATH]... [--json]

  --ref        trusted reference for the diff (default: origin/main, else main)
  --allow-path explicit, auditable exception for one path (upstream merges must state it
               in the PR; never a blanket or environment-driven switch)
  --json       machine-readable output

Exit codes: 0 = PASS, 1 = violations, 2 = usage/internal error (fail-closed).

Checks:
  1. changed paths (A/M/D/T/R/C, both sides of renames) vs the authorized scope;
  2. protected engine/contract paths and proprietary game material, anywhere;
  3. submodule pointer moves (content dirt from the build is ignored, pointer is not);
  4. untracked proprietary files (git status);
  5. harness integrity: deleted gate/hook files fail; and a change that WEAKENS the
     verifier's own policy tables on the analyzed branch fails — the tables are compared
     against the trusted reference via ast, so editing the guard to allow more never
     passes the gate it modified.
"""
from __future__ import annotations

import argparse
import ast
import json
import os
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "hooks"))
import guard_common as g  # noqa: E402  (trusted plugin copy — not the analyzed repo's)

# Repository paths this project's phases are allowed to touch. Anything else is a
# functional change out of scope (AGENTS.md rules 2-4) and fails the gate.
AUTHORIZED_SCOPE = (
    "docs/", "launcher/", "tests/", "zcode/", "packaging/", "tools/", ".github/",
    ".gitignore", "AGENTS.md", "README.md", "README.pt-BR.md", "LICENSE",
    "gpu/shim/gow3_overlay.cpp",  # approved save-screen work
)

HARNESS_FILES = (
    "zcode/gow3-dev-guard/tools/audit_gate.py",
    "zcode/gow3-dev-guard/hooks/guard_common.py",
    "zcode/gow3-dev-guard/hooks/pre_tool_use.py",
    "zcode/gow3-dev-guard/hooks/stop_guard.py",
    "zcode/gow3-dev-guard/hooks/session_context.py",
    "zcode/gow3-dev-guard/hooks/hooks.json",
    "zcode/gow3-dev-guard/tests/test_guard.py",
    "zcode/gow3-dev-guard/tests/test_audit_gate.py",
    "zcode/marketplace.json",
)

# Policy tables that may only grow: shrinking any of them on the analyzed branch is a
# self-disable attempt and fails the gate.
POLICY_TABLES = ("PROTECTED_PREFIXES", "PROPRIETARY_PATTERNS", "TOP_AUTHORIZED_RM",
                 "NESTED_AUTHORIZED_RM", "AUTHORIZED_SCOPE")

EXIT_PASS, EXIT_FAIL, EXIT_ERROR = 0, 1, 2


def git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(repo), "-c", "diff.ignoreSubmodules=dirty",
                           *args], capture_output=True, text=True,
                          timeout=60,
                          creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


def resolve_ref(repo: Path, ref: str) -> str | None:
    done = git(repo, "rev-parse", "--verify", f"{ref}^{{commit}}")
    return done.stdout.strip() if done.returncode == 0 else None


def changed_records(repo: Path, ref: str) -> list[tuple[str, str, str | None]]:
    """[(status, path, rename_source|None)] of everything that differs from `ref` —
    committed, staged and unstaged at once (the diff covers the working tree)."""
    done = git(repo, "diff", "--name-status", "-z", ref)
    if done.returncode != 0:
        raise RuntimeError(f"git diff failed: {done.stderr.strip()}")
    tokens = done.stdout.split("\0")
    records: list[tuple[str, str, str | None]] = []
    index = 0
    while index < len(tokens):
        status = tokens[index]
        if not status:
            index += 1
            continue
        base = status[0]
        if base in ("R", "C") and index + 2 < len(tokens):
            records.append((base, tokens[index + 2], tokens[index + 1]))
            index += 3
        elif index + 1 < len(tokens):
            records.append((base, tokens[index + 1], None))
            index += 2
        else:
            break
    return records


def untracked_proprietary(repo: Path) -> list[str]:
    done = git(repo, "status", "--porcelain", "-z", "--untracked-files=all")
    found: list[str] = []
    for token in done.stdout.split("\0"):
        if token.startswith("?? "):
            path = token[3:].strip('"')
            if g.proprietary(path):
                found.append(path)
    return found


def in_scope(posix: str) -> bool:
    posix = posix[2:] if posix.startswith("./") else posix
    for entry in AUTHORIZED_SCOPE:
        if entry.endswith("/"):
            if posix.startswith(entry) or posix == entry[:-1]:
                return True
        elif posix == entry or posix.startswith(entry + "/"):
            return True
    return False


def path_violation(status: str, posix: str) -> str | None:
    """The reason one changed path fails the gate, or None."""
    if posix in HARNESS_FILES and status == "D":
        return "harness file deleted (integrity)"
    if g.proprietary(posix):
        return "proprietary game material in the changeset (AGENTS.md rule 4)"
    rel = posix[2:] if posix.startswith("./") else posix
    reason = g.write_violation(rel, posix)
    if reason:
        return f"protected path changed: {reason.split(':')[0]}"
    if not in_scope(rel):
        return (f"functional change outside the authorized scope: {rel}"
                " (UI/harness work stays in docs/, launcher/, tests/, zcode/, packaging/,"
                " tools/, .github/, gpu/shim/gow3_overlay.cpp)")
    return None


def policy_tables(source: str) -> dict[str, frozenset[str]]:
    """The policy table literals of a python source, via ast (no import, no execution)."""
    tables: dict[str, frozenset[str]] = {}
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if not (isinstance(target, ast.Name) and target.id in POLICY_TABLES):
                continue
            values = set()
            container = node.value
            if isinstance(container, (ast.Tuple, ast.List)):
                for element in container.elts:
                    if isinstance(element, ast.Constant):
                        values.add(str(element.value))
                    elif isinstance(element, ast.Call) and element.args and \
                            isinstance(element.args[0], ast.Constant):
                        values.add(str(element.args[0].value))  # re.compile("...")
            tables[target.id] = frozenset(values)
    return tables


def file_at(repo: Path, ref: str, path: str) -> str | None:
    done = git(repo, "show", f"{ref}:{path}")
    return done.stdout if done.returncode == 0 else None


def self_weakening(repo: Path, ref: str, changed: list[tuple[str, str, str | None]]) -> list[str]:
    """A change to the verifier's own policy tables that removes entries never passes."""
    problems: list[str] = []
    watched = ("zcode/gow3-dev-guard/hooks/guard_common.py",
               "zcode/gow3-dev-guard/tools/audit_gate.py")
    for path in watched:
        changed_paths = {record[1] for record in changed} | \
            {record[2] for record in changed if record[2]}
        if path not in changed_paths:
            continue
        reference = file_at(repo, ref, path)
        if reference is None:
            continue  # harness is new relative to the reference: nothing to weaken
        current_file = repo / Path(path)
        try:
            current = current_file.read_text(encoding="utf-8")
        except OSError:
            problems.append(f"{path}: verifier file unreadable (fail-closed)")
            continue
        try:
            new_tables = policy_tables(current)
        except SyntaxError:
            problems.append(f"{path}: verifier file unparseable (fail-closed)")
            continue
        old_tables = policy_tables(reference)
        for table, old_values in old_tables.items():
            removed = old_values - new_tables.get(table, frozenset())
            if removed:
                problems.append(f"{path}: policy table {table} weakened on this branch"
                                f" (removed: {', '.join(sorted(removed))})")
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repo", default=".", help="repository to audit (default: cwd)")
    parser.add_argument("--ref", default=None,
                        help="trusted reference (default: origin/main, else main)")
    parser.add_argument("--allow-path", action="append", default=[],
                        metavar="PATH",
                        help="explicit, auditable exception for one path"
                             " (upstream merges must declare it in the PR)")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    args = parser.parse_args()

    repo = Path(args.repo).resolve()
    if not (repo / ".git").exists():
        print(f"audit-gate: {repo} is not a git repository", file=sys.stderr)
        return EXIT_ERROR

    ref = args.ref
    if ref is None:
        ref = next((candidate for candidate in ("origin/main", "main")
                    if resolve_ref(repo, candidate)), None)
    if ref is None:
        print("audit-gate: no trusted reference (origin/main/main missing);"
              " pass --ref explicitly", file=sys.stderr)
        return EXIT_ERROR
    resolved = resolve_ref(repo, ref)
    if resolved is None:
        print(f"audit-gate: reference {ref!r} not found", file=sys.stderr)
        return EXIT_ERROR

    allowed = {((path.replace("\\", "/"))[2:] if path.replace("\\", "/")
                 .startswith("./") else path.replace("\\", "/"))
                for path in args.allow_path}
    try:
        changed = changed_records(repo, ref)
    except (RuntimeError, subprocess.SubprocessError) as error:
        print(f"audit-gate: {error}", file=sys.stderr)
        return EXIT_ERROR

    violations: list[str] = []
    for status, path, source in changed:
        posix = path.replace("\\", "/")
        sides = [(status, posix)]
        if source:
            sides.append((status, source.replace("\\", "/")))
        for entry_status, entry_path in sides:
            if entry_path in allowed:
                continue
            reason = path_violation(entry_status, entry_path)
            if reason:
                violations.append(f"[{entry_status}] {entry_path} — {reason}"
                                  f" (evidence: {ref}..worktree)")
    for path in untracked_proprietary(repo):
        if path.replace("\\", "/") not in allowed:
            violations.append(f"[??] {path} — proprietary game material untracked"
                              f" (evidence: git status)")
    violations.extend(self_weakening(repo, resolved, changed))

    summary = (f"AUDIT GATE: {'PASS' if not violations else 'FAIL'}"
               f" ({len(violations)} violation(s); base {ref} @ {resolved[:9]};"
               f" {len(changed)} changed record(s))")
    if args.json:
        print(json.dumps({"result": "PASS" if not violations else "FAIL",
                          "base": ref, "base_commit": resolved,
                          "changed_records": len(changed),
                          "violations": violations}, indent=2))
    else:
        for violation in violations:
            print(f"FAIL {violation}")
        print(summary)
    return EXIT_PASS if not violations else EXIT_FAIL


if __name__ == "__main__":
    sys.exit(main())
