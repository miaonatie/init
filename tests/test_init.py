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

    def test_r2pipe_forced_repair_reinstalls_even_when_probe_was_healthy(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "pwndbg-python"
            self.bootstrap.r2pipe_target_available = mock.Mock(return_value=True)
            self.bootstrap.run = mock.Mock(
                return_value=subprocess.CompletedProcess(["python3", "-m", "pip"], 0)
            )

            with mock.patch.object(MODULE, "PWNDBG_PYTHON_DIR", target):
                self.assertTrue(self.bootstrap.install_r2pipe_for_pwndbg(force=True))

        command = self.bootstrap.run.call_args.args[0]
        self.assertIn("--force-reinstall", command)

    def test_r2pipe_health_probe_is_cached_within_one_run(self):
        self.bootstrap.run = mock.Mock(
            return_value=subprocess.CompletedProcess(
                ["python3"], 0, stdout="/target/r2pipe/__init__.py\n", stderr=""
            )
        )

        self.assertTrue(self.bootstrap.r2pipe_target_available())
        self.assertTrue(self.bootstrap.r2pipe_target_available())

        self.bootstrap.run.assert_called_once()

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
            self.assertIn("importlib.invalidate_caches()", bridge)
            self.assertIn("spec_from_file_location", bridge)
            self.assertIn('sys.modules["r2pipe"] = module', bridge)
            self.assertIn("_init_r2pipe_checked", bridge)
            self.assertIn("r2pipe.py", bridge)
            self.assertIn('super().__init__("ghidra"', bridge)
            self.assertIn('gdb.execute(f"r2pipe pdg @', bridge)
            self.assertIn("_init_decompile_with_external_r2", bridge)
            self.assertIn('f"aaa; s {address:#x}; af; pdg"', bridge)
            self.assertIn('command.extend(["-B", hex(base)])', bridge)
            self.assertNotIn("shell=True", bridge)

    def test_pwndbg_bridge_can_load_r2pipe_by_exact_package_path(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "pwndbg-python"
            package = target / "r2pipe"
            package.mkdir(parents=True)
            (package / "__init__.py").write_text(
                "from .open_sync import marker\n", encoding="utf-8"
            )
            (package / "open_sync.py").write_text(
                "marker = 'exact-path-ok'\n", encoding="utf-8"
            )

            class FakeGdbError(Exception):
                pass

            class FakeCommand:
                def __init__(self, *_args, **_kwargs):
                    pass

            fake_gdb = mock.Mock()
            fake_gdb.Command = FakeCommand
            fake_gdb.COMMAND_USER = 0
            fake_gdb.TYPE_CODE_FUNC = 1
            fake_gdb.error = FakeGdbError
            fake_gdb.execute.side_effect = FakeGdbError("not registered")
            fake_gdb._init_r2pipe_checked = False
            fake_gdb._init_r2pipe_module = None

            old_path = list(sys.path)
            with (
                mock.patch.object(MODULE, "PWNDBG_PYTHON_DIR", target),
                mock.patch.dict(sys.modules, {"gdb": fake_gdb}, clear=False),
                mock.patch("importlib.import_module", side_effect=ModuleNotFoundError("isolated")),
            ):
                sys.modules.pop("r2pipe", None)
                sys.modules.pop("r2pipe.open_sync", None)
                namespace = {}
                exec(MODULE.Bootstrap.pwndbg_bridge_source(), namespace)
                self.assertEqual(namespace["_INIT_R2PIPE"].marker, "exact-path-ok")
            sys.path[:] = old_path
            sys.modules.pop("r2pipe", None)
            sys.modules.pop("r2pipe.open_sync", None)

    def test_healthy_pwndbg_backend_skips_remote_installer(self):
        self.bootstrap.pwndbg_backend_available = mock.Mock(return_value=True)
        self.bootstrap.download_installer = mock.Mock()

        self.bootstrap.install_remote_tool("pwndbg", ["pwndbg", "pwndbg-gdb"])

        self.bootstrap.download_installer.assert_not_called()
        self.assertEqual(self.bootstrap.failures, [])

    def test_broken_existing_pwndbg_backend_is_reinstalled_and_rechecked(self):
        with tempfile.TemporaryDirectory() as directory:
            installer = Path(directory) / "pwndbg-install.sh"
            installer.touch()
            self.bootstrap.pwndbg_backend_available = mock.Mock(
                side_effect=[False, True]
            )
            self.bootstrap.download_installer = mock.Mock(return_value=installer)
            self.bootstrap.run = mock.Mock(
                return_value=subprocess.CompletedProcess(["bash"], 0)
            )

            self.bootstrap.install_remote_tool("pwndbg", ["pwndbg", "pwndbg-gdb"])

            command = self.bootstrap.run.call_args.args[0]
            self.assertEqual(command[:2], ["bash", str(installer)])
            self.assertEqual(self.bootstrap.failures, [])

    def test_pwndbg_backend_probe_starts_python_and_is_cached(self):
        self.bootstrap.find_command = mock.Mock(return_value="/usr/local/bin/pwndbg")
        self.bootstrap.run = mock.Mock(
            return_value=subprocess.CompletedProcess(
                ["pwndbg"], 0, stdout="INIT_PWNDBG_OK\n", stderr=""
            )
        )

        self.assertTrue(self.bootstrap.pwndbg_backend_available(["pwndbg", "pwndbg-gdb"]))
        self.assertTrue(self.bootstrap.pwndbg_backend_available(["pwndbg", "pwndbg-gdb"]))

        self.bootstrap.run.assert_called_once()
        command = self.bootstrap.run.call_args.args[0]
        self.assertTrue(any("INIT_PWNDBG_OK" in argument for argument in command))

    def test_pwndbg_bridge_install_verifies_after_configuration(self):
        self.bootstrap.install_r2pipe_for_pwndbg = mock.Mock(return_value=True)
        self.bootstrap.configure_pwndbg_r2ghidra = mock.Mock(return_value=True)
        self.bootstrap.configure_pwndbg_launcher = mock.Mock(return_value=True)
        self.bootstrap.pwndbg_r2ghidra_probe = mock.Mock(
            return_value=subprocess.CompletedProcess(
                ["pwndbg-ctf"],
                0,
                stdout=(
                    "INIT_R2PIPE_OK=/home/test/.local/share/pwndbg-python/r2pipe/__init__.py\n"
                    "Decompile an address with Pwndbg\n"
                    "int main(void) { return twice(21); }\n"
                    "INIT_GHIDRA_OK=pwndbg-r2pipe\n"
                ),
                stderr="",
            )
        )
        self.bootstrap.install_pwndbg_r2ghidra_bridge()
        self.bootstrap.install_r2pipe_for_pwndbg.assert_called_once_with()
        self.bootstrap.configure_pwndbg_r2ghidra.assert_called_once_with()
        self.bootstrap.configure_pwndbg_launcher.assert_called_once_with()
        self.bootstrap.pwndbg_r2ghidra_probe.assert_called_once_with()
        self.assertEqual(self.bootstrap.failures, [])

    def test_pwndbg_bridge_repairs_native_r2pipe_once_when_only_fallback_works(self):
        self.bootstrap.install_r2pipe_for_pwndbg = mock.Mock(return_value=True)
        self.bootstrap.configure_pwndbg_r2ghidra = mock.Mock(return_value=True)
        self.bootstrap.configure_pwndbg_launcher = mock.Mock(return_value=True)
        self.bootstrap.pwndbg_r2ghidra_probe = mock.Mock(
            side_effect=[
                subprocess.CompletedProcess(
                    ["pwndbg-ctf"],
                    0,
                    stdout=(
                        "Decompile an address with Pwndbg\n"
                        "INIT_GHIDRA_OK=external-r2\n"
                    ),
                    stderr="Could not import r2pipe python library\n",
                ),
                subprocess.CompletedProcess(
                    ["pwndbg-ctf"],
                    0,
                    stdout=(
                        "INIT_R2PIPE_OK=/target/r2pipe/__init__.py\n"
                        "Decompile an address with Pwndbg\n"
                        "INIT_GHIDRA_OK=pwndbg-r2pipe\n"
                    ),
                    stderr="",
                ),
            ]
        )

        self.bootstrap.install_pwndbg_r2ghidra_bridge()

        self.assertEqual(
            self.bootstrap.install_r2pipe_for_pwndbg.call_args_list,
            [mock.call(), mock.call(force=True)],
        )
        self.assertEqual(self.bootstrap.pwndbg_r2ghidra_probe.call_count, 2)
        self.assertEqual(self.bootstrap.failures, [])

    def test_external_ghidra_fallback_does_not_mask_broken_native_r2pipe(self):
        self.bootstrap.pwndbg_r2ghidra_probe = mock.Mock(
            return_value=subprocess.CompletedProcess(
                ["pwndbg-ctf"],
                0,
                stdout=(
                    "Decompile an address with Pwndbg\n"
                    "INIT_GHIDRA_OK=external-r2\n"
                ),
                stderr="Could not import r2pipe python library\n",
            )
        )

        self.assertFalse(self.bootstrap.pwndbg_r2ghidra_available())

    def test_pwndbg_portable_launcher_is_idempotent_for_bash_and_zsh(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bashrc = root / ".bashrc"
            zshrc = root / ".zshrc"
            launcher = root / "bin" / "pwndbg-ctf"
            bridge = root / "r2ghidra.py"
            backend = "/usr/local/bin/pwndbg"
            self.bootstrap.find_command = mock.Mock(return_value=backend)
            self.bootstrap.install_command_wrapper = mock.Mock(return_value=True)
            with (
                mock.patch.object(MODULE, "BASHRC", bashrc),
                mock.patch.object(MODULE, "ZSHRC", zshrc),
                mock.patch.object(MODULE, "PWNDBG_CTF_COMMAND", launcher),
                mock.patch.object(MODULE, "PWNDBG_BRIDGE_SCRIPT", bridge),
                mock.patch.object(MODULE, "PWNDBG_PYTHON_DIR", root / "pwndbg-python"),
            ):
                self.assertTrue(self.bootstrap.configure_pwndbg_launcher())
                self.assertTrue(self.bootstrap.configure_pwndbg_launcher())

            source = self.bootstrap.install_command_wrapper.call_args.args[1]
            self.assertIn(backend, source)
            self.assertIn(f"-x {bridge}", source)
            self.assertNotIn("PYTHONPATH", source)
            for profile in (bashrc, zshrc):
                text = profile.read_text(encoding="utf-8")
                self.assertEqual(text.count(MODULE.PWNDBG_PROFILE_BEGIN), 1)
                self.assertEqual(text.count(MODULE.PWNDBG_PROFILE_END), 1)
                self.assertIn("pwndbg()", text)
                self.assertIn(str(launcher), text)

    def test_pwndbg_integration_probe_checks_import_command_and_decompiler(self):
        self.bootstrap.find_command = mock.Mock(return_value="/usr/local/bin/pwndbg")
        self.bootstrap.r2pipe_target_available = mock.Mock(return_value=True)
        self.bootstrap.run = mock.Mock(
            side_effect=[
                subprocess.CompletedProcess(["gcc"], 0, stdout="", stderr=""),
                subprocess.CompletedProcess(
                ["pwndbg"],
                0,
                stdout=(
                    "INIT_R2PIPE_OK=/home/test/.local/share/pwndbg-python/r2pipe/__init__.py\n"
                    "Decompile an address with Pwndbg, radare2 and r2ghidra.\n"
                    "int main(void) { return twice(21); }\n"
                    "INIT_GHIDRA_OK=pwndbg-r2pipe\n"
                ),
                stderr="",
                ),
            ]
        )
        with mock.patch.object(
            MODULE, "PWNDBG_CTF_COMMAND", Path("/nonexistent/pwndbg-ctf")
        ):
            self.assertTrue(self.bootstrap.pwndbg_r2ghidra_available())
        self.assertEqual(self.bootstrap.run.call_count, 2)
        command = self.bootstrap.run.call_args_list[1].args[0]
        self.assertIn("-x", command)
        self.assertIn(str(MODULE.PWNDBG_BRIDGE_SCRIPT), command)
        self.assertTrue(any("INIT_R2PIPE_OK=" in argument for argument in command))
        self.assertIn("help ghidra", command)
        self.assertIn("break main", command)
        self.assertIn("run", command)
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
