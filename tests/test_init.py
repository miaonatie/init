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
        with mock.patch.object(init, "install_packages", return_value={"python3", "git"}) as install, \
                mock.patch.object(init, "verify_python", return_value=True) as verify, \
                mock.patch.object(init, "verify_tools", return_value=True) as verify_tools, \
                mock.patch.object(init, "remove_old_activation") as clean:
            self.assertEqual(init.main([]), 0)
        install.assert_called_once_with()
        verify.assert_called_once_with()
        verify_tools.assert_called_once_with({"python3", "git"})
        clean.assert_called_once_with(Path.home())

    def test_arguments_are_rejected_before_installing(self):
        with mock.patch.object(init, "install_packages") as install:
            self.assertEqual(init.main(["--system-python"]), 2)
        install.assert_not_called()

    def test_failed_import_check_keeps_old_activation(self):
        with mock.patch.object(init, "install_packages", return_value=set()), \
                mock.patch.object(init, "verify_python", return_value=False), \
                mock.patch.object(init, "remove_old_activation") as clean:
            self.assertEqual(init.main([]), 1)
        clean.assert_not_called()

    def test_existing_packages_need_no_apt_or_sudo(self):
        installed = "\n".join("installed\t" + package for package in init.PACKAGES)
        output = StringIO()
        with redirect_stdout(output), mock.patch.object(
                init.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, installed)) as run:
            init.install_packages()
        run.assert_called_once()
        self.assertEqual(run.call_args[0][0][0], "dpkg-query")
        self.assertEqual(output.getvalue().count("[installed]"), len(init.PACKAGES))
        self.assertIn("Binary inspection and debugging", output.getvalue())

    def test_missing_packages_are_installed_with_apt(self):
        for alias_available in (True, False):
            requested = ["python3-pil", "gdb"]
            if alias_available:
                requested.append(init.PYTHON_ALIAS)
            final = set(init.PACKAGES)
            if not alias_available:
                final.remove(init.PYTHON_ALIAS)
            before = final - set(requested) - {"gdb", init.PYTHON_ALIAS}
            with self.subTest(alias_available=alias_available), \
                    mock.patch.object(init, "installed_packages", side_effect=[before, final]), \
                    mock.patch.object(init, "available_packages", return_value=set(requested)), \
                    mock.patch.object(init.os, "geteuid", return_value=1000), \
                    mock.patch.object(init.subprocess, "run") as run:
                self.assertEqual(init.install_packages(), final)
            apt = ["sudo", "apt-get", "-o", "Acquire::Retries=2", "-o", "DPkg::Lock::Timeout=60"]
            packages = [package for package in init.PACKAGES if package in requested]
            self.assertEqual(run.call_args_list, [
                mock.call([*apt, "-o", "APT::Update::Error-Mode=any", "update"], check=True),
                mock.call([*apt, "install", "-y", "--no-remove", "--no-install-recommends", *packages], check=True),
            ])

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
