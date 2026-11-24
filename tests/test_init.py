from contextlib import redirect_stdout
from io import StringIO
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import init


class InstallerTests(unittest.TestCase):
    def test_no_arguments_installs_and_verifies_system_python(self):
        output = StringIO()
        with redirect_stdout(output), mock.patch.object(init, "preflight") as preflight, \
                mock.patch.object(init, "installed_packages", return_value=set()), \
                mock.patch.object(init, "refresh_index", return_value={"git"}) as refresh, \
                mock.patch.object(init, "install_packages", side_effect=[{"python3"}, {"python3", "git"}]) as install, \
                mock.patch.object(init, "verify_python", return_value=True) as verify, \
                mock.patch.object(init, "verify_tools", return_value=True) as verify_tools, \
                mock.patch.object(init, "remove_old_activation") as clean:
            self.assertEqual(init.main([]), 0)
        preflight.assert_called_once_with()
        apt = refresh.call_args[0][0]
        self.assertEqual(install.call_args_list, [
            mock.call(init.FOUNDATION, apt, set(), {"git"}),
            mock.call(init.LAB_TOOLS, apt, {"python3"}, {"git"}),
        ])
        verify.assert_called_once_with({"python3", "git"})
        verify_tools.assert_called_once_with({"python3", "git"})
        clean.assert_called_once_with(Path.home())
        self.assertEqual([line for line in output.getvalue().splitlines() if line.startswith("[")], [
            "[1/4] Environment check", "[2/4] System foundation", "[3/4] Lab tools", "[4/4] Verification",
        ])

    def test_arguments_are_rejected_before_installing(self):
        with mock.patch.object(init, "install_packages") as install:
            self.assertEqual(init.main(["--system-python"]), 2)
        install.assert_not_called()

    def test_failed_import_check_keeps_old_activation(self):
        with mock.patch.object(init, "preflight"), \
                mock.patch.object(init, "installed_packages", return_value=set()), \
                mock.patch.object(init, "refresh_index"), \
                mock.patch.object(init, "install_packages", return_value=set()), \
                mock.patch.object(init, "verify_python", return_value=False), \
                mock.patch.object(init, "remove_old_activation") as clean:
            self.assertEqual(init.main([]), 1)
        clean.assert_not_called()

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
        self.assertEqual(output.getvalue().count("[installed]"), len(init.PACKAGES))
        self.assertIn("Binary inspection and debugging", output.getvalue())

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
                init.remove_old_activation(home)
                self.assertEqual(bashrc.read_bytes(), b"# keep\r\n\r\nalias py=python\r\n")
                self.assertFalse((home / ".zshrc").exists())
