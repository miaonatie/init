#!/usr/bin/env python3
"""Install and verify system packages for the lab with APT."""
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import time


PYTHON = "/usr/bin/python3"
PYTHON_ALIAS = "python-is-python3"
LIBRARIES = {
    "python3-pip": "pip",
    "python3-setuptools": "setuptools",
    "python3-wheel": "wheel",
    "python3-ipython": "IPython",
    "python3-magic": "magic",
    "python3-pil": "PIL",
    "python3-requests": "requests",
    "python3-sympy": "sympy",
    "python3-yaml": "yaml",
}
PYTHON_PACKAGES = ("python3", "python3-dev", *LIBRARIES)
EXTRA_LIBRARIES = {"python3-pyelftools": "elftools", "python3-zstandard": "zstandard", "python3-gmpy2": "gmpy2"}
FOUNDATION = {
    "System Python": (*PYTHON_PACKAGES, PYTHON_ALIAS),
    "Shell and everyday tools": (
        "ca-certificates", "gnupg", "curl", "wget", "git", "rsync", "openssh-client",
        "zsh", "bash-completion", "shellcheck", "vim", "nano", "tmux", "tree",
        "bat", "fd-find", "ripgrep", "fzf", "zoxide", "duf", "btop", "htop", "ncdu", "jq", "yq",
        "fastfetch", "hyfetch", "bsdextrautils", "bc", "xmlstarlet",
    ),
    "Network diagnostics": (
        "iproute2", "net-tools", "bind9-dnsutils", "iputils-ping", "traceroute", "lsof", "tcpdump", "openssl",
    ),
}
LAB_TOOLS = {
    "Build and development tools": (
        "build-essential", "pkg-config", "clang", "llvm", "lld", "cmake", "ninja-build", "meson",
        "autoconf", "automake", "libtool", "gawk", "bison", "flex", "gettext", "patch",
        "libssl-dev", "libffi-dev", "zlib1g-dev", "libbz2-dev", "liblzma-dev", "libsqlite3-dev",
        "libreadline-dev", "libncurses-dev",
    ),
    "System language toolchains": (
        "perl", "ruby-full", "bundler", "default-jdk-headless", "nodejs", "npm",
        "golang-go", "rustc", "cargo", "rustfmt", *EXTRA_LIBRARIES,
    ),
    "Binary inspection and debugging": (
        "file", "binutils", "elfutils", "xxd", "gdb", "gdb-multiarch", "strace", "ltrace",
        "patchelf", "nasm", "yasm", "valgrind", "qemu-user", "qemu-utils", "device-tree-compiler",
    ),
    "Archives, media and file forensics": (
        "unzip", "zip", "xz-utils", "zstd", "tar", "gzip", "bzip2", "7zip", "cpio", "cabextract",
        "squashfs-tools", "libimage-exiftool-perl", "pngcheck", "sleuthkit", "sqlite3", "qpdf",
        "poppler-utils", "mediainfo", "ffmpeg", "sox", "tesseract-ocr", "qrencode", "zbar-tools",
        "foremost", "testdisk", "apktool", "steghide", "imagemagick", "libsox-fmt-all",
    ),
}
PACKAGES = tuple(package for group in (*FOUNDATION.values(), *LAB_TOOLS.values()) for package in group)
PACKAGE_ALTERNATIVES = {"7zip": "p7zip-full", "bind9-dnsutils": "dnsutils"}
SYSTEM_PATH = "/usr/bin:/bin:/usr/sbin:/sbin"
COMMAND_CHECKS = {
    "git": ("git", "--version"),
    "curl": ("curl", "--version"),
    "tmux": ("tmux", "-V"),
    "ripgrep": ("rg", "--version"),
    "jq": ("jq", "--version"),
    "bat": (("bat", "batcat"), "--version"),
    "fd-find": (("fd", "fdfind"), "--version"),
    "fastfetch": ("fastfetch", "--version"),
    "bind9-dnsutils": ("dig", "-v"),
    "tcpdump": ("tcpdump", "--version"),
    "build-essential": ("gcc", "--version"),
    "clang": ("clang", "--version"),
    "cmake": ("cmake", "--version"),
    "ninja-build": ("ninja", "--version"),
    "ruby-full": ("ruby", "--version"),
    "bundler": ("bundle", "--version"),
    "default-jdk-headless": ("javac", "-version"),
    "nodejs": ("node", "--version"),
    "npm": ("npm", "--version"),
    "golang-go": ("go", "version"),
    "rustc": ("rustc", "--version"),
    "cargo": ("cargo", "--version"),
    "rustfmt": ("rustfmt", "--version"),
    "file": ("file", "--version"),
    "binutils": ("readelf", "--version"),
    "gdb": ("gdb", "-nx", "--version"),
    "strace": ("strace", "--version"),
    "qemu-user": ("qemu-aarch64", "--version"),
    "qemu-utils": ("qemu-img", "--version"),
    "device-tree-compiler": ("dtc", "--version"),
    "7zip": (("7z", "7zz"), "-h"),
    "libimage-exiftool-perl": ("exiftool", "-ver"),
    "sqlite3": ("sqlite3", "--version"),
    "qpdf": ("qpdf", "--version"),
    "ffmpeg": ("ffmpeg", "-version"),
    "apktool": ("apktool", "--version"),
}
OLD_ACTIVATION = re.compile(
    rb"^# >>> init Python tools >>>\r?\n.*?^# <<< init Python tools <<<(?:\r?\n|\Z)",
    re.MULTILINE | re.DOTALL,
)


def color(text, code):
    if sys.stdout.isatty() and not os.environ.get("NO_COLOR") and os.environ.get("TERM") != "dumb":
        return "\033[{}m{}\033[0m".format(code, text)
    return text


def status(label, message, code):
    print("  {} {}".format(color("[{}]".format(label), code), message), flush=True)


def stage(number, name):
    print("\n" + color("[{}/4] {}".format(number, name), "1;34"), flush=True)


def preflight():
    if not sys.platform.startswith("linux"):
        raise RuntimeError("This installer requires Linux with APT.")
    for command in ("apt-get", "apt-cache", "dpkg-query"):
        if not shutil.which(command, path=SYSTEM_PATH):
            raise RuntimeError("Missing system command: " + command)
    os_release = Path("/etc/os-release")
    release_lines = os_release.read_text(encoding="utf-8").splitlines() if os_release.is_file() else []
    name = next((line.partition("=")[2].strip('"') for line in release_lines if line.startswith("PRETTY_NAME=")), "Linux")
    status("ok", "{} · {} · system Python {}".format(name, platform.machine(), PYTHON), "32")


def installed_packages():
    result = subprocess.run(
        ["dpkg-query", "-W", "-f=${db:Status-Status}\t${Package}\n", *PACKAGES, *PACKAGE_ALTERNATIVES.values()],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        universal_newlines=True,
    )
    return {line.split("\t", 1)[1] for line in result.stdout.splitlines() if line.startswith("installed\t")}


def available_packages(packages):
    if not packages:
        return set()
    result = subprocess.run(
        ["apt-cache", "--no-all-versions", "show", *packages],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        universal_newlines=True,
    )
    return {line[9:] for line in result.stdout.splitlines() if line.startswith("Package: ")}


def select_package(package, installed, available):
    alternate = PACKAGE_ALTERNATIVES.get(package)
    if package not in installed and (alternate in installed or (package not in available and alternate in available)):
        return alternate
    return package


def refresh_index(apt, installed):
    missing = [package for package in PACKAGES if select_package(package, installed, set()) not in installed]
    if not missing:
        return set()
    candidates = missing + [PACKAGE_ALTERNATIVES[p] for p in missing if p in PACKAGE_ALTERNATIVES]
    if (set(PYTHON_PACKAGES).intersection(missing) or available_packages(candidates)
            or not any(Path("/var/lib/apt/lists").glob("*_Packages*"))):
        if os.geteuid() and not shutil.which("sudo", path=SYSTEM_PATH):
            raise RuntimeError("APT needs sudo to install missing packages. Run from a root shell or install sudo.")
        status("update", "APT package indexes", "36")
        subprocess.run([*apt, "-o", "APT::Update::Error-Mode=any", "update"], check=True)
        return available_packages(candidates)
    return set()


def install_packages(groups, apt, installed, available):
    pending = []
    for title, packages in groups.items():
        print(color(title, "1;34"), flush=True)
        for preferred in packages:
            package = select_package(preferred, installed, available)
            if package in installed:
                status("installed", package, "32")
            elif package in available or package in PYTHON_PACKAGES:
                pending.append(package)
                status("install", package, "36")
            else:
                status("unavailable", package, "33")
    if pending:
        subprocess.run([*apt, "install", "-y", "--no-remove", "--no-install-recommends", *pending], check=True)
        installed = installed_packages()
        if not set(pending).issubset(installed):
            raise RuntimeError("APT did not install: " + ", ".join(sorted(set(pending) - installed)))
    return installed


def check_command(label, command, show_output=False):
    try:
        result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                universal_newlines=True, timeout=20,
                                env={**os.environ, "PATH": SYSTEM_PATH, "GOTOOLCHAIN": "local"})
    except (OSError, subprocess.TimeoutExpired) as error:
        status("failed", "{}: {}".format(label, error), "31")
        return False
    lines = result.stdout.strip().splitlines()
    if result.returncode:
        detail = lines[-1] if lines else "exit {}".format(result.returncode)
        status("failed", "{}: {}".format(label, detail), "31")
        return False
    if show_output and lines:
        label += " · " + lines[0]
    status("ok", label, "32")
    return True


def verify_python(installed):
    checks = [check_command(PYTHON, [PYTHON, "--version"], show_output=True)]
    modules = [*LIBRARIES.values(), *(module for package, module in EXTRA_LIBRARIES.items() if package in installed)]
    for module in modules:
        checks.append(check_command("import " + module, [PYTHON, "-I", "-c", "import " + module]))
    return all(checks)


def verify_tools(installed):
    checks = []
    for package, (names, *args) in COMMAND_CHECKS.items():
        if select_package(package, installed, set()) not in installed:
            continue
        if isinstance(names, str):
            names = (names,)
        paths = (shutil.which(name, path=SYSTEM_PATH) for name in names)
        executable = next((path for path in paths if path), None)
        if executable is None:
            status("failed", "{} missing from the system PATH".format(" / ".join(names)), "31")
            checks.append(False)
        else:
            checks.append(check_command(Path(executable).name, [executable, *args], show_output=True))
    if "build-essential" in installed:
        with tempfile.TemporaryDirectory(prefix="init-check-") as directory:
            source = Path(directory) / "check.c"
            binary = source.with_suffix("")
            source.write_text("int main(void) { return 0; }\n", encoding="utf-8")
            compiled = check_command("compile a C program", ["/usr/bin/gcc", str(source), "-o", str(binary)])
            checks.append(compiled and check_command("run the compiled C program", [str(binary)]))
    return all(checks)


def remove_old_activation(home):
    for filename in (".bashrc", ".zshrc"):
        profile = home / filename
        try:
            content = profile.read_bytes()
        except FileNotFoundError:
            continue
        updated = OLD_ACTIVATION.sub(b"", content)
        if updated != content:
            profile.write_bytes(updated)
            print("Removed old Python activation from {}.".format(profile))


def main(args):
    if args:
        print("Usage: python3 init.py", file=sys.stderr)
        return 2

    started = time.monotonic()
    try:
        stage(1, "Environment check")
        preflight()
        apt = ["sudo"] if os.geteuid() else []
        apt += ["apt-get", "-o", "Acquire::Retries=2", "-o", "DPkg::Lock::Timeout=60"]
        installed = installed_packages()
        available = refresh_index(apt, installed)

        stage(2, "System foundation")
        installed = install_packages(FOUNDATION, apt, installed, available)
        stage(3, "Lab tools")
        installed = install_packages(LAB_TOOLS, apt, installed, available)

        stage(4, "Verification")
        python_ok = verify_python(installed)
        tools_ok = verify_tools(installed)
        if not (python_ok and tools_ok):
            status("failed", "Lab verification failed", "31")
            return 1
        remove_old_activation(Path.home())
    except (OSError, RuntimeError, subprocess.CalledProcessError) as error:
        status("failed", "Lab setup: {}".format(error), "31")
        return 1

    ready = sum(select_package(package, installed, set()) in installed for package in PACKAGES)
    status("ok", "{}/{} system packages ready in {:.1f}s".format(ready, len(PACKAGES), time.monotonic() - started), "32")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
