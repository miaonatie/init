#!/usr/bin/env python3
"""Install and verify the CTF lab on Debian-family systems with APT.

Layers, in install order:

1. environment check
2. system Python and its libraries, plus everyday shell networking tools
3. lab tools: compilers, debuggers, forensics, pwn tooling
   (APT first; pip only fills what APT does not ship)
4. verification, plus shell defaults

The IoT firmware lab is a separate layer: `--iot` installs it, `--iot-check`
inspects it. Nothing here removes or upgrades an installed package.
"""
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

# Modules the interpreter must provide for the installer and everyday scripting.
BASE_LIBRARIES = {
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

# CTF-facing libraries that Debian-family archives ship. Every entry is
# optional: a release that predates the package reports it as skipped. A value
# may be a tuple of import names because packaging differs: Debian's
# pycryptodome ships as `Cryptodome`, PyPI's as `Crypto`.
CTF_LIBRARIES = {
    "python3-pyelftools": ("elftools",),
    "python3-zstandard": ("zstandard",),
    "python3-gmpy2": ("gmpy2",),
    "python3-capstone": ("capstone",),
    "python3-unicorn": ("unicorn",),
    "python3-z3": ("z3",),
    "python3-pycryptodome": ("Crypto", "Cryptodome"),
    "python3-sortedcontainers": ("sortedcontainers",),
    "python3-intervaltree": ("intervaltree",),
    "python3-mako": ("mako",),
    "python3-psutil": ("psutil",),
    "python3-paramiko": ("paramiko",),
    "python3-colored-traceback": ("colored_traceback",),
    "python3-dateutil": ("dateutil",),
    "python3-pygments": ("pygments",),
    "python3-packaging": ("packaging",),
    "python3-six": ("six",),
    "python3-socks": ("socks",),
    "python3-serial": ("serial",),
    "python3-rpyc": ("rpyc",),
}

# Python command-line tools. APT ships pwntools and ROPgadget on current
# releases; ropper always comes from pip, which needs Python 3.8 or newer.
PYTHON_CLI = {
    "pwntools": ("pwn", ["--help"]),
    "ROPgadget": ("ROPgadget", ["--version"]),
    "ropper": ("ropper", ["--version"]),
}
PWN_SUBCOMMANDS = ("checksec", "cyclic", "asm", "disasm", "shellcraft")
PWNLIB_NOTERM = "1"

# PyPI filebytes still calls ast.Str at build time, which Python 3.14 removed.
# ropper needs the merged upstream fix (sashs/filebytes#36) until it is released.
FILEBYTES_FIX = (
    "filebytes @ https://codeload.github.com/sashs/filebytes/tar.gz/"
    "ff7492d750140288e2c3ff25b8a648719be470ce"
    "#sha256=38ccb58dc9d3d5076584232880208a08fc57e9db515d63f1f36e08a1579a922b"
    " ; python_version >= '3.14'"
)
PIP_REQUIREMENTS = {
    "pwntools": ("pwntools",),
    "ROPgadget": ("ROPgadget",),
    "ropper": (FILEBYTES_FIX, "ropper"),
}
PIP_ATTEMPTS = 2
PIP_NETWORK = ("--retries", "5", "--timeout", "60")
PYTHON_TOOLS_MIN_VERSION = (3, 8)

PYTHON_PACKAGES = ("python3", "python3-dev", *BASE_LIBRARIES)

FOUNDATION = {
    "System Python": (*PYTHON_PACKAGES, *CTF_LIBRARIES, PYTHON_ALIAS),
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
        "golang-go", "rustc", "cargo", "rustfmt",
    ),
    "Binary inspection and debugging": (
        "file", "binutils", "elfutils", "xxd", "gdb", "gdb-multiarch", "strace", "ltrace",
        "patchelf", "nasm", "yasm", "valgrind", "qemu-user", "qemu-utils", "device-tree-compiler",
    ),
    # APT provides pwntools and ROPgadget on current releases. Older releases and
    # ropper are filled in by the pip fallback in the Python CTF tools group.
    "Pwn and exploitation": (
        "gdbserver", "socat", "netcat-openbsd", "libc6-dbg", "seccomp", "libseccomp-dev",
        "python3-pwntools", "python3-ropgadget", "radare2",
    ),
    "Archives, media and file forensics": (
        "unzip", "zip", "xz-utils", "zstd", "tar", "gzip", "bzip2", "7zip", "cpio", "cabextract",
        "squashfs-tools", "libimage-exiftool-perl", "pngcheck", "sleuthkit", "sqlite3", "qpdf",
        "poppler-utils", "mediainfo", "ffmpeg", "sox", "tesseract-ocr", "qrencode", "zbar-tools",
        "foremost", "testdisk", "apktool", "steghide", "binwalk", "imagemagick", "libsox-fmt-all",
    ),
}

# IoT firmware lab. The shared entries already live in LAB_TOOLS; --iot adds
# them explicitly so the action works on a host that never ran a full install.
# Prerequisites cover the tools --iot itself needs but the lab layer does not
# provide: git for the FirmAE checkout, curl/ca-certificates for downloads.
IOT_PREREQUISITES = ("git", "curl", "ca-certificates")
IOT_SHARED = ("qemu-user", "qemu-utils", "gdb-multiarch", "device-tree-compiler",
              "squashfs-tools", "cpio")
IOT_ONLY = ("qemu-system-arm", "qemu-system-mips", "binutils-multiarch",
            "mtd-utils", "lzop", "lzma")
IOT_PACKAGES = (*IOT_PREREQUISITES, *IOT_SHARED, *IOT_ONLY)
IOT_GROUPS = {
    "IoT download prerequisites": IOT_PREREQUISITES,
    "IoT firmware and emulation": (*IOT_SHARED, *IOT_ONLY),
}
IOT_RUNTIME = Path.home() / ".local/share/init/iot"
IOT_ASSETS = ("lab.py", "Dockerfile", "entrypoint.sh", "USAGE.md")
IOT_LAUNCHERS = ("firmae", "iot-help")
FIRMAE_REPO = "https://github.com/pr0v3rbs/FirmAE.git"
FIRMAE_DIR = Path.home() / "tools/FirmAE"
FIRMAE_REVISION = "653565b5d14e6d69a1dd242aa88ecfb4b090a74a"
QILING_DIR = Path.home() / ".local/share/init/qiling"
IOT_PROBES = {
    "qemu-aarch64": ["--version"],
    "qemu-mipsel": ["--version"],
    "qemu-img": ["--version"],
    "dtc": ["--version"],
    "gdb-multiarch": ["--version"],
}

PACKAGES = tuple(dict.fromkeys(
    package
    for group_packages in (*FOUNDATION.values(), *LAB_TOOLS.values(), *[IOT_PACKAGES])
    for package in group_packages
))
PACKAGE_ALTERNATIVES = {"7zip": "p7zip-full", "bind9-dnsutils": "dnsutils"}
# Verification and launcher probes resolve through this fixed path. /usr/local/bin
# must be present: pip installs its console scripts there, and the pwn wrappers
# this installer writes also live there.
SYSTEM_PATH = "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
APT_INSTALL = ("install", "-y", "--no-remove", "--no-install-recommends")
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
    "strace": ("strace", "-V"),
    "qemu-user": ("qemu-aarch64", "--version"),
    "qemu-utils": ("qemu-img", "--version"),
    "device-tree-compiler": ("dtc", "--version"),
    "7zip": (("7z", "7zz"), "-h"),
    "libimage-exiftool-perl": ("exiftool", "-ver"),
    "sqlite3": ("sqlite3", "--version"),
    "qpdf": ("qpdf", "--version"),
    "ffmpeg": ("ffmpeg", "-version"),
    "apktool": ("apktool", "--version"),
    "gdbserver": ("gdbserver", "--version"),
    "socat": ("socat", "-V"),
    "netcat-openbsd": ("nc", "-h"),
    "radare2": ("r2", "-v"),
}
OLD_ACTIVATION = re.compile(
    rb"^# >>> init Python tools >>>\r?\n.*?^# <<< init Python tools <<<\r?\n?",
    re.MULTILINE | re.DOTALL,
)
NVM_STARTUP = re.compile(
    rb'^([ \t]*\[ -s "\$NVM_DIR/nvm\.sh" \] && (?:\\?\.|source) "\$NVM_DIR/nvm\.sh")'
    rb'([ \t]*(?:#[^\r\n]*)?)(?=\r?$)',
    re.MULTILINE,
)
RUSTUP_STARTUP = re.compile(
    rb'^(# >>> init rustup >>>)(\r?\n)\[ -f "\$HOME/\.cargo/env" \] && \. "\$HOME/\.cargo/env"\r?\n'
    rb'(?=# <<< init rustup <<<\r?$)',
    re.MULTILINE,
)
CARGO_FALLBACK = b'''if [ -d "${CARGO_HOME:-$HOME/.cargo}/bin" ]; then
    case ":$PATH:" in
        *":${CARGO_HOME:-$HOME/.cargo}/bin:"*) ;;
        *) export PATH="$PATH:${CARGO_HOME:-$HOME/.cargo}/bin" ;;
    esac
fi
'''
SYSTEM_TOOLS = re.compile(
    rb"^# >>> init system tools >>>\r?\n.*?^# <<< init system tools <<<\r?\n?",
    re.MULTILINE | re.DOTALL,
)
LINK_STAGES = 4


def system_tool_path(node, rust):
    rules = []
    if node:
        rules.append(b'        "$HOME"/.nvm/versions/node/*/bin|"$HOME"/tools/nvm/versions/node/*/bin|'
                     b'"${NVM_DIR:-$HOME/.nvm}"/versions/node/*/bin|"${NVM_BIN:-/dev/null}") continue ;;')
    if rust:
        rules.append(b'        "${CARGO_HOME:-$HOME/.cargo}/bin") continue ;;')
    if not rules:
        return b""
    return b"\n".join([
        b"# >>> init system tools >>>",
        b"_init_rest=$PATH:",
        b"_init_path=",
        b'while [ -n "$_init_rest" ]; do',
        b"    _init_entry=${_init_rest%%:*}",
        b"    _init_rest=${_init_rest#*:}",
        b'    case "$_init_entry" in',
        *rules,
        b"    esac",
        b"    _init_path=$_init_path$_init_entry:",
        b"done",
        b'export PATH="${_init_path%:}"',
        b"unset _init_rest _init_path _init_entry",
        *([b"unset NVM_BIN NVM_INC"] if node else []),
        *([CARGO_FALLBACK.rstrip(b"\n")] if rust else []),
        b"# <<< init system tools <<<",
        b"",
    ])


def color(text, code):
    if sys.stdout.isatty() and not os.environ.get("NO_COLOR") and os.environ.get("TERM") != "dumb":
        return "\033[{}m{}\033[0m".format(code, text)
    return text


def status(label, message, code):
    line = "  {} {}".format(color("[{}]".format(label), code), message)
    encoding = sys.stdout.encoding
    if encoding:
        line = line.encode(encoding, errors="backslashreplace").decode(encoding)
    print(line, flush=True)


def stage(number, name, total=LINK_STAGES):
    print("\n" + color("[{}/{}] {}".format(number, total, name), "1;34"), flush=True)


def group(title):
    print(color(title, "1;34"), flush=True)


def privilege(apt):
    return ["sudo"] if apt and apt[0] == "sudo" else []


def quote(part):
    return "'" + str(part).replace("'", "'\\''") + "'"


def write_root_file(apt, path, text):
    """Install one root-owned launcher without a shell redirect."""
    with tempfile.TemporaryDirectory(prefix="init-cmd-") as directory:
        staged = Path(directory) / path.name
        staged.write_text(text, encoding="utf-8")
        subprocess.run([*privilege(apt), "install", "-D", "-m", "0755", str(staged), str(path)], check=True)
    status("ok", "installed {}".format(path), "32")


def launcher(apt, name, command):
    """Write an executable wrapper that never starts a curses terminal."""
    parts = " ".join(quote(part) for part in command)
    write_root_file(apt, Path("/usr/local/bin") / name,
                    "#!/bin/sh\nPWNLIB_NOTERM={} exec {} \"$@\"\n".format(PWNLIB_NOTERM, parts))


def preflight():
    if not sys.platform.startswith("linux"):
        raise RuntimeError("This installer requires Linux with APT.")
    for command in ("apt-get", "apt-cache", "dpkg-query"):
        if not shutil.which(command, path=SYSTEM_PATH):
            raise RuntimeError("Missing system command: " + command)
    os_release = Path("/etc/os-release")
    release_lines = os_release.read_text(encoding="utf-8").splitlines() if os_release.is_file() else []
    name = next((line.partition("=")[2].strip('"') for line in release_lines if line.startswith("PRETTY_NAME=")), "Linux")
    status("ok", "{} - {} - system Python {}".format(name, platform.machine(), PYTHON), "32")


def installed_packages():
    result = subprocess.run(
        ["dpkg-query", "-W", "-f=${db:Status-Status}\t${Package}\n", *PACKAGES, *PACKAGE_ALTERNATIVES.values()],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        encoding="utf-8",
        errors="replace",
    )
    return {line.split("\t", 1)[1] for line in result.stdout.splitlines() if line.startswith("installed\t")}


def available_packages(packages):
    if not packages:
        return set()
    result = subprocess.run(
        ["apt-cache", "--no-all-versions", "show", *packages],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        encoding="utf-8",
        errors="replace",
    )
    return {line[9:] for line in result.stdout.splitlines() if line.startswith("Package: ")}


def select_package(package, installed, available):
    alternate = PACKAGE_ALTERNATIVES.get(package)
    if package not in installed and (alternate in installed or (package not in available and alternate in available)):
        return alternate
    return package


def apt_installable(packages):
    result = subprocess.run(["/usr/bin/apt-get", "-s", *APT_INSTALL, *packages],
                            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    return result.returncode == 0 and not any(line.startswith(b"Remv ") for line in (result.stdout or b"").splitlines())


def grouped_packages(groups):
    return tuple(dict.fromkeys(package for packages in groups.values() for package in packages))


def refresh_index(apt, installed, groups=None):
    """Refresh APT indexes only when this run actually has something to install.

    `groups` narrows the check to the layers being installed, so a layer that is
    deliberately deferred (the IoT lab) cannot force a refresh on every run.
    """
    wanted = grouped_packages(groups) if groups else PACKAGES
    missing = [package for package in wanted if select_package(package, installed, set()) not in installed]
    if not missing:
        return set()
    candidates = missing + [PACKAGE_ALTERNATIVES[p] for p in missing if p in PACKAGE_ALTERNATIVES]
    required = set(PYTHON_PACKAGES).intersection(missing)
    cached = set() if required else available_packages(candidates)
    # An already known dependency conflict does not require a network refresh on every run.
    if cached == {"npm"} and not apt_installable(["npm"]):
        return cached
    if required or cached or not any(Path("/var/lib/apt/lists").glob("*_Packages*")):
        if os.geteuid() and not shutil.which("sudo", path=SYSTEM_PATH):
            raise RuntimeError("APT needs sudo to install missing packages. Run from a root shell or install sudo.")
        status("update", "APT package indexes", "36")
        subprocess.run([*apt, "-o", "APT::Update::Error-Mode=any", "update"], check=True)
        return available_packages(candidates)
    return set()


def install_packages(groups, apt, installed, available):
    selected = {title: [select_package(package, installed, available) for package in packages]
                for title, packages in groups.items()}
    pending = [package for packages in selected.values() for package in packages
               if package not in installed and (package in available or package in PYTHON_PACKAGES)]
    # Older npm pulls in Node development headers that may conflict with the system OpenSSL headers.
    npm_conflict = False
    if "npm" in pending and not apt_installable(pending):
        without_npm = [package for package in pending if package != "npm"]
        if not without_npm or apt_installable(without_npm):
            pending = without_npm
            npm_conflict = True

    for title, packages in selected.items():
        group(title)
        for package in packages:
            if package in installed:
                status("installed", package, "32")
            elif package in pending:
                status("install", package, "36")
            elif package == "npm" and npm_conflict:
                status("skipped", "npm conflicts with the system APT toolchain", "33")
            else:
                status("unavailable", package, "33")
    if pending:
        subprocess.run([*apt, *APT_INSTALL, *pending], check=True)
        installed = installed_packages()
        if not set(pending).issubset(installed):
            raise RuntimeError("APT did not install: " + ", ".join(sorted(set(pending) - installed)))
    return installed


def python_version():
    """(major, minor) of the interpreter this file installs packages for."""
    try:
        result = subprocess.run([PYTHON, "-c", "import sys; print('%d.%d' % sys.version_info[:2])"],
                                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                encoding="utf-8", errors="replace", timeout=20)
    except (OSError, subprocess.SubprocessError):
        return None
    parts = (result.stdout or "").strip().split(".")
    if result.returncode or len(parts) != 2 or not all(part.isdigit() for part in parts):
        return None
    return tuple(int(part) for part in parts)


def externally_managed():
    """True when PEP 668 forbids plain pip writes into this interpreter."""
    return any(Path("/usr/lib").glob("python3*/EXTERNALLY-MANAGED"))


def missing_python_cli():
    """Tools whose command is absent, plus those that exist but no longer launch.

    A launcher can survive an interpreter upgrade while its module is gone; that
    case must be reinstalled, not silently accepted as present.
    """
    states = cli_states()
    return [name for name, state in states.items() if state != "ok"]


def broken_python_cli():
    return [name for name, state in cli_states().items() if state == "broken"]


def cli_states():
    """Map every Python CLI to 'ok', 'missing' or 'broken' by launching it."""
    states = {}
    for name, (command, arguments) in PYTHON_CLI.items():
        executable = shutil.which(command, path=SYSTEM_PATH)
        if executable is None:
            states[name] = "missing"
            continue
        try:
            result = subprocess.run([executable, *arguments], stdout=subprocess.DEVNULL,
                                    stderr=subprocess.DEVNULL, timeout=60,
                                    env={**os.environ, "PATH": SYSTEM_PATH,
                                         "PWNLIB_NOTERM": PWNLIB_NOTERM})
        except (OSError, subprocess.SubprocessError):
            states[name] = "broken"
            continue
        states[name] = "ok" if result.returncode == 0 else "broken"
    return states


def pip_install(apt, names):
    """Install the named Python CLI tools, one package at a time so a single
    failure cannot hide the others. A surviving-but-broken launcher gets a
    forced reinstall of package files only, preserving shared dependencies.
    Network failures are retried once before the tool is reported."""
    flags = ["--break-system-packages"] if externally_managed() else []
    base = [PYTHON, "-m", "pip", "install", "--disable-pip-version-check",
            "--no-warn-script-location", *PIP_NETWORK, *flags]
    broken = set(broken_python_cli())
    installed = []
    for name in names:
        repair = ["--force-reinstall", "--no-deps"] if name in broken else []
        command = [*privilege(apt), *base, *repair, *PIP_REQUIREMENTS[name]]
        for attempt in range(1, PIP_ATTEMPTS + 1):
            status("pip", "{}{}".format(name, "" if attempt == 1 else " (retry {})".format(attempt - 1)), "36")
            try:
                result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                        encoding="utf-8", errors="replace", timeout=1200)
            except (OSError, subprocess.SubprocessError) as error:
                last = str(error)
                continue
            if result.returncode == 0:
                installed.append(name)
                last = None
                break
            lines = [line for line in (result.stdout or "").splitlines() if line.strip()]
            last = lines[-1] if lines else "exit {}".format(result.returncode)
        if name not in installed:
            status("failed", "pip install {}: {}".format(name, last), "31")
    return installed


def install_python_tools(apt):
    """Fill in the Python CTF tools APT does not provide, then add pwn wrappers."""
    group("Python CTF tools")
    for name in broken_python_cli():
        status("repair", "{} launcher exists but no longer runs".format(name), "36")
    missing = missing_python_cli()
    if missing:
        version = python_version()
        if version is not None and version >= PYTHON_TOOLS_MIN_VERSION:
            pip_install(apt, missing)
        else:
            for name in missing:
                status("skipped", "{} (needs Python {}+ or an APT build; this release has {})".format(
                    name,
                    ".".join(str(part) for part in PYTHON_TOOLS_MIN_VERSION),
                    ".".join(str(part) for part in version) if version else "an unknown interpreter"), "33")
    install_pwn_wrappers(apt)


PWN_MODULE_ENTRY = (
    'import sys; from pwnlib.commandline.main import main; '
    'sys.argv[0] = "pwn"; sys.exit(main())'
)


def writes_noterm(path):
    """True when this launcher already sets PWNLIB_NOTERM, so it stays idempotent."""
    try:
        return b"PWNLIB_NOTERM" in Path(path).read_bytes()
    except OSError:
        return False


def install_pwn_wrappers(apt):
    """Make every pwntools entry point quiet and reachable.

    APT's pwntools ships only /usr/bin/pwn, and pip's console script prints a
    curses warning when no terminfo database exists. Both cases get a launcher
    under /usr/local/bin that sets PWNLIB_NOTERM and calls the library entry
    point directly, so no wrapper ever recurses into itself.
    """
    pwn = shutil.which("pwn", path=SYSTEM_PATH)
    if pwn is None:
        return
    for name in PWN_SUBCOMMANDS:
        existing = shutil.which(name, path=SYSTEM_PATH)
        if existing is None:
            launcher(apt, name, [pwn, name])
    if not writes_noterm(pwn):
        launcher(apt, "pwn", [PYTHON, "-c", PWN_MODULE_ENTRY])


def check_command(label, command, show_output=False):
    try:
        result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                encoding="utf-8", errors="replace", timeout=20,
                                env={**os.environ, "PATH": SYSTEM_PATH, "GOTOOLCHAIN": "local",
                                     "PWNLIB_NOTERM": PWNLIB_NOTERM})
    except (OSError, subprocess.SubprocessError) as error:
        status("failed", "{}: {}".format(label, error), "31")
        return False
    lines = (result.stdout or "").strip().splitlines()
    if result.returncode:
        detail = lines[-1] if lines else "exit {}".format(result.returncode)
        status("failed", "{}: {}".format(label, detail), "31")
        return False
    if show_output and lines:
        label += " - " + lines[0]
    status("ok", label, "32")
    return True


def module_names(value):
    return (value,) if isinstance(value, str) else tuple(value)


def verify_python(installed):
    """Import every library APT installed. Missing optional ones are reported."""
    checks = [check_command(PYTHON, [PYTHON, "--version"], show_output=True)]
    for package, value in (*BASE_LIBRARIES.items(), *CTF_LIBRARIES.items()):
        modules = module_names(value)
        label = "import " + " / ".join(modules)
        if package not in installed:
            status("skipped", "{} ({} is not installed)".format(label, package), "33")
            continue
        checks.append(check_command(label, [PYTHON, "-I", "-c", import_probe(modules)]))
    return all(checks)


def import_probe(modules):
    """Exit 0 when any of the alternative module names imports."""
    return (
        "import importlib, sys\n"
        "for name in {!r}:\n"
        "    try:\n"
        "        importlib.import_module(name)\n"
        "    except ImportError:\n"
        "        continue\n"
        "    sys.exit(0)\n"
        "sys.exit(1)\n"
    ).format(list(modules))


def verify_python_cli():
    """pwn and the other Python CLIs must actually launch, not just exist."""
    checks = []
    pwn = shutil.which("pwn", path=SYSTEM_PATH)
    if pwn is None:
        status("skipped", "pwntools (no pwn command)", "33")
    for name, (command, arguments) in PYTHON_CLI.items():
        executable = shutil.which(command, path=SYSTEM_PATH)
        if executable is None:
            status("skipped", "{} (not installed)".format(name), "33")
            continue
        checks.append(check_command(name, [executable, *arguments]))
    if pwn is None:
        return all(checks)
    for name in PWN_SUBCOMMANDS:
        executable = shutil.which(name, path=SYSTEM_PATH)
        if executable is None:
            status("failed", "{} wrapper missing; rerun the installer".format(name), "31")
            checks.append(False)
            continue
        checks.append(check_command(name, [executable, "--help"]))
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


def install_iot_assets(apt):
    """Stage the firmware lab and its launchers; no network access."""
    assets = Path(__file__).resolve().parent / "iot"
    IOT_RUNTIME.mkdir(parents=True, exist_ok=True)
    for name in IOT_ASSETS:
        source = assets / name
        if not source.is_file():
            raise RuntimeError("IoT asset missing: {}; use a complete git checkout".format(source))
        destination = IOT_RUNTIME / name
        content = source.read_bytes()
        if not destination.is_file() or destination.read_bytes() != content:
            destination.write_bytes(content)
    config = IOT_RUNTIME / "config.json"
    expected = '{{\n  "firmae": "{}",\n  "revision": "{}",\n  "qiling": "{}"\n}}\n'.format(
        FIRMAE_DIR, FIRMAE_REVISION, QILING_DIR)
    if not config.is_file() or config.read_text(encoding="utf-8") != expected:
        config.write_text(expected, encoding="utf-8")
    status("ok", "IoT lab assets in {}".format(IOT_RUNTIME), "32")
    for name in IOT_LAUNCHERS:
        command = [PYTHON, str(IOT_RUNTIME / "lab.py")] + (["help"] if name == "iot-help" else [])
        launcher(apt, name, command)


def firmae_ready():
    return (FIRMAE_DIR / ".git").is_dir()


def install_firmae(apt):
    """Clone FirmAE at the pinned revision and build its image when Docker is up."""
    if platform.machine().lower() not in ("x86_64", "amd64"):
        status("skipped", "FirmAE (needs an x86_64 host; QEMU and Qiling still work)", "33")
        return
    if not firmae_ready():
        status("clone", FIRMAE_REPO, "36")
        result = subprocess.run([*privilege(apt), "git", "clone", "--depth", "1", FIRMAE_REPO, str(FIRMAE_DIR)],
                                check=False)
        if result.returncode:
            status("failed", "FirmAE clone failed; rerun with --iot", "31")
            return
    subprocess.run(["git", "-C", str(FIRMAE_DIR), "fetch", "--depth", "1", "origin", FIRMAE_REVISION],
                   check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    build = subprocess.run([PYTHON, str(IOT_RUNTIME / "lab.py"), "build", "--if-available"], check=False)
    if build.returncode == 3:
        status("skipped", "FirmAE image (Docker daemon unavailable; run firmae build later)", "33")
    elif build.returncode:
        status("failed", "FirmAE image build; retry with firmae build", "31")


def firmae_status():
    """Run `lab.py status`; returns 0 ready, 3 pending, 1 broken or missing."""
    lab = IOT_RUNTIME / "lab.py"
    if not lab.is_file():
        return 1
    try:
        result = subprocess.run([PYTHON, str(lab), "status"], check=False,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                encoding="utf-8", errors="replace", timeout=120)
    except (OSError, subprocess.SubprocessError):
        return 1
    return result.returncode


def verify_iot():
    """Check the IoT layer without starting a container or a build.

    A host that never ran --iot reports IoT as deferred rather than failing, so
    a normal install stays green on machines that do not need firmware work.
    """
    checks = []
    installed_probe = [name for name in IOT_PROBES if shutil.which(name, path=SYSTEM_PATH)]
    if not installed_probe:
        status("skipped", "IoT layer (not installed; run --iot)", "33")
        return True
    for name in installed_probe:
        checks.append(check_command(name, [shutil.which(name, path=SYSTEM_PATH), *IOT_PROBES[name]]))
    for name in IOT_LAUNCHERS:
        executable = shutil.which(name, path=SYSTEM_PATH)
        if executable is None:
            status("failed", "{} launcher missing; rerun --iot".format(name), "31")
            checks.append(False)
            continue
        checks.append(check_command(name, [executable, "--help"]))
    if not firmae_ready():
        status("skipped", "FirmAE source (run --iot, then firmae build)", "33")
        return all(checks)
    code = firmae_status()
    if code == 3:
        status("skipped", "FirmAE image (Docker daemon unavailable or image not built; run firmae build)", "33")
    elif code != 0:
        status("failed", "FirmAE source/image broken; run firmae doctor", "31")
        checks.append(False)
    else:
        checks.append(True)
    return all(checks)


def configure_shell_defaults(home, installed):
    for filename in (".bashrc", ".zshrc"):
        profile = (home / filename).resolve()
        try:
            content = profile.read_bytes()
        except FileNotFoundError:
            continue
        updated = SYSTEM_TOOLS.sub(b"", OLD_ACTIVATION.sub(b"", content))
        node = {"nodejs", "npm"}.issubset(installed) and b"$NVM_DIR/nvm.sh" in updated
        rust = {"rustc", "cargo"}.issubset(installed) and b"# >>> init rustup >>>" in updated
        if node:
            updated = NVM_STARTUP.sub(rb"\1 --no-use\2", updated)
        if rust:
            updated = RUSTUP_STARTUP.sub(
                lambda match: match[1] + match[2] + CARGO_FALLBACK.replace(b"\n", match[2]), updated
            )
        block = system_tool_path(node, rust)
        if block:
            newline = b"\r\n" if b"\r\n" in updated else b"\n"
            if updated and not updated.endswith(b"\n"):
                updated += newline
            updated += block.replace(b"\n", newline)
        if updated == content:
            continue
        with tempfile.TemporaryDirectory(prefix=".init-shell-", dir=profile.parent) as directory:
            temporary = Path(directory) / profile.name
            temporary.write_bytes(updated)
            shutil.copymode(profile, temporary)
            temporary.replace(profile)
        status("ok", "Updated system tool defaults in {}".format(profile), "32")


def help_text():
    return """init - CTF lab installer (system Python, APT first)

Usage:
  python3 init.py             Install and verify the lab
  python3 init.py --check     Verify only; installs nothing
  python3 init.py --check-python
                              Verify only the Python layer; installs nothing
  python3 init.py --iot       Install/repair the IoT firmware lab
  python3 init.py --iot-check Verify the IoT lab; installs nothing
  python3 init.py --help      Show this help

Python libraries come from APT. pwntools and ROPgadget fall back to pip on
releases whose archive predates them; ropper always uses pip, which needs
Python 3.8 or newer. Packages that a release cannot supply are reported as
skipped rather than failing the run. Nothing is removed or upgraded.
"""


def verify_all(installed):
    """Read-only verification of every layer; returns True when all pass."""
    python_ok = verify_python(installed) and verify_python_cli()
    tools_ok = verify_tools(installed)
    iot_ok = verify_iot()
    return python_ok and tools_ok and iot_ok


def run_install(apt, installed):
    available = refresh_index(apt, installed, {**FOUNDATION, **LAB_TOOLS})
    stage(2, "System foundation")
    installed = install_packages(FOUNDATION, apt, installed, available)
    stage(3, "Lab tools")
    installed = install_packages(LAB_TOOLS, apt, installed, available)
    install_python_tools(apt)
    install_iot_assets(apt)

    stage(4, "Verification")
    if not verify_all(installed):
        status("failed", "Lab verification failed", "31")
        return 1
    configure_shell_defaults(Path.home(), installed)
    return 0


def run_iot(apt, installed):
    available = refresh_index(apt, installed, IOT_GROUPS)
    stage(2, "IoT lab", total=3)
    installed = install_packages(IOT_GROUPS, apt, installed, available)
    install_iot_assets(apt)
    install_firmae(apt)
    stage(3, "Verification", total=3)
    if not verify_iot():
        status("failed", "IoT lab verification failed", "31")
        return 1
    return 0


def main(args):
    if args in (["-h"], ["--help"]):
        print(help_text())
        return 0
    actions = {"--check": "check", "--check-python": "check-python",
               "--iot": "iot", "--iot-check": "iot-check"}
    if args and (len(args) != 1 or args[0] not in actions):
        print("Usage: python3 init.py [--check] [--check-python] [--iot] [--iot-check]", file=sys.stderr)
        return 2
    action = actions[args[0]] if args else "install"

    started = time.monotonic()
    installed = set()
    try:
        if action != "check-python":
            stage(1, "Environment check")
        preflight()
        installed = installed_packages()
        if action == "check-python":
            return 0 if verify_python(installed) else 1
        if action == "check":
            stage(4, "Verification")
            if not verify_all(installed):
                status("failed", "Lab verification failed", "31")
                return 1
            status("ok", "lab verified in {:.1f}s".format(time.monotonic() - started), "32")
            return 0
        if action == "iot-check":
            return 0 if verify_iot() else 1

        apt = ["sudo"] if os.geteuid() else []
        apt += ["apt-get", "-o", "Acquire::Retries=2", "-o", "DPkg::Lock::Timeout=60"]
        if action == "iot":
            return run_iot(apt, installed)
        if run_install(apt, installed):
            return 1
    except (OSError, RuntimeError, subprocess.CalledProcessError) as error:
        status("failed", "Lab setup: {}".format(error), "31")
        return 1

    ready = sum(select_package(package, installed, set()) in installed for package in PACKAGES)
    summary = "{}/{} system packages ready in {:.1f}s".format(ready, len(PACKAGES), time.monotonic() - started)
    if any(package not in installed for package in IOT_ONLY):
        summary += "; IoT layer deferred (run --iot)"
    status("ok", summary, "32")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except KeyboardInterrupt:
        print("\ninstallation cancelled", file=sys.stderr)
        sys.exit(130)
