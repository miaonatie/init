"""Full installer integration, only in disposable Linux CI containers.

Download one glibc revision per architecture; unit tests cover full index
selection. Everything else uses the production install/verify paths unchanged.
"""
import hashlib
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import init


class CIEnvironment(init.Bootstrap):
    def glibc_aio_latest_packages(self):
        packages = super().glibc_aio_latest_packages()
        # Bound network/storage cost without mocking download or validation.
        selected = {}
        for arch in init.GLIBC_LIBRARY_ARCHES:
            candidates = [(key, value) for key, value in packages.items() if key[1] == arch]
            if candidates:
                key, value = max(candidates, key=self.glibc_package_sort_key)
                selected[key] = value
        return selected


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def exercise_languages(b):
    """Compile and execute tiny programs, not just --version probes."""
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        samples = [
            ('hello.cpp', '#include <iostream>\nint main(){std::cout << "init-ok";}',
             ['g++'], ['clang++']),
            ('hello.go', 'package main\nimport "fmt"\nfunc main(){fmt.Print("init-ok")}', ['go', 'build']),
            ('hello.rs', 'fn main(){print!("init-ok");}', [str(init.CARGO_HOME / 'bin/rustc')]),
        ]
        for name, source, *compilers in samples:
            path, binary = root / name, root / 'program'
            path.write_text(source)
            for compiler in compilers:
                b.run(compiler + ['-o', str(binary), str(path)], capture=True, timeout=120)
                assert b.run([str(binary)], capture=True).stdout.strip() == 'init-ok', compiler
        java = root / 'Hello.java'
        java.write_text('public class Hello {public static void main(String[] a){System.out.print("init-ok");}}')
        b.run(['javac', str(java)], capture=True, timeout=60)
        assert b.run(['java', '-cp', str(root), 'Hello'], capture=True).stdout == 'init-ok'
        assert b.run(['ruby', '-e', 'print "init-ok"'], capture=True).stdout == 'init-ok'
        assert b.run(['python2', '-c', 'print("init-ok")'], capture=True).stdout.strip() == 'init-ok'
        if 'node' not in b.compat_skips:
            result = b.run_node_shell("nvm use --silent default >/dev/null\nnode -e 'process.stdout.write(\"init-ok\")'", capture=True)
            assert result.returncode == 0 and result.stdout == 'init-ok', result


def main():
    system_python = Path('/usr/bin/python3').resolve()
    system_digest = digest(system_python)
    b = CIEnvironment()
    assert b.install() == 0, b.failures
    assert Path('/usr/bin/python3').resolve() == system_python
    assert digest(system_python) == system_digest
    # Installer PATH alone is insufficient: test clean interactive shell startup.
    for shell in ('bash', 'zsh'):
        b.run([shell, '-ic', 'command -v uv && command -v ROPgadget && command -v ropper'],
              env={'PATH': '/usr/bin:/bin'}, capture=True, timeout=60)
    exercise_languages(b)
    python = b.system_python()
    b.run([python, str(Path(__file__).with_name('smoke_pwn.py')), '--exercise'])
    # Exercise real repair with metadata intact (pip upgrade alone is a no-op).
    for name in ('ROPgadget', 'ropper'):
        launcher = Path(b.find_command([name]))
        broken = "#!/bin/sh\nprintf 'ModuleNotFoundError: injected CI failure\\n' >&2\nexit 1\n"
        assert b.install_command_wrapper(launcher, broken)
    b.install_python_tools()
    assert not b.failures, b.failures
    for name in ('ROPgadget', 'ropper'):
        assert b.find_usable_command([name], init.COMMAND_PROBE_ARGUMENTS[name]), name
    profiles = [p for p in (init.BASHRC, init.ZSHRC, init.VIMRC, init.TMUX_CONF, init.GDBINIT) if p.exists()]
    before = {str(p): digest(p) for p in profiles}
    # A fresh instance also checks cache-independent idempotence.
    repeat = CIEnvironment()
    assert repeat.install() == 0, repeat.failures
    assert before == {str(p): digest(p) for p in profiles}, 'configuration changed on repeat'
    assert digest(system_python) == system_digest
    print('PASS: full installation, verification, CLI repair and repeat installation')
    print('Compatibility skips:', repeat.skipped)


if __name__ == '__main__':
    main()
