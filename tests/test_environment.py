"""Environment routing and failure handling regressions (no system mutation)."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import init


class EnvironmentTests(unittest.TestCase):
    def setUp(self):
        self.b = init.Bootstrap()

    def test_python_interpreter_matrix(self):
        for distro, version, isolated in [('ubuntu', '18.04', True), ('ubuntu', '20.04', True),
                                         ('ubuntu', '22.04', True), ('ubuntu', '24.04', True),
                                         ('ubuntu', '26.04', True), ('kali', '2026.3', True)]:
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
        self.assertEqual(run.call_args[0][0], ['sudo', 'env', 'PIP_BREAK_SYSTEM_PACKAGES=1',
                         'DEBIAN_FRONTEND=noninteractive', '/usr/bin/python3', '-m', 'pip', '--version'])

    def test_root_does_not_use_sudo(self):
        with mock.patch.object(os, 'geteuid', return_value=0), mock.patch.object(
                subprocess, 'run', return_value=subprocess.CompletedProcess([], 0)) as run:
            self.b.run(['true'], sudo=True, env={'PIP_BREAK_SYSTEM_PACKAGES': '1'}, capture=True)
        self.assertEqual(run.call_args[0][0], ['true'])
        self.assertEqual(run.call_args[1]['env']['PIP_BREAK_SYSTEM_PACKAGES'], '1')

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

    def test_managed_python_repair_only_clears_broken_environment(self):
        self.b.distro = {'id': 'ubuntu', 'version': '18.04'}
        self.b.install_uv = mock.Mock(return_value=True)
        self.b.uv_executable = mock.Mock(return_value='/bin/uv')
        self.b.update_managed_block = mock.Mock()
        with tempfile.TemporaryDirectory() as directory:
            python = Path(directory) / 'python/bin/python3'
            python.parent.mkdir(parents=True)
            python.touch()
            self.b.system_python = mock.Mock(return_value=str(python))
            self.b.run = mock.Mock(side_effect=[subprocess.CompletedProcess([], 1),
                                               subprocess.CompletedProcess([], 0)])
            with mock.patch.dict(os.environ):
                self.assertTrue(self.b.prepare_python_tools())
            command = self.b.run.call_args[0][0]
            self.assertIn('--clear', command)
            self.assertEqual(command[-1], str(python.parent.parent))
            self.assertNotIn('sudo', self.b.run.call_args[1])

    def test_ruby_batch_failure_recovers_only_failed_tool(self):
        self.b.distro = {'id': 'ubuntu', 'version': '24.04'}
        self.b.command_exists = mock.Mock(return_value=True)
        self.b.find_usable_command = mock.Mock(side_effect=[
            '/bin/one_gadget', None, '/bin/zsteg', None,
            '/bin/one_gadget', '/bin/seccomp-tools', '/bin/zsteg'])
        self.b.run = mock.Mock(side_effect=[subprocess.CompletedProcess([], 1),
                                           subprocess.CompletedProcess([], 0)])
        self.b.install_ruby_tools()
        self.assertEqual(self.b.run.call_count, 2)
        self.assertEqual(self.b.run.call_args[0][0][-1], 'seccomp-tools')
        self.assertFalse(self.b.failures)

    def test_ruby_version_routing(self):
        for version, expected in [('18.04', 'one_gadget:1.7.3'), ('20.04', 'one_gadget:1.7.3'),
                                  ('22.04', 'one_gadget'), ('24.04', 'one_gadget')]:
            self.b.distro = {'id': 'ubuntu', 'version': version}
            self.b.command_exists = mock.Mock(return_value=True)
            self.b.find_usable_command = mock.Mock(side_effect=[None, '/bin/seccomp-tools', '/bin/zsteg',
                                                               '/bin/one_gadget', '/bin/seccomp-tools', '/bin/zsteg'])
            self.b.run = mock.Mock(return_value=subprocess.CompletedProcess([], 0))
            self.b.install_ruby_tools()
            self.assertEqual(self.b.run.call_args[0][0][-1], expected)

    def test_ruby25_zsteg_downgrade_activates_compatible_version(self):
        self.b.distro = {'id': 'ubuntu', 'version': '18.04'}
        self.b.command_exists = mock.Mock(return_value=True)
        self.b.find_usable_command = mock.Mock(side_effect=[
            '/bin/one_gadget', '/bin/seccomp-tools', None,
            '/bin/one_gadget', '/bin/seccomp-tools', '/usr/local/bin/zsteg'])
        self.b.run = mock.Mock(return_value=subprocess.CompletedProcess([], 0))
        self.b.install_command_wrapper = mock.Mock(return_value=True)
        self.b.install_ruby_tools()
        self.assertIn('zsteg:0.2.12', self.b.run.call_args[0][0])
        wrapper = self.b.install_command_wrapper.call_args[0][1]
        self.assertIn('gem "zsteg", "= 0.2.12"', wrapper)
        self.assertIn('"$@"', wrapper)
        self.assertFalse(self.b.failures)

    def test_every_registered_probe_rejects_import_and_loader_errors(self):
        for name, arguments in init.COMMAND_PROBE_ARGUMENTS.items():
            for error in ('ModuleNotFoundError', 'ImportError', 'error while loading shared libraries',
                          'cannot load such file', 'Traceback (most recent call last)'):
                with self.subTest(tool=name, error=error):
                    self.b.run = mock.Mock(return_value=subprocess.CompletedProcess([], 0, '', error))
                    self.assertFalse(self.b.executable_usable(name, arguments))

    def test_shell_tool_paths_are_persistent_and_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            bashrc, zshrc = Path(directory) / '.bashrc', Path(directory) / '.zshrc'
            bashrc.write_text('# user setting\n')
            with mock.patch.object(init, 'BASHRC', bashrc), mock.patch.object(init, 'ZSHRC', zshrc):
                self.b.configure_tool_paths()
                before = bashrc.read_text()
                self.b.configure_tool_paths()
                self.assertEqual(bashrc.read_text(), before)
                self.assertTrue(before.startswith('# user setting'))
            result = subprocess.check_output(['bash', '-c', '. "$1"; . "$1"; printf "%s" "$PATH"',
                                              'test', str(bashrc)],
                                             env={'PATH': '/usr/bin:/bin', 'HOME': directory},
                                             universal_newlines=True)
            self.assertEqual(result.split(':').count(directory + '/.local/bin'), 1)
            self.assertEqual(result.split(':').count('/usr/local/bin'), 1)

    def test_corrupt_library_metadata_is_repaired_and_rechecked(self):
        for repaired in (True, False):
            with self.subTest(repaired=repaired):
                b = init.Bootstrap()
                b.distro = {'id': 'ubuntu', 'version': '24.04'}
                b.find_usable_command = mock.Mock(return_value='/bin/tool')
                b.run = mock.Mock(side_effect=[
                    subprocess.CompletedProcess([], 0, 'capstone\n', ''),
                    subprocess.CompletedProcess([], 0),
                    subprocess.CompletedProcess([], 0, 'capstone\n', ''),
                    subprocess.CompletedProcess([], 0),
                    subprocess.CompletedProcess([], 0, '' if repaired else 'capstone\n', ''),
                ])
                b.install_python_tools()
                repair = b.run.call_args_list[3][0][0]
                self.assertIn('--force-reinstall', repair)
                self.assertEqual(repair[-1], 'capstone')
                self.assertEqual(bool(b.failures), not repaired)

    def test_apt_availability_cache_is_invalidated_by_index_refresh(self):
        self.b.run = mock.Mock(side_effect=[subprocess.CompletedProcess([], 0, 'Package: gcc', ''),
                                           subprocess.CompletedProcess([], 0, '', ''),
                                           subprocess.CompletedProcess([], 100, '', '')])
        self.assertTrue(self.b.package_available('gcc'))
        self.assertTrue(self.b.package_available('gcc'))
        self.assertEqual(self.b.run.call_count, 1)
        self.assertTrue(self.b.apt_update(force=True))
        self.assertFalse(self.b.package_available('gcc'))
        self.assertEqual(self.b.run.call_count, 3)

    def test_neowofetch_version_exit_is_narrowly_allowed(self):
        for name, args, code, output, expected in [
            ('neowofetch', ['--version'], 1, 'Neofetch 7.2.0', True),
            ('neowofetch', ['--version'], 1, 'Neowofetch 7.3.11', True),
            ('tool', ['--version'], 1, 'Neofetch 7.2.0', False),
            ('neowofetch', ['--version'], 2, 'Neofetch 7.2.0', False),
            ('neowofetch', ['--version'], 1, 'broken', False),
        ]:
            self.b.run = mock.Mock(return_value=subprocess.CompletedProcess([], code, output, ''))
            self.assertEqual(self.b.executable_usable(name, args), expected)

    def test_glibc_multiarch_payload_gets_relative_links_and_is_reusable(self):
        for arch in ('x86_64-linux-gnu', 'i386-linux-gnu'):
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                nested = root / arch
                nested.mkdir()
                (nested / 'libc.so.6').write_bytes(b'ELF fixture')
                (nested / 'ld-linux.so.2').write_bytes(b'loader fixture')
                self.b.normalize_glibc_payload(root)
                self.assertTrue(self.b.glibc_package_payload_available(root))
                self.assertEqual(os.readlink(str(root / 'libc.so.6')), arch + '/libc.so.6')
                before = (root / 'libc.so.6').lstat().st_mtime_ns
                self.b.normalize_glibc_payload(root)
                self.assertEqual((root / 'libc.so.6').lstat().st_mtime_ns, before)

    def test_healthy_binwalk_is_not_modified(self):
        self.b.find_usable_command = mock.Mock(return_value='/usr/bin/binwalk')
        self.b.install_command_wrapper = mock.Mock()
        self.b.repair_distro_python_commands()
        self.b.install_command_wrapper.assert_not_called()

    def test_binwalk_wrapper_uses_distro_dependencies_and_preserves_arguments(self):
        self.b.find_usable_command = mock.Mock(return_value=None)
        self.b.executable_usable = mock.Mock(return_value=True)
        self.b.install_command_wrapper = mock.Mock(return_value=True)
        with mock.patch.object(Path, 'open', mock.mock_open(read_data='#!/usr/bin/python3\n')):
            self.b.repair_distro_python_commands()
        probe_args = self.b.executable_usable.call_args[0][1]
        self.assertEqual(probe_args[:2], ['-I', '-S'])
        self.assertEqual(probe_args[-1], '--help')
        path, content = self.b.install_command_wrapper.call_args[0]
        self.assertEqual(path, Path('/usr/local/bin/binwalk'))
        self.assertIn('/usr/lib/python3/dist-packages', content)
        self.assertIn('"$@"', content)


if __name__ == '__main__':
    unittest.main()
