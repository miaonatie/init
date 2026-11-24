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


class InstallerTests(unittest.TestCase):
    def test_no_arguments_installs_and_verifies_system_python(self):
        output = StringIO()
        with redirect_stdout(output), mock.patch.object(init, "preflight") as preflight, \
                mock.patch.object(init, "installed_packages", return_value=set()), \
                mock.patch.object(init, "refresh_index", return_value={"git"}) as refresh, \
                mock.patch.object(init, "install_packages", side_effect=[{"python3"}, {"python3", "git"}]) as install, \
                mock.patch.object(init, "verify_python", return_value=True) as verify, \
                mock.patch.object(init, "verify_tools", return_value=True) as verify_tools, \
                mock.patch.object(init, "configure_shell_defaults") as clean:
            self.assertEqual(init.main([]), 0)
        preflight.assert_called_once_with()
        apt = refresh.call_args[0][0]
        self.assertEqual(install.call_args_list, [
            mock.call(init.FOUNDATION, apt, set(), {"git"}),
            mock.call(init.LAB_TOOLS, apt, {"python3"}, {"git"}),
        ])
        verify.assert_called_once_with({"python3", "git"})
        verify_tools.assert_called_once_with({"python3", "git"})
        clean.assert_called_once_with(Path.home(), {"python3", "git"})
        self.assertEqual([line for line in output.getvalue().splitlines() if line.startswith("[")], [
            "[1/4] Environment check", "[2/4] System foundation", "[3/4] Lab tools", "[4/4] Verification",
        ])

    def test_arguments_are_rejected_before_installing(self):
        with mock.patch.object(init, "install_packages") as install:
            self.assertEqual(init.main(["--system-python"]), 2)
        install.assert_not_called()

    def test_check_python_is_read_only_and_returns_the_verification_result(self):
        installed = {"python3", "python3-pyelftools"}
        with mock.patch.object(init, "preflight"), \
                mock.patch.object(init, "installed_packages", return_value=installed), \
                mock.patch.object(init, "verify_python", side_effect=[True, False]) as verify, \
                mock.patch.object(init, "refresh_index") as refresh, \
                mock.patch.object(init, "install_packages") as install, \
                mock.patch.object(init, "verify_tools") as verify_tools, \
                mock.patch.object(init, "configure_shell_defaults") as configure:
            self.assertEqual(init.main(["--check-python"]), 0)
            self.assertEqual(init.main(["--check-python"]), 1)
        self.assertEqual(verify.call_args_list, [mock.call(installed), mock.call(installed)])
        for operation in (refresh, install, verify_tools, configure):
            operation.assert_not_called()

    def test_system_python_checks_installed_optional_libraries_and_reports_missing_ones(self):
        output = StringIO()
        with redirect_stdout(output), mock.patch.object(init, "check_command", return_value=True) as check:
            self.assertTrue(init.verify_python({"python3-pyelftools"}))
        check.assert_any_call("import elftools", [init.PYTHON, "-I", "-c", "import elftools"])
        self.assertNotIn("import zstandard", [call[0][0] for call in check.call_args_list])
        self.assertIn("[skipped] import zstandard (python3-zstandard is not installed)", output.getvalue())

    def test_failed_import_check_keeps_old_activation(self):
        with mock.patch.object(init, "preflight"), \
                mock.patch.object(init, "installed_packages", return_value=set()), \
                mock.patch.object(init, "refresh_index"), \
                mock.patch.object(init, "install_packages", return_value=set()), \
                mock.patch.object(init, "verify_python", return_value=False), \
                mock.patch.object(init, "configure_shell_defaults") as clean:
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
                init.configure_shell_defaults(home, set())
                self.assertEqual(bashrc.read_bytes(), b"# keep\r\n\r\nalias py=python\r\n")
                self.assertFalse((home / ".zshrc").exists())

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
