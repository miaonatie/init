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


class InstallerTests(unittest.TestCase):
    def setUp(self):
        self.bootstrap = MODULE.Bootstrap()

    def test_version_has_single_source_of_truth(self):
        self.assertEqual(MODULE.VERSION, (ROOT / "VERSION").read_text(encoding="utf-8").strip())

    def test_rejects_unapproved_installer_url(self):
        with self.assertRaises(RuntimeError):
            self.bootstrap.download_installer("test", "http://example.com/install.sh")

    def test_supports_only_modern_ubuntu_and_kali(self):
        self.assertTrue(MODULE.Bootstrap.supported_distro({"id": "ubuntu", "version": "24.04"}))
        self.assertTrue(MODULE.Bootstrap.supported_distro({"id": "kali", "version": "2026.2"}))
        self.assertFalse(MODULE.Bootstrap.supported_distro({"id": "ubuntu", "version": "22.04"}))
        self.assertFalse(MODULE.Bootstrap.supported_distro({"id": "debian", "version": "13"}))

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

    def test_python_install_uses_break_system_packages_globally(self):
        install_result = subprocess.CompletedProcess(["python3", "-m", "pip"], 0)
        self.bootstrap.run = mock.Mock(return_value=install_result)
        self.bootstrap.install_python_tools()
        install_call = self.bootstrap.run.call_args
        command = install_call.args[0]
        self.assertNotIn("--user", command)
        self.assertIn("--break-system-packages", command)
        self.assertNotIn("venv", command)
        self.assertTrue(install_call.kwargs["sudo"])

    def test_progress_output_is_plain_text_when_not_tty(self):
        output = io.StringIO()
        with redirect_stdout(output):
            self.bootstrap.section("Example")
        text = output.getvalue()
        self.assertIn("[01/04] Example", text)
        self.assertIn("elapsed 00:00:00", text)
        self.assertNotIn("\033", text)

    def test_color_output_when_enabled(self):
        self.bootstrap.color = True
        output = io.StringIO()
        with redirect_stdout(output):
            self.bootstrap.ok("Example")
        self.assertIn("\033[32mOK: Example\033[0m", output.getvalue())

    def test_only_pwndbg_remote_installer_remains(self):
        self.assertEqual(set(MODULE.REMOTE_INSTALLERS), {"pwndbg"})
        self.assertEqual(MODULE.ALLOWED_INSTALLER_HOSTS, {"install.pwndbg.re"})

    def test_extended_toolchain_keeps_direct_system_python(self):
        packages = set(MODULE.REQUIRED_APT) | set(MODULE.DAILY_APT) | set(MODULE.CTF_APT)
        expected = {
            "clang", "llvm", "lld", "ninja-build", "meson", "default-jdk",
            "radare2", "libradare2-dev", "qemu-user", "qemu-system", "hyfetch",
            "xxd", "hexyl", "zsh", "shellcheck", "bash-completion",
        }
        self.assertTrue(expected <= packages)
        self.assertNotIn("python3-venv", packages)
        self.assertNotIn("pipx", packages)

    def test_ctf_cli_toolset_is_present_without_system_services(self):
        packages = set(MODULE.REQUIRED_APT) | set(MODULE.CTF_APT)
        expected = {
            "steghide", "stegseek", "binwalk", "libimage-exiftool-perl", "pngcheck",
            "foremost", "sleuthkit", "tshark", "hashcat", "john", "apktool",
            "nasm", "valgrind", "ffmpeg", "sox", "zbar-tools", "tesseract-ocr",
        }
        self.assertTrue(expected <= packages)
        self.assertTrue({"Pillow", "pycryptodome", "oletools", "volatility3"} <= set(MODULE.PYTHON_PACKAGES))
        self.assertIn("zsteg", MODULE.RUBY_GEMS)
        self.assertNotIn("hexedit", packages)
        self.assertFalse({"fail2ban", "ufw", "dkms"} & packages)

    def test_r2ghidra_uses_official_r2pm_installer(self):
        self.bootstrap.r2ghidra_available = mock.Mock(side_effect=[False, True])
        self.bootstrap.command_exists = mock.Mock(return_value=True)
        self.bootstrap.run = mock.Mock(
            return_value=subprocess.CompletedProcess(["r2pm"], 0)
        )
        self.bootstrap.install_r2ghidra()
        commands = [call.args[0] for call in self.bootstrap.run.call_args_list]
        self.assertEqual(commands, [["r2pm", "-U"], ["r2pm", "-ci", "r2ghidra"]])
        self.assertEqual(self.bootstrap.failures, [])


if __name__ == "__main__":
    unittest.main()
