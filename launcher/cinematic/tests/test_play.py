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
    """HOTFIX P0: a ponte só devolve a ESPECIFICAÇÃO (prepare_play); o spawn e a
    vigília por evento são do RUST (testados em cargo). Aqui simulamos o lado Rust
    com subprocess descartável para manter as garantías de código de saída REAL,
    arquivo de pid/exit e log — tudo em fixtures temporárias."""

    def _prepare(self, command=None):
        if command is not None:
            os.environ["GOW3_CINEMATIC_RUN_CMD"] = json.dumps(command)
        os.environ["GOW3_CINEMATIC_SKIP_GAME_CHECK"] = "1"
        try:
            spec = self.module.prepare_play()
        finally:
            os.environ.pop("GOW3_CINEMATIC_RUN_CMD", None)
            os.environ.pop("GOW3_CINEMATIC_SKIP_GAME_CHECK", None)
        return spec

    def _launch(self, code_snippet):
        """Simula o Rust: spawn pela spec, grava pid, espera, grava exit code."""
        spec = self._prepare([sys.executable, "-c", code_snippet])
        self.assertTrue(spec.get("ok"), spec)
        log = open(spec["log_file"], "w", encoding="utf-8", errors="replace")
        proc = subprocess.Popen(spec["command"], cwd=spec["cwd"], env=spec["env"],
                                stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT)
        Path(spec["pid_file"]).write_text(str(proc.pid), encoding="utf-8")
        log.close()
        exit_code = proc.wait()
        Path(spec["exit_file"]).write_text(str(exit_code), encoding="utf-8")
        return spec, exit_code

    def test_spec_shape_and_stale_files_cleared(self):
        (self.home / "run.pid").write_text("999999", encoding="utf-8")
        (self.home / "run.exit").write_text("13", encoding="utf-8")
        spec = self._prepare([sys.executable, "-c", "pass"])
        for key in ("command", "cwd", "env", "pid_file", "exit_file", "log_file"):
            self.assertIn(key, spec, f"spec sem {key}")
        self.assertEqual(Path(spec["pid_file"]), self.home / "run.pid")
        self.assertFalse(Path(spec["pid_file"]).exists(), "pid antigo deve ser limpo")
        self.assertFalse(Path(spec["exit_file"]).exists(), "exit antigo deve ser limpo")
        # a ponte NÃO cria mais monitor nem nenhum processo
        self.assertFalse((Path(tempfile.gettempdir()) / "gow3-cinematic-monitor.py").exists()
                         and (Path(tempfile.gettempdir()) / "gow3-cinematic-monitor.py")
                         .stat().st_mtime > time.time() - 60,
                         "nenhum monitor deve ser (re)escrito")

    def test_success_exit_zero(self):
        spec, exit_code = self._launch("print('jogo simulado iniciado')")
        self.assertEqual(exit_code, 0)
        status = self.wait_status(self.module, want_running=False, timeout=10)
        self.assertFalse(status["running"])
        self.assertEqual(status["exit_code"], 0)
        self.assertEqual(status["outcome"], "finished")
        self.assertIn("jogo simulado", status["last_line"])

    def test_error_exit_nonzero(self):
        _spec, exit_code = self._launch("import sys; print('falha na preparação'); sys.exit(7)")
        self.assertEqual(exit_code, 7)
        status = self.wait_status(self.module, want_running=False, timeout=10)
        self.assertEqual(status["exit_code"], 7)
        self.assertEqual(status["outcome"], "error")
        self.assertIn("falha na preparação", status["last_line"])

    def test_long_preparation_then_finish(self):
        spec = self._prepare([sys.executable, "-c", "import time; time.sleep(3); print('pronto')"])
        log = open(spec["log_file"], "w", encoding="utf-8")
        proc = subprocess.Popen(spec["command"], cwd=spec["cwd"], env=spec["env"],
                                stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT)
        Path(spec["pid_file"]).write_text(str(proc.pid), encoding="utf-8")
        log.close()
        status = self.wait_status(self.module, want_running=True, timeout=5)
        self.assertTrue(status["running"])
        self.assertIsNone(status["exit_code"])
        Path(spec["exit_file"]).write_text(str(proc.wait()), encoding="utf-8")
        status = self.wait_status(self.module, want_running=False, timeout=10)
        self.assertEqual(status["exit_code"], 0)
        self.assertEqual(status["outcome"], "finished")

    def test_spawn_failure_surfaces_at_spawn(self):
        """Binário inexistente: quem denuncia é o spawn do RUST (erro direto ao
        frontend), não um monitor com exit 127 — a spec propaga o comando intacto."""
        spec = self._prepare(["binario_inexistente_xyz"])
        self.assertTrue(spec.get("ok"), spec)
        self.assertEqual(spec["command"][0], "binario_inexistente_xyz")
        with self.assertRaises(FileNotFoundError):
            subprocess.Popen(spec["command"], cwd=spec["cwd"], env=spec["env"],
                             stdin=subprocess.DEVNULL,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


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
