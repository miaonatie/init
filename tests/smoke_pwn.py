"""Run in disposable CI containers; installs and exercises core Pwn commands."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import init

b = init.Bootstrap()
if sys.argv[1:] != ["--exercise"]:
    original_path, original_wsl = os.environ["PATH"], b.is_wsl
    windows_dir = Path("/mnt/c/Users/init-ci/Python/Scripts")
    windows_dir.mkdir(parents=True, exist_ok=True)
    launcher = windows_dir / "init-broken-ROPgadget"
    launcher.write_text("#!/nonexistent/windows/python.exe\n")
    launcher.chmod(0o755)
    os.environ["PATH"] = str(windows_dir) + os.pathsep + original_path
    b.is_wsl = True
    assert b.find_command([launcher.name]) is None
    assert str(windows_dir) not in os.environ["PATH"].split(os.pathsep)
    assert b.run([str(launcher)], capture=True, check=False).returncode == 127
    os.environ["PATH"], b.is_wsl = original_path, original_wsl

if sys.argv[1:] != ["--exercise"]:
    assert b.supported_distro(b.distro), b.distro
    b.apt_updated = True
    aliases = ["7zip", "bind9-dnsutils", "libncurses-dev", "python-is-python3", "checksec", "bsdextrautils"]
    packages = b.compatible_packages(aliases)
    packages += [p for p in init.REQUIRED_APT if p not in aliases]
    result = b.run(["apt-cache", "--no-all-versions", "show"] + packages, capture=True, check=False)
    available = {line.split(": ", 1)[1] for line in result.stdout.splitlines() if line.startswith("Package: ")}
    assert not set(packages) - available, set(packages) - available
    core = ["file", "binutils", "libc-bin", "bsdextrautils", "build-essential", "gdb", "gdbserver",
            "gdb-multiarch", "patchelf", "strace", "ltrace", "nasm", "yasm", "valgrind", "xxd",
            "netcat-openbsd", "socat", "checksec"]
    assert set(core) <= set(init.REQUIRED_APT)
    assert b.apt_install(b.compatible_packages(core), "Pwn smoke dependencies", required=True)
    assert b.install_uv()
    python = "/tmp/init-pwn-smoke/bin/python"
    b.run([b.uv_executable(), "venv", "--seed", "--python", "3.12", python.rsplit("/bin/", 1)[0]], timeout=600)
    os.environ["PATH"] = str(Path(python).parent) + os.pathsep + os.environ["PATH"]
    b.system_python = lambda: python
    b.install_python_tools()
    assert not b.failures, b.failures
    b.run([python, "-c", "import importlib; [importlib.import_module(m) for m in " + repr(init.PYTHON_IMPORTS) + "]"])
    os.execv(python, [python, __file__, "--exercise"])

b.install_checksec_fallback()
assert not b.failures, b.failures
for name, args in dict(init.PWN_SYSTEM_PROBES, **{n: ["--help"] for n in ("pwn", *init.PWN_ENTRYPOINTS)}).items():
    result = b.run([name] + args, capture=True, check=False, timeout=30)
    assert result.returncode == 0, (name, result.stdout, result.stderr)

with tempfile.TemporaryDirectory() as directory:
    source = Path(directory) / "hello.c"
    binary = Path(directory) / "hello"
    source.write_text('int main(void) { return 0; }\n')
    b.run(["gcc", "-g", "-O0", "-o", str(binary), str(source)])
    for command, marker in [(["file", str(binary)], "ELF"),
                            (["readelf", "-h", str(binary)], "ELF"),
                            (["objdump", "-d", str(binary)], "main"),
                            (["pwn", "checksec", str(binary)], "NX")]:
        result = b.run(command, capture=True)
        assert marker in (result.stdout + result.stderr), command
    b.run(["patchelf", "--print-interpreter", str(binary)], capture=True)
    b.run(["gdb", "-nx", "-batch", "-ex", "info files", str(binary)], capture=True)
    pattern = b.run(["cyclic", "32"], capture=True).stdout.strip()
    assert len(pattern) == 32, pattern
    assert b.run(["cyclic", "-l", pattern[8:12]], capture=True).stdout.strip() == "8"
    assert b.run(["asm", "-c", "amd64", "-f", "hex", "nop"], capture=True).stdout.strip() == "90"
    assert "nop" in b.run(["disasm", "-c", "amd64", "90"], capture=True).stdout
    b.run(["shellcraft", "amd64.linux.exit", "0"], capture=True)
print("Pwn core command installation and ELF/CLI smoke tests passed")
