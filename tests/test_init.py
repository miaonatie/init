from contextlib import redirect_stdout
from io import StringIO
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import init


class StopBeforeShell(unittest.TestCase):
    """Shared installer harness: nothing here touches the host."""

    def run_install(self, **patch):
        """Run the default action with every effect stubbed; return the mocks."""
        effects = {
            "preflight": mock.MagicMock(),
            "installed_packages": mock.MagicMock(return_value=set()),
            "refresh_index": mock.MagicMock(return_value=set()),
            "install_packages": mock.MagicMock(side_effect=[{"python3"}, {"python3", "git"}]),
            "install_python_tools": mock.MagicMock(),
            "install_iot_assets": mock.MagicMock(),
            "verify_python": mock.MagicMock(return_value=True),
            "verify_python_cli": mock.MagicMock(return_value=True),
            "verify_tools": mock.MagicMock(return_value=True),
            "verify_iot": mock.MagicMock(return_value=True),
            "configure_shell_defaults": mock.MagicMock(),
        }
        effects.update(patch)
        patchers = [mock.patch.object(init, name, value) for name, value in effects.items()]
        for patcher in patchers:
            patcher.start()
            self.addCleanup(patcher.stop)
        self.output = StringIO()
        with redirect_stdout(self.output):
            self.code = init.main([])
        return effects


class InstallerTests(StopBeforeShell):
    def test_no_arguments_runs_four_stages_then_each_layer(self):
        effects = self.run_install()
        self.assertEqual(self.code, 0)
        effects["preflight"].assert_called_once_with()
        effects["install_python_tools"].assert_called_once()
        effects["install_iot_assets"].assert_called_once()
        effects["configure_shell_defaults"].assert_called_once()
        self.assertEqual([line for line in self.output.getvalue().splitlines() if line.startswith("[")], [
            "[1/4] Environment check", "[2/4] System foundation", "[3/4] Lab tools", "[4/4] Verification",
        ])

    def test_unknown_arguments_are_rejected_before_installing(self):
        with mock.patch.object(init, "install_packages") as install:
            for args in (["--system-python"], ["--check", "--iot"], ["extra"]):
                self.assertEqual(init.main(args), 2)
        install.assert_not_called()

    def test_help_is_read_only_and_documents_every_action(self):
        for args in (["-h"], ["--help"]):
            output = StringIO()
            with redirect_stdout(output):
                self.assertEqual(init.main(args), 0)
            for action in ("--check", "--check-python", "--iot", "--iot-check"):
                self.assertIn(action, output.getvalue())

    def test_check_verifies_every_layer_without_mutating_anything(self):
        effects = self.run_install()
        for name in ("refresh_index", "install_packages", "install_python_tools",
                     "install_iot_assets", "configure_shell_defaults"):
            effects[name].reset_mock()
        with redirect_stdout(StringIO()):
            self.assertEqual(init.main(["--check"]), 0)
        effects["verify_python"].assert_called()
        effects["verify_python_cli"].assert_called()
        effects["verify_tools"].assert_called()
        effects["verify_iot"].assert_called()
        for name in ("refresh_index", "install_packages", "install_python_tools",
                     "install_iot_assets", "configure_shell_defaults"):
            effects[name].assert_not_called()

    def test_check_reports_failure_when_a_layer_fails(self):
        effects = self.run_install()
        effects["verify_tools"].return_value = False
        output = StringIO()
        with redirect_stdout(output):
            self.assertEqual(init.main(["--check"]), 1)
        self.assertIn("[failed] Lab verification failed", output.getvalue())

    def test_check_python_only_imports_the_python_layer(self):
        installed = {"python3", "python3-pyelftools"}
        with mock.patch.object(init, "preflight"), \
                mock.patch.object(init, "installed_packages", return_value=installed), \
                mock.patch.object(init, "verify_python", side_effect=[True, False]) as verify, \
                mock.patch.object(init, "refresh_index") as refresh, \
                mock.patch.object(init, "install_packages") as install, \
                mock.patch.object(init, "verify_tools") as verify_tools, \
                mock.patch.object(init, "verify_iot") as verify_iot, \
                mock.patch.object(init, "configure_shell_defaults") as configure:
            self.assertEqual(init.main(["--check-python"]), 0)
            self.assertEqual(init.main(["--check-python"]), 1)
        self.assertEqual(verify.call_args_list, [mock.call(installed), mock.call(installed)])
        for operation in (refresh, install, verify_tools, verify_iot, configure):
            operation.assert_not_called()

    def test_failed_verification_keeps_shell_profiles_untouched(self):
        effects = self.run_install(verify_python=mock.MagicMock(return_value=False))
        self.assertEqual(self.code, 1)
        effects["configure_shell_defaults"].assert_not_called()
        self.assertIn("[failed] Lab verification failed", self.output.getvalue())

    def test_unexpected_os_error_is_reported_not_raised(self):
        effects = self.run_install()
        effects["install_packages"].side_effect = FileNotFoundError("apt-get vanished")
        output = StringIO()
        with redirect_stdout(output):
            self.assertEqual(init.main([]), 1)
        self.assertIn("[failed] Lab setup: apt-get vanished", output.getvalue())


class PythonLayerTests(unittest.TestCase):
    def test_python_layer_skips_uninstalled_optional_libraries(self):
        output = StringIO()
        with redirect_stdout(output), mock.patch.object(init, "check_command", return_value=True) as check:
            self.assertTrue(init.verify_python({"python3-pyelftools"}))
        labels = [call[0][0] for call in check.call_args_list]
        self.assertIn("import elftools", labels)
        self.assertFalse(any("zstandard" in label for label in labels))
        self.assertIn("[skipped] import zstandard (python3-zstandard is not installed)", output.getvalue())

    def test_pycryptodome_accepts_either_import_name(self):
        with mock.patch.object(init, "check_command", return_value=True) as check, \
                redirect_stdout(StringIO()):
            self.assertTrue(init.verify_python({"python3-pycryptodome"}))
        probes = [call for call in check.call_args_list if "Crypto" in call[0][0]]
        self.assertEqual(len(probes), 1)
        self.assertIn("Cryptodome", probes[0][0][1][-1])

    def test_pip_fallback_is_skipped_below_python_3_8(self):
        output = StringIO()
        with redirect_stdout(output), mock.patch.object(init, "cli_states", return_value={"ropper": "missing"}), \
                mock.patch.object(init, "python_version", return_value=(3, 6)), \
                mock.patch.object(init, "pip_install") as pip, \
                mock.patch.object(init, "install_pwn_wrappers") as wrappers:
            init.install_python_tools(["apt-get"])
        pip.assert_not_called()
        wrappers.assert_called_once()
        self.assertIn("[skipped] ropper (needs Python 3.8+", output.getvalue())

    def test_pip_fallback_runs_on_supported_python(self):
        with mock.patch.object(init, "cli_states", return_value={"ropper": "missing"}), \
                mock.patch.object(init, "python_version", return_value=(3, 12)), \
                mock.patch.object(init, "pip_install") as pip, \
                mock.patch.object(init, "install_pwn_wrappers"), redirect_stdout(StringIO()):
            init.install_python_tools(["apt-get"])
        self.assertEqual(pip.call_args[0][1], ["ropper"])

    def test_a_launcher_that_no_longer_runs_is_treated_as_missing(self):
        def run(command, **kwargs):
            return subprocess.CompletedProcess(command, 0 if command[0].endswith("/good") else 1)

        with mock.patch.object(init.shutil, "which", side_effect=lambda name, path=None:
                               "/usr/bin/" + name if name in ("good", "bad") else None), \
                mock.patch.object(init, "PYTHON_CLI", {"Good": ("good", ["--help"]),
                                                       "Bad": ("bad", ["--help"]),
                                                       "Gone": ("gone", ["--help"])}), \
                mock.patch.object(init.subprocess, "run", side_effect=run):
            self.assertEqual(init.cli_states(), {"Good": "ok", "Bad": "broken", "Gone": "missing"})
            self.assertEqual(init.broken_python_cli(), ["Bad"])
            self.assertEqual(sorted(init.missing_python_cli()), ["Bad", "Gone"])

    def test_broken_launcher_gets_a_forced_reinstall_without_dependencies(self):
        with mock.patch.object(init, "broken_python_cli", return_value=["ropper"]), \
                mock.patch.object(init, "externally_managed", return_value=False), \
                mock.patch.object(init.subprocess, "run",
                                  return_value=subprocess.CompletedProcess([], 0, "")) as run, \
                redirect_stdout(StringIO()):
            init.pip_install(["apt-get"], ["ropper"])
        command = run.call_args[0][0]
        self.assertIn("--force-reinstall", command)
        self.assertIn("--no-deps", command)

    def test_healthy_tool_is_not_force_reinstalled(self):
        with mock.patch.object(init, "broken_python_cli", return_value=[]), \
                mock.patch.object(init, "externally_managed", return_value=False), \
                mock.patch.object(init.subprocess, "run",
                                  return_value=subprocess.CompletedProcess([], 0, "")) as run, \
                redirect_stdout(StringIO()):
            init.pip_install(["apt-get"], ["pwntools"])
        self.assertNotIn("--force-reinstall", run.call_args[0][0])

    def test_pip_uses_pep668_flag_when_the_interpreter_is_externally_managed(self):
        with mock.patch.object(init, "externally_managed", return_value=True), \
                mock.patch.object(init, "broken_python_cli", return_value=[]), \
                mock.patch.object(init.subprocess, "run",
                                  return_value=subprocess.CompletedProcess([], 0, "")) as run:
            self.assertEqual(init.pip_install(["apt-get"], ["ropper"]), ["ropper"])
        command = run.call_args[0][0]
        self.assertIn("--break-system-packages", command)
        self.assertTrue(any("filebytes" in argument for argument in command))
        self.assertIn("ropper", command)

    def test_pip_leaves_out_the_pep668_flag_when_it_is_not_needed(self):
        with mock.patch.object(init, "externally_managed", return_value=False), \
                mock.patch.object(init, "broken_python_cli", return_value=[]), \
                mock.patch.object(init.subprocess, "run",
                                  return_value=subprocess.CompletedProcess([], 0, "")) as run:
            init.pip_install(["apt-get"], ["pwntools"])
        self.assertNotIn("--break-system-packages", run.call_args[0][0])

    def test_pip_failure_is_reported_without_hiding_other_tools(self):
        output = StringIO()
        failure = subprocess.CompletedProcess([], 1, "ERROR: no match\n")
        with redirect_stdout(output), mock.patch.object(init, "broken_python_cli", return_value=[]), \
                mock.patch.object(init, "PIP_ATTEMPTS", 1), \
                mock.patch.object(
                    init.subprocess, "run",
                    side_effect=[failure, subprocess.CompletedProcess([], 0, "")]):
            self.assertEqual(init.pip_install(["apt-get"], ["ropper", "pwntools"]), ["pwntools"])
        self.assertIn("[failed] pip install ropper: ERROR: no match", output.getvalue())

    def test_pip_failure_is_retried_once_before_reporting(self):
        output = StringIO()
        failure = subprocess.CompletedProcess([], 1, "Read timed out\n")
        success = subprocess.CompletedProcess([], 0, "")
        with redirect_stdout(output), mock.patch.object(init, "broken_python_cli", return_value=[]), \
                mock.patch.object(init.subprocess, "run", side_effect=[failure, success]) as run:
            self.assertEqual(init.pip_install(["apt-get"], ["ropper"]), ["ropper"])
        self.assertEqual(init.PIP_ATTEMPTS, 2)
        self.assertEqual(run.call_count, 2)
        self.assertIn("(retry 1)", output.getvalue())

    def test_pip_reports_the_last_error_after_exhausting_attempts(self):
        output = StringIO()
        failure = subprocess.CompletedProcess([], 1, "boom\n")
        with redirect_stdout(output), mock.patch.object(init, "broken_python_cli", return_value=[]), \
                mock.patch.object(init.subprocess, "run", return_value=failure) as run:
            self.assertEqual(init.pip_install(["apt-get"], ["ropper"]), [])
        self.assertEqual(run.call_count, init.PIP_ATTEMPTS)
        self.assertIn("[failed] pip install ropper: boom", output.getvalue())

    def test_pwn_wrappers_are_written_through_install_with_noterm(self):
        with mock.patch.object(init, "status"), \
                mock.patch.object(init, "write_root_file") as write, \
                mock.patch.object(init, "writes_noterm", return_value=False), \
                mock.patch.object(init.shutil, "which", side_effect=lambda name, path=None:
                                  "/usr/bin/pwn" if name == "pwn" else None):
            init.install_pwn_wrappers(["sudo", "apt-get"])
        written = {call[0][1].name: call for call in write.call_args_list}
        self.assertEqual(sorted(written), sorted((*init.PWN_SUBCOMMANDS, "pwn")))
        for name, call in written.items():
            self.assertEqual(call[0][0], ["sudo", "apt-get"])
            self.assertEqual(call[0][1].parent, Path("/usr/local/bin"))
            self.assertIn("PWNLIB_NOTERM=1", call[0][2])
            if name == "pwn":
                # The wrapper calls the library entry point, never itself.
                self.assertIn("pwnlib.commandline.main", call[0][2])
                self.assertNotIn("/usr/bin/pwn", call[0][2])

    def test_pwn_wrapper_is_not_rewritten_when_it_already_sets_noterm(self):
        with mock.patch.object(init, "status"), \
                mock.patch.object(init, "write_root_file") as write, \
                mock.patch.object(init, "writes_noterm", return_value=True), \
                mock.patch.object(init.shutil, "which", side_effect=lambda name, path=None:
                                  "/usr/local/bin/pwn" if name == "pwn" else None):
            init.install_pwn_wrappers(["apt-get"])
        self.assertEqual(len(write.call_args_list), len(init.PWN_SUBCOMMANDS))

    def test_writes_noterm_reads_the_launcher(self):
        with tempfile.TemporaryDirectory() as directory:
            launcher = Path(directory) / "pwn"
            launcher.write_text("#!/bin/sh\nexec /usr/bin/pwn \"$@\"\n", encoding="utf-8")
            self.assertFalse(init.writes_noterm(launcher))
            launcher.write_text("#!/bin/sh\nPWNLIB_NOTERM=1 exec /usr/bin/pwn \"$@\"\n", encoding="utf-8")
            self.assertTrue(init.writes_noterm(launcher))
            self.assertFalse(init.writes_noterm(Path(directory) / "missing"))

    def test_write_root_file_stages_through_install_not_a_redirect(self):
        with mock.patch.object(init.subprocess, "run") as run, \
                mock.patch.object(init, "status"):
            init.write_root_file(["sudo", "apt-get"], Path("/usr/local/bin/firmae"), "#!/bin/sh\nexit 0\n")
        command = run.call_args[0][0]
        self.assertEqual(command[:5], ["sudo", "install", "-D", "-m", "0755"])
        self.assertEqual(command[-1], "/usr/local/bin/firmae")
        self.assertEqual(Path(command[-2]).name, "firmae")
        self.assertTrue(Path(command[-2]).parent.name.startswith("init-cmd-"))
        run.assert_called_once_with(command, check=True)

    def test_wrappers_are_skipped_when_every_command_already_exists(self):
        with mock.patch.object(init, "write_root_file") as write, \
                mock.patch.object(init, "status"), \
                mock.patch.object(init, "writes_noterm", return_value=True), \
                mock.patch.object(init.shutil, "which", return_value="/usr/local/bin/exists"):
            init.install_pwn_wrappers(["apt-get"])
        write.assert_not_called()

    def test_verify_python_cli_requires_pwn_wrappers(self):
        output = StringIO()
        with redirect_stdout(output), \
                mock.patch.object(init.shutil, "which",
                                  side_effect=lambda name, path=None: "/usr/bin/pwn" if name == "pwn" else None), \
                mock.patch.object(init, "check_command", return_value=True):
            self.assertFalse(init.verify_python_cli())
        self.assertIn("wrapper missing", output.getvalue())

    def test_import_probe_accepts_any_alternative_name(self):
        probe = init.import_probe(("Crypto", "Cryptodome"))
        self.assertIn("'Crypto'", probe)
        self.assertIn("'Cryptodome'", probe)
        self.assertIn("sys.exit(0)", probe)


class PackageTests(unittest.TestCase):
    def test_existing_packages_need_no_apt_or_sudo(self):
        installed = "\n".join("installed\t" + package for package in init.PACKAGES)
        output = StringIO()
        with redirect_stdout(output), mock.patch.object(
                init.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, installed)) as run:
            packages = init.installed_packages()
            self.assertEqual(packages, set(init.PACKAGES))
            self.assertEqual(init.refresh_index(["apt-get"], packages), set())
            init.install_packages(init.FOUNDATION, ["apt-get"], packages, set())
            init.install_packages(init.LAB_TOOLS, ["apt-get"], packages, set())
        run.assert_called_once()
        self.assertEqual(run.call_args[0][0][0], "dpkg-query")
        # One status line per package in the two install layers.
        expected = sum(len(group_packages) for group_packages in
                       (*init.FOUNDATION.values(), *init.LAB_TOOLS.values()))
        self.assertEqual(output.getvalue().count("[installed]"), expected)
        self.assertIn("Binary inspection and debugging", output.getvalue())
        self.assertIn("Pwn and exploitation", output.getvalue())

    def test_python_ctf_tools_are_part_of_the_lab_layer(self):
        pwn_group = init.LAB_TOOLS["Pwn and exploitation"]
        for package in ("gdbserver", "socat", "netcat-openbsd", "python3-pwntools", "python3-ropgadget"):
            self.assertIn(package, pwn_group)
            self.assertIn(package, init.PACKAGES)

    def test_iot_packages_are_tracked_and_installed_by_the_iot_action(self):
        for package in init.IOT_PACKAGES:
            self.assertIn(package, init.PACKAGES)
        with mock.patch.object(init, "preflight"), \
                mock.patch.object(init, "installed_packages", return_value=set()), \
                mock.patch.object(init, "refresh_index") as refresh, \
                mock.patch.object(init, "install_packages", return_value=set()) as install, \
                mock.patch.object(init, "install_iot_assets") as assets, \
                mock.patch.object(init, "install_firmae") as firmae, \
                mock.patch.object(init, "verify_iot", return_value=True), \
                redirect_stdout(StringIO()):
            self.assertEqual(init.main(["--iot"]), 0)
        groups = install.call_args[0][0]
        self.assertIn("IoT download prerequisites", groups)
        self.assertIn("IoT firmware and emulation", groups)
        self.assertEqual(refresh.call_args[0][2], init.IOT_GROUPS)
        assets.assert_called_once()
        firmae.assert_called_once()

    def test_iot_prerequisites_cover_what_the_clone_needs(self):
        """--iot must work on a host that never ran a full install."""
        for tool in ("git", "curl", "ca-certificates"):
            self.assertIn(tool, init.IOT_PREREQUISITES)
            self.assertIn(tool, init.IOT_PACKAGES)
            self.assertIn(tool, init.PACKAGES)

    def test_iot_check_is_read_only(self):
        with mock.patch.object(init, "preflight"), \
                mock.patch.object(init, "installed_packages", return_value=set()), \
                mock.patch.object(init, "install_packages") as install, \
                mock.patch.object(init, "verify_iot", return_value=True) as verify, \
                redirect_stdout(StringIO()):
            self.assertEqual(init.main(["--iot-check"]), 0)
        install.assert_not_called()
        verify.assert_called_once()

    def test_iot_verification_reports_unbuilt_image_as_deferred(self):
        output = StringIO()
        with redirect_stdout(output), \
                mock.patch.object(init.shutil, "which", return_value="/usr/bin/tool"), \
                mock.patch.object(init, "IOT_PROBES", {"qemu-mipsel": ["--version"]}), \
                mock.patch.object(init, "check_command", return_value=True), \
                mock.patch.object(init, "firmae_ready", return_value=True), \
                mock.patch.object(init, "firmae_status", return_value=3):
            self.assertTrue(init.verify_iot())
        self.assertIn("[skipped] FirmAE image", output.getvalue())

    def test_iot_verification_fails_when_the_checkout_is_broken(self):
        output = StringIO()
        with redirect_stdout(output), \
                mock.patch.object(init.shutil, "which", return_value="/usr/bin/tool"), \
                mock.patch.object(init, "IOT_PROBES", {"qemu-mipsel": ["--version"]}), \
                mock.patch.object(init, "check_command", return_value=True), \
                mock.patch.object(init, "firmae_ready", return_value=True), \
                mock.patch.object(init, "firmae_status", return_value=1):
            self.assertFalse(init.verify_iot())
        self.assertIn("[failed] FirmAE source/image broken", output.getvalue())

    def test_iot_layer_is_skipped_entirely_on_hosts_without_it(self):
        output = StringIO()
        with redirect_stdout(output), mock.patch.object(init.shutil, "which", return_value=None):
            self.assertTrue(init.verify_iot())
        self.assertIn("[skipped] IoT layer (not installed; run --iot)", output.getvalue())

    def test_missing_packages_are_installed_with_apt_and_alias_is_reused(self):
        before = set(init.PACKAGES) - {"python3-pil", "gdb", "7zip", init.PYTHON_ALIAS}
        after_foundation = before | {"python3-pil"}
        after_lab = after_foundation | {"gdb", "p7zip-full"}
        available = {"python3-pil", "gdb", "p7zip-full"}
        apt = ["apt-get"]
        with redirect_stdout(StringIO()), \
                mock.patch.object(init, "installed_packages", side_effect=[after_foundation, after_lab]), \
                mock.patch.object(init, "available_packages", return_value=available), \
                mock.patch.object(init.os, "geteuid", return_value=0), \
                mock.patch.object(init.subprocess, "run") as run:
            candidates = init.refresh_index(apt, before)
            installed = init.install_packages(init.FOUNDATION, apt, before, candidates)
            self.assertEqual(init.install_packages(init.LAB_TOOLS, apt, installed, candidates), after_lab)
            run.assert_has_calls([
                mock.call([*apt, "-o", "APT::Update::Error-Mode=any", "update"], check=True),
                mock.call([*apt, "install", "-y", "--no-remove", "--no-install-recommends", "python3-pil"], check=True),
                mock.call([*apt, "install", "-y", "--no-remove", "--no-install-recommends", "gdb", "p7zip-full"], check=True),
            ])
        self.assertEqual(init.select_package("7zip", after_lab, set()), "p7zip-full")

    def test_installs_development_packages_when_legacy_npm_conflicts(self):
        groups = {"System language toolchains": ("nodejs", "npm", "libssl-dev")}
        output = StringIO()
        installed = {"nodejs", "libssl-dev"}
        with redirect_stdout(output), mock.patch.object(init, "installed_packages", return_value=installed), \
                mock.patch.object(init.subprocess, "run", side_effect=[
                    subprocess.CompletedProcess([], 100), subprocess.CompletedProcess([], 0),
                    subprocess.CompletedProcess([], 0),
                ]) as run:
            self.assertEqual(init.install_packages(groups, ["apt-get"], set(), installed | {"npm"}), installed)
        self.assertIn("[skipped] npm conflicts", output.getvalue())
        self.assertNotIn("npm", run.call_args[0][0])

        all_except_npm = set(init.PACKAGES) - {"npm"}
        with mock.patch.object(init, "available_packages", return_value={"npm"}), \
                mock.patch.object(init, "apt_installable", return_value=False), \
                mock.patch.object(init.subprocess, "run") as no_update:
            self.assertEqual(init.refresh_index(["apt-get"], all_except_npm), {"npm"})
        no_update.assert_not_called()

    def test_no_package_appears_twice_within_a_layer(self):
        """A shared IoT package may sit in two layers, but never twice in one."""
        for layer, groups in (("foundation", init.FOUNDATION), ("lab", init.LAB_TOOLS)):
            packages = [package for group_packages in groups.values() for package in group_packages]
            duplicates = {package for package in packages if packages.count(package) > 1}
            self.assertEqual(duplicates, set(), "{} repeats a package".format(layer))
        self.assertEqual(len(init.IOT_PACKAGES), len(set(init.IOT_PACKAGES)))

    def test_iot_shared_packages_are_also_in_the_lab_layer(self):
        lab = {package for group_packages in init.LAB_TOOLS.values() for package in group_packages}
        for package in init.IOT_SHARED:
            self.assertIn(package, lab)
            self.assertIn(package, init.PACKAGES)


class ShellProfileTests(unittest.TestCase):
    def test_cleanup_preserves_other_profile_bytes_and_is_repeatable(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            bashrc = home / ".bashrc"
            bashrc.write_bytes(
                b"# keep\r\n\r\n# >>> init Python tools >>>\r\n"
                b"ctf_env() { :; }\r\n# <<< init Python tools <<<\r\n"
                b"alias py=python\r\n"
            )
            for _ in range(2):
                init.configure_shell_defaults(home, set())
                self.assertEqual(bashrc.read_bytes(), b"# keep\r\n\r\nalias py=python\r\n")
                self.assertFalse((home / ".zshrc").exists())

    def test_system_node_and_rust_precede_old_toolchains_after_migration(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            for relative in ("system/bin", ".nvm/versions/node/v1/bin", ".cargo/bin"):
                (home / relative).mkdir(parents=True)
            nvm_bin = home / ".nvm/versions/node/v1/bin"
            for relative in ("system/bin/node", "system/bin/rustc", ".nvm/versions/node/v1/bin/node",
                             ".cargo/bin/rustc", ".cargo/bin/cargo-extra"):
                command = home / relative
                command.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
                command.chmod(0o755)
            (home / ".nvm/nvm.sh").write_text(
                'nvm() { :; }\n[ "$1" = --no-use ] || export PATH="$NVM_DIR/versions/node/v1/bin:$PATH"\n',
                encoding="utf-8"
            )
            profile = home / ".bashrc"
            profile.write_text(
                'export NVM_DIR="$HOME/.nvm"\n'
                '[ -s "$NVM_DIR/nvm.sh" ] && \\. "$NVM_DIR/nvm.sh"  # keep this\n'
                '[ -s "$NVM_DIR/nvm.sh" ] && . "$NVM_DIR/nvm.sh"\n'
                '# >>> init rustup >>>\n[ -f "$HOME/.cargo/env" ] && . "$HOME/.cargo/env"\n'
                '# <<< init rustup <<<\n', encoding="utf-8"
            )
            original = profile.read_bytes()
            init.configure_shell_defaults(home, {"nodejs", "rustc"})
            self.assertEqual(profile.read_bytes(), original)

            installed = {"nodejs", "npm", "rustc", "cargo"}
            init.configure_shell_defaults(home, installed)
            updated = profile.read_bytes()
            init.configure_shell_defaults(home, installed)
            self.assertEqual(profile.read_bytes(), updated)
            self.assertEqual(updated.count(b"--no-use"), 2)
            self.assertIn(b"--no-use  # keep this", updated)

            for shell in ("bash", "zsh"):
                executable = shutil.which(shell)
                if not executable:
                    continue
                result = subprocess.run(
                    [executable, "-c", '. "$HOME/.bashrc"; command -v node rustc cargo-extra nvm'],
                    env={**os.environ, "HOME": str(home), "NVM_BIN": str(nvm_bin),
                         "CARGO_HOME": str(home / ".cargo"),
                         "PATH": os.pathsep.join(map(str, (nvm_bin, home / ".cargo/bin", home / "system/bin",
                                                          "/usr/bin", "/bin")))},
                    stdout=subprocess.PIPE, universal_newlines=True, check=True,
                )
                self.assertEqual(result.stdout.splitlines(), [
                    str(home / "system/bin/node"), str(home / "system/bin/rustc"),
                    str(home / ".cargo/bin/cargo-extra"), "nvm",
                ])


if __name__ == "__main__":
    unittest.main()
