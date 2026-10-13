#!/usr/bin/env python3
"""Deterministic tests for the independent Audit Gate (layer 2).

Every case builds a disposable repository, makes real git changes, and asserts the gate's
verdict (exit code and message). Nothing destructive touches the real repository.

Run:  python zcode/gow3-dev-guard/tests/test_audit_gate.py -v
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

GATE = Path(__file__).resolve().parent.parent / "tools" / "audit_gate.py"

GUARD_COMMON_MINIMAL = '''
PROTECTED_PREFIXES = ("src/", "gpu/shadps4/")
PROPRIETARY_PATTERNS = ()
TOP_AUTHORIZED_RM = ("out",)
NESTED_AUTHORIZED_RM = ("__pycache__",)
'''


def g(repo: Path, *args: str) -> None:
    done = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True,
                          timeout=60)
    assert done.returncode == 0, (f"git {args} failed: rc={done.returncode}"
                                  f" out={done.stdout!r} err={done.stderr!r}")


def commit_all(repo: Path, message: str) -> None:
    g(repo, "add", "-A")
    g(repo, "commit", "-m", message)


def make_repo() -> Path:
    """A repository on `main` with one base commit holding allowed and protected files."""
    repo = Path(tempfile.mkdtemp(prefix="gow3-gate-")) / "r"
    repo.mkdir()
    g(repo, "init", "-b", "main")
    g(repo, "config", "user.email", "t@t")
    g(repo, "config", "user.name", "t")
    (repo / "docs").mkdir()
    (repo / "docs" / "a.md").write_text("docs\n", encoding="utf-8")
    (repo / "launcher").mkdir()
    (repo / "launcher" / "x.py").write_text("x = 1\n", encoding="utf-8")
    (repo / "src").mkdir()
    (repo / "src" / "engine.c").write_text("int x;\n", encoding="utf-8")
    (repo / "build.sh").write_text("#!/bin/sh\n", encoding="utf-8")
    commit_all(repo, "base")
    g(repo, "checkout", "-b", "feat/work")
    return repo


def run_gate(repo: Path, *args: str) -> tuple[int, str]:
    done = subprocess.run([sys.executable, str(GATE), "--repo", str(repo), *args],
                          capture_output=True, text=True, timeout=120)
    return done.returncode, done.stdout + done.stderr


class PositiveFixtures(unittest.TestCase):
    def test_allowed_changes_pass(self):
        repo = make_repo()
        try:
            (repo / "docs" / "a.md").write_text("docs 2\n", encoding="utf-8")
            (repo / "launcher" / "x.py").write_text("x = 2\n", encoding="utf-8")
            (repo / "tools").mkdir()
            (repo / "tools" / "helper.py").write_text("pass\n", encoding="utf-8")
            (repo / ".gitignore").write_text("out/\n", encoding="utf-8")  # dot path kept
            commit_all(repo, "ui work")
            rc, out = run_gate(repo, "--ref", "main")
            self.assertEqual(rc, 0, out)
            self.assertIn("AUDIT GATE: PASS", out)
        finally:
            shutil.rmtree(repo.parent, ignore_errors=True)

    def test_worktree_only_changes_pass(self):
        repo = make_repo()
        try:
            (repo / "docs" / "a.md").write_text("uncommitted\n", encoding="utf-8")
            rc, out = run_gate(repo, "--ref", "main")
            self.assertEqual(rc, 0, out)  # in-scope uncommitted change: allowed
        finally:
            shutil.rmtree(repo.parent, ignore_errors=True)


class NegativeFixtures(unittest.TestCase):
    def assert_fail(self, repo: Path, needle: str, *args: str):
        rc, out = run_gate(repo, "--ref", "main", *args)
        self.assertEqual(rc, 1, out)
        self.assertIn(needle, out)

    def test_protected_file_modified(self):
        repo = make_repo()
        try:
            (repo / "src" / "engine.c").write_text("int y;\n", encoding="utf-8")
            commit_all(repo, "engine tweak")
            self.assert_fail(repo, "src/engine.c")
        finally:
            shutil.rmtree(repo.parent, ignore_errors=True)

    def test_proprietary_file_added(self):
        repo = make_repo()
        try:
            (repo / "dump").mkdir()
            (repo / "dump" / "eboot.bin").write_bytes(b"MZ...")
            commit_all(repo, "oops")
            self.assert_fail(repo, "eboot.bin")
        finally:
            shutil.rmtree(repo.parent, ignore_errors=True)

    def test_proprietary_file_untracked(self):
        repo = make_repo()
        try:
            (repo / "sce_module").mkdir()
            (repo / "sce_module" / "libc.prx").write_bytes(b"\0")
            rc, out = run_gate(repo, "--ref", "main")
            self.assertEqual(rc, 1, out)
            self.assertIn("libc.prx", out)
            self.assertIn("untracked", out)
        finally:
            shutil.rmtree(repo.parent, ignore_errors=True)

    def test_functional_change_outside_scope(self):
        repo = make_repo()
        try:
            (repo / "build.sh").write_text("#!/bin/sh\necho x\n", encoding="utf-8")
            commit_all(repo, "build tweak")
            self.assert_fail(repo, "outside the authorized scope")
        finally:
            shutil.rmtree(repo.parent, ignore_errors=True)

    def test_rename_into_protected(self):
        repo = make_repo()
        try:
            g(repo, "mv", "docs/a.md", "src/a.md")
            commit_all(repo, "move")
            self.assert_fail(repo, "src/a.md")
        finally:
            shutil.rmtree(repo.parent, ignore_errors=True)

    def test_gate_file_deleted(self):
        repo = make_repo()
        try:
            harness = repo / "zcode" / "gow3-dev-guard" / "hooks" / "guard_common.py"
            harness.parent.mkdir(parents=True)
            g(repo, "checkout", "main")
            harness.write_text(GUARD_COMMON_MINIMAL, encoding="utf-8")
            commit_all(repo, "add harness on main")
            g(repo, "checkout", "-b", "feat/drop")
            harness.unlink()
            commit_all(repo, "remove harness")
            self.assert_fail(repo, "harness file deleted")
        finally:
            shutil.rmtree(repo.parent, ignore_errors=True)

    def test_self_weakening_detected(self):
        repo = make_repo()
        try:
            guard = repo / "zcode" / "gow3-dev-guard" / "hooks" / "guard_common.py"
            guard.parent.mkdir(parents=True)
            g(repo, "checkout", "main")
            guard.write_text(GUARD_COMMON_MINIMAL, encoding="utf-8")
            commit_all(repo, "add harness on main")
            g(repo, "checkout", "-b", "feat/weaken")
            # shrink a policy table on the analyzed branch
            guard.write_text('PROTECTED_PREFIXES = ("src/",)\n' + GUARD_COMMON_MINIMAL
                             .replace('PROTECTED_PREFIXES = ("src/", "gpu/shadps4/")', ''),
                             encoding="utf-8")
            commit_all(repo, "weaken")
            rc, out = run_gate(repo, "--ref", "main")
            self.assertEqual(rc, 1, out)
            self.assertIn("weakened", out)
            self.assertIn("gpu/shadps4/", out)
        finally:
            shutil.rmtree(repo.parent, ignore_errors=True)

    def test_bad_reference_errors(self):
        repo = make_repo()
        try:
            rc, out = run_gate(repo, "--ref", "no-such-ref")
            self.assertEqual(rc, 2, out)
        finally:
            shutil.rmtree(repo.parent, ignore_errors=True)


class SubmoduleFixtures(unittest.TestCase):
    """Submodule content dirt (the build's patches) is fine; a pointer move is not."""

    def repo_with_submodule(self) -> Path:
        repo = make_repo()
        outer = repo.parent
        sub = outer / "sub-src"
        sub.mkdir()
        g(sub, "init", "-b", "main")
        g(sub, "config", "user.email", "t@t")
        g(sub, "config", "user.name", "t")
        (sub / "lib.cpp").write_text("int a;\n", encoding="utf-8")
        commit_all(sub, "sub base")
        # the submodule belongs to the trusted base: add it on main, then branch
        g(repo, "checkout", "main")
        # newer git blocks the file transport for submodules unless explicitly allowed
        done = subprocess.run(["git", "-C", str(repo), "-c", "protocol.file.allow=always",
                               "submodule", "add", str(sub), "gpu/third_party/fake"],
                              capture_output=True, text=True, timeout=60)
        assert done.returncode == 0, f"submodule add failed: {done.stderr}"
        commit_all(repo, "add submodule on main")
        g(repo, "checkout", "-b", "feat/sub")
        return repo

    def test_submodule_content_dirt_passes(self):
        repo = self.repo_with_submodule()
        try:
            (repo / "gpu" / "third_party" / "fake" / "lib.cpp").write_text("int b;\n",
                                                                          encoding="utf-8")
            rc, out = run_gate(repo, "--ref", "main")
            self.assertEqual(rc, 0, out)
        finally:
            shutil.rmtree(repo.parent, ignore_errors=True)

    def test_submodule_pointer_move_fails(self):
        repo = self.repo_with_submodule()
        try:
            g(repo.parent / "sub-src", "commit", "--allow-empty", "-m", "sub second")
            inside = repo / "gpu" / "third_party" / "fake"
            subprocess.run(["git", "-C", str(inside), "-c", "protocol.file.allow=always",
                            "fetch", "origin"], capture_output=True, timeout=60)
            g(inside, "checkout", "origin/main")  # the submodule worktree moves forward
            g(repo, "add", "gpu/third_party/fake")
            g(repo, "commit", "-m", "bump submodule", "gpu/third_party/fake")
            rc, out = run_gate(repo, "--ref", "main")
            self.assertEqual(rc, 1, out)
            self.assertIn("gpu/third_party/fake", out)
        finally:
            shutil.rmtree(repo.parent, ignore_errors=True)


class TrustBoundaryFixtures(unittest.TestCase):
    """The trust-boundary requirements: --head (trusted, commit-to-commit) mode,
    upstream exceptions with blob-level proof, review-required for security files,
    allowlist expansion as weakening, CI deletion. Written first (red step)."""

    REVIEW_REQUIRED = 3

    def test_head_mode_detects_protected_change(self):
        repo = make_repo()
        try:
            (repo / "src" / "engine.c").write_text("int y;\n", encoding="utf-8")
            commit_all(repo, "engine tweak")
            head = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"],
                                  capture_output=True, text=True).stdout.strip()
            rc, out = run_gate(repo, "--ref", "main", "--head", head)
            self.assertEqual(rc, 1, out)
            self.assertIn("src/engine.c", out)
        finally:
            shutil.rmtree(repo.parent, ignore_errors=True)

    def test_security_file_change_requires_trusted_review(self):
        repo = make_repo()
        try:
            harness = repo / "zcode" / "gow3-dev-guard"
            (harness / "hooks").mkdir(parents=True)
            (harness / "hooks" / "guard_common.py").write_text(GUARD_COMMON_MINIMAL,
                                                               encoding="utf-8")
            (harness / "tools").mkdir()
            (harness / "tools" / "audit_gate.py").write_text("AUTHORIZED_SCOPE = ('docs/',)\n",
                                                             encoding="utf-8")
            g(repo, "checkout", "main")
            commit_all(repo, "harness on main")
            g(repo, "checkout", "-b", "feat/gate-edit")
            # same tables, but the verifier CODE changed — tables alone must not bless it
            (harness / "tools" / "audit_gate.py").write_text(
                "AUTHORIZED_SCOPE = ('docs/',)\n# innocent-looking comment\n",
                encoding="utf-8")
            commit_all(repo, "gate edit")
            head = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"],
                                  capture_output=True, text=True).stdout.strip()
            rc, out = run_gate(repo, "--ref", "main", "--head", head)
            self.assertEqual(rc, self.REVIEW_REQUIRED, out)
            self.assertIn("review", out.lower())
        finally:
            shutil.rmtree(repo.parent, ignore_errors=True)

    def test_workflow_deletion_fails(self):
        repo = make_repo()
        try:
            workflow = repo / ".github" / "workflows" / "guard-audit.yml"
            workflow.parent.mkdir(parents=True)
            g(repo, "checkout", "main")
            workflow.write_text("name: guard-audit\n", encoding="utf-8")
            commit_all(repo, "ci on main")
            g(repo, "checkout", "-b", "feat/no-ci")
            workflow.unlink()
            commit_all(repo, "remove ci")
            rc, out = run_gate(repo, "--ref", "main")
            self.assertEqual(rc, 1, out)
            self.assertIn("guard-audit.yml", out)
        finally:
            shutil.rmtree(repo.parent, ignore_errors=True)

    def test_new_workflow_requires_review(self):
        repo = make_repo()
        try:
            workflow = repo / ".github" / "workflows" / "brand-new.yml"
            workflow.parent.mkdir(parents=True)
            workflow.write_text("name: sneaky\n", encoding="utf-8")
            commit_all(repo, "add workflow")
            rc, out = run_gate(repo, "--ref", "main")
            self.assertEqual(rc, self.REVIEW_REQUIRED, out)  # never an automatic PASS
            self.assertIn(".github/workflows/brand-new.yml", out)
        finally:
            shutil.rmtree(repo.parent, ignore_errors=True)

    def test_modifying_audit_workflow_requires_review(self):
        repo = make_repo()
        try:
            workflow = repo / ".github" / "workflows" / "guard-audit.yml"
            workflow.parent.mkdir(parents=True)
            g(repo, "checkout", "main")
            workflow.write_text("name: guard-audit\n", encoding="utf-8")
            commit_all(repo, "ci on main")
            g(repo, "checkout", "-b", "feat/ci-edit")
            workflow.write_text("name: guard-audit\n# tweak\n", encoding="utf-8")
            commit_all(repo, "edit ci")
            rc, out = run_gate(repo, "--ref", "main")
            self.assertEqual(rc, self.REVIEW_REQUIRED, out)
            self.assertIn("guard-audit.yml", out)
        finally:
            shutil.rmtree(repo.parent, ignore_errors=True)

    def test_approval_record_on_trusted_ref_resolves_review(self):
        repo = make_repo()
        try:
            workflow = repo / ".github" / "workflows" / "new.yml"
            workflow.parent.mkdir(parents=True)
            workflow.write_text("name: new\n", encoding="utf-8")
            commit_all(repo, "add workflow")
            head = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"],
                                  capture_output=True, text=True).stdout.strip()
            rc, out = run_gate(repo, "--ref", "main")
            self.assertEqual(rc, self.REVIEW_REQUIRED, out)  # unresolved first
            # the maintainer records the approval ON THE TRUSTED REFERENCE (main),
            # never inside the analyzed branch: a PR cannot approve itself
            reviews = repo / "zcode" / "gow3-dev-guard" / "reviews"
            g(repo, "checkout", "main")
            reviews.mkdir(parents=True)
            (reviews / "2026-10-13-new-workflow.json").write_text(json.dumps(
                {"head_sha": head, "pr": 7, "approved_by": "maintainer",
                 "note": "workflow reviewed"}), encoding="utf-8")
            commit_all(repo, "record approval")
            g(repo, "checkout", "-")  # back to the analyzed branch (same head sha)
            rc, out = run_gate(repo, "--ref", "main")
            self.assertEqual(rc, 0, out)
            self.assertIn("APPROVED", out)
        finally:
            shutil.rmtree(repo.parent, ignore_errors=True)

    def test_allowlist_expansion_needs_trusted_review(self):
        repo = make_repo()
        try:
            gate = repo / "zcode" / "gow3-dev-guard" / "tools" / "audit_gate.py"
            gate.parent.mkdir(parents=True)
            g(repo, "checkout", "main")
            gate.write_text("AUTHORIZED_SCOPE = ('docs/', 'launcher/')\n", encoding="utf-8")
            commit_all(repo, "gate on main")
            g(repo, "checkout", "-b", "feat/widen")
            gate.write_text("AUTHORIZED_SCOPE = ('docs/', 'launcher/', 'src/')\n",
                            encoding="utf-8")
            commit_all(repo, "widen scope")
            head = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"],
                                  capture_output=True, text=True).stdout.strip()
            rc, out = run_gate(repo, "--ref", "main", "--head", head)
            self.assertEqual(rc, self.REVIEW_REQUIRED, out)  # widening is never auto-PASS
            self.assertIn("allowlist", out.lower())
            self.assertIn("trusted-source review", out)
        finally:
            shutil.rmtree(repo.parent, ignore_errors=True)


class UpstreamExceptionFixtures(unittest.TestCase):
    """Exceptions only bless content PROVABLY identical to the approved upstream commit."""

    def context(self):
        outer = Path(tempfile.mkdtemp(prefix="gow3-upstream-"))
        upstream = outer / "upstream"
        upstream.mkdir()
        g(upstream, "init", "-b", "main")
        g(upstream, "config", "user.email", "t@t")
        g(upstream, "config", "user.name", "t")
        (upstream / "run.py").write_text("print('upstream 2.1.7')\n", encoding="utf-8")
        commit_all(upstream, "upstream release")
        approved = subprocess.run(["git", "-C", str(upstream), "rev-parse", "HEAD"],
                                  capture_output=True, text=True).stdout.strip()
        registry = outer / "registry.json"
        registry.write_text(json.dumps({"windows-v2.1.7":
                                        {"repo": str(upstream), "commit": approved}}),
                            encoding="utf-8")
        repo = make_repo()
        return repo, upstream, registry

    def exception_file(self, repo: Path, files: list[str], tag: str = "windows-v2.1.7") -> Path:
        path = repo / "zcode" / "upstream-exceptions" / "windows-v2.1.7.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"tag": tag, "files": files}), encoding="utf-8")
        return path

    def test_matching_content_is_allowed(self):
        repo, upstream, registry = self.context()
        try:
            (repo / "run.py").write_text("print('upstream 2.1.7')\n", encoding="utf-8")
            self.exception_file(repo, ["run.py"])
            commit_all(repo, "sync upstream")
            rc, out = run_gate(repo, "--ref", "main", "--registry-file", str(registry),
                               "--upstream-exception", "zcode/upstream-exceptions/windows-v2.1.7.json")
            self.assertEqual(rc, 0, out)
            self.assertIn("upstream exception", out.lower())
        finally:
            shutil.rmtree(repo.parent, ignore_errors=True)

    def test_diverging_content_fails(self):
        repo, upstream, registry = self.context()
        try:
            (repo / "run.py").write_text("print('tampered')\n", encoding="utf-8")
            self.exception_file(repo, ["run.py"])
            commit_all(repo, "fake sync")
            rc, out = run_gate(repo, "--ref", "main", "--registry-file", str(registry),
                               "--upstream-exception", "zcode/upstream-exceptions/windows-v2.1.7.json")
            self.assertEqual(rc, 1, out)
            self.assertIn("does not match", out)
        finally:
            shutil.rmtree(repo.parent, ignore_errors=True)

    def test_proprietary_cannot_be_excepted(self):
        repo, upstream, registry = self.context()
        try:
            (repo / "dump").mkdir()
            (repo / "dump" / "eboot.bin").write_bytes(b"MZ")
            self.exception_file(repo, ["dump/eboot.bin"])
            commit_all(repo, "oops")
            rc, out = run_gate(repo, "--ref", "main", "--registry-file", str(registry),
                               "--upstream-exception", "zcode/upstream-exceptions/windows-v2.1.7.json")
            self.assertEqual(rc, 1, out)
            self.assertIn("eboot.bin", out)
        finally:
            shutil.rmtree(repo.parent, ignore_errors=True)

    def test_unknown_tag_fails(self):
        repo, upstream, registry = self.context()
        try:
            (repo / "run.py").write_text("print('upstream 2.1.7')\n", encoding="utf-8")
            self.exception_file(repo, ["run.py"], tag="windows-v9.9.9")
            commit_all(repo, "sync")
            rc, out = run_gate(repo, "--ref", "main", "--registry-file", str(registry),
                               "--upstream-exception", "zcode/upstream-exceptions/windows-v2.1.7.json")
            self.assertEqual(rc, 1, out)
            self.assertIn("windows-v9.9.9", out)
        finally:
            shutil.rmtree(repo.parent, ignore_errors=True)

    def test_workflow_cannot_be_excepted(self):
        repo, upstream, registry = self.context()
        try:
            workflow = repo / ".github" / "workflows" / "guard-audit.yml"
            workflow.parent.mkdir(parents=True)
            g(repo, "checkout", "main")
            workflow.write_text("name: guard-audit\n", encoding="utf-8")
            commit_all(repo, "ci on main")
            g(repo, "checkout", "-b", "feat/ci-sneak")
            workflow.write_text("name: guard-audit\n# changed\n", encoding="utf-8")
            self.exception_file(repo, [".github/workflows/guard-audit.yml"])
            commit_all(repo, "except ci away")
            rc, out = run_gate(repo, "--ref", "main", "--registry-file", str(registry),
                               "--upstream-exception", "zcode/upstream-exceptions/windows-v2.1.7.json")
            self.assertEqual(rc, 1, out)
            self.assertIn("never exceptable", out)
        finally:
            shutil.rmtree(repo.parent, ignore_errors=True)

    def test_harness_cannot_be_excepted(self):
        repo, upstream, registry = self.context()
        try:
            harness = repo / "zcode" / "gow3-dev-guard" / "hooks" / "guard_common.py"
            harness.parent.mkdir(parents=True)
            g(repo, "checkout", "main")
            harness.write_text(GUARD_COMMON_MINIMAL, encoding="utf-8")
            commit_all(repo, "harness on main")
            g(repo, "checkout", "-b", "feat/sneaky")
            harness.unlink()
            self.exception_file(repo, ["zcode/gow3-dev-guard/hooks/guard_common.py"])
            commit_all(repo, "except harness away")
            rc, out = run_gate(repo, "--ref", "main", "--registry-file", str(registry),
                               "--upstream-exception", "zcode/upstream-exceptions/windows-v2.1.7.json")
            self.assertEqual(rc, 1, out)
            self.assertIn("harness", out.lower())
        finally:
            shutil.rmtree(repo.parent, ignore_errors=True)


class ProprietaryUnconditionalFixtures(unittest.TestCase):
    """Proprietary game material fails UNCONDITIONALLY — no surface, special directory or
    approval mechanism can ever shelter it (audit item 2)."""

    def _assert_fail(self, repo: Path, needle: str):
        rc, out = run_gate(repo, "--ref", "main")
        self.assertEqual(rc, 1, out)  # FAIL, never PASS and never REVIEW_REQUIRED
        self.assertIn(needle, out)

    def test_proprietary_inside_reviews_dir(self):
        repo = make_repo()
        try:
            sneaky = repo / "zcode" / "gow3-dev-guard" / "reviews" / "eboot.bin"
            sneaky.parent.mkdir(parents=True)
            sneaky.write_bytes(b"MZ")
            commit_all(repo, "sneak review")
            self._assert_fail(repo, "eboot.bin")
        finally:
            shutil.rmtree(repo.parent, ignore_errors=True)

    def test_proprietary_inside_upstream_exceptions_dir(self):
        repo = make_repo()
        try:
            sneaky = repo / "zcode" / "upstream-exceptions" / "game.pkg"
            sneaky.parent.mkdir(parents=True)
            sneaky.write_bytes(b"\x7fPKG")
            commit_all(repo, "sneak exception")
            self._assert_fail(repo, "game.pkg")
        finally:
            shutil.rmtree(repo.parent, ignore_errors=True)

    def test_proprietary_inside_workflows_dir(self):
        repo = make_repo()
        try:
            sneaky = repo / ".github" / "workflows" / "lib.prx"
            sneaky.parent.mkdir(parents=True)
            sneaky.write_bytes(b"\0")
            commit_all(repo, "sneak workflow")
            self._assert_fail(repo, "lib.prx")
        finally:
            shutil.rmtree(repo.parent, ignore_errors=True)

    def test_proprietary_savedata_inside_zcode(self):
        repo = make_repo()
        try:
            sneaky = repo / "zcode" / "savedata" / "slot1.bin"
            sneaky.parent.mkdir(parents=True)
            sneaky.write_bytes(b"\0")
            commit_all(repo, "sneak savedata")
            self._assert_fail(repo, "savedata")
        finally:
            shutil.rmtree(repo.parent, ignore_errors=True)

    def test_self_approval_inside_the_pr_is_ignored(self):
        repo = make_repo()
        try:
            workflow = repo / ".github" / "workflows" / "new.yml"
            workflow.parent.mkdir(parents=True)
            workflow.write_text("name: new\n", encoding="utf-8")
            reviews = repo / "zcode" / "gow3-dev-guard" / "reviews"
            reviews.mkdir(parents=True)
            (reviews / "self-approval.json").write_text("{}", encoding="utf-8")
            commit_all(repo, "add workflow + self approval placeholder")
            # the PR tries to approve ITSELF: the record lives in the analyzed branch,
            # not in the trusted reference — it must be ignored (still REVIEW_REQUIRED)
            head = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"],
                                  capture_output=True, text=True).stdout.strip()
            (reviews / "self-approval.json").write_text(json.dumps(
                {"head_sha": head, "pr": 99, "approved_by": "attacker",
                 "note": "self approval"}), encoding="utf-8")
            commit_all(repo, "self approve")
            head = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"],
                                  capture_output=True, text=True).stdout.strip()
            rc, out = run_gate(repo, "--ref", "main", "--head", head)
            self.assertEqual(rc, 3, out)
            self.assertIn("REVIEW REQUIRED", out)
        finally:
            shutil.rmtree(repo.parent, ignore_errors=True)


if __name__ == "__main__":
    unittest.main(verbosity=2)
