#!/usr/bin/env python3
"""Bridge tests — read/write of the port's real configuration files using TEMPORARY
fixtures only (a throwaway APPDATA and a throwaway port data dir via GOW3_DATA_DIR +
GOW3_CONFIG). The maintainer's real settings.json / gow3.ini are never touched."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

BRIDGE = Path(__file__).resolve().parents[1] / "bridge" / "launcher_bridge.py"
LAUNCHER_DIR = BRIDGE.parents[2]  # launcher/ (imports gow3_launcher_win from here)


class BridgeFixture(unittest.TestCase):
    def setUp(self):
        self.home = Path(tempfile.mkdtemp(prefix="gow3-bridge-test-"))
        self.appdata = self.home / "appdata"
        self.data = self.home / "data"
        self.appdata.mkdir(), self.data.mkdir()
        (self.data / "gow3.ini").write_text(
            "# fixture: comments must survive\nrender_resolution=native\n"
            "engine_fps=240\ndisplay_mode=windowed\n# a key the launcher does not manage\n"
            "custom_key=keepme\n", encoding="utf-8")
        self.env = {**os.environ,
                    "APPDATA": str(self.appdata),
                    "GOW3_DATA_DIR": str(self.data),
                    "GOW3_CONFIG": str(self.data / "gow3.ini"),
                    "GOW3_GAME_DIR": ""}

    def bridge(self, request):
        done = subprocess.run([sys.executable, str(BRIDGE)], input=json.dumps(request),
                              capture_output=True, text=True, env=self.env, cwd=str(LAUNCHER_DIR),
                              timeout=60)
        self.assertIn(done.returncode, (0, 2), done.stderr[-400:])  # 2 = recusa documentada
        return json.loads(done.stdout)


class StateTests(BridgeFixture):
    def test_state_reads_defaults_and_fixture_ini(self):
        state = self.bridge({"cmd": "state"})
        self.assertEqual(state["ini"]["render_resolution"], "native")
        self.assertEqual(state["ini"]["engine_fps"], "240")
        self.assertFalse(state["game"]["found"])  # no game dump in the fixture
        self.assertEqual(state["game"]["summary"], "Pasta do jogo não configurada")
        self.assertIn("display_mode", state["choices"])
        labels = [c["value"] for c in state["choices"]["render_resolution"]]
        self.assertEqual(labels[0], "native")


class IniWriteTests(BridgeFixture):
    def test_set_ini_writes_only_known_keys_and_preserves_comments(self):
        response = self.bridge({"cmd": "set_ini", "values": {
            "display_mode": "fullscreen", "render_resolution": "1440p", "vsync": False}})
        self.assertTrue(response["ok"])
        self.assertEqual(response["ini"]["display_mode"], "fullscreen")
        self.assertEqual(response["ini"]["render_resolution"], "1440p")
        self.assertEqual(response["ini"]["vsync"], "0")
        text = (self.data / "gow3.ini").read_text(encoding="utf-8")
        self.assertIn("# fixture: comments must survive", text)   # comments preserved
        self.assertIn("custom_key=keepme", text)                  # foreign key preserved
        self.assertIn("display_mode=fullscreen", text)

    def test_set_ini_rejects_keys_outside_the_contract(self):
        response = self.bridge({"cmd": "set_ini", "values": {"hack": "1"}})
        self.assertIn("error", response)
        self.assertIn("not part of the port contract", response["error"])


class AppSettingsTests(BridgeFixture):
    def test_set_app_roundtrip_and_music_keys(self):
        response = self.bridge({"cmd": "set_app", "values": {
            "ambient_volume": 0.4, "ambient_muted": True, "ambient_file": "X:/m.mp3"}})
        self.assertTrue(response["ok"])
        saved = json.loads((self.appdata / "gow3-launcher" / "settings.json").read_text(encoding="utf-8"))
        self.assertEqual(saved["ambient_volume"], 0.4)
        self.assertTrue(saved["ambient_muted"])
        state = self.bridge({"cmd": "state"})
        self.assertEqual(state["music"]["volume"], 0.4)
        self.assertTrue(state["music"]["muted"])

    def test_set_app_rejects_unknown_keys(self):
        response = self.bridge({"cmd": "set_app", "values": {"nope": 1}})
        self.assertIn("error", response)

    def test_real_user_settings_untouched(self):
        real = Path(os.environ.get("APPDATA", "")) / "gow3-launcher" / "settings.json"
        before = real.read_bytes() if real.is_file() else None
        self.bridge({"cmd": "set_app", "values": {"ambient_volume": 0.9}})
        after = real.read_bytes() if real.is_file() else None
        self.assertEqual(before, after)


class PlayTests(BridgeFixture):
    def test_play_refuses_without_game(self):
        response = self.bridge({"cmd": "play"})
        self.assertIn("error", response)
        self.assertIn("Pasta do jogo", response["error"])

    def test_play_status_reports_not_running(self):
        status = self.bridge({"cmd": "play_status"})
        self.assertFalse(status["running"])
        self.assertIn("outcome", status)


class ProcessLivenessTests(unittest.TestCase):
    """pid_alive must never harm the checked process: validated with a THROWAWAY
    subprocess (never the game)."""

    def test_pid_alive_is_read_only_and_accurate(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("launcher_bridge", BRIDGE)
        bridge = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(bridge)  # noqa: SLF001 (module load for the probe only)
        child = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(30)"],
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        try:
            self.assertTrue(bridge.pid_alive(child.pid))       # alive before…
            self.assertTrue(bridge.pid_alive(child.pid))       # …and still alive after a
            self.assertIsNone(child.poll())                    # check (never terminated)
        finally:
            child.terminate()
            child.wait(timeout=10)
        self.assertFalse(bridge.pid_alive(child.pid))          # gone after termination
        self.assertFalse(bridge.pid_alive(0))
        self.assertFalse(bridge.pid_alive(-1))


if __name__ == "__main__":
    unittest.main()
