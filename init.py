#!/usr/bin/env python3
"""Install and verify system packages for the lab with APT."""
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
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
PACKAGE_GROUPS = {
    "System Python": (*PYTHON_PACKAGES, PYTHON_ALIAS),
    "Shell and everyday tools": (
        "ca-certificates", "curl", "wget", "git", "rsync", "openssh-client",
        "zsh", "bash-completion", "shellcheck", "vim", "nano", "tmux", "tree",
        "bat", "fd-find", "ripgrep", "fzf", "zoxide", "duf", "btop", "htop", "ncdu", "jq", "yq",
    ),
    "Build and development tools": (
        "build-essential", "pkg-config", "clang", "llvm", "lld", "cmake", "ninja-build", "meson",
        "autoconf", "automake", "libtool", "gawk", "bison", "flex", "gettext", "patch",
        "libssl-dev", "libffi-dev", "zlib1g-dev", "libbz2-dev", "liblzma-dev", "libsqlite3-dev",
    ),
    "Binary inspection and debugging": (
        "file", "binutils", "elfutils", "xxd", "gdb", "gdb-multiarch", "strace", "ltrace",
        "patchelf", "nasm", "valgrind", "qemu-user",
    ),
    "Archives, media and file forensics": (
        "unzip", "zip", "xz-utils", "zstd", "tar", "gzip", "bzip2", "7zip", "cpio", "cabextract",
        "squashfs-tools", "libimage-exiftool-perl", "pngcheck", "sleuthkit", "sqlite3", "qpdf",
        "poppler-utils", "mediainfo", "ffmpeg", "sox", "tesseract-ocr", "qrencode", "zbar-tools",
    ),
}
PACKAGES = tuple(package for group in PACKAGE_GROUPS.values() for package in group)
COMMAND_CHECKS = {
    "git": ("git", "--version"),
    "curl": ("curl", "--version"),
    "tmux": ("tmux", "-V"),
    "ripgrep": ("rg", "--version"),
    "jq": ("jq", "--version"),
    "build-essential": ("gcc", "--version"),
    "clang": ("clang", "--version"),
    "cmake": ("cmake", "--version"),
    "ninja-build": ("ninja", "--version"),
    "file": ("file", "--version"),
    "binutils": ("readelf", "--version"),
    "gdb": ("gdb", "-nx", "--version"),
    "strace": ("strace", "--version"),
    "qemu-user": ("qemu-aarch64", "--version"),
    "libimage-exiftool-perl": ("exiftool", "-ver"),
    "sqlite3": ("sqlite3", "--version"),
    "qpdf": ("qpdf", "--version"),
    "ffmpeg": ("ffmpeg", "-version"),
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


def installed_packages():
    result = subprocess.run(
        ["dpkg-query", "-W", "-f=${db:Status-Status}\t${Package}\n", *PACKAGES],
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


def install_packages():
    installed = installed_packages()
    missing = [package for package in PACKAGES if package not in installed]
    required = set(PYTHON_PACKAGES)
    apt = ["sudo"] if os.geteuid() else []
    apt += ["apt-get", "-o", "Acquire::Retries=2", "-o", "DPkg::Lock::Timeout=60"]
    available = set()
    if required.intersection(missing) or available_packages(missing):
        status("update", "APT package indexes", "36")
        subprocess.run([*apt, "-o", "APT::Update::Error-Mode=any", "update"], check=True)
        available = available_packages(missing)

    pending = [package for package in missing if package in available or package in required]
    for title, packages in PACKAGE_GROUPS.items():
        print(color(title, "1;34"), flush=True)
        for package in packages:
            if package in installed:
                status("installed", package, "32")
            elif package in pending:
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
                                universal_newlines=True, timeout=20)
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


def verify_python():
    checks = [check_command(PYTHON, [PYTHON, "--version"], show_output=True)]
    for module in LIBRARIES.values():
        checks.append(check_command("import " + module, [PYTHON, "-I", "-c", "import " + module]))
    return all(checks)


def verify_tools(installed):
    checks = []
    for package, (command, *args) in COMMAND_CHECKS.items():
        if package not in installed:
            continue
        executable = shutil.which(command, path="/usr/bin:/bin:/usr/sbin:/sbin")
        if executable is None:
            status("failed", "{} missing from the system PATH".format(command), "31")
            checks.append(False)
        else:
            checks.append(check_command(command, [executable, *args], show_output=True))
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
        print(color("[1/2] Install system packages", "1;34"), flush=True)
        installed = install_packages()
        print(color("\n[2/2] Verify system tools and Python", "1;34"), flush=True)
        python_ok = verify_python()
        tools_ok = verify_tools(installed)
        if not (python_ok and tools_ok):
            status("failed", "Lab verification failed", "31")
            return 1
        remove_old_activation(Path.home())
    except (OSError, RuntimeError, subprocess.CalledProcessError) as error:
        status("failed", "Lab setup: {}".format(error), "31")
        return 1

    status("ok", "{} system packages ready in {:.1f}s".format(len(installed), time.monotonic() - started), "32")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
