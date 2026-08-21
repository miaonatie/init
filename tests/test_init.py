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

    def test_apt_install_excludes_unavailable_packages_before_batch(self):
        self.bootstrap.package_installed = mock.Mock(return_value=False)
        self.bootstrap.apt_update = mock.Mock(return_value=True)
        self.bootstrap.package_available = mock.Mock(side_effect=lambda package: package != "gone")
        self.bootstrap.run = mock.Mock(
            return_value=subprocess.CompletedProcess(["apt-get"], 0, stdout="", stderr="")
        )
        self.assertFalse(self.bootstrap.apt_install(["kept", "gone"], "test", required=True))
        command = self.bootstrap.run.call_args.args[0]
        self.assertIn("kept", command)
        self.assertNotIn("gone", command)
        self.assertIn("APT package unavailable: gone", self.bootstrap.failures)

    def test_apt_install_does_not_duplicate_apt_network_retries(self):
        self.bootstrap.package_installed = mock.Mock(return_value=False)
        self.bootstrap.apt_update = mock.Mock(return_value=True)
        self.bootstrap.package_available = mock.Mock(return_value=True)
        self.bootstrap.run = mock.Mock(
            return_value=subprocess.CompletedProcess(["apt-get"], 0, stdout="", stderr="")
        )
        self.assertTrue(self.bootstrap.apt_install(["sample"], "test", required=True))
        self.assertNotIn("network", self.bootstrap.run.call_args.kwargs)

    def test_existing_repository_is_not_updated(self):
        with tempfile.TemporaryDirectory() as directory:
            tools_dir = Path(directory)
            (tools_dir / "sample" / ".git").mkdir(parents=True)
            self.bootstrap.run = mock.Mock()
            with mock.patch.object(MODULE, "TOOLS_DIR", tools_dir):
                self.assertTrue(
                    self.bootstrap.clone_or_update("sample", "https://github.com/example/sample.git")
                )
            self.bootstrap.run.assert_not_called()
            self.assertEqual(self.bootstrap.failures, [])

    def test_python_install_uses_break_system_packages_globally(self):
        probe_result = subprocess.CompletedProcess(["python3", "-c"], 1, stdout="", stderr="")
        install_result = subprocess.CompletedProcess(["python3", "-m", "pip"], 0)
        self.bootstrap.run = mock.Mock(side_effect=[probe_result, install_result])
        self.bootstrap.install_python_tools()
        install_call = self.bootstrap.run.call_args
        command = install_call.args[0]
        self.assertNotIn("--user", command)
        self.assertIn("--break-system-packages", command)
        self.assertIn("--upgrade", command)
        self.assertNotIn("venv", command)
        self.assertTrue(install_call.kwargs["sudo"])

    def test_python_install_skips_when_imports_are_present(self):
        probe_result = subprocess.CompletedProcess(["python3", "-c"], 0, stdout="", stderr="")
        self.bootstrap.run = mock.Mock(return_value=probe_result)
        self.bootstrap.command_exists = mock.Mock(return_value=True)
        self.bootstrap.install_python_tools()
        self.bootstrap.run.assert_called_once()

    def test_python_missing_import_installs_matching_package(self):
        probe_result = subprocess.CompletedProcess(
            ["python3", "-c"], 0, stdout="capstone\n", stderr=""
        )
        install_result = subprocess.CompletedProcess(["python3", "-m", "pip"], 0)
        self.bootstrap.run = mock.Mock(side_effect=[probe_result, install_result])
        self.bootstrap.command_exists = mock.Mock(return_value=True)
        self.bootstrap.install_python_tools()
        command = self.bootstrap.run.call_args.args[0]
        self.assertIn("capstone", command)
        self.assertNotIn("ROPgadget", command)
        self.assertNotIn("ropper", command)

    def test_python2_existing_runtime_is_not_reinstalled(self):
        self.bootstrap.existing_python2 = mock.Mock(return_value=Path("/usr/bin/python2"))
        self.bootstrap.clone_or_update = mock.Mock()
        self.bootstrap.install_python2_legacy()
        self.bootstrap.clone_or_update.assert_not_called()

    def test_python2_pyenv_install_never_changes_global_python(self):
        with tempfile.TemporaryDirectory() as directory:
            tools_dir = Path(directory)
            (tools_dir / "pyenv" / "bin").mkdir(parents=True)
            (tools_dir / "pyenv" / "bin" / "pyenv").touch()
            runtime_bin = tools_dir / "pyenv" / "versions" / MODULE.PYTHON2_VERSION / "bin"
            runtime_bin.mkdir(parents=True)
            (runtime_bin / "python2.7").touch()
            (runtime_bin / "pip2").touch()
            self.bootstrap.existing_python2 = mock.Mock(return_value=None)
            self.bootstrap.clone_or_update = mock.Mock(return_value=True)
            self.bootstrap.valid_python2 = mock.Mock(return_value=True)
            self.bootstrap.run = mock.Mock(
                return_value=subprocess.CompletedProcess(["command"], 0, stdout="", stderr="")
            )
            with mock.patch.object(MODULE, "TOOLS_DIR", tools_dir):
                self.bootstrap.install_python2_legacy()
            commands = [call.args[0] for call in self.bootstrap.run.call_args_list]
            self.assertTrue(any(command[1:3] == ["install", "-s"] for command in commands))
            self.assertFalse(any("global" in command for command in commands))

    def test_docker_repository_targets_ubuntu_and_kali(self):
        self.bootstrap.distro = {
            "id": "ubuntu", "version": "24.04", "codename": "noble",
            "ubuntu_codename": "noble",
        }
        self.assertEqual(self.bootstrap.docker_repository(), ("ubuntu", "noble"))
        self.bootstrap.distro = {
            "id": "kali", "version": "2026.2", "codename": "kali-rolling",
            "ubuntu_codename": "",
        }
        self.assertEqual(self.bootstrap.docker_repository(), ("debian", "trixie"))

    def test_docker_existing_install_is_skipped(self):
        self.bootstrap.docker_ready = mock.Mock(return_value=True)
        self.bootstrap.setup_docker_repository = mock.Mock()
        self.bootstrap.apt_install = mock.Mock()
        self.bootstrap.install_docker()
        self.bootstrap.setup_docker_repository.assert_not_called()
        self.bootstrap.apt_install.assert_not_called()

    def test_docker_repository_configuration_is_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            keyring = root / "docker.asc"
            source_path = root / "docker.sources"
            keyring.write_bytes(b"x" * 100)
            source_path.write_text(
                "Types: deb\n"
                "URIs: https://download.docker.com/linux/ubuntu\n"
                "Suites: noble\n"
                "Components: stable\n"
                "Architectures: amd64\n"
                f"Signed-By: {keyring}\n",
                encoding="utf-8",
            )
            self.bootstrap.distro = {
                "id": "ubuntu", "version": "24.04", "codename": "noble",
                "ubuntu_codename": "noble",
            }
            self.bootstrap.run = mock.Mock(
                return_value=subprocess.CompletedProcess(["dpkg"], 0, stdout="amd64\n", stderr="")
            )
            with (
                mock.patch.object(MODULE, "DOCKER_KEYRING", keyring),
                mock.patch.object(MODULE, "DOCKER_SOURCE", source_path),
            ):
                self.assertTrue(self.bootstrap.setup_docker_repository())
            self.bootstrap.run.assert_called_once()

    def test_docker_package_set_is_complete(self):
        self.assertEqual(
            MODULE.DOCKER_PACKAGES,
            [
                "docker-ce", "docker-ce-cli", "containerd.io",
                "docker-buildx-plugin", "docker-compose-plugin",
            ],
        )

    def test_disk_limits_scale_with_missing_work(self):
        self.bootstrap.package_installed = mock.Mock(return_value=False)
        self.assertEqual(self.bootstrap.installation_space_limits(), (10, 15))

        self.bootstrap.package_installed = mock.Mock(return_value=True)
        self.bootstrap.existing_python2 = mock.Mock(return_value=Path("/usr/bin/python2"))
        self.bootstrap.docker_ready = mock.Mock(return_value=True)
        self.assertEqual(self.bootstrap.installation_space_limits(), (1, 3))

        self.bootstrap.existing_python2 = mock.Mock(return_value=None)
        self.assertEqual(self.bootstrap.installation_space_limits(), (3, 5))

    def test_progress_output_is_plain_text_when_not_tty(self):
        output = io.StringIO()
        with redirect_stdout(output):
            self.bootstrap.section("Example")
        text = output.getvalue()
        self.assertIn("[01/04] Example", text)
        self.assertIn("elapsed 00:00:00", text)
        self.assertNotIn("\033", text)

    def test_stage_runner_reports_stage_duration(self):
        output = io.StringIO()
        action = mock.Mock()
        self.bootstrap.started_monotonic = 100
        with mock.patch.object(MODULE.time, "monotonic", side_effect=[100, 100, 102]):
            with redirect_stdout(output):
                self.bootstrap.run_stage("CTF toolchain", action)
        action.assert_called_once_with()
        text = output.getvalue()
        self.assertIn("[01/04] CTF toolchain", text)
        self.assertIn("CTF toolchain finished in 00:00:02", text)

    def test_stage_runner_does_not_report_success_after_recorded_failure(self):
        def action():
            self.bootstrap.failures.append("example")

        output = io.StringIO()
        self.bootstrap.started_monotonic = 100
        with mock.patch.object(MODULE.time, "monotonic", side_effect=[100, 100, 101]):
            with redirect_stdout(output):
                self.bootstrap.run_stage("CTF toolchain", action)
        text = output.getvalue()
        self.assertIn("WARN: CTF toolchain finished with 1 failure(s) in 00:00:01", text)
        self.assertNotIn("OK: CTF toolchain finished", text)

    def test_install_uses_four_ctf_environment_stages(self):
        self.bootstrap.run_stage = mock.Mock()
        self.bootstrap.summary = mock.Mock(return_value=0)
        with redirect_stdout(io.StringIO()):
            self.assertEqual(self.bootstrap.install(), 0)
        titles = [call.args[0] for call in self.bootstrap.run_stage.call_args_list]
        self.assertEqual(
            titles,
            ["Environment check", "System foundation", "CTF toolchain", "Verification"],
        )

    def test_system_packages_are_installed_in_bounded_groups(self):
        self.bootstrap.distro = {"id": "kali"}
        self.bootstrap.enable_i386 = mock.Mock(return_value=list(MODULE.I386_APT))
        self.bootstrap.apt_install = mock.Mock(return_value=True)
        self.bootstrap.install_command_links = mock.Mock()
        self.bootstrap.install_docker = mock.Mock()
        self.bootstrap.install_system_foundation()
        calls = self.bootstrap.apt_install.call_args_list
        self.assertEqual([call.args[1] for call in calls], [
            "system and development packages",
            "daily CLI tools",
            "CTF CLI tools",
            "32-bit development support",
        ])
        self.assertEqual(calls[0].args[0], MODULE.REQUIRED_APT)
        self.assertEqual(calls[1].args[0], [*MODULE.DAILY_APT, *MODULE.KALI_APT])
        self.assertEqual(calls[2].args[0], MODULE.CTF_APT)
        self.assertEqual(calls[3].args[0], MODULE.I386_APT)

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
            "xxd", "zsh", "shellcheck", "bash-completion",
        }
        self.assertTrue(expected <= packages)
        self.assertNotIn("hexyl", packages)
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
