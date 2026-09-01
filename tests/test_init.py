import importlib.util
import io
import subprocess
import sys
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

    def test_update_flag_selects_explicit_update_mode(self):
        bootstrap = mock.Mock()
        bootstrap.install.return_value = 0
        with mock.patch.object(MODULE, "Bootstrap", return_value=bootstrap) as constructor:
            self.assertEqual(MODULE.main(["--update"]), 0)
        constructor.assert_called_once_with(update_existing=True)
        bootstrap.install.assert_called_once_with()
        self.assertIn("--update", MODULE.help_text())

    def test_portable_pwndbg_cleanup_has_an_explicit_cli_mode(self):
        bootstrap = mock.Mock()
        bootstrap.remove_portable_pwndbg_only.return_value = 0
        with mock.patch.object(MODULE, "Bootstrap", return_value=bootstrap) as constructor:
            self.assertEqual(MODULE.main(["--remove-portable-pwndbg"]), 0)
        constructor.assert_called_once_with(update_existing=False)
        bootstrap.remove_portable_pwndbg_only.assert_called_once_with()
        bootstrap.install.assert_not_called()
        self.assertIn("--remove-portable-pwndbg", MODULE.help_text())

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

    def test_apt_failed_batch_falls_back_to_chunks_not_every_package(self):
        packages = [f"package-{index}" for index in range(18)]
        self.bootstrap.package_installed = mock.Mock(return_value=False)
        self.bootstrap.apt_update = mock.Mock(return_value=True)
        self.bootstrap.package_available = mock.Mock(return_value=True)
        self.bootstrap.run = mock.Mock(
            side_effect=[
                subprocess.CompletedProcess(["apt-get"], 1),
                subprocess.CompletedProcess(["apt-get"], 0),
                subprocess.CompletedProcess(["apt-get"], 0),
                subprocess.CompletedProcess(["apt-get"], 0),
            ]
        )

        self.assertTrue(self.bootstrap.apt_install(packages, "test", required=True))
        self.assertEqual(self.bootstrap.run.call_count, 4)
        fallback_sizes = [
            len(call.args[0]) - call.args[0].index("--no-install-recommends") - 1
            for call in self.bootstrap.run.call_args_list[1:]
        ]
        self.assertEqual(fallback_sizes, [8, 8, 2])

    @mock.patch.object(MODULE.time, "sleep")
    @mock.patch.object(MODULE.subprocess, "run")
    def test_network_retry_is_limited_to_one_short_retry(self, run, _sleep):
        run.side_effect = [
            subprocess.CompletedProcess(["git"], 1),
            subprocess.CompletedProcess(["git"], 0),
        ]
        result = self.bootstrap.run(["git", "fetch"], check=False, network=True)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(run.call_count, 2)
        _sleep.assert_called_once_with(2)

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
        self.bootstrap.python2_pip_ready = mock.Mock(return_value=True)
        self.bootstrap.configure_python2_runtime = mock.Mock(return_value=True)
        self.bootstrap.clone_or_update = mock.Mock()
        self.bootstrap.install_python2_legacy()
        self.bootstrap.configure_python2_runtime.assert_called_once_with(python2)
        self.bootstrap.clone_or_update.assert_not_called()

    def test_system_python2_without_pip_skips_disabled_ensurepip(self):
        python2 = Path("/usr/bin/python2")
        self.bootstrap.existing_python2 = mock.Mock(return_value=python2)
        self.bootstrap.python2_pip_ready = mock.Mock(return_value=False)
        self.bootstrap.configure_python2_runtime = mock.Mock()
        self.bootstrap.clone_or_update = mock.Mock(return_value=False)

        self.bootstrap.install_python2_legacy()

        self.bootstrap.configure_python2_runtime.assert_not_called()
        self.bootstrap.clone_or_update.assert_called_once_with("pyenv", MODULE.PYENV_URL)

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

    def test_python2_runtime_does_not_rewrite_matching_commands(self):
        with tempfile.TemporaryDirectory() as directory:
            command_dir = Path(directory) / "bin"
            command_dir.mkdir()
            python2 = Path(directory) / "python2.7"
            python2.touch()
            for name in ("python2", "python2.7"):
                (command_dir / name).symlink_to(python2)
            pip2 = command_dir / "pip2"
            pip2.write_text(
                "#!/bin/sh\n"
                f"exec {python2.resolve()} -m pip \"$@\"\n",
                encoding="utf-8",
            )
            pip2.chmod(0o755)
            self.bootstrap.python2_pip_ready = mock.Mock(return_value=True)
            self.bootstrap.run = mock.Mock(
                return_value=subprocess.CompletedProcess([str(pip2)], 0)
            )

            with mock.patch.object(MODULE, "PYTHON2_COMMAND_DIR", command_dir):
                self.assertTrue(self.bootstrap.configure_python2_runtime(python2))

            commands = [call.args[0] for call in self.bootstrap.run.call_args_list]
            self.assertFalse(any(command[0] in {"ln", "install"} for command in commands))

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

    def test_docker_health_probe_is_cached_within_one_run(self):
        self.bootstrap.command_exists = mock.Mock(return_value=True)
        self.bootstrap.run = mock.Mock(
            return_value=subprocess.CompletedProcess(["docker"], 0)
        )

        self.assertTrue(self.bootstrap.docker_ready())
        self.assertTrue(self.bootstrap.docker_ready())

        self.assertEqual(self.bootstrap.run.call_count, 4)

    def test_broken_existing_docker_packages_are_reinstalled_once(self):
        self.bootstrap.docker_ready = mock.Mock(side_effect=[False, True])
        self.bootstrap.setup_docker_repository = mock.Mock(return_value=True)
        self.bootstrap.package_installed = mock.Mock(
            side_effect=lambda package: package in MODULE.DOCKER_PACKAGES
        )
        self.bootstrap.apt_update = mock.Mock(return_value=True)
        self.bootstrap.run = mock.Mock(
            return_value=subprocess.CompletedProcess(["apt-get"], 0)
        )

        self.bootstrap.install_docker()

        command = self.bootstrap.run.call_args.args[0]
        self.assertIn("--reinstall", command)
        self.assertEqual(self.bootstrap.run.call_count, 1)
        self.assertEqual(self.bootstrap.failures, [])

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
        self.bootstrap.install_fastfetch = mock.Mock()
        self.bootstrap.configure_vim = mock.Mock()
        self.bootstrap.configure_tmux = mock.Mock()
        self.bootstrap.install_oh_my_zsh = mock.Mock()
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
        self.bootstrap.install_fastfetch.assert_called_once_with()
        self.bootstrap.configure_vim.assert_called_once_with()
        self.bootstrap.configure_tmux.assert_called_once_with()
        self.bootstrap.install_oh_my_zsh.assert_called_once_with()

    def test_healthy_fastfetch_skips_package_and_network_work(self):
        self.bootstrap.fastfetch_ready = mock.Mock(return_value=True)
        self.bootstrap.package_available = mock.Mock()
        self.bootstrap.apt_install = mock.Mock()
        self.bootstrap.run = mock.Mock()

        self.bootstrap.install_fastfetch()

        self.bootstrap.package_available.assert_not_called()
        self.bootstrap.apt_install.assert_not_called()
        self.bootstrap.run.assert_not_called()

    def test_fastfetch_release_is_arch_checked_and_installed_once(self):
        self.bootstrap.arch = "x86_64"
        self.bootstrap.fastfetch_ready = mock.Mock(side_effect=[False, True])
        self.bootstrap.package_available = mock.Mock(return_value=False)

        def run(command, **_kwargs):
            if command[:2] == ["dpkg-deb", "--field"]:
                return subprocess.CompletedProcess(
                    command, 0,
                    stdout="Package: fastfetch\nArchitecture: amd64\n",
                    stderr="",
                )
            if command == ["dpkg", "--print-architecture"]:
                return subprocess.CompletedProcess(command, 0, stdout="amd64\n", stderr="")
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

        self.bootstrap.run = mock.Mock(side_effect=run)
        self.bootstrap.install_fastfetch()

        commands = [call.args[0] for call in self.bootstrap.run.call_args_list]
        curl = next(command for command in commands if command[0] == "curl")
        self.assertIn(
            "https://github.com/fastfetch-cli/fastfetch/releases/latest/download/"
            "fastfetch-linux-amd64.deb",
            curl,
        )
        self.assertNotIn("--retry", curl)
        installs = [command for command in commands if command[0] == "apt-get"]
        self.assertEqual(len(installs), 1)
        self.assertIn("--no-install-recommends", installs[0])
        self.assertEqual(self.bootstrap.failures, [])

    def test_broken_fastfetch_package_is_reinstalled_once(self):
        self.bootstrap.fastfetch_ready = mock.Mock(side_effect=[False, True])
        self.bootstrap.package_available = mock.Mock(return_value=True)
        self.bootstrap.package_installed = mock.Mock(return_value=True)
        self.bootstrap.apt_update = mock.Mock(return_value=True)
        self.bootstrap.run = mock.Mock(
            return_value=subprocess.CompletedProcess(["apt-get"], 0)
        )

        self.bootstrap.install_fastfetch()

        command = self.bootstrap.run.call_args.args[0]
        self.assertIn("--reinstall", command)
        self.assertEqual(command[-1], "fastfetch")
        self.assertEqual(self.bootstrap.run.call_count, 1)
        self.assertEqual(self.bootstrap.failures, [])

    def test_vim_configuration_preserves_user_settings_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            vimrc = Path(directory) / ".vimrc"
            vimrc.write_text("set relativenumber\n", encoding="utf-8")
            with mock.patch.object(MODULE, "VIMRC", vimrc):
                self.bootstrap.configure_vim()
                first = vimrc.read_text(encoding="utf-8")
                self.bootstrap.configure_vim()
                second = vimrc.read_text(encoding="utf-8")
                self.assertTrue(self.bootstrap.vim_config_ready())

        self.assertEqual(first, second)
        self.assertIn("set relativenumber", first)
        self.assertEqual(first.count(MODULE.VIM_PROFILE_BEGIN), 1)
        self.assertIn("set tabstop=4", first)
        self.assertIn("set shiftwidth=4", first)
        self.assertIn("set expandtab", first)
        self.assertIn("set autoindent", first)

    def test_tmux_configuration_preserves_user_settings_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            tmux_conf = Path(directory) / ".tmux.conf"
            tmux_conf.write_text("setw -g mode-keys vi\n", encoding="utf-8")
            self.bootstrap.find_command = mock.Mock(return_value="/usr/bin/tmux")
            self.bootstrap.run = mock.Mock(
                return_value=subprocess.CompletedProcess(["tmux"], 0)
            )
            with mock.patch.object(MODULE, "TMUX_CONF", tmux_conf):
                self.bootstrap.configure_tmux()
                first = tmux_conf.read_text(encoding="utf-8")
                self.bootstrap.configure_tmux()
                second = tmux_conf.read_text(encoding="utf-8")
                self.assertTrue(self.bootstrap.tmux_config_ready())

        self.assertEqual(first, second)
        self.assertIn("setw -g mode-keys vi", first)
        self.assertEqual(first.count(MODULE.TMUX_PROFILE_BEGIN), 1)
        self.assertIn("set -g mouse on", first)
        self.assertIn("set -g history-limit 50000", first)
        self.assertNotIn("escape-time", first)
        self.assertNotIn("base-index", first)
        self.assertNotIn("renumber-windows", first)
        self.bootstrap.run.assert_called_once_with(
            ["/usr/bin/tmux", "source-file", str(tmux_conf)],
            check=False,
            capture=True,
            timeout=10,
        )

    def test_oh_my_zsh_configuration_merges_plugins_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            zshrc = Path(directory) / ".zshrc"
            zshrc.write_text(
                "export CUSTOM_SETTING=1\n"
                "plugins=(git docker)\n"
                "source \"$ZSH/oh-my-zsh.sh\"\n",
                encoding="utf-8",
            )
            with mock.patch.object(MODULE, "ZSHRC", zshrc):
                self.assertTrue(self.bootstrap.configure_oh_my_zsh_rc())
                first = zshrc.read_text(encoding="utf-8")
                self.assertFalse(self.bootstrap.configure_oh_my_zsh_rc())
                second = zshrc.read_text(encoding="utf-8")

        self.assertEqual(first, second)
        self.assertIn("export CUSTOM_SETTING=1", first)
        match = MODULE.re.search(r"(?ms)^\s*plugins=\((.*?)\)", first)
        self.assertIsNotNone(match)
        plugins = self.bootstrap.zsh_plugin_tokens(match.group(1))
        self.assertIn("docker", plugins)
        self.assertTrue(set(MODULE.OH_MY_ZSH_PLUGINS) <= set(plugins))
        self.assertEqual(plugins[-1], "zsh-syntax-highlighting")
        self.assertEqual(first.count("source \"$ZSH/oh-my-zsh.sh\""), 1)
        self.assertEqual(first.count("alias py='python'"), 1)

    def test_oh_my_zsh_health_probe_checks_files_config_and_default_shell(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            omz = root / ".oh-my-zsh"
            custom = omz / "custom" / "plugins"
            (omz / "oh-my-zsh.sh").parent.mkdir(parents=True)
            (omz / "oh-my-zsh.sh").touch()
            for name in MODULE.OH_MY_ZSH_PLUGIN_URLS:
                path = custom / name / f"{name}.plugin.zsh"
                path.parent.mkdir(parents=True)
                path.touch()
            zshrc = root / ".zshrc"
            with (
                mock.patch.object(MODULE, "OH_MY_ZSH_DIR", omz),
                mock.patch.object(MODULE, "ZSHRC", zshrc),
                mock.patch.object(
                    MODULE.pwd,
                    "getpwuid",
                    return_value=mock.Mock(pw_shell="/usr/bin/zsh"),
                ),
            ):
                self.bootstrap.configure_oh_my_zsh_rc()
                self.assertTrue(self.bootstrap.oh_my_zsh_ready())

    def test_default_zsh_is_not_reconfigured_when_already_selected(self):
        self.bootstrap.find_command = mock.Mock(return_value="/usr/bin/zsh")
        self.bootstrap.run = mock.Mock()
        with mock.patch.object(
            MODULE.pwd,
            "getpwuid",
            return_value=mock.Mock(pw_shell="/bin/zsh", pw_name="alice"),
        ):
            self.assertTrue(self.bootstrap.configure_default_zsh())
        self.bootstrap.run.assert_not_called()

    def test_sudo_entry_is_rejected_before_root_owned_dotfiles_are_created(self):
        with (
            mock.patch.object(MODULE.os, "geteuid", return_value=0),
            mock.patch.dict(MODULE.os.environ, {"SUDO_USER": "alice"}, clear=False),
        ):
            with self.assertRaisesRegex(RuntimeError, "do not run.*with sudo"):
                self.bootstrap.require_sudo()

    def test_color_output_when_enabled(self):
        self.bootstrap.color = True
        output = io.StringIO()
        with redirect_stdout(output):
            self.bootstrap.ok("Example")
        self.assertIn("\033[32mOK: Example\033[0m", output.getvalue())

    def test_remote_installer_hosts_are_official_and_pwndbg_uses_uv(self):
        self.assertEqual(
            MODULE.ALLOWED_INSTALLER_HOSTS,
            {"astral.sh", "raw.githubusercontent.com", "sh.rustup.rs"},
        )
        self.assertEqual(MODULE.UV_INSTALLER_URL, "https://astral.sh/uv/install.sh")
        self.assertEqual(MODULE.PWNDBG_VERSION, "2026.07.29")
        self.assertEqual(
            MODULE.PWNDBG_UV_SPEC,
            "git+https://github.com/pwndbg/pwndbg@2026.07.29",
        )

    def test_node_and_rust_installers_use_pinned_or_official_sources(self):
        self.assertEqual(MODULE.NVM_VERSION, "0.40.7")
        self.assertEqual(
            MODULE.NVM_URL,
            "https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.7/install.sh",
        )
        self.assertEqual(MODULE.RUSTUP_URL, "https://sh.rustup.rs")
        self.assertEqual(
            MODULE.OH_MY_ZSH_URL,
            "https://github.com/ohmyzsh/ohmyzsh.git",
        )
        self.assertEqual(
            set(MODULE.OH_MY_ZSH_PLUGIN_URLS.values()),
            {
                "https://github.com/zsh-users/zsh-autosuggestions.git",
                "https://github.com/zsh-users/zsh-syntax-highlighting.git",
            },
        )

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
        self.bootstrap.update_existing = True
        self.bootstrap.install_nvm = mock.Mock(return_value=True)
        self.bootstrap.configure_node_shells = mock.Mock(return_value=True)
        self.bootstrap.run_node_shell = mock.Mock(
            return_value=subprocess.CompletedProcess(["bash"], 0)
        )
        self.bootstrap.node_runtime_available = mock.Mock(return_value=True)
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
        self.assertNotIn("network", call.kwargs)
        self.assertEqual(call.kwargs["timeout"], 900)
        self.assertEqual(self.bootstrap.failures, [])

    def test_healthy_node_environment_skips_all_network_updates(self):
        self.bootstrap.install_nvm = mock.Mock(return_value=True)
        self.bootstrap.configure_node_shells = mock.Mock(return_value=True)
        self.bootstrap.node_environment_available = mock.Mock(return_value=True)
        self.bootstrap.run_node_shell = mock.Mock()

        self.bootstrap.install_node_environment()

        self.bootstrap.run_node_shell.assert_not_called()
        self.assertEqual(self.bootstrap.failures, [])

    def test_partial_node_environment_repairs_corepack_without_reinstalling_node(self):
        self.bootstrap.install_nvm = mock.Mock(return_value=True)
        self.bootstrap.configure_node_shells = mock.Mock(return_value=True)
        self.bootstrap.node_environment_available = mock.Mock(side_effect=[False, True])
        self.bootstrap.node_runtime_available = mock.Mock(return_value=True)
        self.bootstrap.run_node_shell = mock.Mock(
            return_value=subprocess.CompletedProcess(["bash"], 0)
        )

        self.bootstrap.install_node_environment()

        commands = self.bootstrap.run_node_shell.call_args.args[0]
        self.assertIn("nvm use --silent default", commands)
        self.assertNotIn("nvm install --lts", commands)
        self.assertIn("npm install --global corepack@latest", commands)
        self.assertIn("corepack install --global pnpm@latest", commands)
        self.assertIn("corepack install --global yarn@stable", commands)
        self.assertEqual(self.bootstrap.failures, [])

    def test_node_shell_uses_short_nvm_lock_wait_and_stale_lock_recovery(self):
        self.bootstrap.run = mock.Mock(
            return_value=subprocess.CompletedProcess(["bash"], 0)
        )

        self.bootstrap.run_node_shell("nvm install --lts")

        environment = self.bootstrap.run.call_args.kwargs["env"]
        self.assertEqual(environment["NVM_INSTALL_LOCK_TIMEOUT"], "20")
        self.assertEqual(environment["NVM_INSTALL_LOCK_STALE"], "10")

    def test_node_probe_is_reused_within_one_installer_run(self):
        with tempfile.TemporaryDirectory() as directory:
            nvm_dir = Path(directory) / "nvm"
            nvm_dir.mkdir()
            (nvm_dir / "nvm.sh").touch()
            result = subprocess.CompletedProcess(
                ["bash"], 0,
                stdout="nvm 0.40.7\nnode v24\nnpm 11\ncorepack 1\npnpm 10\nyarn 4\n",
                stderr="",
            )
            self.bootstrap.run_node_shell = mock.Mock(return_value=result)
            with mock.patch.object(MODULE, "NVM_DIR", nvm_dir):
                self.assertTrue(self.bootstrap.node_environment_available())
                self.assertTrue(self.bootstrap.node_environment_available())

        self.bootstrap.run_node_shell.assert_called_once()

    def test_nvm_installer_creates_custom_directory_before_running(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            nvm_dir = root / "tools" / "nvm"
            installer = root / "install-nvm.sh"
            installer.touch()
            self.bootstrap.nvm_version = mock.Mock(side_effect=[None, MODULE.NVM_VERSION])
            self.bootstrap.download_installer = mock.Mock(return_value=installer)
            self.bootstrap.run = mock.Mock(
                return_value=subprocess.CompletedProcess(["bash"], 0)
            )
            with mock.patch.object(MODULE, "NVM_DIR", nvm_dir):
                self.assertTrue(self.bootstrap.install_nvm())

            self.assertTrue(nvm_dir.is_dir())
            call = self.bootstrap.run.call_args
            self.assertEqual(call.kwargs["env"]["NVM_DIR"], str(nvm_dir))
            self.assertEqual(call.kwargs["env"]["PROFILE"], "/dev/null")

    def test_existing_rustup_updates_stable_and_standard_components(self):
        self.bootstrap.update_existing = True
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
            self.assertTrue(
                all("network" not in call.kwargs for call in self.bootstrap.run.call_args_list)
            )
            self.assertEqual(self.bootstrap.failures, [])

    def test_existing_rust_runtime_repairs_components_without_updating_toolchain(self):
        with tempfile.TemporaryDirectory() as directory:
            cargo_home = Path(directory) / ".cargo"
            rustup = cargo_home / "bin" / "rustup"
            rustup.parent.mkdir(parents=True)
            rustup.touch()
            self.bootstrap.configure_rust_shells = mock.Mock(return_value=True)
            self.bootstrap.rust_environment_available = mock.Mock(side_effect=[False, True])
            self.bootstrap.rust_runtime_available = mock.Mock(return_value=True)
            self.bootstrap.run = mock.Mock(
                return_value=subprocess.CompletedProcess(["rustup"], 0)
            )

            with mock.patch.object(MODULE, "CARGO_HOME", cargo_home):
                self.bootstrap.install_rust_environment()

            commands = [call.args[0] for call in self.bootstrap.run.call_args_list]
            self.assertEqual(
                commands,
                [[
                    str(rustup), "component", "add", "--toolchain", "stable",
                    "rustfmt", "clippy",
                ]],
            )
            self.assertEqual(self.bootstrap.failures, [])

    def test_fresh_rustup_install_skips_redundant_immediate_update(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cargo_home = root / ".cargo"
            rustup_home = root / ".rustup"
            installer = root / "rustup-init.sh"
            installer.touch()
            self.bootstrap.download_installer = mock.Mock(return_value=installer)
            self.bootstrap.run = mock.Mock(
                return_value=subprocess.CompletedProcess(["rustup-init"], 0)
            )
            self.bootstrap.configure_rust_shells = mock.Mock(return_value=True)
            self.bootstrap.rust_environment_available = mock.Mock(return_value=True)
            with (
                mock.patch.object(MODULE, "CARGO_HOME", cargo_home),
                mock.patch.object(MODULE, "RUSTUP_HOME", rustup_home),
            ):
                self.bootstrap.install_rust_environment()

            self.bootstrap.run.assert_called_once()
            command = self.bootstrap.run.call_args.args[0]
            self.assertEqual(command[:2], ["sh", str(installer)])
            self.assertNotIn("update", command)
            self.assertEqual(self.bootstrap.failures, [])

    def test_healthy_rust_environment_skips_all_network_updates(self):
        with tempfile.TemporaryDirectory() as directory:
            cargo_home = Path(directory) / ".cargo"
            rustup = cargo_home / "bin" / "rustup"
            rustup.parent.mkdir(parents=True)
            rustup.touch()
            self.bootstrap.configure_rust_shells = mock.Mock(return_value=True)
            self.bootstrap.rust_environment_available = mock.Mock(return_value=True)
            self.bootstrap.run = mock.Mock()
            with mock.patch.object(MODULE, "CARGO_HOME", cargo_home):
                self.bootstrap.install_rust_environment()

        self.bootstrap.run.assert_not_called()
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

    def test_uv_install_includes_r2pipe_and_matches_system_gdb_python(self):
        self.bootstrap.install_uv = mock.Mock(return_value=True)
        self.bootstrap.pwndbg_uv_packages_available = mock.Mock(
            side_effect=[False, True]
        )
        self.bootstrap.gdb_python_install_target = mock.Mock(
            return_value="/usr/bin/python3.13"
        )
        self.bootstrap.uv_executable = mock.Mock(return_value="/home/test/.local/bin/uv")
        self.bootstrap.find_command = mock.Mock(return_value=None)
        self.bootstrap.pwndbg_gdbinit_path = mock.Mock(return_value=None)
        self.bootstrap.run = mock.Mock(
            return_value=subprocess.CompletedProcess(["uv"], 0)
        )

        self.assertTrue(self.bootstrap.install_pwndbg_uv())

        command = self.bootstrap.run.call_args.args[0]
        self.assertEqual(command[:3], ["/home/test/.local/bin/uv", "tool", "install"])
        self.assertIn("--python", command)
        self.assertEqual(
            command[command.index("--python") + 1], "/usr/bin/python3.13"
        )
        self.assertIn("--with", command)
        self.assertEqual(
            command[command.index("--with") + 1],
            f"r2pipe=={MODULE.R2PIPE_VERSION}",
        )
        self.assertEqual(command[-1], MODULE.PWNDBG_UV_SPEC)
        self.assertNotIn("pwndbg-gdb", " ".join(command))
        self.assertTrue(self.bootstrap.run.call_args.kwargs["capture"])

    def test_healthy_uv_pwndbg_skips_network_install(self):
        self.bootstrap.install_uv = mock.Mock(return_value=True)
        self.bootstrap.pwndbg_uv_packages_available = mock.Mock(return_value=True)
        self.bootstrap.find_command = mock.Mock(return_value="/home/test/.local/bin/pwndbg")
        self.bootstrap.run = mock.Mock()

        self.assertTrue(self.bootstrap.install_pwndbg_uv())
        self.bootstrap.run.assert_not_called()

    def test_forced_uv_pwndbg_repair_reinstalls(self):
        self.bootstrap.install_uv = mock.Mock(return_value=True)
        self.bootstrap.pwndbg_uv_packages_available = mock.Mock(
            side_effect=[True, True]
        )
        self.bootstrap.gdb_python_install_target = mock.Mock(
            return_value="/usr/bin/python3.13"
        )
        self.bootstrap.uv_executable = mock.Mock(return_value="uv")
        self.bootstrap.pwndbg_gdbinit_path = mock.Mock(
            return_value=Path("/tool/pwndbg/share/pwndbg/gdbinit.py")
        )
        self.bootstrap.run = mock.Mock(
            return_value=subprocess.CompletedProcess(["uv"], 0)
        )

        self.assertTrue(self.bootstrap.install_pwndbg_uv(force=True))
        command = self.bootstrap.run.call_args.args[0]
        self.assertNotIn("--upgrade", command)
        self.assertIn("--reinstall", command)

    def test_broken_existing_uv_pwndbg_reinstalls_without_upgrading(self):
        with tempfile.TemporaryDirectory() as directory:
            gdbinit = Path(directory) / "gdbinit.py"
            gdbinit.touch()
            self.bootstrap.install_uv = mock.Mock(return_value=True)
            self.bootstrap.pwndbg_uv_packages_available = mock.Mock(
                side_effect=[False, True]
            )
            self.bootstrap.gdb_python_install_target = mock.Mock(
                return_value="/usr/bin/python3.13"
            )
            self.bootstrap.uv_executable = mock.Mock(return_value="uv")
            self.bootstrap.find_command = mock.Mock(return_value="pwndbg")
            self.bootstrap.pwndbg_gdbinit_path = mock.Mock(return_value=gdbinit)
            self.bootstrap.run = mock.Mock(
                return_value=subprocess.CompletedProcess(["uv"], 0)
            )

            self.assertTrue(self.bootstrap.install_pwndbg_uv())

        command = self.bootstrap.run.call_args.args[0]
        self.assertIn("--reinstall", command)
        self.assertNotIn("--upgrade", command)

    def test_gdb_python_abi_is_detected_once(self):
        self.bootstrap.run = mock.Mock(
            return_value=subprocess.CompletedProcess(
                ["gdb"], 0,
                stdout="warning\n3.13\tlibpython3.13.so.1.0\n",
                stderr="",
            )
        )

        expected = ("3.13", "libpython3.13.so.1.0")
        self.assertEqual(self.bootstrap.gdb_python_abi(), expected)
        self.assertEqual(self.bootstrap.gdb_python_abi(), expected)
        self.bootstrap.run.assert_called_once()

    def test_gdb_python_target_prefers_matching_system_interpreter(self):
        self.bootstrap.gdb_python_abi = mock.Mock(
            return_value=("3.13", "libpython3.13.so.1.0")
        )
        self.bootstrap.run = mock.Mock(
            return_value=subprocess.CompletedProcess(
                ["python3.13"], 0,
                stdout="3.13\tlibpython3.13.so.1.0\n",
                stderr="",
            )
        )
        with (
            mock.patch.object(MODULE.Path, "is_file", return_value=True),
            mock.patch.object(MODULE.os, "access", return_value=True),
            mock.patch.object(MODULE.shutil, "which", return_value=None),
        ):
            self.assertEqual(
                self.bootstrap.gdb_python_install_target(),
                "/usr/bin/python3.13",
            )

    def test_gdb_python_target_falls_back_to_version_on_abi_mismatch(self):
        self.bootstrap.gdb_python_abi = mock.Mock(
            return_value=("3.13", "libpython3.13.so.1.0")
        )
        self.bootstrap.run = mock.Mock(
            return_value=subprocess.CompletedProcess(
                ["python3.13"], 0,
                stdout="3.13\tlibpython3.13-custom.so\n",
                stderr="",
            )
        )
        with (
            mock.patch.object(MODULE.Path, "is_file", return_value=True),
            mock.patch.object(MODULE.os, "access", return_value=True),
            mock.patch.object(MODULE.shutil, "which", return_value=None),
        ):
            self.assertEqual(self.bootstrap.gdb_python_install_target(), "3.13")

    def test_pwndbg_uv_package_probe_uses_tool_python_and_imports_r2pipe(self):
        with tempfile.TemporaryDirectory() as directory:
            tool = Path(directory) / "pwndbg"
            gdbinit = tool / "share" / "pwndbg" / "gdbinit.py"
            python = tool / "bin" / "python"
            gdbinit.parent.mkdir(parents=True)
            python.parent.mkdir(parents=True)
            gdbinit.touch()
            python.touch(mode=0o755)
            self.bootstrap.uv_tool_dir = mock.Mock(return_value=Path(directory))
            self.bootstrap.run = mock.Mock(
                return_value=subprocess.CompletedProcess(
                    [str(python)],
                    0,
                    stdout=(
                        f"INIT_PWNDBG_VERSION={MODULE.PWNDBG_VERSION}\n"
                        f"INIT_R2PIPE_OK={MODULE.R2PIPE_VERSION}\n"
                    ),
                    stderr="",
                )
            )
            self.assertTrue(self.bootstrap.pwndbg_uv_packages_available())
            self.assertTrue(self.bootstrap.pwndbg_uv_packages_available())

        self.bootstrap.run.assert_called_once()
        command = self.bootstrap.run.call_args.args[0]
        self.assertEqual(command[0], str(python))
        self.assertNotIn("gdb", command)
        self.assertTrue(any("import r2pipe" in argument for argument in command))

    def test_pwndbg_system_gdb_configuration_is_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            tool_init = root / "tools" / "pwndbg" / "share" / "pwndbg" / "gdbinit.py"
            tool_init.parent.mkdir(parents=True)
            tool_init.touch()
            bridge = root / "share" / "r2ghidra.py"
            gdbinit = root / ".gdbinit"
            gdbinit.write_text("set height 0\n", encoding="utf-8")
            self.bootstrap.pwndbg_gdbinit_path = mock.Mock(return_value=tool_init)
            with (
                mock.patch.object(MODULE, "PWNDBG_BRIDGE_SCRIPT", bridge),
                mock.patch.object(MODULE, "GDBINIT", gdbinit),
            ):
                self.assertTrue(self.bootstrap.configure_pwndbg_system_gdb())
                first = gdbinit.read_text(encoding="utf-8")
                self.assertTrue(self.bootstrap.configure_pwndbg_system_gdb())
                second = gdbinit.read_text(encoding="utf-8")
                self.assertTrue(self.bootstrap.pwndbg_system_gdb_configured())

            self.assertEqual(first, second)
            self.assertIn("set height 0", second)
            self.assertEqual(second.count(MODULE.PWNDBG_GDBINIT_BEGIN), 1)
            self.assertIn(f"source {tool_init}", second)
            self.assertIn("set debuginfod enabled on", second)
            self.assertIn("set disassembly-flavor intel", second)
            bridge_text = bridge.read_text(encoding="utf-8")
            self.assertIn("import r2pipe as _INIT_R2PIPE", bridge_text)
            self.assertIn('super().__init__("ghidra"', bridge_text)
            self.assertIn('gdb.execute(f"r2pipe pdg @', bridge_text)
            self.assertIn("_init_decompile_with_external_r2", bridge_text)
            self.assertNotIn("spec_from_file_location", bridge_text)
            self.assertNotIn("shell=True", bridge_text)

    def test_legacy_portable_cleanup_removes_only_managed_artifacts(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            home = root / "home"
            user_portable = home / ".local" / "lib" / "pwndbg-gdb"
            portable_binary = user_portable / "bin" / "pwndbg"
            portable_binary.parent.mkdir(parents=True)
            portable_binary.touch()
            user_command = home / ".local" / "bin" / "pwndbg"
            user_command.parent.mkdir(parents=True)
            user_command.symlink_to(portable_binary)
            legacy_python = home / ".local" / "share" / "pwndbg-python"
            legacy_python.mkdir(parents=True)
            bashrc = home / ".bashrc"
            zshrc = home / ".zshrc"
            gdbinit = home / ".gdbinit"
            shell_text = (
                "keep-shell\n"
                f"{MODULE.PWNDBG_LEGACY_PROFILE_BEGIN}\nold\n"
                f"{MODULE.PWNDBG_LEGACY_PROFILE_END}\n"
            )
            bashrc.write_text(shell_text, encoding="utf-8")
            zshrc.write_text(shell_text, encoding="utf-8")
            gdbinit.write_text(
                "keep-gdb\n"
                f"{MODULE.PWNDBG_LEGACY_GDBINIT_BEGIN}\nold\n"
                f"{MODULE.PWNDBG_LEGACY_GDBINIT_END}\n",
                encoding="utf-8",
            )
            with (
                mock.patch.object(MODULE, "HOME", home),
                mock.patch.object(MODULE, "BASHRC", bashrc),
                mock.patch.object(MODULE, "ZSHRC", zshrc),
                mock.patch.object(MODULE, "GDBINIT", gdbinit),
                mock.patch.object(MODULE, "PWNDBG_PORTABLE_USER_DIR", user_portable),
                mock.patch.object(MODULE, "PWNDBG_PORTABLE_SYSTEM_DIR", root / "system"),
                mock.patch.object(MODULE, "PWNDBG_PORTABLE_COMMANDS", (user_command,)),
                mock.patch.object(MODULE, "PWNDBG_LEGACY_PYTHON_DIR", legacy_python),
                mock.patch.object(MODULE, "PWNDBG_LEGACY_CTF_COMMAND", root / "pwndbg-ctf"),
            ):
                self.bootstrap.remove_legacy_pwndbg_portable()
                self.bootstrap.remove_legacy_pwndbg_portable()

            self.assertFalse(user_portable.exists())
            self.assertFalse(user_command.exists())
            self.assertFalse(legacy_python.exists())
            self.assertIn("keep-shell", bashrc.read_text(encoding="utf-8"))
            self.assertIn("keep-gdb", gdbinit.read_text(encoding="utf-8"))
            self.assertNotIn("init pwndbg bridge", bashrc.read_text(encoding="utf-8"))
            self.assertNotIn("init r2ghidra bridge", gdbinit.read_text(encoding="utf-8"))

    def test_pwndbg_backend_probe_uses_system_gdb_and_is_cached(self):
        self.bootstrap.pwndbg_uv_packages_available = mock.Mock(return_value=True)
        self.bootstrap.pwndbg_system_gdb_configured = mock.Mock(return_value=True)
        self.bootstrap.run = mock.Mock(
            return_value=subprocess.CompletedProcess(
                ["gdb"],
                0,
                stdout="INIT_PWNDBG_OK\nINIT_R2PIPE_OK\n",
                stderr="",
            )
        )

        self.assertTrue(self.bootstrap.pwndbg_backend_available())
        self.assertTrue(self.bootstrap.pwndbg_backend_available())
        self.bootstrap.run.assert_called_once()
        command = self.bootstrap.run.call_args.args[0]
        self.assertEqual(command[0], "gdb")
        self.assertTrue(any("INIT_PWNDBG_OK" in argument for argument in command))

    def test_pwndbg_backend_reuses_real_integration_probe(self):
        self.bootstrap._pwndbg_probe_cache = subprocess.CompletedProcess(
            ["gdb"], 0,
            stdout="INIT_PWNDBG_OK\nINIT_R2PIPE_OK=/tool/r2pipe.py\n",
            stderr="",
        )
        self.bootstrap.run = mock.Mock()

        self.assertTrue(self.bootstrap.pwndbg_backend_available())
        self.bootstrap.run.assert_not_called()

    def test_pwndbg_environment_verifies_after_configuration(self):
        self.bootstrap.remove_legacy_pwndbg_portable = mock.Mock()
        self.bootstrap.install_pwndbg_uv = mock.Mock(return_value=True)
        self.bootstrap.configure_pwndbg_system_gdb = mock.Mock(return_value=True)
        self.bootstrap.pwndbg_r2ghidra_probe = mock.Mock(
            return_value=subprocess.CompletedProcess(
                ["gdb"],
                0,
                stdout=(
                    "INIT_PWNDBG_OK\n"
                    "INIT_R2PIPE_OK=/tool/r2pipe/__init__.py\n"
                    "Decompile an address with Pwndbg\n"
                    "INIT_GHIDRA_OK=pwndbg-r2pipe\n"
                ),
                stderr="",
            )
        )

        self.bootstrap.install_pwndbg_environment()
        self.bootstrap.remove_legacy_pwndbg_portable.assert_called_once_with()
        self.bootstrap.install_pwndbg_uv.assert_called_once_with()
        self.bootstrap.configure_pwndbg_system_gdb.assert_called_once_with()
        self.assertEqual(self.bootstrap.failures, [])

    def test_pwndbg_environment_repairs_uv_tool_once_when_native_r2pipe_fails(self):
        self.bootstrap.remove_legacy_pwndbg_portable = mock.Mock()
        self.bootstrap.install_pwndbg_uv = mock.Mock(return_value=True)
        self.bootstrap.configure_pwndbg_system_gdb = mock.Mock(return_value=True)
        self.bootstrap.pwndbg_r2ghidra_probe = mock.Mock(
            side_effect=[
                subprocess.CompletedProcess(
                    ["gdb"], 0,
                    stdout="INIT_PWNDBG_OK\nINIT_GHIDRA_OK=external-r2\n",
                    stderr="Could not import r2pipe\n",
                ),
                subprocess.CompletedProcess(
                    ["gdb"], 0,
                    stdout=(
                        "INIT_PWNDBG_OK\nINIT_R2PIPE_OK=/tool/r2pipe.py\n"
                        "Decompile an address with Pwndbg\n"
                        "INIT_GHIDRA_OK=pwndbg-r2pipe\n"
                    ),
                    stderr="",
                ),
            ]
        )

        self.bootstrap.install_pwndbg_environment()
        self.assertEqual(
            self.bootstrap.install_pwndbg_uv.call_args_list,
            [mock.call(), mock.call(force=True)],
        )
        self.assertEqual(self.bootstrap.pwndbg_r2ghidra_probe.call_count, 2)
        self.assertEqual(self.bootstrap.failures, [])

    def test_external_ghidra_fallback_does_not_mask_broken_native_r2pipe(self):
        self.bootstrap.pwndbg_r2ghidra_probe = mock.Mock(
            return_value=subprocess.CompletedProcess(
                ["gdb"], 0,
                stdout="INIT_PWNDBG_OK\nINIT_GHIDRA_OK=external-r2\n",
                stderr="Could not import r2pipe\n",
            )
        )
        self.assertFalse(self.bootstrap.pwndbg_r2ghidra_available())

    def test_pwndbg_integration_probe_uses_system_gdb_and_real_decompiler(self):
        self.bootstrap.pwndbg_uv_packages_available = mock.Mock(return_value=True)
        self.bootstrap.run = mock.Mock(
            side_effect=[
                subprocess.CompletedProcess(["gcc"], 0, stdout="", stderr=""),
                subprocess.CompletedProcess(
                    ["gdb"], 0,
                    stdout=(
                        "INIT_PWNDBG_OK\n"
                        "INIT_R2PIPE_OK=/tool/r2pipe.py\n"
                        "Decompile an address with Pwndbg, radare2 and r2ghidra.\n"
                        "int main(void) { return twice(21); }\n"
                        "INIT_GHIDRA_OK=pwndbg-r2pipe\n"
                    ),
                    stderr="",
                ),
            ]
        )

        self.assertTrue(self.bootstrap.pwndbg_r2ghidra_available())
        command = self.bootstrap.run.call_args_list[1].args[0]
        self.assertEqual(command[0], "gdb")
        self.assertNotIn("-nx", command)
        self.assertTrue(any("INIT_PWNDBG_OK" in argument for argument in command))
        self.assertTrue(any("INIT_R2PIPE_OK=" in argument for argument in command))
        self.assertIn("help ghidra", command)
        self.assertIn("break main", command)
        self.assertIn("ghidra &main", command)
        self.assertEqual(
            self.bootstrap.run.call_args_list[1].kwargs["env"],
            {"INIT_GHIDRA_PROBE": "1"},
        )

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
            self.bootstrap.glibc_aio_runtime_available = mock.Mock(
                side_effect=[False, True]
            )
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

    def test_glibc_missing_index_does_not_reinstall_healthy_python_package(self):
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "glibc-all-in-one"
            command_path = Path(directory) / "bin" / "glibc-aio"
            destination.mkdir()
            (destination / "pyproject.toml").touch()
            self.bootstrap.glibc_aio_runtime_available = mock.Mock(return_value=True)
            self.bootstrap.glibc_aio_index_available = mock.Mock(
                side_effect=[False, True]
            )
            self.bootstrap.install_command_wrapper = mock.Mock()
            self.bootstrap.run = mock.Mock(
                return_value=subprocess.CompletedProcess(["glibc-aio"], 0)
            )

            with (
                mock.patch.object(MODULE, "GLIBC_AIO_DIR", destination),
                mock.patch.object(MODULE, "GLIBC_AIO_COMMAND", command_path),
            ):
                self.bootstrap.install_glibc_all_in_one()

            self.bootstrap.run.assert_called_once_with(
                [str(command_path), "mirror", "update"],
                cwd=MODULE.HOME,
                check=False,
                network=True,
                timeout=300,
            )
            self.bootstrap.install_command_wrapper.assert_not_called()
            self.assertEqual(self.bootstrap.failures, [])

    def test_glibc_all_in_one_v2_repairs_package_even_when_index_is_ready(self):
        self.bootstrap.update_existing = True
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

    def test_unchanged_executable_wrapper_skips_reinstallation(self):
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "wrapper"
            content = "#!/bin/sh\nexec true\n"
            destination.write_text(content, encoding="utf-8")
            destination.chmod(0o755)
            self.bootstrap.run = mock.Mock()

            self.assertTrue(self.bootstrap.install_command_wrapper(destination, content))

        self.bootstrap.run.assert_not_called()

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

    def test_ctf_toolchain_installs_uv_pwndbg_after_r2ghidra(self):
        names = [
            "install_python2_legacy", "install_python_tools", "install_ruby_tools",
            "install_node_environment", "install_rust_environment",
            "install_radare2", "install_r2ghidra", "install_pwndbg_environment",
            "install_helper_repositories",
        ]
        calls = []
        for name in names:
            def record(*_args, _name=name, **_kwargs):
                calls.append(_name)
                return True if _name == "install_radare2" else None
            setattr(
                self.bootstrap,
                name,
                mock.Mock(side_effect=record),
            )
        self.bootstrap.install_ctf_toolchain()
        self.assertLess(calls.index("install_node_environment"), calls.index("install_radare2"))
        self.assertLess(calls.index("install_rust_environment"), calls.index("install_radare2"))
        self.assertLess(calls.index("install_r2ghidra"), calls.index("install_pwndbg_environment"))
        self.assertLess(calls.index("install_pwndbg_environment"), calls.index("install_helper_repositories"))


if __name__ == "__main__":
    unittest.main()
