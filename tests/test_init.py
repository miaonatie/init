import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import init


class InstallerTests(unittest.TestCase):
    def test_no_arguments_installs_and_verifies_system_python(self):
        with mock.patch.object(init, "install_packages") as install, \
                mock.patch.object(init.subprocess, "run") as run, \
                mock.patch.object(init, "remove_old_activation") as clean:
            self.assertEqual(init.main([]), 0)
        install.assert_called_once_with()
        run.assert_called_once_with(
            ["/usr/bin/python3", "-I", "-c", "import " + ", ".join(init.LIBRARIES.values())],
            check=True,
        )
        clean.assert_called_once_with(Path.home())

    def test_arguments_are_rejected_before_installing(self):
        with mock.patch.object(init, "install_packages") as install:
            self.assertEqual(init.main(["--system-python"]), 2)
        install.assert_not_called()

    def test_failed_import_check_keeps_old_activation(self):
        with mock.patch.object(init, "install_packages"), \
                mock.patch.object(init.subprocess, "run", side_effect=subprocess.CalledProcessError(1, "python3")), \
                mock.patch.object(init, "remove_old_activation") as clean:
            self.assertEqual(init.main([]), 1)
        clean.assert_not_called()

    def test_existing_packages_need_no_apt_or_sudo(self):
        installed = "\n".join("installed\t" + package for package in (*init.PACKAGES, init.PYTHON_ALIAS))
        with mock.patch.object(init.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, installed)) as run:
            init.install_packages()
        run.assert_called_once()
        self.assertEqual(run.call_args[0][0][0], "dpkg-query")

    def test_missing_packages_are_installed_with_apt(self):
        for alias_available in (True, False):
            with self.subTest(alias_available=alias_available), \
                    mock.patch.object(init, "missing_packages", return_value=(["python3-pil"], True)), \
                    mock.patch.object(init, "alias_available", return_value=alias_available), \
                    mock.patch.object(init.os, "geteuid", return_value=1000), \
                    mock.patch.object(init.subprocess, "run") as run:
                init.install_packages()
            apt = ["sudo", "apt-get", "-o", "Acquire::Retries=2"]
            packages = ["python3-pil", init.PYTHON_ALIAS] if alias_available else ["python3-pil"]
            self.assertEqual(run.call_args_list, [
                mock.call([*apt, "update"], check=True),
                mock.call([*apt, "install", "-y", "--no-install-recommends", *packages], check=True),
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
