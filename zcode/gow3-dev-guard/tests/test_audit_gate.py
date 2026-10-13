#!/usr/bin/env python3
"""Deterministic tests for the independent Audit Gate (layer 2).

Every case builds a disposable repository, makes real git changes, and asserts the gate's
verdict (exit code and message). Nothing destructive touches the real repository.

Run:  python zcode/gow3-dev-guard/tests/test_audit_gate.py -v
"""
from __future__ import annotations

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
            (repo / "zcode").mkdir()
            (repo / "zcode" / "new.py").write_text("pass\n", encoding="utf-8")
            (repo / "launcher" / "x.py").write_text("x = 2\n", encoding="utf-8")
            # dot-prefixed authorized paths must not lose their leading dot
            (repo / ".github" / "workflows").mkdir(parents=True)
            (repo / ".github" / "workflows" / "ci.yml").write_text("name: ci\n",
                                                                    encoding="utf-8")
            (repo / ".gitignore").write_text("out/\n", encoding="utf-8")
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

    def test_allow_path_exception_is_explicit(self):
        repo = make_repo()
        try:
            (repo / "build.sh").write_text("#!/bin/sh\necho x\n", encoding="utf-8")
            commit_all(repo, "build tweak")
            rc, out = run_gate(repo, "--ref", "main", "--allow-path", "build.sh")
            self.assertEqual(rc, 0, out)
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


if __name__ == "__main__":
    unittest.main(verbosity=2)
