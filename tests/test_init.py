import importlib.util
import io
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("init_module", ROOT / "init.py")
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class ConfigTests(unittest.TestCase):
    def setUp(self):
        self.bootstrap = MODULE.Bootstrap()

    def test_upsert_replaces_only_named_block(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "rc"
            target.write_text(
                "before\n# >>> other >>>\nkeep\n# <<< other <<<\n",
                encoding="utf-8",
            )
            self.bootstrap.upsert_block(target, "init-shell", "source managed")
            self.bootstrap.upsert_block(target, "init-shell", "source updated")
            text = target.read_text(encoding="utf-8")
            self.assertIn("# >>> other >>>\nkeep\n# <<< other <<<", text)
            self.assertNotIn("source managed", text)
            self.assertEqual(text.count("# >>> init-shell >>>"), 1)
            self.assertIn("source updated", text)

    def test_remove_block_keeps_unmanaged_content(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "rc"
            target.write_text(
                "before\n# >>> init-shell >>>\nmanaged\n# <<< init-shell <<<\nafter\n",
                encoding="utf-8",
            )
            self.assertTrue(self.bootstrap.remove_block(target, "init-shell"))
            self.assertEqual(target.read_text(encoding="utf-8"), "before\nafter\n")

    def test_atomic_write_replaces_content(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "file"
            MODULE.Bootstrap.atomic_write(target, "first\n")
            MODULE.Bootstrap.atomic_write(target, "second\n")
            self.assertEqual(target.read_text(encoding="utf-8"), "second\n")

    def test_required_config_files_exist(self):
        for name in ("shell.sh", "gdbinit", "tmux.conf"):
            self.assertTrue((ROOT / "config" / name).is_file())

    def test_version_has_single_source_of_truth(self):
        self.assertEqual(MODULE.VERSION, (ROOT / "VERSION").read_text(encoding="utf-8").strip())

    def test_rejects_unapproved_installer_url(self):
        with self.assertRaises(RuntimeError):
            self.bootstrap.download_installer("test", "http://example.com/install.sh")

    @mock.patch.object(MODULE.time, "sleep")
    def test_apt_update_rejects_partial_index(self, _sleep):
        result = subprocess.CompletedProcess(
            ["apt-get", "update"],
            0,
            stdout="W: Failed to fetch repository metadata\n",
            stderr="",
        )
        self.bootstrap.run = mock.Mock(return_value=result)
        self.assertFalse(self.bootstrap.apt_update())
        self.assertEqual(self.bootstrap.run.call_count, MODULE.NETWORK_ATTEMPTS)
        self.assertIn("APT index update failed", self.bootstrap.failures)

    def test_repository_pull_failure_is_not_success(self):
        with tempfile.TemporaryDirectory() as directory:
            tools_dir = Path(directory)
            (tools_dir / "sample" / ".git").mkdir(parents=True)
            result = subprocess.CompletedProcess(["git", "pull"], 1)
            self.bootstrap.run = mock.Mock(return_value=result)
            with mock.patch.object(MODULE, "TOOLS_DIR", tools_dir):
                self.assertFalse(
                    self.bootstrap.clone_or_update("sample", "https://github.com/example/sample.git")
                )
            self.assertIn("repository update failed: sample", self.bootstrap.failures)

    def test_python_install_uses_break_system_packages(self):
        help_result = subprocess.CompletedProcess(
            ["python3", "-m", "pip", "install", "--help"],
            0,
            stdout="options: --break-system-packages",
            stderr="",
        )
        install_result = subprocess.CompletedProcess(["python3", "-m", "pip"], 0)
        self.bootstrap.run = mock.Mock(side_effect=[help_result, install_result])
        self.bootstrap.install_python_tools()
        command = self.bootstrap.run.call_args_list[1].args[0]
        self.assertIn("--user", command)
        self.assertIn("--break-system-packages", command)
        self.assertNotIn("venv", command)

    def test_progress_output_is_plain_text_when_not_tty(self):
        output = io.StringIO()
        with redirect_stdout(output):
            self.bootstrap.section("Example")
        text = output.getvalue()
        self.assertIn("[01/05] Example", text)
        self.assertIn("elapsed 00:00:00", text)
        self.assertNotIn("\033", text)

    def test_color_output_when_enabled(self):
        self.bootstrap.color = True
        output = io.StringIO()
        with redirect_stdout(output):
            self.bootstrap.ok("Example")
        self.assertIn("\033[32mOK: Example\033[0m", output.getvalue())


if __name__ == "__main__":
    unittest.main()
