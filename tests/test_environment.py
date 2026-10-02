"""Environment routing and failure handling regressions (no system mutation)."""
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import init


class EnvironmentTests(unittest.TestCase):
    def setUp(self):
        self.b = init.Bootstrap()

    def test_python_interpreter_matrix(self):
        for distro, version, isolated in [('ubuntu', '18.04', True), ('ubuntu', '20.04', True),
                                         ('ubuntu', '22.04', True), ('ubuntu', '24.04', False),
                                         ('ubuntu', '26.04', False), ('kali', '2026.3', False)]:
            with self.subTest(distro=distro, version=version):
                self.b.distro = {'id': distro, 'version': version}
                with mock.patch.object(Path, 'exists', return_value=True):
                    path = self.b.system_python()
                self.assertEqual(path, str(init.HOME / '.local/share/init/python/bin/python3')
                                 if isolated else '/usr/bin/python3')

    def test_sudo_keeps_explicit_install_environment(self):
        overrides = {'PIP_BREAK_SYSTEM_PACKAGES': '1', 'DEBIAN_FRONTEND': 'noninteractive'}
        with mock.patch.object(os, 'geteuid', return_value=1000), mock.patch.object(
                subprocess, 'run', return_value=subprocess.CompletedProcess([], 0)) as run:
            self.b.run(['/usr/bin/python3', '-m', 'pip', '--version'], sudo=True, env=overrides, capture=True)
        self.assertEqual(run.call_args.args[0], ['sudo', 'env', 'PIP_BREAK_SYSTEM_PACKAGES=1',
                         'DEBIAN_FRONTEND=noninteractive', '/usr/bin/python3', '-m', 'pip', '--version'])

    def test_root_does_not_use_sudo(self):
        with mock.patch.object(os, 'geteuid', return_value=0), mock.patch.object(
                subprocess, 'run', return_value=subprocess.CompletedProcess([], 0)) as run:
            self.b.run(['true'], sudo=True, env={'PIP_BREAK_SYSTEM_PACKAGES': '1'}, capture=True)
        self.assertEqual(run.call_args.args[0], ['true'])
        self.assertEqual(run.call_args.kwargs['env']['PIP_BREAK_SYSTEM_PACKAGES'], '1')

    def test_failed_version_probes_never_pass(self):
        for code in (1, 2, 124, 126, 127, -11):
            for output in ('', 'unknown option', 'Usage: tool'):
                with self.subTest(code=code, output=output):
                    self.b.run = mock.Mock(return_value=subprocess.CompletedProcess([], code, output, ''))
                    self.assertFalse(self.b.executable_usable('tool', ['--version']))

    def test_no_arguments_only_accept_known_usage_exit(self):
        for code, output, expected in [(1, 'Usage: tool', True), (2, 'Usage: tool', True),
                                       (1, 'fatal configuration error', False), (3, 'Usage: tool', False),
                                       (1, 'Usage: tool\nImportError', False)]:
            self.b.run = mock.Mock(return_value=subprocess.CompletedProcess([], code, output, ''))
            self.assertEqual(self.b.executable_usable('tool', []), expected)

    def test_multilib_architecture_routing(self):
        for arch in ('x86_64', 'amd64', 'aarch64', 'armv7l'):
            self.b.arch = arch
            self.b.run = mock.Mock(return_value=subprocess.CompletedProcess([], 0, 'i386\n', ''))
            self.assertEqual(bool(self.b.enable_i386()), arch in ('x86_64', 'amd64'))
            if arch not in ('x86_64', 'amd64'):
                self.b.run.assert_not_called()

    def test_all_python_commands_have_launch_probes_and_imports(self):
        for package in init.PYTHON_COMMAND_PACKAGES:
            self.assertIn(package, init.COMMAND_PROBE_ARGUMENTS)
            self.assertIn(package, init.PYTHON_IMPORT_PACKAGES)

    def test_all_ruby_commands_have_launch_probes(self):
        for package in init.RUBY_GEMS:
            self.assertIn(package, init.COMMAND_PROBE_ARGUMENTS)

    def test_docker_distribution_matrix(self):
        for version, suite in [('18.04', 'bionic'), ('20.04', 'focal'), ('22.04', 'jammy'),
                               ('24.04', 'noble'), ('26.04', 'resolute')]:
            self.b.distro = {'id': 'ubuntu', 'version': version, 'codename': suite}
            self.assertEqual(self.b.docker_repository(), ('ubuntu', suite))
        self.b.distro = {'id': 'kali'}
        self.assertEqual(self.b.docker_repository(), ('debian', 'trixie'))


if __name__ == '__main__':
    unittest.main()
