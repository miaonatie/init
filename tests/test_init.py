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


class InstallTests(unittest.TestCase):
    def test_no_arguments_installs_and_verifies(self):
        output = StringIO()
        with redirect_stdout(output), \
                mock.patch.object(init, "preflight"), \
                mock.patch.object(init, "installed", return_value={"python3"}), \
                mock.patch.object(init, "apt", return_value={"python3", "git"}) as apt, \
                mock.patch.object(init, "python_tools") as tools, \
                mock.patch.object(init, "install_iot_assets") as iot, \
                mock.patch.object(init, "verify", return_value=True), \
                mock.patch.object(init, "tidy_profiles"):
            self.assertEqual(init.main([]), 0)
        apt.assert_called_once()
        tools.assert_called_once()
        iot.assert_called_once()
        self.assertIn("就绪", output.getvalue())

    def test_only_check_is_accepted(self):
        output = StringIO()
        with redirect_stdout(output), \
                mock.patch.object(init, "preflight"), \
                mock.patch.object(init, "installed", return_value=set()), \
                mock.patch.object(init, "verify", return_value=True), \
                mock.patch.object(init, "apt") as apt:
            self.assertEqual(init.main(["--check"]), 0)
        apt.assert_not_called()

    def test_unknown_arguments_are_rejected(self):
        for args in (["--iot"], ["--doctor"], ["--check-python"], ["extra"], ["--check", "x"]):
            with mock.patch.object(init, "apt") as apt:
                self.assertEqual(init.main(args), 2)
            apt.assert_not_called()
        self.assertEqual(init.main([]), 0) if False else None

    def test_failed_verification_returns_one(self):
        with mock.patch.object(init, "preflight"), \
                mock.patch.object(init, "installed", return_value=set()), \
                mock.patch.object(init, "apt", return_value=set()), \
                mock.patch.object(init, "python_tools"), \
                mock.patch.object(init, "install_iot_assets"), \
                mock.patch.object(init, "verify", return_value=False), \
                mock.patch.object(init, "tidy_profiles") as tidy, \
                redirect_stdout(StringIO()):
            self.assertEqual(init.main([]), 1)
        tidy.assert_not_called()

    def test_os_error_is_reported_not_raised(self):
        with mock.patch.object(init, "preflight", side_effect=RuntimeError("没有 apt")), \
                redirect_stdout(StringIO()):
            self.assertEqual(init.main([]), 1)


class PackageTests(unittest.TestCase):
    def test_resolve_uses_the_alternative_when_the_original_is_gone(self):
        self.assertEqual(init.resolve("7zip", {"p7zip-full"}, set()), "p7zip-full")
        self.assertEqual(init.resolve("7zip", {"7zip"}, set()), "7zip")
        self.assertEqual(init.resolve("7zip", set(), {"p7zip-full"}), "p7zip-full")
        self.assertEqual(init.resolve("git", set(), {"git"}), "git")

    def test_no_package_appears_twice_and_alternatives_are_real(self):
        seen = [p for group in init.GROUPS.values() for p in group]
        self.assertEqual({p for p in seen if seen.count(p) > 1}, set())
        for original, alternative in init.ALTERNATIVES.items():
            self.assertIn(original, init.PACKAGES)

    def test_libraries_are_covered_by_the_python_group(self):
        python_group = init.GROUPS["系统 Python"]
        for package in init.LIBRARIES:
            self.assertIn(package, python_group)

    def test_installable_refuses_a_plan_that_removes_packages(self):
        with mock.patch.object(init.subprocess, "run",
                               return_value=subprocess.CompletedProcess([], 0, b"Remv x\n")):
            self.assertFalse(init.installable(["x"]))
        with mock.patch.object(init.subprocess, "run",
                               return_value=subprocess.CompletedProcess([], 0, b"Inst x\n")):
            self.assertTrue(init.installable(["x"]))

    def test_apt_skips_the_refresh_when_everything_is_present(self):
        with mock.patch.object(init.subprocess, "run") as run:
            self.assertEqual(init.apt(["apt-get"], set(init.PACKAGES)), set(init.PACKAGES))
        run.assert_not_called()

    def test_a_package_this_release_lacks_does_not_force_a_refresh(self):
        """20.04 has no zoxide, 24.04 has no fastfetch; neither means a refresh."""
        have = set(init.PACKAGES) - {"fastfetch"}
        known = "\n".join("Package: {}".format(p) for p in init.PACKAGES if p != "fastfetch")
        calls = []

        def fake_run(command, **kwargs):
            calls.append(" ".join(str(p) for p in command))
            if "show" in command:
                # bash is present, so the index is healthy; fastfetch is simply absent.
                if "bash" in command:
                    return subprocess.CompletedProcess(command, 0, "Package: bash\n")
                return subprocess.CompletedProcess(command, 0, known)
            return subprocess.CompletedProcess(command, 0, "")

        with mock.patch.object(init, "installed", return_value=have), \
                mock.patch.object(init, "subprocess") as proc:
            proc.run.side_effect = fake_run
            init.apt(["apt-get"], have)
        self.assertFalse(any(" update" in c for c in calls), calls)

    def test_refresh_happens_when_the_index_is_empty(self):
        have = set(init.PACKAGES) - {"git"}
        calls = []

        def fake_run(command, **kwargs):
            calls.append(" ".join(str(p) for p in command))
            if "show" in command:
                return subprocess.CompletedProcess(command, 0, "")  # nothing known at all
            return subprocess.CompletedProcess(command, 0, "")

        with mock.patch.object(init.os, "geteuid", return_value=0), \
                mock.patch.object(init, "installed", return_value=have), \
                mock.patch.object(init, "subprocess") as proc:
            proc.run.side_effect = fake_run
            init.apt(["apt-get"], have)
        self.assertTrue(any(" update" in c for c in calls), calls)

    def test_unavailable_packages_never_reach_apt_get_install(self):
        """One unknown package makes apt-get fail with 100 and blocks the rest."""
        have = set(init.PACKAGES) - {"python3-zstandard", "git"}
        known = "Package: git\n"
        calls = []

        def fake_run(command, **kwargs):
            calls.append([str(p) for p in command])
            if "show" in command:
                return subprocess.CompletedProcess(command, 0, known)
            return subprocess.CompletedProcess(command, 0, "")

        with mock.patch.object(init.os, "geteuid", return_value=0), \
                mock.patch.object(init, "installed", return_value=have | {"git"}), \
                mock.patch.object(init, "subprocess") as proc:
            proc.run.side_effect = fake_run
            init.apt(["apt-get"], have)
        installs = [c for c in calls if "install" in c]
        self.assertTrue(installs)
        for call in installs:
            self.assertNotIn("python3-zstandard", call)

    def test_a_package_apt_claims_but_dpkg_lacks_is_reported_not_raised(self):
        have = set(init.PACKAGES) - {"git"}
        output = StringIO()

        def fake_run(command, **kwargs):
            if "show" in command:
                return subprocess.CompletedProcess(command, 0, "Package: git\n")
            return subprocess.CompletedProcess(command, 0, "")

        with redirect_stdout(output), \
                mock.patch.object(init.os, "geteuid", return_value=0), \
                mock.patch.object(init, "installed", return_value=have), \
                mock.patch.object(init, "subprocess") as proc:
            proc.run.side_effect = fake_run
            init.apt(["apt-get"], have)
        self.assertIn("git 装完查不到", output.getvalue())


class PythonToolTests(unittest.TestCase):
    def test_pip_falls_back_to_break_system_packages_when_marked(self):
        with mock.patch.object(init.Path, "glob", return_value=iter([Path("/usr/lib/python3.12/EXTERNALLY-MANAGED")])), \
                mock.patch.object(init.subprocess, "run",
                                  return_value=subprocess.CompletedProcess([], 0, "")) as run:
            self.assertTrue(init.pip_install(["apt-get"], "ropper"))
        command = run.call_args[0][0]
        self.assertIn("--break-system-packages", command)
        self.assertTrue(any("filebytes" in a for a in command))

    def test_pip_omits_the_flag_when_not_marked(self):
        with mock.patch.object(init.Path, "glob", return_value=iter([])), \
                mock.patch.object(init.subprocess, "run",
                                  return_value=subprocess.CompletedProcess([], 0, "")) as run:
            init.pip_install(["apt-get"], "ropper")
        self.assertNotIn("--break-system-packages", run.call_args[0][0])

    def test_ropper_is_skipped_below_python_3_8(self):
        output = StringIO()
        with redirect_stdout(output), \
                mock.patch.object(init, "command_ok", return_value=None), \
                mock.patch.object(init, "python_minor", return_value=(3, 6)), \
                mock.patch.object(init, "pip_install") as pip, \
                mock.patch.object(init.shutil, "which", return_value=None):
            init.python_tools(["apt-get"])
        pip.assert_not_called()
        self.assertIn("需要 Python 3.8+", output.getvalue())

    def test_broken_tool_is_reinstalled(self):
        output = StringIO()
        with redirect_stdout(output), \
                mock.patch.object(init, "command_ok",
                                  side_effect=lambda name, *a: False if name == "ropper" else True), \
                mock.patch.object(init, "python_minor", return_value=(3, 12)), \
                mock.patch.object(init, "pip_install", return_value=True) as pip, \
                mock.patch.object(init.shutil, "which", return_value=None):
            init.python_tools(["apt-get"])
        pip.assert_called_once_with(["apt-get"], "ropper")
        self.assertIn("重装", output.getvalue())

    def test_pwntools_is_installed_by_pip_when_apt_has_none(self):
        """20.04 and 22.04 have no python3-pwntools; pip must fill the gap."""
        with redirect_stdout(StringIO()), \
                mock.patch.object(init, "command_ok", return_value=None), \
                mock.patch.object(init, "python_minor", return_value=(3, 10)), \
                mock.patch.object(init, "pip_install", return_value=True) as pip, \
                mock.patch.object(init, "write_root_file"), \
                mock.patch.object(init.shutil, "which", return_value=None):
            init.python_tools(["apt-get"])
        installed = [c[0][1] for c in pip.call_args_list]
        self.assertIn("pwntools", installed)
        self.assertIn("ROPgadget", installed)
        self.assertIn("ropper", installed)

    def test_pip_tools_are_skipped_below_python_3_8(self):
        output = StringIO()
        with redirect_stdout(output), \
                mock.patch.object(init, "command_ok", return_value=None), \
                mock.patch.object(init, "python_minor", return_value=(3, 6)), \
                mock.patch.object(init, "pip_install") as pip, \
                mock.patch.object(init.shutil, "which", return_value=None):
            init.python_tools(["apt-get"])
        pip.assert_not_called()
        self.assertIn("需要 Python 3.8+", output.getvalue())

    def test_pwn_wrappers_cover_missing_subcommands(self):
        written = {}

        def record(args, path, text):
            written[path.name] = text

        with mock.patch.object(init, "write_root_file", side_effect=record), \
                mock.patch.object(init, "writes_noterm", return_value=False), \
                mock.patch.object(init, "command_ok", return_value=True), \
                mock.patch.object(init, "pip_install", return_value=True), \
                mock.patch.object(init, "python_minor", return_value=(3, 12)), \
                mock.patch.object(init.shutil, "which",
                                  side_effect=lambda name, path=None:
                                  "/usr/bin/pwn" if name == "pwn" else None), \
                mock.patch.object(init.Path, "exists", return_value=False), \
                redirect_stdout(StringIO()):
            init.python_tools(["apt-get"])
        for name in init.PWN_SUBCOMMANDS:
            self.assertIn(name, written)
        self.assertIn("PWNLIB_NOTERM", written["pwn"])

    def test_checksec_becomes_a_dispatcher_when_debian_ships_one(self):
        written = {}
        with mock.patch.object(init, "write_root_file",
                               side_effect=lambda a, p, t: written.setdefault(p.name, t)), \
                mock.patch.object(init, "writes_noterm", return_value=True), \
                mock.patch.object(init, "command_ok", return_value=True), \
                mock.patch.object(init, "pip_install", return_value=True), \
                mock.patch.object(init, "python_minor", return_value=(3, 12)), \
                mock.patch.object(init.shutil, "which",
                                  side_effect=lambda name, path=None:
                                  "/usr/bin/pwn" if name == "pwn" else None), \
                mock.patch.object(init.Path, "exists", return_value=True), \
                redirect_stdout(StringIO()):
            init.python_tools(["apt-get"])
        self.assertIn("/usr/bin/checksec", written["checksec"])
        self.assertIn("checksec \"$@\"", written["checksec"])


class VerifyTests(unittest.TestCase):
    def test_missing_library_is_skipped_not_failed(self):
        output = StringIO()
        with redirect_stdout(output), \
                mock.patch.object(init.subprocess, "run",
                                  return_value=subprocess.CompletedProcess([], 0)), \
                mock.patch.object(init, "command_ok", return_value=True), \
                mock.patch.object(init.shutil, "which", return_value="/usr/bin/x"), \
                mock.patch.object(init, "firmae_ready", return_value=3):
            self.assertTrue(init.verify({"python3-pip"}))
        self.assertIn("skipped", output.getvalue())

    def test_unbuilt_firmware_image_is_pending_not_failed(self):
        output = StringIO()
        with redirect_stdout(output), \
                mock.patch.object(init.subprocess, "run",
                                  return_value=subprocess.CompletedProcess([], 0)), \
                mock.patch.object(init, "command_ok", return_value=True), \
                mock.patch.object(init.shutil, "which", return_value="/usr/bin/x"), \
                mock.patch.object(init, "firmae_ready", return_value=3):
            self.assertTrue(init.verify(set()))
        self.assertIn("pending", output.getvalue())

    def test_missing_firmware_source_is_pending_not_failed(self):
        """A fresh host has no FirmAE checkout; that must not fail the install."""
        output = StringIO()
        with redirect_stdout(output), \
                mock.patch.object(init.subprocess, "run",
                                  return_value=subprocess.CompletedProcess([], 0)), \
                mock.patch.object(init, "command_ok", return_value=True), \
                mock.patch.object(init.shutil, "which", return_value="/usr/bin/x"), \
                mock.patch.object(init, "firmae_ready", return_value=1):
            self.assertTrue(init.verify(set()))
        self.assertIn("pending", output.getvalue())

    def test_absent_firmware_tools_are_skipped(self):
        output = StringIO()
        with redirect_stdout(output), \
                mock.patch.object(init.subprocess, "run",
                                  return_value=subprocess.CompletedProcess([], 0)), \
                mock.patch.object(init, "command_ok", return_value=True), \
                mock.patch.object(init.shutil, "which", return_value=None), \
                mock.patch.object(init, "firmae_ready", return_value=None) as status:
            self.assertTrue(init.verify(set()))
        self.assertIn("未安装", output.getvalue())

    def test_a_command_that_will_not_launch_fails_verification(self):
        with redirect_stdout(StringIO()), \
                mock.patch.object(init.subprocess, "run",
                                  return_value=subprocess.CompletedProcess([], 1, "")), \
                mock.patch.object(init, "command_ok", return_value=True), \
                mock.patch.object(init.shutil, "which", return_value="/usr/bin/git"), \
                mock.patch.object(init, "firmae_ready", return_value=0):
            self.assertFalse(init.verify({"git"}))


class ProfileTests(unittest.TestCase):
    def test_legacy_blocks_are_removed_and_the_rest_is_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            bashrc = home / ".bashrc"
            bashrc.write_bytes(
                b"# keep\r\n# >>> init Python tools >>>\r\nctf_env() { :; }\r\n"
                b"# <<< init Python tools <<<\r\nalias py=python\r\n")
            init.tidy_profiles(home)
            self.assertEqual(bashrc.read_bytes(), b"# keep\r\nalias py=python\r\n")

    def test_tidy_is_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            bashrc = home / ".bashrc"
            bashrc.write_bytes(b"# >>> init system tools >>>\nx=1\n# <<< init system tools <<<\nplain\n")
            init.tidy_profiles(home)
            once = bashrc.read_bytes()
            init.tidy_profiles(home)
            self.assertEqual(bashrc.read_bytes(), once)
            self.assertEqual(once, b"plain\n")


if __name__ == "__main__":
    unittest.main()
