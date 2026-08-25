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

    def test_managed_git_repositories_live_under_tools(self):
        self.assertEqual(MODULE.GLIBC_AIO_DIR, MODULE.TOOLS_DIR / "glibc-all-in-one")
        self.assertEqual(MODULE.LIBC_DATABASE_DIR, MODULE.TOOLS_DIR / "libc-database")
        self.assertEqual(self.bootstrap.python2_prefix().parents[2], MODULE.TOOLS_DIR)

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
        self.bootstrap.find_usable_command = mock.Mock(return_value="/usr/local/bin/tool")
        self.bootstrap.install_python_tools()
        self.bootstrap.run.assert_called_once()

    def test_python_missing_import_installs_matching_package(self):
        probe_result = subprocess.CompletedProcess(
            ["python3", "-c"], 0, stdout="capstone\n", stderr=""
        )
        install_result = subprocess.CompletedProcess(["python3", "-m", "pip"], 0)
        self.bootstrap.run = mock.Mock(side_effect=[probe_result, install_result])
        self.bootstrap.find_usable_command = mock.Mock(return_value="/usr/local/bin/tool")
        self.bootstrap.install_python_tools()
        command = self.bootstrap.run.call_args.args[0]
        self.assertIn("capstone", command)
        self.assertNotIn("ROPgadget", command)
        self.assertNotIn("ropper", command)

    def test_python2_existing_runtime_is_not_reinstalled(self):
        python2 = Path("/usr/bin/python2")
        self.bootstrap.existing_python2 = mock.Mock(return_value=python2)
        self.bootstrap.configure_python2_runtime = mock.Mock(return_value=True)
        self.bootstrap.clone_or_update = mock.Mock()
        self.bootstrap.install_python2_legacy()
        self.bootstrap.configure_python2_runtime.assert_called_once_with(python2)
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
            self.bootstrap.configure_python2_runtime = mock.Mock(return_value=True)
            self.bootstrap.run = mock.Mock(
                return_value=subprocess.CompletedProcess(["command"], 0, stdout="", stderr="")
            )
            with mock.patch.object(MODULE, "TOOLS_DIR", tools_dir):
                self.bootstrap.install_python2_legacy()
            commands = [call.args[0] for call in self.bootstrap.run.call_args_list]
            self.assertTrue(any(command[1:3] == ["install", "-s"] for command in commands))
            self.assertFalse(any("global" in command for command in commands))

    def test_python2_runtime_creates_pip2_wrapper_from_pip_module(self):
        with tempfile.TemporaryDirectory() as directory:
            python2 = Path(directory) / "python2.7"
            python2.touch()
            wrapper_content = []

            def run(command, **_kwargs):
                if command[0] == "install":
                    wrapper_content.append(Path(command[3]).read_text(encoding="utf-8"))
                stdout = "pip 20.3.4 from test (python 2.7)\n"
                return subprocess.CompletedProcess(command, 0, stdout=stdout, stderr="")

            self.bootstrap.run = mock.Mock(side_effect=run)
            self.assertTrue(self.bootstrap.configure_python2_runtime(python2))
            commands = [call.args[0] for call in self.bootstrap.run.call_args_list]
            self.assertIn(
                ["ln", "-sf", str(python2.resolve()), "/usr/local/bin/python2"],
                commands,
            )
            self.assertTrue(
                any(command[0:3] == ["install", "-m", "0755"] for command in commands)
            )
            self.assertEqual(len(wrapper_content), 1)
            self.assertIn(str(python2.resolve()), wrapper_content[0])
            self.assertIn('-m pip "$@"', wrapper_content[0])

    def test_python2_runtime_bootstraps_missing_pip_before_wrapper(self):
        with tempfile.TemporaryDirectory() as directory:
            python2 = Path(directory) / "python2.7"
            python2.touch()
            pip_probes = 0

            def run(command, **_kwargs):
                nonlocal pip_probes
                if command[1:4] == ["-m", "pip", "--version"]:
                    pip_probes += 1
                    return subprocess.CompletedProcess(
                        command,
                        1 if pip_probes == 1 else 0,
                        stdout="" if pip_probes == 1 else "pip 20.3.4\n",
                        stderr="",
                    )
                return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

            self.bootstrap.run = mock.Mock(side_effect=run)
            self.assertTrue(self.bootstrap.configure_python2_runtime(python2))
            commands = [call.args[0] for call in self.bootstrap.run.call_args_list]
            self.assertIn(
                [str(python2.resolve()), "-m", "ensurepip", "--upgrade"],
                commands,
            )
            self.assertEqual(pip_probes, 2)

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
        self.assertEqual(self.bootstrap.installation_space_limits(), (12, 18))

        self.bootstrap.package_installed = mock.Mock(return_value=True)
        self.bootstrap.existing_python2 = mock.Mock(return_value=Path("/usr/bin/python2"))
        self.bootstrap.docker_ready = mock.Mock(return_value=True)
        self.bootstrap.node_environment_available = mock.Mock(return_value=True)
        self.bootstrap.rust_environment_available = mock.Mock(return_value=True)
        self.assertEqual(self.bootstrap.installation_space_limits(), (1, 3))

        self.bootstrap.existing_python2 = mock.Mock(return_value=None)
        self.assertEqual(self.bootstrap.installation_space_limits(), (4, 7))

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
        self.assertEqual(
            MODULE.ALLOWED_INSTALLER_HOSTS,
            {"install.pwndbg.re", "raw.githubusercontent.com", "sh.rustup.rs"},
        )

    def test_node_and_rust_installers_use_pinned_or_official_sources(self):
        self.assertEqual(MODULE.NVM_VERSION, "0.40.7")
        self.assertEqual(
            MODULE.NVM_URL,
            "https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.7/install.sh",
        )
        self.assertEqual(MODULE.RUSTUP_URL, "https://sh.rustup.rs")

    def test_node_and_rust_shell_configuration_is_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bashrc = root / ".bashrc"
            zshrc = root / ".zshrc"
            bashrc.write_text("export CUSTOM_SETTING=1\n", encoding="utf-8")
            with (
                mock.patch.object(MODULE, "BASHRC", bashrc),
                mock.patch.object(MODULE, "ZSHRC", zshrc),
            ):
                self.assertTrue(self.bootstrap.configure_node_shells())
                self.assertTrue(self.bootstrap.configure_rust_shells())
                self.assertTrue(self.bootstrap.configure_node_shells())
                self.assertTrue(self.bootstrap.configure_rust_shells())

            bash_text = bashrc.read_text(encoding="utf-8")
            zsh_text = zshrc.read_text(encoding="utf-8")
            self.assertIn("export CUSTOM_SETTING=1", bash_text)
            for text in (bash_text, zsh_text):
                self.assertEqual(text.count(MODULE.NVM_PROFILE_BEGIN), 1)
                self.assertEqual(text.count(MODULE.NVM_PROFILE_END), 1)
                self.assertEqual(text.count(MODULE.RUST_PROFILE_BEGIN), 1)
                self.assertEqual(text.count(MODULE.RUST_PROFILE_END), 1)
                self.assertIn('export NVM_DIR="$HOME/tools/nvm"', text)
                self.assertIn('[ -f "$HOME/.cargo/env" ]', text)

    def test_node_install_uses_lts_and_corepack_managed_package_managers(self):
        self.bootstrap.install_nvm = mock.Mock(return_value=True)
        self.bootstrap.configure_node_shells = mock.Mock(return_value=True)
        self.bootstrap.run_node_shell = mock.Mock(
            return_value=subprocess.CompletedProcess(["bash"], 0)
        )
        self.bootstrap.node_environment_available = mock.Mock(return_value=True)

        self.bootstrap.install_node_environment()

        call = self.bootstrap.run_node_shell.call_args
        commands = call.args[0]
        self.assertIn("nvm install --lts", commands)
        self.assertIn("nvm alias default 'lts/*'", commands)
        self.assertIn("nvm use --lts", commands)
        self.assertIn("npm install --global corepack@latest", commands)
        self.assertIn("corepack enable", commands)
        self.assertIn("corepack install --global pnpm@latest", commands)
        self.assertIn("corepack install --global yarn@stable", commands)
        self.assertTrue(call.kwargs["network"])
        self.assertEqual(call.kwargs["timeout"], 900)
        self.assertEqual(self.bootstrap.failures, [])

    def test_existing_rustup_updates_stable_and_standard_components(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cargo_home = root / ".cargo"
            rustup_home = root / ".rustup"
            rustup = cargo_home / "bin" / "rustup"
            rustup.parent.mkdir(parents=True)
            rustup.touch()
            self.bootstrap.run = mock.Mock(
                return_value=subprocess.CompletedProcess(["rustup"], 0)
            )
            self.bootstrap.configure_rust_shells = mock.Mock(return_value=True)
            self.bootstrap.rust_environment_available = mock.Mock(return_value=True)
            with (
                mock.patch.object(MODULE, "CARGO_HOME", cargo_home),
                mock.patch.object(MODULE, "RUSTUP_HOME", rustup_home),
            ):
                self.bootstrap.install_rust_environment()

            commands = [call.args[0] for call in self.bootstrap.run.call_args_list]
            self.assertEqual(commands[0], [str(rustup), "update", "stable"])
            self.assertEqual(commands[1], [str(rustup), "default", "stable"])
            self.assertEqual(
                commands[2],
                [
                    str(rustup), "component", "add", "--toolchain", "stable",
                    "rustfmt", "clippy",
                ],
            )
            self.assertTrue(all(call.kwargs["network"] for call in self.bootstrap.run.call_args_list))
            self.assertEqual(self.bootstrap.failures, [])

    def test_extended_toolchain_keeps_direct_system_python(self):
        packages = set(MODULE.REQUIRED_APT) | set(MODULE.DAILY_APT) | set(MODULE.CTF_APT)
        expected = {
            "clang", "llvm", "lld", "ninja-build", "meson", "default-jdk",
            "qemu-user", "qemu-system", "hyfetch",
            "xxd", "zsh", "shellcheck", "bash-completion", "perl",
        }
        self.assertTrue(expected <= packages)
        self.assertFalse({"radare2", "libradare2-dev"} & packages)
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

    def test_radare2_version_is_parsed(self):
        self.bootstrap.command_exists = mock.Mock(return_value=True)
        self.bootstrap.run = mock.Mock(
            return_value=subprocess.CompletedProcess(
                ["r2", "-v"], 0, stdout="radare2 6.2.1 0 @ linux-x86-64\n", stderr=""
            )
        )
        self.assertEqual(self.bootstrap.radare2_version(), (6, 2, 1))

    def test_compatible_radare2_is_not_rebuilt(self):
        self.bootstrap.radare2_version = mock.Mock(return_value=(6, 2, 1))
        self.bootstrap.command_exists = mock.Mock(return_value=True)
        self.bootstrap.run = mock.Mock()
        self.assertTrue(self.bootstrap.install_radare2())
        self.bootstrap.run.assert_not_called()

    def test_old_radare2_is_updated_from_official_git(self):
        with tempfile.TemporaryDirectory() as directory:
            tools_dir = Path(directory)
            source = tools_dir / "radare2"
            (source / ".git").mkdir(parents=True)
            (source / "sys").mkdir()
            (source / "sys" / "install.sh").touch()
            self.bootstrap.radare2_version = mock.Mock(
                side_effect=[(5, 9, 8), (6, 2, 1)]
            )
            self.bootstrap.command_exists = mock.Mock(return_value=True)
            self.bootstrap.run = mock.Mock(
                return_value=subprocess.CompletedProcess(["command"], 0, stdout="", stderr="")
            )
            with mock.patch.object(MODULE, "TOOLS_DIR", tools_dir):
                self.assertTrue(self.bootstrap.install_radare2())
            commands = [call.args[0] for call in self.bootstrap.run.call_args_list]
            self.assertEqual(
                commands[0],
                ["git", "-C", str(source), "pull", "--ff-only", "origin", "master"],
            )
            self.assertEqual(
                commands[1],
                [
                    "sh", str(source / "sys" / "install.sh"),
                    "--install", "--without-pull",
                ],
            )

    def test_r2ghidra_uses_official_r2pm_installer(self):
        self.bootstrap.r2ghidra_available = mock.Mock(side_effect=[False, True])
        self.bootstrap.command_exists = mock.Mock(return_value=True)
        self.bootstrap.run = mock.Mock(
            return_value=subprocess.CompletedProcess(["r2pm"], 0)
        )
        self.bootstrap.install_r2ghidra()
        commands = [call.args[0] for call in self.bootstrap.run.call_args_list]
        self.assertEqual(commands, [["r2pm", "-U"], ["r2pm", "-ci", "r2ghidra"]])
        self.assertTrue(self.bootstrap.run.call_args_list[0].kwargs["network"])
        self.assertNotIn("network", self.bootstrap.run.call_args_list[1].kwargs)
        self.assertEqual(self.bootstrap.failures, [])

    def test_r2ghidra_stops_when_r2pm_database_update_fails(self):
        self.bootstrap.r2ghidra_available = mock.Mock(return_value=False)
        self.bootstrap.command_exists = mock.Mock(return_value=True)
        self.bootstrap.run = mock.Mock(
            return_value=subprocess.CompletedProcess(["r2pm", "-U"], 1)
        )
        self.bootstrap.install_r2ghidra()
        self.bootstrap.run.assert_called_once()
        self.assertIn("r2pm -U", self.bootstrap.failures[0])

    def test_r2ghidra_reports_unloadable_plugin_after_install(self):
        self.bootstrap.r2ghidra_available = mock.Mock(return_value=False)
        self.bootstrap.command_exists = mock.Mock(return_value=True)
        self.bootstrap.run = mock.Mock(
            return_value=subprocess.CompletedProcess(["r2pm"], 0)
        )
        self.bootstrap.install_r2ghidra()
        self.assertIn("matching versions", self.bootstrap.failures[0])

    def test_r2pipe_install_uses_fixed_user_directory_without_sudo(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "pwndbg-python"
            self.bootstrap.r2pipe_target_available = mock.Mock(side_effect=[False, True])
            self.bootstrap.run = mock.Mock(
                return_value=subprocess.CompletedProcess(["python3", "-m", "pip"], 0)
            )
            with mock.patch.object(MODULE, "PWNDBG_PYTHON_DIR", target):
                self.assertTrue(self.bootstrap.install_r2pipe_for_pwndbg())
            call = self.bootstrap.run.call_args
            command = call.args[0]
            self.assertIn("--target", command)
            self.assertEqual(command[command.index("--target") + 1], str(target))
            self.assertIn(f"r2pipe=={MODULE.R2PIPE_VERSION}", command)
            self.assertIn("--no-deps", command)
            self.assertNotIn("sudo", command)
            self.assertNotIn("sudo", call.kwargs)

    def test_r2pipe_install_skips_when_exact_version_is_available(self):
        self.bootstrap.r2pipe_target_available = mock.Mock(return_value=True)
        self.bootstrap.run = mock.Mock()
        self.assertTrue(self.bootstrap.install_r2pipe_for_pwndbg())
        self.bootstrap.run.assert_not_called()

    def test_pwndbg_bridge_configuration_is_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "pwndbg-python"
            script = root / "share" / "r2ghidra.py"
            gdbinit = root / ".gdbinit"
            gdbinit.write_text("set pagination off\n", encoding="utf-8")
            with (
                mock.patch.object(MODULE, "PWNDBG_PYTHON_DIR", target),
                mock.patch.object(MODULE, "PWNDBG_BRIDGE_SCRIPT", script),
                mock.patch.object(MODULE, "GDBINIT", gdbinit),
            ):
                self.assertTrue(self.bootstrap.configure_pwndbg_r2ghidra())
                first = gdbinit.read_text(encoding="utf-8")
                self.assertTrue(self.bootstrap.configure_pwndbg_r2ghidra())
                second = gdbinit.read_text(encoding="utf-8")
            self.assertEqual(first, second)
            self.assertIn("set pagination off", second)
            self.assertEqual(second.count(MODULE.GDBINIT_BEGIN), 1)
            self.assertEqual(second.count(MODULE.GDBINIT_END), 1)
            bridge = script.read_text(encoding="utf-8")
            self.assertIn(str(target), bridge)
            self.assertIn('super().__init__("ghidra"', bridge)
            self.assertIn('gdb.execute(f"r2pipe pdg @', bridge)

    def test_pwndbg_bridge_install_verifies_after_configuration(self):
        self.bootstrap.install_r2pipe_for_pwndbg = mock.Mock(return_value=True)
        self.bootstrap.configure_pwndbg_r2ghidra = mock.Mock(return_value=True)
        self.bootstrap.pwndbg_r2ghidra_available = mock.Mock(return_value=True)
        self.bootstrap.install_pwndbg_r2ghidra_bridge()
        self.bootstrap.install_r2pipe_for_pwndbg.assert_called_once_with()
        self.bootstrap.configure_pwndbg_r2ghidra.assert_called_once_with()
        self.bootstrap.pwndbg_r2ghidra_available.assert_called_once_with()
        self.assertEqual(self.bootstrap.failures, [])

    def test_pwndbg_integration_probe_checks_import_command_and_decompiler(self):
        self.bootstrap.find_command = mock.Mock(return_value="/usr/local/bin/pwndbg")
        self.bootstrap.r2pipe_target_available = mock.Mock(return_value=True)
        self.bootstrap.run = mock.Mock(
            return_value=subprocess.CompletedProcess(
                ["pwndbg"],
                0,
                stdout=(
                    "/home/test/.local/share/pwndbg-python/r2pipe/__init__.py\n"
                    "Decompile an address with Pwndbg, radare2 and r2ghidra.\n"
                    "Native Ghidra decompiler plugin\n"
                ),
                stderr="",
            )
        )
        self.assertTrue(self.bootstrap.pwndbg_r2ghidra_available())
        command = self.bootstrap.run.call_args.args[0]
        self.assertIn("pi import r2pipe; print(r2pipe.__file__)", command)
        self.assertIn("help ghidra", command)
        self.assertIn("r2pipe pdg?", command)

    def test_glibc_all_in_one_v2_installs_editable_cli_and_index(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            destination = root / "glibc-all-in-one"
            command_path = root / "bin" / "glibc-aio"
            destination.mkdir()
            (destination / "pyproject.toml").write_text(
                "[project]\nname='glibc-aio'\n", encoding="utf-8"
            )
            def run(command, **_kwargs):
                if command[-2:] == ["mirror", "update"]:
                    (destination / "list").write_text(
                        "2.35-0ubuntu3_amd64\n", encoding="utf-8"
                    )
                return subprocess.CompletedProcess(command, 0)

            self.bootstrap.run = mock.Mock(side_effect=run)
            self.bootstrap.install_command_wrapper = mock.Mock(return_value=True)
            self.bootstrap.glibc_aio_runtime_available = mock.Mock(return_value=True)
            with (
                mock.patch.object(MODULE, "GLIBC_AIO_DIR", destination),
                mock.patch.object(MODULE, "GLIBC_AIO_COMMAND", command_path),
            ):
                self.bootstrap.install_glibc_all_in_one()
            dependency_call, editable_call, index_call = self.bootstrap.run.call_args_list
            self.assertEqual(
                dependency_call.args[0][-2:], ["pyelftools", "zstandard"]
            )
            self.assertEqual(editable_call.args[0][-2:], ["--editable", "."])
            self.assertEqual(editable_call.kwargs["cwd"], destination)
            self.assertTrue(dependency_call.kwargs["sudo"])
            self.assertTrue(editable_call.kwargs["sudo"])
            self.assertEqual(
                index_call.args[0], [str(command_path), "mirror", "update"]
            )
            self.bootstrap.install_command_wrapper.assert_called_once()
            self.assertEqual(self.bootstrap.failures, [])

    def test_glibc_all_in_one_v2_repairs_package_even_when_index_is_ready(self):
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "glibc-all-in-one"
            destination.mkdir()
            (destination / "pyproject.toml").touch()
            (destination / "list").write_text("libc6 example\n", encoding="utf-8")
            self.bootstrap.run = mock.Mock(
                return_value=subprocess.CompletedProcess(["pip"], 0)
            )
            self.bootstrap.install_command_wrapper = mock.Mock(return_value=True)
            self.bootstrap.glibc_aio_runtime_available = mock.Mock(return_value=True)
            with mock.patch.object(MODULE, "GLIBC_AIO_DIR", destination):
                self.bootstrap.install_glibc_all_in_one()
            commands = [call.args[0] for call in self.bootstrap.run.call_args_list]
            self.assertEqual(len(commands), 2)
            self.assertEqual(commands[0][-2:], ["pyelftools", "zstandard"])
            self.assertEqual(commands[1][-2:], ["--editable", "."])
            self.assertEqual(self.bootstrap.failures, [])

    def test_glibc_legacy_checkout_is_fast_forwarded_to_v2(self):
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "glibc-all-in-one"
            (destination / ".git").mkdir(parents=True)

            def run(command, **_kwargs):
                if command[:3] == ["git", "-C", str(destination)]:
                    (destination / "pyproject.toml").touch()
                    (destination / "list").write_text(
                        "2.35-0ubuntu3_amd64\n", encoding="utf-8"
                    )
                return subprocess.CompletedProcess(command, 0)

            self.bootstrap.run = mock.Mock(side_effect=run)
            self.bootstrap.install_command_wrapper = mock.Mock(return_value=True)
            self.bootstrap.glibc_aio_runtime_available = mock.Mock(return_value=True)
            with mock.patch.object(MODULE, "GLIBC_AIO_DIR", destination):
                self.bootstrap.install_glibc_all_in_one()
            commands = [call.args[0] for call in self.bootstrap.run.call_args_list]
            self.assertEqual(
                commands[0],
                [
                    "git", "-C", str(destination), "pull", "--ff-only",
                    "origin", "master",
                ],
            )
            self.assertTrue(any("--editable" in command for command in commands))
            self.assertEqual(self.bootstrap.failures, [])

    def test_repository_wrapper_uses_managed_data_and_preserves_relative_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repository = root / "managed repo"
            caller = root / "caller"
            repository.mkdir()
            caller.mkdir()
            sample = caller / "libc.so.6"
            sample.touch()
            wrapper = root / "wrapper"
            wrapper.write_text(
                self.bootstrap.repository_command_wrapper(
                    repository,
                    [
                        "python3", "-c",
                        "import os, sys; print(os.getcwd()); print(sys.argv[1])",
                    ],
                ),
                encoding="utf-8",
            )
            wrapper.chmod(0o755)

            result = subprocess.run(
                [str(wrapper), sample.name],
                cwd=caller,
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0)
            self.assertEqual(
                result.stdout.splitlines(), [str(repository), str(sample)]
            )

    def test_libc_database_installs_direct_commands(self):
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "libc-database"
            destination.mkdir()
            for script_name in MODULE.LIBC_DATABASE_COMMANDS.values():
                (destination / script_name).touch()
            self.bootstrap.install_command_wrapper = mock.Mock(return_value=True)
            self.bootstrap.command_exists = mock.Mock(return_value=True)
            with mock.patch.object(MODULE, "LIBC_DATABASE_DIR", destination):
                self.bootstrap.configure_libc_database_commands()

            destinations = {
                call.args[0] for call in self.bootstrap.install_command_wrapper.call_args_list
            }
            self.assertEqual(
                destinations,
                {
                    Path("/usr/local/bin") / name
                    for name in MODULE.LIBC_DATABASE_COMMANDS
                },
            )
            self.assertEqual(self.bootstrap.failures, [])

    def test_launch_probe_rejects_broken_python_entrypoints(self):
        self.bootstrap.run = mock.Mock(
            return_value=subprocess.CompletedProcess(
                ["tool", "--help"],
                1,
                stdout="",
                stderr="Traceback (most recent call last): ModuleNotFoundError",
            )
        )
        self.assertFalse(self.bootstrap.executable_usable("tool", ["--help"]))

        self.bootstrap.run.return_value = subprocess.CompletedProcess(
            ["tool"], 2, stdout="", stderr="Usage: tool arguments"
        )
        self.assertTrue(self.bootstrap.executable_usable("tool", []))

    def test_ctf_toolchain_configures_bridge_after_pwndbg(self):
        names = [
            "install_python2_legacy", "install_python_tools", "install_ruby_tools",
            "install_node_environment", "install_rust_environment",
            "install_radare2", "install_r2ghidra", "install_remote_tool",
            "install_pwndbg_r2ghidra_bridge", "install_helper_repositories",
        ]
        calls = []
        for name in names:
            result = True if name == "install_radare2" else None
            setattr(
                self.bootstrap,
                name,
                mock.Mock(side_effect=lambda *args, _name=name, **kwargs: calls.append(_name),
                          return_value=result),
            )
        self.bootstrap.install_ctf_toolchain()
        self.assertLess(calls.index("install_node_environment"), calls.index("install_radare2"))
        self.assertLess(calls.index("install_rust_environment"), calls.index("install_radare2"))
        self.assertLess(calls.index("install_remote_tool"), calls.index("install_pwndbg_r2ghidra_bridge"))
        self.assertLess(calls.index("install_pwndbg_r2ghidra_bridge"), calls.index("install_helper_repositories"))


if __name__ == "__main__":
    unittest.main()
