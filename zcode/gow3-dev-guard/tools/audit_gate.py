#!/usr/bin/env python3
"""gow3-dev-guard — Audit Gate v2 (trusted-source integrity verifier).

Independent, deterministic verifier of the repository's REAL changes. It reads git itself
(committed, staged, worktree and untracked state), never the LLM's interpretation and never
the text of the commands that produced the changes.

Trust boundary (the code that approves a PR must not be the PR's own code):
  * CI runs this gate FROM THE TRUSTED BASE REF (see .github/workflows/guard-audit.yml,
    pull_request_target, permissions: contents: read). The PR head is fetched as DATA
    (objects for diffing) and no PR code is ever executed in that privileged context.
  * `--head COMMIT` audits commit-to-commit, so the worktree never influences the verdict.
  * Functional tests of the PR branch run in a SEPARATE unprivileged pull_request workflow
    (guard-tests.yml).

Usage (CLI or CI):
  python audit_gate.py [--repo DIR] [--ref REF] [--head COMMIT]
                       [--upstream-exception FILE] [--registry-file FILE] [--json]

Exit codes: 0 PASS · 1 FAIL (violations) · 2 error (fail-closed) ·
3 REVIEW REQUIRED — security files (verifier/hooks/CI) changed with no other violation;
only the trusted source (maintainer review on the protected base) can bless that.

Integrity model (audited classes of self-change):
  * blocklists (PROTECTED_PREFIXES, PROPRIETARY_PATTERNS, MAIN_BRANCHES):
        removing entries weakens  -> FAIL;
  * allowlists (AUTHORIZED_SCOPE, TOP_AUTHORIZED_RM, NESTED_AUTHORIZED_RM,
        APPROVED_UPSTREAM): adding entries weakens -> FAIL;
  * any other change to the verifier/hooks/CI files themselves: never auto-approved by
        table comparison -> exit 3 (trusted review required);
  * deleting harness or CI files: FAIL, and NO exception can ever cover it.

Upstream sync exceptions (`--upstream-exception FILE`, a JSON committed with the PR):
  {"tag": "windows-v2.1.7", "files": ["run.py", ...]}
  The tag must exist in the pinned registry (APPROVED_UPSTREAM below, or --registry-file
  for tests/maintenance), and every listed file must be BLOB-IDENTICAL to the approved
  upstream commit — content proven by `git rev-parse <commit>:<path>`, not by trust in the
  path name. Proprietary material, harness deletion and CI changes are never exceptable.
"""
from __future__ import annotations

import argparse
import ast
import json
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

# Approved upstream integrations (tag -> repository and exact commit). Grows only through
# trusted-source review: adding an entry on a branch fails the gate (allowlist expansion).
APPROVED_UPSTREAM = {
    "windows-v2.1.7": {
        "repo": "https://github.com/FelipePrado0/gow3_pc",
        "commit": "b907d8a9f2324ba5f514fbfe7de803e027c6ca26",
    },
    "windows-v2.1.8": {
        "repo": "https://github.com/FelipePrado0/gow3_pc",
        "commit": "bb74e41cc3c9435c89e3bbd3994b608ad3cff627",
    },
}

# Security surfaces: every workflow file and the whole harness/plugin tree. Any change
# there (add/modify/rename) requires trusted review; deletion is a hard violation; none
# of it can be excepted. Maintainer approval records live under REVIEWS_PREFIX and are
# read from the TRUSTED reference only — a PR can never approve itself.
WORKFLOWS_PREFIX = ".github/workflows/"
HARNESS_PREFIX = "zcode/"
REVIEWS_PREFIX = "zcode/gow3-dev-guard/reviews/"
# Exception declarations are data: their effect is bounded by the pinned registry and the
# blob-identity proof, so they are not a security surface on their own.
UPSTREAM_EXCEPTIONS_PREFIX = "zcode/upstream-exceptions/"

# Integrity classes of the policy tables.
BLOCKLIST_TABLES = ("PROTECTED_PREFIXES", "PROPRIETARY_PATTERNS", "MAIN_BRANCHES")
ALLOWLIST_TABLES = ("AUTHORIZED_SCOPE", "TOP_AUTHORIZED_RM", "NESTED_AUTHORIZED_RM",
                    "APPROVED_UPSTREAM")
POLICY_TABLES = BLOCKLIST_TABLES + ALLOWLIST_TABLES

EXIT_PASS, EXIT_FAIL, EXIT_ERROR, EXIT_REVIEW = 0, 1, 2, 3


def git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(repo), "-c", "diff.ignoreSubmodules=dirty",
                           *args], capture_output=True, text=True, timeout=90,
                          creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


def resolve_ref(repo: Path, ref: str) -> str | None:
    done = git(repo, "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}")
    return done.stdout.strip() if done.returncode == 0 else None


def changed_records(repo: Path, ref: str, head: str | None) -> list[tuple[str, str, str | None]]:
    """[(status, path, rename_source|None)] — head mode diffs ref...head (merge-base, the
    PR's own changes); worktree mode diffs ref..worktree (committed+staged+unstaged)."""
    spec = f"{ref}...{head}" if head else ref
    done = git(repo, "diff", "--name-status", "-z", spec)
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


def normalize(path: str) -> str:
    path = path.replace("\\", "/")
    return path[2:] if path.startswith("./") else path


def is_security_path(posix: str) -> bool:
    """Workflows and the harness/plugin tree are security surfaces. Exception
    declarations and maintainer approval records are data, not control code."""
    posix = normalize(posix)
    if posix.startswith(UPSTREAM_EXCEPTIONS_PREFIX) or posix.startswith(REVIEWS_PREFIX):
        return False
    return posix.startswith(WORKFLOWS_PREFIX) or posix.startswith(HARNESS_PREFIX)


def path_violation(status: str, posix: str) -> str | None:
    """The reason one changed path fails the gate (before exceptions), or None.
    Proprietary game material is checked FIRST and fails unconditionally — no surface,
    prefix or special directory (reviews, upstream exceptions, workflows, harness) can
    ever shelter it."""
    posix = normalize(posix)
    if g.proprietary(posix):
        return "proprietary game material in the changeset (AGENTS.md rule 4)"
    if posix.startswith(REVIEWS_PREFIX) or posix.startswith(UPSTREAM_EXCEPTIONS_PREFIX):
        return None  # maintainer approval records and exception declarations: data
    if posix.startswith(WORKFLOWS_PREFIX):
        if status == "D":
            return "workflow deleted — CI disablement, never exceptable"
        return None  # workflow add/modify/rename: REVIEW REQUIRED, not auto-PASS
    if posix.startswith(HARNESS_PREFIX):
        if status == "D":
            return "harness file deleted — removal can never be excepted"
        return None  # harness add/modify: REVIEW REQUIRED (auditable protocol)
    reason = g.write_violation(posix, posix)
    if reason:
        return f"protected path changed: {reason.split(':')[0]}"
    if not in_scope(posix):
        return (f"functional change outside the authorized scope: {posix}"
                " (UI/harness work stays in docs/, launcher/, tests/, zcode/, packaging/,"
                " tools/, .github/, gpu/shim/gow3_overlay.cpp)")
    return None


def policy_tables(source: str) -> dict[str, frozenset[str]]:
    """The policy table literals of a python source, via ast (no import, no execution).
    Mapping tables (APPROVED_UPSTREAM) contribute composite 'tag:{k=v,...}' keys."""
    tables: dict[str, frozenset[str]] = {}
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if not (isinstance(target, ast.Name) and target.id in POLICY_TABLES):
                continue
            values: set[str] = set()
            container = node.value
            if isinstance(container, (ast.Tuple, ast.List)):
                for element in container.elts:
                    if isinstance(element, ast.Constant):
                        values.add(str(element.value))
                    elif isinstance(element, ast.Call) and element.args and \
                            isinstance(element.args[0], ast.Constant):
                        values.add(str(element.args[0].value))  # re.compile("...")
            elif isinstance(container, ast.Dict):
                for key, value in zip(container.keys, container.values):
                    if isinstance(key, ast.Constant) and isinstance(value, ast.Dict):
                        parts = []
                        for sub_key, sub_value in zip(value.keys, value.values):
                            if isinstance(sub_key, ast.Constant):
                                rendered = sub_value.value \
                                    if isinstance(sub_value, ast.Constant) else "<expr>"
                                parts.append(f"{sub_key.value}={rendered}")
                        values.add(f"{key.value}:{{{','.join(sorted(parts))}}}")
            tables[target.id] = frozenset(values)
    return tables


def file_at(repo: Path, ref: str, path: str) -> str | None:
    done = git(repo, "show", f"{ref}:{path}")
    return done.stdout if done.returncode == 0 else None


def self_integrity(repo: Path, ref: str, head: str | None,
                   changed: list[tuple[str, str, str | None]]) -> tuple[list[str], list[str]]:
    """(violations, review_required): policy-table weakening fails; every other change on
    a security surface (workflows, harness) demands trusted review — which a maintainer
    records under REVIEWS_PREFIX on the trusted reference (never in the PR)."""
    violations: list[str] = []
    review: list[str] = []
    changed_paths = {normalize(record[1]) for record in changed} | \
        {normalize(record[2]) for record in changed if record[2]}
    for path, tables in (("zcode/gow3-dev-guard/hooks/guard_common.py",
                          BLOCKLIST_TABLES + ALLOWLIST_TABLES[1:3]),
                         ("zcode/gow3-dev-guard/tools/audit_gate.py",
                          ("AUTHORIZED_SCOPE", "APPROVED_UPSTREAM"))):
        if path not in changed_paths:
            continue
        reference = file_at(repo, ref, path)
        if reference is None:
            continue  # harness is new relative to the reference: nothing to weaken yet
        current = file_at(repo, head, path) if head else None
        if current is None:
            try:
                current = (repo / Path(path)).read_text(encoding="utf-8")
            except OSError:
                violations.append(f"{path}: verifier file unreadable (fail-closed)")
                continue
        try:
            new_tables = policy_tables(current)
        except SyntaxError:
            violations.append(f"{path}: verifier file unparseable (fail-closed)")
            continue
        old_tables = policy_tables(reference)
        for table in tables:
            old_values = old_tables.get(table, frozenset())
            new_values = new_tables.get(table, frozenset())
            if table in BLOCKLIST_TABLES:
                removed = old_values - new_values
                if removed:
                    violations.append(f"{path}: blocklist {table} weakened on this branch"
                                      f" (removed: {', '.join(sorted(removed))})")
            else:
                added = new_values - old_values
                if added:
                    review.append(f"{path}: allowlist {table} expanded on this branch"
                                  f" (added: {', '.join(sorted(added))}) — widening"
                                  " permissions needs trusted-source review")
    for record_status, path, source in changed:
        for side in (path, source or ""):
            posix = normalize(side)
            if not posix or not is_security_path(posix) or record_status == "D":
                continue  # deletions are already hard violations
            review.append(f"{posix} (security surface changed)")
    return violations, review


def approved_heads(repo: Path, ref: str) -> dict[str, str]:
    """{head_sha: record} of maintainer approval records ON THE TRUSTED REFERENCE.
    The analyzed PR cannot inject approvals: they are read from the ref's tree only."""
    approved: dict[str, str] = {}
    done = git(repo, "ls-tree", "-r", "--name-only", ref, "--", REVIEWS_PREFIX)
    if done.returncode != 0:
        return approved
    for name in done.stdout.splitlines():
        if not name.endswith(".json"):
            continue
        content = file_at(repo, ref, name)
        if not content:
            continue
        try:
            record = json.loads(content)
        except ValueError:
            continue
        sha = record.get("head_sha")
        if isinstance(sha, str) and re.fullmatch(r"[0-9a-f]{40}", sha):
            approved[sha] = name
    return approved


def load_registry(path: str | None) -> dict:
    if path:
        try:
            return json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            raise RuntimeError(f"registry file unreadable: {error}")
    return APPROVED_UPSTREAM


def fetch_upstream(repo: Path, url: str, commit: str) -> bool:
    """Bring the approved upstream commit's objects in as DATA (never executed)."""
    for args in ((url, commit), (url, "+refs/heads/*:refs/remotes/gow3-upstream/*")):
        done = git(repo, "fetch", "--quiet", "--no-tags", *args)
        if done.returncode == 0 and resolve_ref(repo, commit):
            return True
    return False


def upstream_exception_files(repo: Path, head: str | None, exception_path: str,
                             registry: dict) -> tuple[set[str], list[str]]:
    """(exempt_paths, problems) — a file is exempt only when its blob is identical to the
    approved upstream commit's blob (content provenance, not trust in a path name)."""
    problems: list[str] = []
    try:
        declaration = json.loads((repo / exception_path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        return set(), [f"upstream exception unreadable: {error}"]
    tag = declaration.get("tag")
    files = declaration.get("files")
    if not isinstance(tag, str) or not isinstance(files, list):
        return set(), ["upstream exception must declare {tag, files[]}"]
    entry = registry.get(tag)
    if not isinstance(entry, dict):
        return set(), [f"upstream exception: unknown tag {tag!r} (not in the approved"
                       " registry)"]
    url, commit = entry.get("repo", ""), entry.get("commit", "")
    if not url or not commit:
        return set(), [f"upstream registry entry for {tag} is incomplete"]
    if not fetch_upstream(repo, url, commit):
        return set(), [f"upstream commit {commit[:9]} of {tag} could not be fetched"
                       " (fail-closed)"]
    exempt: set[str] = set()
    for name in files:
        posix = normalize(str(name))
        if g.proprietary(posix):
            problems.append(f"upstream exception for {posix}: proprietary material is"
                            " never exceptable")
            continue
        if is_security_path(posix):
            problems.append(f"upstream exception for {posix}: security/harness files are"
                            " never exceptable")
            continue
        ours = git(repo, "rev-parse", "--verify", "--quiet",
                   f"{head or 'HEAD'}:{posix}").stdout.strip()
        if not head:
            blob = repo / posix
            if blob.is_file():
                ours = git(repo, "hash-object", str(blob)).stdout.strip() or ours
        theirs = git(repo, "rev-parse", "--verify", "--quiet",
                     f"{commit}:{posix}").stdout.strip()
        if not theirs:
            problems.append(f"upstream exception for {posix}: file does not exist at"
                            f" {tag} ({commit[:9]})")
        elif ours != theirs:
            problems.append(f"upstream exception for {posix}: content does not match"
                            f" {tag} ({commit[:9]}) — only blob-identical files are"
                            " exceptable")
        else:
            exempt.add(posix)
    return exempt, problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repo", default=".", help="repository to audit (default: cwd)")
    parser.add_argument("--ref", default=None,
                        help="trusted reference (default: origin/main, else main)")
    parser.add_argument("--head", default=None,
                        help="audit ref...HEAD-commit (trusted CI mode; worktree ignored)")
    parser.add_argument("--upstream-exception", action="append", default=None, metavar="FILE",
                        help="JSON declaration {tag, files[]} for an approved upstream"
                             " sync (blob-identical content only); repeatable")
    parser.add_argument("--registry-file", default=None, metavar="FILE",
                        help="override the pinned upstream registry (tests/maintenance;"
                             " trusted CI never passes this)")
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
    head = resolve_ref(repo, args.head) if args.head else None
    if args.head and head is None:
        print(f"audit-gate: head {args.head!r} not found", file=sys.stderr)
        return EXIT_ERROR

    try:
        changed = changed_records(repo, ref, head)
        registry = load_registry(args.registry_file)
    except (RuntimeError, subprocess.SubprocessError) as error:
        print(f"audit-gate: {error}", file=sys.stderr)
        return EXIT_ERROR

    exempt: set[str] = set()
    upstream_notes: list[str] = []
    for exception_path in (args.upstream_exception or []):
        exempted, problems = upstream_exception_files(repo, head, exception_path, registry)
        exempt |= exempted
        upstream_notes.extend(problems)
    violations = list(upstream_notes)

    for status, path, source in changed:
        sides = [(status, normalize(path))]
        if source:
            sides.append((status, normalize(source)))
        for entry_status, posix in sides:
            if not posix:
                continue  # rename records carry a source; plain records do not
            if posix in exempt:
                continue
            reason = path_violation(entry_status, posix)
            if reason:
                violations.append(f"[{entry_status}] {posix} — {reason}"
                                  f" (evidence: {ref}..{head[:9] if head else 'worktree'})")
    if not head:
        for path in untracked_proprietary(repo):
            violations.append(f"[??] {normalize(path)} — proprietary game material"
                              " untracked (evidence: git status)")

    integrity_violations, review = self_integrity(repo, resolved, head, changed)
    violations.extend(integrity_violations)

    # REVIEW_REQUIRED never turns into PASS by itself: it is resolved only by a maintainer
    # approval record that lives on the TRUSTED reference (never in the analyzed PR).
    audited_sha = head or resolve_ref(repo, "HEAD")
    approvals = approved_heads(repo, resolved)
    approval_record = approvals.get(audited_sha) if audited_sha else None
    if approval_record and review and not violations:
        print(f"APPROVED by maintainer record {approval_record} @ {ref}")
        review = []

    if violations:
        result, code = "FAIL", EXIT_FAIL
    elif review:
        result, code = "REVIEW_REQUIRED", EXIT_REVIEW
    else:
        result, code = "PASS", EXIT_PASS
    exception_note = f"; upstream exception applied to {len(exempt)} file(s)" if exempt else ""
    summary = (f"AUDIT GATE: {result} ({len(violations)} violation(s);"
               f" {len(review)} review-required; base {ref} @ {resolved[:9]};"
               f" head {head[:9] if head else 'worktree'}; {len(changed)} changed"
               f" record(s){exception_note})")
    if args.json:
        print(json.dumps({"result": result, "base": ref, "base_commit": resolved,
                          "head": head, "changed_records": len(changed),
                          "upstream_exempt": sorted(exempt),
                          "violations": violations,
                          "review_required": review}, indent=2))
    else:
        for note in upstream_notes:
            print(f"FAIL {note}")
        for violation in violations:
            print(f"FAIL {violation}")
        for item in review:
            print(f"REVIEW REQUIRED (trusted source): {item}")
        print(summary)
    return code


if __name__ == "__main__":
    sys.exit(main())
