"""Testes de INTEGRAÇÃO do fluxo JOGAR (M1.4) — processo substituto descartável.

Exercita a cadeia ponte→monitor→processo com binários Python descartáveis (nunca o
jogo), capturando CÓDIGOS DE SAÍDA REAIS, e as validações de pré-requisito que o
Tkinter faz (arquivos ausentes, atualização incompleta, Sc0, probe). Tudo em
diretórios temporários; nenhuma configuração real é tocada."""
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

BRIDGE = Path(__file__).resolve().parents[1] / "bridge" / "launcher_bridge.py"
LAUNCHER_DIR = BRIDGE.parents[2]


def load_bridge(home: Path):
    import importlib.util
    spec = importlib.util.spec_from_file_location("launcher_bridge_test", BRIDGE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # noqa: SLF001
    module.RUN_LOG = home / "run.log"
    module.RUN_PID = home / "run.pid"
    return module


class PlayChainFixture(unittest.TestCase):
    def setUp(self):
        self.home = Path(tempfile.mkdtemp(prefix="gow3-play-test-"))
        (self.home / "appdata").mkdir()
        (self.home / "data").mkdir()
        (self.home / "data" / "gow3.ini").write_text("engine_fps=240\n", encoding="utf-8")
        self.module = load_bridge(self.home)
        self.env = {**os.environ,
                    "APPDATA": str(self.home / "appdata"),
                    "GOW3_DATA_DIR": str(self.home / "data"),
                    "GOW3_CONFIG": str(self.home / "data" / "gow3.ini"),
                    "GOW3_GAME_DIR": "",
                    "PYTHONIOENCODING": "utf-8"}

    def bridge(self, request):
        done = subprocess.run([sys.executable, str(BRIDGE)],
                              input=json.dumps(request).encode("utf-8"),
                              capture_output=True, env=self.env, cwd=str(LAUNCHER_DIR),
                              timeout=60)
        return json.loads(done.stdout.decode("utf-8"))

    def wait_status(self, module, want_running, timeout=15):
        deadline = time.time() + timeout
        status = module.cmd_play_status()
        while time.time() < deadline:
            status = module.cmd_play_status()
            if status["running"] == want_running:
                if want_running or status["exit_code"] is not None:
                    return status  # encerrado: esperar o exit code real do monitor
            time.sleep(0.15)
        return status


class SubstituteProcessTests(PlayChainFixture):
    def _launch(self, code_snippet):
        os.environ["GOW3_CINEMATIC_RUN_CMD"] = json.dumps([sys.executable, "-c", code_snippet])
        os.environ["GOW3_CINEMATIC_SKIP_GAME_CHECK"] = "1"
        response = self.module.cmd_play()
        os.environ.pop("GOW3_CINEMATIC_RUN_CMD")
        os.environ.pop("GOW3_CINEMATIC_SKIP_GAME_CHECK")
        return response

    def test_success_exit_zero(self):
        response = self._launch("print('jogo simulado iniciado')")
        self.assertTrue(response.get("ok"), response)
        status = self.wait_status(self.module, want_running=False, timeout=10)
        self.assertFalse(status["running"])
        self.assertEqual(status["exit_code"], 0)
        self.assertEqual(status["outcome"], "finished")
        self.assertIn("jogo simulado", status["last_line"])

    def test_error_exit_nonzero(self):
        response = self._launch("import sys; print('falha na preparação'); sys.exit(7)")
        self.assertTrue(response.get("ok"), response)
        status = self.wait_status(self.module, want_running=False, timeout=10)
        self.assertEqual(status["exit_code"], 7)
        self.assertEqual(status["outcome"], "error")
        self.assertIn("falha na preparação", status["last_line"])

    def test_long_preparation_then_finish(self):
        response = self._launch("import time; time.sleep(3); print('pronto')")
        self.assertTrue(response.get("ok"), response)
        status = self.wait_status(self.module, want_running=True, timeout=5)
        self.assertTrue(status["running"])
        self.assertIsNone(status["exit_code"])
        status = self.wait_status(self.module, want_running=False, timeout=10)
        self.assertEqual(status["exit_code"], 0)
        self.assertEqual(status["outcome"], "finished")

    def test_spawn_failure_reported(self):
        os.environ["GOW3_CINEMATIC_RUN_CMD"] = json.dumps(["binario_inexistente_xyz"])
        os.environ["GOW3_CINEMATIC_SKIP_GAME_CHECK"] = "1"
        response = self.module.cmd_play()
        os.environ.pop("GOW3_CINEMATIC_RUN_CMD")
        os.environ.pop("GOW3_CINEMATIC_SKIP_GAME_CHECK")
        # o monitor nasce; o processo falha imediatamente e o exit code denuncia
        status = self.wait_status(self.module, want_running=False, timeout=10)
        self.assertIsNotNone(status["exit_code"])
        self.assertNotEqual(status["exit_code"], 0)
        self.assertEqual(status["outcome"], "error")


class PrerequisiteTests(PlayChainFixture):
    """As validações que o Tkinter executa em Launcher.play, com mensagens claras."""

    def test_no_game_folder(self):
        problem = self.module._check_play_prerequisites({"game_dir": "", "update_dir": ""})
        self.assertIn("Pasta do jogo", problem)

    def test_incomplete_dump(self):
        game = self.home / "fakegame"
        game.mkdir()
        (game / "eboot.bin").write_bytes(b"\0" * 16)  # pequeno demais/sem estrutura
        problem = self.module._check_play_prerequisites({"game_dir": str(game), "update_dir": ""})
        self.assertIsNotNone(problem)  # game_info/missingGameFiles recusam o dump fake

    def test_update_same_folder(self):
        game = self.home / "fakegame2"
        game.mkdir()
        problem = self.module._check_play_prerequisites(
            {"game_dir": str(game), "update_dir": str(game)})
        self.assertIn("pastas separadas", problem)

    def test_probe_missing_message(self):
        real = self.module.L.find_tool
        self.module.L.find_tool = lambda name: None
        try:
            info = self.module.L.game_info  # precisa passar do game_info primeiro
            self.module.L.game_info = lambda folder: ("GoW3", "1.02") if folder else None
            self.module.L.missing_game_files = lambda folder, required=None: []
            self.module.L.system_files_beside = lambda folder, reference=None, game=None: None
            problem = self.module._check_play_prerequisites(
                {"game_dir": "X:/jogo", "update_dir": ""})
            self.assertIn("gow3-probe.exe", problem)
            self.assertIn("build.sh", problem)
        finally:
            self.module.L.find_tool = real


if __name__ == "__main__":
    unittest.main()
