#!/usr/bin/env python3
"""Deterministic negative/positive tests for the gow3-dev-guard hooks.

Every case feeds a simulated hook payload (the same JSON the ZCode hook runner delivers on
stdin) to the real hook scripts and asserts the exit code (0 = pass, 2 = deliberate block).
No LLM, no network, no game files: verdicts come from code and conditions only.

Run:  python zcode/gow3-dev-guard/tests/test_guard.py -v
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
PLUGIN = HERE.parent
REPO = PLUGIN.parents[1]
HOOKS = PLUGIN / "hooks"

PASS, BLOCK = 0, 2


def run_hook(script: str, payload, env_extra: dict | None = None, raw_stdin: bytes | None = None):
    """Run a hook script the way the host does: JSON on stdin, exit code decides."""
    env = dict(os.environ)
    env.setdefault("ZCODE_PROJECT_DIR", str(REPO))
    env.update(env_extra or {})
    data = raw_stdin if raw_stdin is not None else json.dumps(payload).encode("utf-8")
    done = subprocess.run([sys.executable, str(HOOKS / script)], input=data,
                          capture_output=True, text=False, env=env, timeout=60)
    return done.returncode, done.stderr.decode("utf-8", errors="replace"), \
        done.stdout.decode("utf-8", errors="replace")


def bash(command: str, project: str | None = None) -> tuple[int, str, str]:
    return run_hook("pre_tool_use.py",
                    {"tool_name": "Bash", "tool_input": {"command": command},
                     "cwd": project or str(REPO), "session_id": "test-session"},
                    {"ZCODE_PROJECT_DIR": project or str(REPO)})


def edit(path: str, project: str | None = None) -> tuple[int, str, str]:
    return run_hook("pre_tool_use.py",
                    {"tool_name": "Edit", "tool_input": {"file_path": path, "old_string": "a",
                                                         "new_string": "b"},
                     "cwd": project or str(REPO), "session_id": "test-session"},
                    {"ZCODE_PROJECT_DIR": project or str(REPO)})


VALID_REPORT = """```text
╔══════════════════════════════════════════╗
║           GOW3 — ZCODE REPORT            ║
╚══════════════════════════════════════════╝

TASK
  Name:        teste
  Status:      COMPLETED

GIT
  Branch:      chore/test
  Commit:      abc1234
  Remote:      SYNCED

BASELINE
  Status:      PASS
  Reference:   a603752

CHANGES
  Added:       1
  Modified:    0
  Removed:     0
  Files:       zcode/gow3-dev-guard/x.py

VALIDATION
  Python:      PASS
  Native:      BLOCKED
  Build:       NOT_RUN
  Package:     NOT_RUN
  UI:          NOT_RUN
  Runtime:     NOT_RUN

AUDIT GATE
  Result:      PASS
  Regressions: 0
  Evidence:    tests/test_guard.py

RISKS
  NONE

FINAL STATUS
  READY_FOR_REVIEW

NEXT
  próxima ação
```"""


def temp_repo(default_branch: str = "feat/x") -> Path:
    """A disposable git repository with one commit, on `default_branch`."""
    tmp = Path(tempfile.mkdtemp(prefix="gow3-guard-fixture-"))
    repo = tmp / "r"
    repo.mkdir()
    for args in (["init", "-b", default_branch], ["config", "user.email", "t@t"],
                 ["config", "user.name", "t"], ["commit", "--allow-empty", "-m", "x"]):
        subprocess.run(["git", "-C", str(repo), *args], capture_output=True, timeout=30)
    return repo


class PluginDeclaration(unittest.TestCase):
    """The plugin declares itself exactly the way the installed ZCode expects."""

    def test_manifest_valid(self):
        manifest = json.loads((PLUGIN / ".zcode-plugin" / "plugin.json").read_text(encoding="utf-8"))
        self.assertTrue(re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,127}", manifest["name"]),
                        "plugin name must match the official pattern")
        # hooks/hooks.json is auto-discovered at its default location; an explicit
        # "hooks": "hooks" declaration is redundant (audit item 6) and must stay out.
        self.assertNotIn("hooks", manifest)
        for component in ("commands", "skills", "mcpServers"):
            self.assertNotIn(component, manifest, "this plugin intentionally has only hooks")
        self.assertTrue((HOOKS / "hooks.json").is_file(),
                        "default hooks/hooks.json must exist for auto-discovery")

    def test_hooks_json_schema(self):
        spec = json.loads((HOOKS / "hooks.json").read_text(encoding="utf-8"))
        events = spec["hooks"]
        for event in events:
            self.assertIn(event, {"SessionStart", "UserPromptSubmit", "PreToolUse",
                                  "PermissionRequest", "PostToolUse", "PostToolUseFailure",
                                  "Stop"}, f"unsupported event {event}")
            for group in events[event]:
                if "matcher" in group:
                    re.compile(group["matcher"])  # must be a valid regular expression
                for hook in group["hooks"]:
                    self.assertIn(hook["type"], ("command", "process"))
                    if hook["type"] == "process":
                        self.assertEqual(set(hook), {"type", "command", "args", "timeoutMs",
                                                     "statusMessage"},
                                         "process hooks take exactly command/args/timeoutMs"
                                         " (+statusMessage)")
                    for value in hook.get("args", []):
                        self.assertNotIn("${SKILL", value, "skill vars are invalid in hooks")
        self.assertEqual(set(events), {"SessionStart", "PreToolUse", "Stop"})

    def test_marketplace_json_valid(self):
        market = json.loads((REPO / "zcode" / "marketplace.json").read_text(encoding="utf-8"))
        self.assertIn("name", market)
        entry = market["plugins"][0]
        self.assertEqual(entry["name"], "gow3-dev-guard")
        source = entry["source"]
        plugin_dir = (REPO / "zcode" / source).resolve() if isinstance(source, str) else None
        self.assertIsNotNone(plugin_dir, "source must be a relative path for a local marketplace")
        self.assertTrue((plugin_dir / ".zcode-plugin" / "plugin.json").is_file(),
                        "marketplace source must point at the plugin root")

    def test_hook_scripts_exist(self):
        for name in ("pre_tool_use.py", "stop_guard.py", "session_context.py",
                     "guard_common.py"):
            self.assertTrue((HOOKS / name).is_file(), f"missing {name}")


class BlocksMainChanges(unittest.TestCase):
    def test_checkout_main(self):
        rc, _, _ = bash("git checkout main")
        self.assertEqual(rc, BLOCK)

    def test_switch_main(self):
        rc, _, _ = bash("git switch main")
        self.assertEqual(rc, BLOCK)

    def test_push_main(self):
        rc, _, _ = bash("git push origin main")
        self.assertEqual(rc, BLOCK)

    def test_push_head_to_main(self):
        rc, _, _ = bash("git push origin HEAD:main")
        self.assertEqual(rc, BLOCK)

    def test_commit_while_on_main(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "r"
            repo.mkdir()
            for args in (["init", "-b", "main"], ["config", "user.email", "t@t"],
                         ["config", "user.name", "t"], ["commit", "--allow-empty", "-m", "x"]):
                subprocess.run(["git", "-C", str(repo), *args], capture_output=True, timeout=30)
            rc, err, _ = bash("git commit -m 'x'", project=str(repo))
            self.assertEqual(rc, BLOCK)
            rc, _, _ = edit(str(repo / "README.md"), project=str(repo))
            self.assertEqual(rc, BLOCK)
            # and a branch switch away from main makes the same write pass
            subprocess.run(["git", "-C", str(repo), "checkout", "-b", "feat/x"],
                           capture_output=True, timeout=30)
            rc, _, _ = edit(str(repo / "README.md"), project=str(repo))
            self.assertEqual(rc, PASS)

    def test_compound_git_commit_on_main(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "r"
            repo.mkdir()
            for args in (["init", "-b", "main"], ["config", "user.email", "t@t"],
                         ["config", "user.name", "t"], ["commit", "--allow-empty", "-m", "x"]):
                subprocess.run(["git", "-C", str(repo), *args], capture_output=True, timeout=30)
            rc, _, _ = bash(f"cd {repo} && git commit -m x", project=str(repo))
            self.assertEqual(rc, BLOCK)


class BlocksDestructive(unittest.TestCase):
    def test_force_push(self):
        self.assertEqual(bash("git push --force origin chore/x")[0], BLOCK)

    def test_force_with_lease(self):
        self.assertEqual(bash("git push --force-with-lease origin chore/x")[0], BLOCK)

    def test_reset_hard(self):
        self.assertEqual(bash("git reset --hard HEAD~3")[0], BLOCK)

    def test_clean_fdx(self):
        self.assertEqual(bash("git clean -fdx")[0], BLOCK)

    def test_branch_capital_d(self):
        self.assertEqual(bash("git branch -D feat/ui")[0], BLOCK)

    def test_rm_rf_src(self):
        self.assertEqual(bash("rm -rf src/")[0], BLOCK)

    def test_rm_rf_user_data(self):
        self.assertEqual(bash("rm -rf user/savedata")[0], BLOCK)

    def test_rm_rf_home(self):
        self.assertEqual(bash("rm -rf $HOME/gow3")[0], BLOCK)

    def test_format_drive(self):
        self.assertEqual(bash("format C:")[0], BLOCK)

    def test_shutdown(self):
        self.assertEqual(bash("shutdown /s /t 0")[0], BLOCK)

    def test_windows_recursive_delete(self):
        self.assertEqual(bash("rd /s /q build")[0], BLOCK)
        self.assertEqual(bash("del /s /q *.tmp")[0], BLOCK)

    def test_fork_bomb(self):
        self.assertEqual(bash(":(){ :|:& };:")[0], BLOCK)

    def test_taskkill_game(self):
        self.assertEqual(bash("taskkill /IM gow3-probe.exe /F")[0], BLOCK)
        self.assertEqual(bash("Stop-Process -Name 'God of War III'")[0], BLOCK)


class BlocksOutOfScopeAndCritical(unittest.TestCase):
    def test_edit_runtime(self):
        self.assertEqual(edit(str(REPO / "src" / "runtime_services.c"))[0], BLOCK)

    def test_edit_shadps4(self):
        self.assertEqual(edit(str(REPO / "gpu" / "shadps4" / "video_core" / "vk_instance.cpp"))[0], BLOCK)

    def test_edit_patch_xml(self):
        self.assertEqual(edit(str(REPO / "patches" / "God_of_War_III_Remastered.xml"))[0], BLOCK)

    def test_edit_patch_whitelist(self):
        self.assertEqual(edit(str(REPO / "scripts" / "patches.py"))[0], BLOCK)

    def test_edit_run_py(self):
        self.assertEqual(edit(str(REPO / "run.py"))[0], BLOCK)

    def test_edit_git_internals(self):
        self.assertEqual(edit(str(REPO / ".git" / "config"))[0], BLOCK)

    def test_write_proprietary(self):
        self.assertEqual(edit(r"C:\games\CUSA01623\eboot.bin")[0], BLOCK)
        self.assertEqual(edit(str(REPO / "dump" / "sce_sys" / "param.sfo"))[0], BLOCK)
        self.assertEqual(edit(str(REPO / "d" / "game.pkg"))[0], BLOCK)
        self.assertEqual(edit(str(REPO / "user" / "savedata" / "x"))[0], BLOCK)

    def test_bash_git_add_proprietary(self):
        self.assertEqual(bash("git add -f eboot.bin")[0], BLOCK)
        self.assertEqual(bash("git add sce_module/")[0], BLOCK)

    def test_force_patches_env(self):
        self.assertEqual(bash("GOW3_FORCE_PATCHES=1 python run.py")[0], BLOCK)
        self.assertEqual(bash("export GOW3_FORCE_PATCHES=1")[0], BLOCK)


class AllowsSafeOperations(unittest.TestCase):
    def test_read_only_git(self):
        for command in ("git status", "git log --oneline -5", "git diff main",
                        "git checkout -b feat/save-screen", "git switch -c fix/x"):
            self.assertEqual(bash(command)[0], PASS, command)

    def test_common_build_and_test(self):
        for command in ("ls -la", "python -m unittest discover -s tests", "bash build.sh",
                        "ninja -C out/gpu mp3-test", "cmake -S gpu -B out/gpu -G Ninja",
                        "git add docs/DEV-BASELINE.md", "git commit -m 'docs: x'",
                        "git push origin chore/zcode-harness"):
            self.assertEqual(bash(command)[0], PASS, command)

    def test_writes_in_scope(self):
        for rel in ("docs/DEV-BASELINE.md", "launcher/gow3_launcher_win.py",
                    "zcode/gow3-dev-guard/hooks/pre_tool_use.py", "tests/test_probe.py",
                    "gpu/shim/gow3_overlay.cpp", "packaging/windows/package.sh",
                    "zcode/gow3-dev-guard/tests/test_guard.py"):
            self.assertEqual(edit(str(REPO / rel))[0], PASS, rel)

    def test_rm_rf_rebuildable(self):
        self.assertEqual(bash("rm -rf out/gpu")[0], PASS)
        self.assertEqual(bash("rm -rf dist")[0], PASS)

    def test_reads_never_reach_guard(self):
        # Read/Grep/Glob are not in the matcher; the hook passes them anyway if ever routed.
        rc, _, _ = run_hook("pre_tool_use.py", {"tool_name": "Read",
                                                "tool_input": {"file_path": str(REPO / "src" / "probe.c")}})
        self.assertEqual(rc, PASS)


class StopReportValidation(unittest.TestCase):
    def hook(self, text: str | None, session: str, **extra):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "transcript.jsonl"
            lines = []
            if text is not None:
                lines.append(json.dumps({"type": "message", "message": {"role": "user",
                                                                        "content": "go"}}))
                lines.append(json.dumps({"message": {"role": "assistant",
                                                     "content": [{"type": "text", "text": text}]}}))
            path.write_text("\n".join(lines) + "\n", encoding="utf-8")
            payload = {"transcript_path": str(path), "session_id": session, **extra}
            return run_hook("stop_guard.py", payload, {"ZCODE_PLUGIN_DATA": tmp})

    def test_missing_report_blocks(self):
        rc, err, _ = self.hook("trabalho concluído, tudo certo", "s1")
        self.assertEqual(rc, BLOCK)
        self.assertIn("ZCODE FINAL REPORT", err)

    def test_incomplete_report_blocks(self):
        broken = VALID_REPORT.replace("AUDIT GATE\n", "").replace("  Evidence:    tests/test_guard.py\n", "")
        rc, err, _ = self.hook(broken, "s2")
        self.assertEqual(rc, BLOCK)
        self.assertIn("AUDIT GATE", err)

    def test_empty_field_value_blocks(self):
        broken = VALID_REPORT.replace("  Commit:      abc1234", "  Commit:")
        rc, err, _ = self.hook(broken, "s3")
        self.assertEqual(rc, BLOCK)
        self.assertIn("GIT.Commit", err)

    def test_no_text_block_blocks(self):
        rc, _, _ = self.hook("GOW3 — ZCODE REPORT solto sem bloco", "s4")
        self.assertEqual(rc, BLOCK)

    def test_valid_report_passes(self):
        rc, _, _ = self.hook(VALID_REPORT, "s5")
        self.assertEqual(rc, PASS)

    def test_ascii_header_also_accepted(self):
        rc, _, _ = self.hook(VALID_REPORT.replace("GOW3 — ZCODE", "GOW3 - ZCODE"), "s6")
        self.assertEqual(rc, PASS)


class StopLoopSafety(unittest.TestCase):
    def hook(self, text: str, session: str, plugin_data: Path, **extra):
        transcript = plugin_data / "t.jsonl"
        transcript.write_text(json.dumps({"message": {"role": "assistant",
                                                      "content": [{"type": "text", "text": text}]}}) + "\n",
                              encoding="utf-8")
        return run_hook("stop_guard.py",
                        {"transcript_path": str(transcript), "session_id": session, **extra},
                        {"ZCODE_PLUGIN_DATA": str(plugin_data)})

    def test_stop_hook_active_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            rc, err, _ = self.hook("sem relatório", "s7", Path(tmp), stop_hook_active=True)
            self.assertEqual(rc, PASS)
            self.assertIn("loop", err.lower())

    def test_self_limit_after_two_blocks(self):
        with tempfile.TemporaryDirectory() as tmp:
            for expected in (BLOCK, BLOCK):
                rc, _, _ = self.hook("sem relatório", "s8", Path(tmp))
                self.assertEqual(rc, expected)
            rc, err, _ = self.hook("sem relatório", "s8", Path(tmp))
            self.assertEqual(rc, PASS, "third stop must pass so the session can end")
            self.assertIn("missing", err.lower())

    def test_valid_report_resets_counter(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(self.hook("sem relatório", "s9", Path(tmp))[0], BLOCK)
            self.assertEqual(self.hook(VALID_REPORT, "s9", Path(tmp))[0], PASS)
            self.assertEqual(self.hook("sem relatório", "s9", Path(tmp))[0], BLOCK)


class Robustness(unittest.TestCase):
    """Malformed input must never crash a hook. For the write-capable PreToolUse it now
    BLOCKS with a specific reason (audit: fail-closed); SessionStart/Stop stay fail-open —
    they cannot write and must not trap the session."""

    def test_invalid_json_write_hook_blocks(self):
        rc, err, _ = run_hook("pre_tool_use.py", None, raw_stdin=b"{not json\x00\xff")
        self.assertEqual(rc, BLOCK)
        self.assertIn("fail-closed", err.lower())

    def test_invalid_json_context_hooks_pass(self):
        for script in ("stop_guard.py", "session_context.py"):
            rc, _, _ = run_hook(script, None, raw_stdin=b"{not json\x00\xff")
            self.assertEqual(rc, PASS, script)

    def test_missing_fields(self):
        # PreToolUse: cannot tell what would be written -> block. Others: pass.
        self.assertEqual(run_hook("pre_tool_use.py", {})[0], BLOCK)
        for script in ("stop_guard.py", "session_context.py"):
            self.assertEqual(run_hook(script, {})[0], PASS, script)

    def test_missing_transcript_fails_open(self):
        rc, _, _ = run_hook("stop_guard.py", {"session_id": "sx"})  # no transcript_path
        self.assertEqual(rc, PASS)

    def test_transcript_without_assistant_message(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "t.jsonl"
            path.write_text(json.dumps({"message": {"role": "user", "content": "hi"}}) + "\n"
                            + "{broken line\n", encoding="utf-8")
            rc, _, _ = run_hook("stop_guard.py", {"transcript_path": str(path),
                                                  "session_id": "sy"})
            self.assertEqual(rc, PASS)

    def test_session_start_emits_context(self):
        rc, _, out = run_hook("session_context.py", {"session_id": "sz",
                                                     "source": "startup"})
        self.assertEqual(rc, PASS)
        data = json.loads(out)
        self.assertIn("additionalContext", data)
        for needle in ("Baseline", "AGENTS.md", "FORA do escopo", "ZCODE REPORT"):
            self.assertIn(needle, data["additionalContext"])

    def test_session_start_modifies_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            before = sorted(p.name for p in Path(tmp).iterdir())
            run_hook("session_context.py", {"session_id": "s10", "cwd": tmp},
                     {"ZCODE_PLUGIN_DATA": tmp})
            after = sorted(p.name for p in Path(tmp).iterdir())
            self.assertEqual(before, after, "SessionStart must not create files")


class AuditRegressions(unittest.TestCase):
    """Every case below reproduces a protection gap found by the independent audit of 7e85be1.
    They must BLOCK (or specifically PASS where noted) after the hardening — and they are
    written first, against the vulnerable implementation, as the red step of the fix."""

    # --- 1. destructive deletes must resolve and normalize paths -------------------------
    def test_rmrf_current_and_parent_dir_blocked(self):
        for command in ("rm -rf .", "rm -rf ..", "rm -rf ./", "rm -fr ."):
            self.assertEqual(bash(command)[0], BLOCK, command)

    def test_rmrf_repo_root_absolute_blocked(self):
        self.assertEqual(bash(f"rm -rf {REPO}")[0], BLOCK)
        self.assertEqual(bash(f"rm -rf {REPO}/")[0], BLOCK)

    def test_rmrf_protected_absolute_blocked(self):
        self.assertEqual(bash(f"rm -rf {REPO}/src")[0], BLOCK)
        self.assertEqual(bash(f"rm -rf {REPO}\\gpu\\shadps4")[0], BLOCK)
        self.assertEqual(bash(f"rm -rf {REPO}/.git")[0], BLOCK)

    def test_rmrf_proprietary_absolute_blocked(self):
        self.assertEqual(bash("rm -rf D:/games/CUSA01623/savedata")[0], BLOCK)
        self.assertEqual(bash("rm -rf 'D:\\games\\dump\\eboot.bin'")[0], BLOCK)

    def test_rmrf_ancestor_of_repo_blocked(self):
        self.assertEqual(bash("rm -rf C:/gow3")[0], BLOCK)

    def test_rmrf_inside_repo_needs_authorized_target(self):
        self.assertEqual(bash("rm -rf zcode")[0], BLOCK)
        self.assertEqual(bash("rm -rf tests")[0], BLOCK)
        # explicitly authorized rebuildable/temporary locations still pass
        self.assertEqual(bash("rm -rf zcode/gow3-dev-guard/tests/__pycache__")[0], PASS)
        self.assertEqual(bash("rm -rf out/gpu")[0], PASS)
        self.assertEqual(bash("rm -rf dist")[0], PASS)

    def test_rmrf_external_temp_allowed(self):
        self.assertEqual(bash("rm -rf C:/Users/x/AppData/Local/Temp/pytest-thing")[0], PASS)

    # --- 2. complete write-tool coverage ------------------------------------------------
    def test_write_without_identifiable_path_blocks(self):
        rc, _, _ = run_hook("pre_tool_use.py", {"tool_name": "Edit", "tool_input": {}})
        self.assertEqual(rc, BLOCK)
        rc, _, _ = run_hook("pre_tool_use.py", {"tool_name": "Write",
                                                "tool_input": {"content": "x"}})
        self.assertEqual(rc, BLOCK)

    def test_applypatch_patch_text_analyzed(self):
        payload = {"tool_name": "ApplyPatch", "tool_input": {
            "patch": "*** Begin Patch\n*** Update File: src/runtime_services.c\n@@\n-x\n+y\n"
                     "*** End Patch"}}
        rc, err, _ = run_hook("pre_tool_use.py", payload)
        self.assertEqual(rc, BLOCK)
        self.assertIn("src/runtime_services.c", err)

    def test_applypatch_patch_list_analyzed(self):
        payload = {"tool_name": "ApplyPatch", "tool_input": {
            "patches": [{"path": "docs/a.md"}, {"file_path": "scripts/patches.py"}]}}
        rc, err, _ = run_hook("pre_tool_use.py", payload)
        self.assertEqual(rc, BLOCK)
        self.assertIn("scripts/patches.py", err)

    def test_multiedit_analyzed(self):
        payload = {"tool_name": "MultiEdit", "tool_input": {
            "file_path": str(REPO / "src" / "probe.c"), "edits": [{"old": "a", "new": "b"}]}}
        self.assertEqual(run_hook("pre_tool_use.py", payload)[0], BLOCK)

    def test_multiedit_unresolvable_blocks(self):
        payload = {"tool_name": "MultiEdit", "tool_input": {"edits": [{"old": "a", "new": "b"}]}}
        self.assertEqual(run_hook("pre_tool_use.py", payload)[0], BLOCK)

    # --- 3. bash write policy beyond the blacklist --------------------------------------
    def test_redirection_to_protected_blocked(self):
        for command in ("echo x > src/probe.c", "echo x >> gpu/shadps4/vk_instance.cpp",
                        "tee patches/God_of_War_III_Remastered.xml",
                        "sed -i s/a/b/ scripts/patches.py",
                        "cp dist/a.bin src/a.bin", "mv out/x.bin gpu/shim/gow3gpu.cpp",
                        "dd of=src/probe.c if=x.bin", "truncate -s 0 run.py"):
            self.assertEqual(bash(command)[0], BLOCK, command)

    def test_redirection_to_safe_targets_allowed(self):
        for command in ("python -m unittest discover -s tests > out/test.log",
                        "echo hi > C:/gow3/build.log", "cp docs/a.md docs/b.md",
                        "tee out/x.log", "sed -i s/a/b/ launcher/note.md"):
            self.assertEqual(bash(command)[0], PASS, command)

    def test_powershell_write_to_protected_blocked(self):
        rc, _, _ = bash("powershell -NoProfile -Command \"Set-Content -Path 'gpu/shadps4/x.cpp'"
                        " -Value hi\"")
        self.assertEqual(rc, BLOCK)
        rc, _, _ = bash("pwsh -Command \"Out-File -FilePath patches/list.xml -InputObject x\"")
        self.assertEqual(rc, BLOCK)

    def test_powershell_write_without_resolvable_path_blocks(self):
        rc, _, _ = bash("powershell -Command Set-Content $env:TMP\\x -Value hi")
        self.assertEqual(rc, BLOCK)  # write cmdlet with an unverifiable target: fail closed

    def test_powershell_read_only_allowed(self):
        rc, _, _ = bash("powershell -NoProfile -Command \"Compress-Archive -Path out -DestinationPath dist.zip\"")
        self.assertEqual(rc, PASS)

    def test_git_add_protected_path_blocked(self):
        self.assertEqual(bash("git add src/probe.c")[0], BLOCK)
        self.assertEqual(bash(f"git add {REPO}/scripts/patches.py")[0], BLOCK)
        repo = temp_repo()
        try:
            (repo / "launcher").mkdir()
            (repo / "launcher" / "x.py").write_text("x", encoding="utf-8")
            self.assertEqual(bash("git add launcher/x.py", project=str(repo))[0], PASS)
        finally:
            shutil.rmtree(repo, ignore_errors=True)

    def test_git_commit_staged_protected_blocked(self):
        repo = temp_repo()
        try:
            (repo / "src").mkdir()
            (repo / "src" / "runtime.c").write_text("x", encoding="utf-8")
            subprocess.run(["git", "-C", str(repo), "add", "src/runtime.c"],
                           capture_output=True, timeout=30)
            self.assertEqual(bash("git commit -m x", project=str(repo))[0], BLOCK)
            self.assertEqual(bash(f"git -C {repo} commit -m x", project=str(repo))[0], BLOCK)
        finally:
            shutil.rmtree(repo, ignore_errors=True)

    def test_git_commit_staged_safe_allowed(self):
        repo = temp_repo()
        try:
            (repo / "launcher").mkdir()
            (repo / "launcher" / "x.py").write_text("x", encoding="utf-8")
            subprocess.run(["git", "-C", str(repo), "add", "launcher/x.py"],
                           capture_output=True, timeout=30)
            self.assertEqual(bash("git commit -m x", project=str(repo))[0], PASS)
        finally:
            shutil.rmtree(repo, ignore_errors=True)

    def test_git_commit_branch_unknown_blocks(self):
        with tempfile.TemporaryDirectory() as tmp:  # not a git repository at all
            self.assertEqual(bash("git commit -m x", project=tmp)[0], BLOCK)

    def test_git_worktree_discard_blocked(self):
        for command in ("git checkout -- src/probe.c", "git restore src/",
                        "git stash push", "git stash pop", "git rm src/probe.c"):
            self.assertEqual(bash(command)[0], BLOCK, command)

    # --- 4. fail-closed for write operations --------------------------------------------
    def test_pretooluse_invalid_json_blocks(self):
        rc, err, _ = run_hook("pre_tool_use.py", None, raw_stdin=b"{not json\x00\xff")
        self.assertEqual(rc, BLOCK)
        self.assertIn("fail-closed", err.lower())

    def test_pretooluse_missing_tool_name_blocks(self):
        self.assertEqual(run_hook("pre_tool_use.py", {})[0], BLOCK)

    def test_pretooluse_tool_input_not_object_blocks(self):
        self.assertEqual(run_hook("pre_tool_use.py",
                                  {"tool_name": "Bash", "tool_input": "ls"})[0], BLOCK)

    def test_pretooluse_bash_without_command_blocks(self):
        self.assertEqual(run_hook("pre_tool_use.py",
                                  {"tool_name": "Bash", "tool_input": {}})[0], BLOCK)


class AuditRegressionsStop(unittest.TestCase):
    """Stop-hook gaps from the audit."""

    def hook(self, last_message=None, transcript_text=None, session="aud"):
        with tempfile.TemporaryDirectory() as tmp:
            payload = {"session_id": session}
            if last_message is not None:
                payload["last_assistant_message"] = last_message
            if transcript_text is not None:
                path = Path(tmp) / "t.jsonl"
                path.write_text(json.dumps({"message": {"role": "assistant",
                                                        "content": [{"type": "text",
                                                                     "text": transcript_text}]}}) + "\n",
                                encoding="utf-8")
                payload["transcript_path"] = str(path)
            return run_hook("stop_guard.py", payload, {"ZCODE_PLUGIN_DATA": tmp})

    def test_risks_section_required(self):
        broken = VALID_REPORT.replace("RISKS\n  NONE\n", "")
        rc, err, _ = self.hook(last_message=broken)
        self.assertEqual(rc, BLOCK)
        self.assertIn("RISKS", err)

    def test_field_must_be_inside_its_own_section(self):
        # BASELINE's own Status line removed; TASK still has one — a global regex would pass.
        broken = VALID_REPORT.replace("BASELINE\n  Status:      PASS\n",
                                      "BASELINE\n")
        rc, err, _ = self.hook(last_message=broken)
        self.assertEqual(rc, BLOCK)
        self.assertIn("BASELINE.Status", err)

    def test_multiple_text_blocks_rejected(self):
        doubled = VALID_REPORT + "\n```text\nextra block\n```\n"
        rc, err, _ = self.hook(last_message=doubled)
        self.assertEqual(rc, BLOCK)
        self.assertIn("text block", err)

    def test_last_assistant_message_takes_priority(self):
        # payload message has no report, transcript has a valid one: must BLOCK.
        rc, _, _ = self.hook(last_message="pronto", transcript_text=VALID_REPORT)
        self.assertEqual(rc, BLOCK)
        # payload message valid, no transcript at all: must PASS.
        rc, _, _ = self.hook(last_message=VALID_REPORT)
        self.assertEqual(rc, PASS)

    def test_valid_report_still_passes(self):
        rc, _, _ = self.hook(transcript_text=VALID_REPORT)
        self.assertEqual(rc, PASS)


class IntegrityPreToolUse(unittest.TestCase):
    """The six gaps demonstrated by the re-audit of 20250d1. Written first (red step)."""

    def test_applypatch_move_to_protected(self):
        payload = {"tool_name": "ApplyPatch", "tool_input": {
            "patch": "*** Begin Patch\n*** Update File: docs/a.md\n@@\n-x\n+y\n"
                     "*** Move to: src/runtime_services.c\n*** End Patch"}}
        rc, err, _ = run_hook("pre_tool_use.py", payload)
        self.assertEqual(rc, BLOCK)
        self.assertIn("src/runtime_services.c", err)

    def test_bash_cd_before_write(self):
        self.assertEqual(bash("cd src && echo x > runtime_services.c")[0], BLOCK)
        self.assertEqual(bash("cd gpu && rm -rf shadps4")[0], BLOCK)
        self.assertEqual(bash("cd docs && echo x > notes.md")[0], PASS)
        self.assertEqual(bash("cd out && echo done > build.log")[0], PASS)

    def test_bash_write_while_on_main(self):
        repo = temp_repo(default_branch="main")
        try:
            (repo / "launcher").mkdir()
            (repo / "launcher" / "x.py").write_text("x", encoding="utf-8")
            subprocess.run(["git", "-C", str(repo), "add", "launcher"],
                           capture_output=True, timeout=30)
            subprocess.run(["git", "-C", str(repo), "commit", "-m", "base"],
                           capture_output=True, timeout=30)
            rc, _, _ = bash("echo generated > launcher/new.py", project=str(repo))
            self.assertEqual(rc, BLOCK)
            subprocess.run(["git", "-C", str(repo), "checkout", "-b", "feat/ui"],
                           capture_output=True, timeout=30)
            rc, _, _ = bash("echo generated > launcher/new.py", project=str(repo))
            self.assertEqual(rc, PASS)
        finally:
            shutil.rmtree(repo, ignore_errors=True)

    def test_git_commit_all_with_protected_worktree_changes(self):
        repo = temp_repo()
        try:
            (repo / "src").mkdir()
            (repo / "src" / "engine.c").write_text("int x;\n", encoding="utf-8")
            (repo / "launcher").mkdir()
            (repo / "launcher" / "x.py").write_text("x = 1\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(repo), "add", "."], capture_output=True, timeout=30)
            subprocess.run(["git", "-C", str(repo), "commit", "-m", "base"],
                           capture_output=True, timeout=30)
            # protected tracked file modified but NOT staged
            (repo / "src" / "engine.c").write_text("int y;\n", encoding="utf-8")
            for command in ("git commit -am x", "git commit -a -m x",
                            "git commit --all -m x"):
                self.assertEqual(bash(command, project=str(repo))[0], BLOCK, command)
            # allowed tracked file modified: -a commit passes
            (repo / "src" / "engine.c").write_text("int x;\n", encoding="utf-8")
            (repo / "launcher" / "x.py").write_text("x = 2\n", encoding="utf-8")
            self.assertEqual(bash("git commit -am x", project=str(repo))[0], PASS)
        finally:
            shutil.rmtree(repo, ignore_errors=True)

    def test_git_dash_c_push_main_and_force(self):
        self.assertEqual(bash("git -C /c/somewhere push origin main")[0], BLOCK)
        self.assertEqual(bash("git -C /c/somewhere push --force origin feat/x")[0], BLOCK)
        self.assertEqual(bash("git -C /c/somewhere push origin feat/x")[0], PASS)

    def test_unresolvable_write_destinations_block(self):
        self.assertEqual(bash("echo x > $OUT/probe.c")[0], BLOCK)
        self.assertEqual(bash("cp a.out $(pwd)/src/b.h")[0], BLOCK)
        self.assertEqual(bash("echo hi > `mktemp -d`/x.log")[0], BLOCK)
        # a real, resolvable environment variable is still allowed
        self.assertEqual(bash("echo hi > $TEMP/gow3-guard-check.log")[0], PASS)


if __name__ == "__main__":
    unittest.main(verbosity=2)
