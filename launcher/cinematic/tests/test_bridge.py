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
        for mod in ("ModA", "ModB"):  # layout real: cada mod em pasta com dvdroot_ps4
            (self.data / "mods" / mod / "dvdroot_ps4").mkdir(parents=True, exist_ok=True)
        (self.data / "gow3.ini").write_text(
            "# fixture: comments must survive\nrender_resolution=native\n"
            "engine_fps=240\ndisplay_mode=windowed\n# a key the launcher does not manage\n"
            "custom_key=keepme\n", encoding="utf-8")
        self.env = {**os.environ,
                    "APPDATA": str(self.appdata),
                    "GOW3_DATA_DIR": str(self.data),
                    "GOW3_CONFIG": str(self.data / "gow3.ini"),
                    "GOW3_GAME_DIR": "",
                    "PYTHONIOENCODING": "utf-8"}

    def bridge(self, request, raw_input=None):
        payload = raw_input if raw_input is not None else json.dumps(request, ensure_ascii=False)
        done = subprocess.run([sys.executable, str(BRIDGE)], input=payload.encode("utf-8"),
                              capture_output=True, env=self.env, cwd=str(LAUNCHER_DIR),
                              timeout=90)
        self.assertIn(done.returncode, (0, 2), done.stderr.decode("utf-8", "replace")[-400:])  # 2 = recusa documentada
        return done, json.loads(done.stdout.decode("utf-8"))


class StateTests(BridgeFixture):
    def test_state_reads_defaults_and_fixture_ini(self):
        _, state = self.bridge({"cmd": "state"})
        self.assertEqual(state["ini"]["render_resolution"], "native")
        self.assertEqual(state["ini"]["engine_fps"], "240")
        self.assertEqual(state["game"]["summary"], "Pasta do jogo não configurada")
        for key in ("display_mode", "upscaler", "preset", "output_res", "live_resolution",
                    "frames_queued", "stream_memory", "draw_pipe", "readbacks", "language",
                    "ui_language", "gpu_id", "no_msaa", "engine_fps", "fps_limit",
                    "render_resolution", "video_backend"):
            self.assertIn(key, state["choices"], f"choices faltando: {key}")
        self.assertIn("controls", state)
        self.assertIn("rows", state["controls"])
        self.assertGreater(len(state["controls"]["rows"]), 10)


class Utf8RoundTripTests(BridgeFixture):
    """O rodapé real e caracteres pt-BR precisam sobreviver Python→JSON→Rust sem U+FFFD."""

    def test_stdout_is_utf8_bytes(self):
        request = json.dumps({"cmd": "set_app", "values": {"ambient_file": "cafe com cafeína é í →.mp3"}},
                             ensure_ascii=False)
        done, response = self.bridge(None, raw_input=request)
        self.assertTrue(response["ok"])
        saved = json.loads((self.appdata / "gow3-launcher" / "settings.json").read_text(encoding="utf-8"))
        self.assertEqual(saved["ambient_file"], "cafe com cafeína é í →.mp3")
        done, state = self.bridge({"cmd": "state"})
        self.assertIn("Pasta do jogo não configurada".encode("utf-8"), done.stdout)
        self.assertNotIn(bytes([0xEF, 0xBF, 0xBD]), done.stdout)  # U+FFFD proibido

    def test_summary_has_no_replacement_char(self):
        done, state = self.bridge({"cmd": "state"})
        text = done.stdout.decode("utf-8")
        self.assertNotIn(chr(0xFFFD), text)
        self.assertIn("não", state["game"]["summary"])


class IniWriteTests(BridgeFixture):
    def test_set_ini_writes_only_known_keys_and_preserves_comments(self):
        _, response = self.bridge({"cmd": "set_ini", "values": {
            "display_mode": "fullscreen", "render_resolution": "1440p", "vsync": False}})
        self.assertTrue(response["ok"])
        self.assertEqual(response["ini"]["display_mode"], "fullscreen")
        self.assertEqual(response["ini"]["render_resolution"], "1440p")
        self.assertEqual(response["ini"]["vsync"], "0")
        text = (self.data / "gow3.ini").read_text(encoding="utf-8")
        self.assertIn("# fixture: comments must survive", text)
        self.assertIn("custom_key=keepme", text)
        self.assertIn("display_mode=fullscreen", text)

    def test_set_ini_rejects_keys_outside_the_contract(self):
        _, response = self.bridge({"cmd": "set_ini", "values": {"hack": "1"}})
        self.assertIn("error", response)


class AppSettingsTests(BridgeFixture):
    def test_set_app_roundtrip_and_music_keys(self):
        _, response = self.bridge({"cmd": "set_app", "values": {
            "ambient_volume": 0.4, "ambient_muted": True}})
        self.assertTrue(response["ok"])
        saved = json.loads((self.appdata / "gow3-launcher" / "settings.json").read_text(encoding="utf-8"))
        self.assertEqual(saved["ambient_volume"], 0.4)
        _, state = self.bridge({"cmd": "state"})
        self.assertEqual(state["music"]["volume"], 0.4)

    def test_set_app_rejects_unknown_keys(self):
        _, response = self.bridge({"cmd": "set_app", "values": {"nope": 1}})
        self.assertIn("error", response)

    def test_real_user_settings_untouched(self):
        real = Path(os.environ.get("APPDATA", "")) / "gow3-launcher" / "settings.json"
        before = real.read_bytes() if real.is_file() else None
        self.bridge({"cmd": "set_app", "values": {"ambient_volume": 0.9}})
        after = real.read_bytes() if real.is_file() else None
        self.assertEqual(before, after)


class ModsPatchesPresetsTests(BridgeFixture):
    def test_mods_set_and_preset_roundtrip(self):
        _, response = self.bridge({"cmd": "mods_set", "order": ["ModA", "ModB"],
                                   "disabled": ["ModB"]})
        self.assertTrue(response["ok"])
        saved = json.loads((self.data / "mods.json").read_text(encoding="utf-8"))
        self.assertEqual(saved, {"order": ["ModA", "ModB"], "disabled": ["ModB"]})
        _, state = self.bridge({"cmd": "state"})
        self.assertEqual(state["mods"]["order"], ["ModA", "ModB"])
        self.assertEqual(state["mods"]["disabled"], ["ModB"])
        _, saved_preset = self.bridge({"cmd": "preset", "name": "Teste Á", "op": "save"})
        self.assertTrue(saved_preset["ok"])
        presets = json.loads((self.data / "mods_presets.json").read_text(encoding="utf-8"))
        self.assertIn("Teste Á", presets)

    def test_external_patches_selection(self):
        _, response = self.bridge({"cmd": "set_external_patches",
                                   "enabled": ["PatchUm"], "disabled": ["PatchDois"]})
        self.assertTrue(response["ok"])
        chosen = json.loads((self.data / "patches.json").read_text(encoding="utf-8"))
        self.assertEqual(chosen["enabled"], ["PatchUm"])
        self.assertEqual(chosen["disabled"], ["PatchDois"])


class ControlsTests(BridgeFixture):
    def test_controls_set_persists_maps_and_style(self):
        _, response = self.bridge({"cmd": "controls_set",
                                   "key": {"cross": "Return"}, "pad": {"cross": "x"},
                                   "pad_style": "xbox"})
        self.assertTrue(response["ok"])
        _, state = self.bridge({"cmd": "state"})
        self.assertEqual(state["controls"]["style"], "xbox")
        row = next(r for r in state["controls"]["rows"] if r["button"] == "cross")
        self.assertEqual(row["key"], "Return")
        self.assertEqual(row["pad"], "x")

    def test_controls_set_rejects_bad_style(self):
        _, response = self.bridge({"cmd": "controls_set", "key": {}, "pad": {},
                                   "pad_style": "switch"})
        self.assertIn("error", response)


class PlayTests(BridgeFixture):
    def test_play_refuses_without_game(self):
        _, response = self.bridge({"cmd": "play"})
        self.assertIn("error", response)
        self.assertIn("Pasta do jogo", response["error"])

    def test_play_status_reports_not_running(self):
        _, status = self.bridge({"cmd": "play_status"})
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
            self.assertTrue(bridge.pid_alive(child.pid))
            self.assertTrue(bridge.pid_alive(child.pid))
            self.assertIsNone(child.poll())
        finally:
            child.terminate()
            child.wait(timeout=10)
        self.assertFalse(bridge.pid_alive(child.pid))
        self.assertFalse(bridge.pid_alive(0))
        self.assertFalse(bridge.pid_alive(-1))


if __name__ == "__main__":
    unittest.main()
