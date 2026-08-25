#!/usr/bin/env python3
"""Idempotent CTF workstation bootstrap for Ubuntu and Kali."""

from __future__ import annotations

import os
import platform
import re
import shlex
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path
from typing import Callable, Iterable
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parent
HOME = Path.home()
TOOLS_DIR = HOME / "tools"
VERSION_FILE = ROOT / "VERSION"
VERSION = VERSION_FILE.read_text(encoding="utf-8").strip() if VERSION_FILE.exists() else "dev"

NETWORK_ATTEMPTS = 3
NETWORK_DELAYS = (2, 5)
APT_UPDATE_WARN_PATTERNS = (
    "Failed to fetch",
    "Some index files failed",
    "Unable to connect",
    "Could not connect",
    "Connection timed out",
    "Temporary failure resolving",
    "does not have a Release file",
    "NO_PUBKEY",
    "Hash Sum mismatch",
)

REQUIRED_APT = [
    "ca-certificates", "gnupg", "curl", "wget", "git", "rsync", "sudo",
    "unzip", "zip", "xz-utils", "zstd", "tar", "gzip", "bzip2", "7zip",
    "cpio", "rpm2cpio",
    "pkg-config", "file", "vim", "nano", "tmux", "tree",
    "socat", "netcat-openbsd", "openssh-client",
    "build-essential", "clang", "llvm", "lld", "libssl-dev", "libffi-dev", "libc6-dev",
    "libbz2-dev", "libreadline-dev", "libsqlite3-dev", "liblzma-dev", "libncurses-dev",
    "zlib1g-dev",
    "autoconf", "automake", "libtool", "cmake", "ninja-build", "meson",
    "gawk", "bison", "flex", "gettext", "patch", "perl", "default-jdk",
    "python3", "python3-dev", "python3-pip", "python3-setuptools", "python3-wheel",
    "python3-ipython", "python-is-python3", "ruby-full", "bundler",
    "gdb", "gdbserver", "gdb-multiarch", "patchelf", "binutils", "binutils-multiarch",
    "elfutils", "xxd", "ltrace", "strace", "checksec",
    "libseccomp-dev", "seccomp", "libc6-dbg",
    "qemu-user", "qemu-system", "qemu-user-binfmt",
    "net-tools", "bind9-dnsutils", "iputils-ping", "traceroute", "mtr-tiny", "iperf3",
    "tcpdump", "nmap", "lsof", "zsh", "shellcheck", "bash-completion",
]

DAILY_APT = [
    "bat", "fd-find", "ripgrep", "fzf", "zoxide", "duf", "btop",
    "htop", "ncdu", "jq", "yq", "hyfetch",
]

KALI_APT = ["gdu"]

CTF_APT = [
    "nasm", "yasm", "valgrind", "apktool",
    "steghide", "stegseek", "binwalk", "libimage-exiftool-perl", "pngcheck",
    "foremost", "sleuthkit", "testdisk", "squashfs-tools", "mtd-utils", "cabextract",
    "imagemagick", "ffmpeg", "sox", "libsox-fmt-all", "mediainfo",
    "zbar-tools", "qrencode", "tesseract-ocr", "poppler-utils", "qpdf",
    "hashcat", "john", "tshark", "sqlite3", "bc", "xmlstarlet", "openssl",
]

I386_APT = [
    "gcc-multilib", "g++-multilib", "libc6-i386", "libc6-dev-i386", "libc6-dbg:i386",
]

PYTHON_IMPORT_PACKAGES = {
    "pwntools": "pwn",
    "capstone": "capstone",
    "unicorn": "unicorn",
    "keystone-engine": "keystone",
    "z3-solver": "z3",
    "pyelftools": "elftools",
    "lief": "lief",
    "Pillow": "PIL",
    "pycryptodome": "Crypto",
    "gmpy2": "gmpy2",
    "sympy": "sympy",
    "oletools": "oletools",
    "volatility3": "volatility3",
    "python-magic": "magic",
}

PYTHON_COMMAND_PACKAGES = {
    "ROPgadget": ("ROPgadget", "ropgadget"),
    "ropper": ("ropper",),
}

PYTHON_PACKAGES = [*PYTHON_IMPORT_PACKAGES, *PYTHON_COMMAND_PACKAGES]
PYTHON_IMPORTS = list(PYTHON_IMPORT_PACKAGES.values())

RUBY_GEMS = ["one_gadget", "seccomp-tools", "zsteg"]

HELPER_REPOS = {
    "glibc-all-in-one": "https://github.com/matrix1001/glibc-all-in-one.git",
    "libc-database": "https://github.com/niklasb/libc-database.git",
}

GLIBC_AIO_DIR = TOOLS_DIR / "glibc-all-in-one"
LIBC_DATABASE_DIR = TOOLS_DIR / "libc-database"

REMOTE_INSTALLERS = {
    "pwndbg": ("https://install.pwndbg.re", ["-t", "pwndbg-gdb", "-u"]),
}

ALLOWED_INSTALLER_HOSTS = {"install.pwndbg.re"}

PYTHON2_VERSION = "2.7.18"
PYENV_URL = "https://github.com/pyenv/pyenv.git"
PYTHON2_COMMAND_DIR = Path("/usr/local/bin")

RADARE2_MIN_VERSION = (6, 1, 4)
RADARE2_URL = "https://github.com/radareorg/radare2.git"

R2PIPE_VERSION = "1.9.8"
PWNDBG_PYTHON_DIR = HOME / ".local" / "share" / "pwndbg-python"
PWNDBG_BRIDGE_DIR = HOME / ".local" / "share" / "init" / "gdb"
PWNDBG_BRIDGE_SCRIPT = PWNDBG_BRIDGE_DIR / "r2ghidra.py"
GDBINIT = HOME / ".gdbinit"
GDBINIT_BEGIN = "# >>> init r2ghidra bridge >>>"
GDBINIT_END = "# <<< init r2ghidra bridge <<<"

DOCKER_PACKAGES = [
    "docker-ce", "docker-ce-cli", "containerd.io",
    "docker-buildx-plugin", "docker-compose-plugin",
]

DOCKER_CONFLICTS = [
    "docker.io", "docker-compose", "docker-doc", "docker-buildx",
    "podman-docker", "containerd", "runc",
]

DOCKER_KEYRING = Path("/etc/apt/keyrings/docker.asc")
DOCKER_SOURCE = Path("/etc/apt/sources.list.d/docker.sources")


class Bootstrap:
    def __init__(self) -> None:
        self.failures: list[str] = []
        self.skipped: list[str] = []
        self.started_monotonic = time.monotonic()
        self.step = 0
        self.step_total = 4
        self.apt_updated = False
        self._package_cache: dict[str, bool] = {}
        self.distro = self.detect_distro()
        self.arch = platform.machine().lower()
        self.is_wsl = self.detect_wsl()
        self.color = sys.stdout.isatty() and not os.environ.get("NO_COLOR")
        self._extend_path()

    def colorize(self, code: str, text: str) -> str:
        return f"\033[{code}m{text}\033[0m" if self.color else text

    def info(self, message: str) -> None:
        print(self.colorize("36", f"INFO: {message}"))

    def ok(self, message: str) -> None:
        print(self.colorize("32", f"OK: {message}"))

    def warn(self, message: str) -> None:
        print(self.colorize("33", f"WARN: {message}"))

    def error(self, message: str) -> None:
        print(self.colorize("31", f"ERROR: {message}"), file=sys.stderr)

    @staticmethod
    def format_duration(seconds: float) -> str:
        total = max(0, int(seconds))
        hours, remainder = divmod(total, 3600)
        minutes, seconds = divmod(remainder, 60)
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"

    def section(self, title: str) -> None:
        self.step += 1
        elapsed = self.format_duration(time.monotonic() - self.started_monotonic)
        stage = self.colorize("34;1", f"[{self.step:02d}/{self.step_total:02d}] {title}")
        timing = self.colorize("2", f"elapsed {elapsed}")
        print(f"\n{stage} | {timing}")

    def run_stage(self, title: str, action: Callable[[], object]) -> None:
        self.section(title)
        started = time.monotonic()
        failures_before = len(self.failures)
        action()
        duration = self.format_duration(time.monotonic() - started)
        new_failures = len(self.failures) - failures_before
        if new_failures:
            self.warn(f"{title} finished with {new_failures} failure(s) in {duration}")
        else:
            self.ok(f"{title} finished in {duration}")

    @staticmethod
    def command_exists(command: str) -> bool:
        return shutil.which(command) is not None

    @staticmethod
    def detect_distro() -> dict[str, str]:
        result: dict[str, str] = {
            "id": "unknown",
            "name": "Unknown Linux",
            "version": "",
            "codename": "",
            "ubuntu_codename": "",
        }
        try:
            for line in Path("/etc/os-release").read_text(encoding="utf-8").splitlines():
                if "=" not in line:
                    continue
                key, value = line.split("=", 1)
                value = value.strip().strip('"')
                if key == "ID":
                    result["id"] = value.lower()
                elif key == "PRETTY_NAME":
                    result["name"] = value
                elif key == "VERSION_ID":
                    result["version"] = value
                elif key == "VERSION_CODENAME":
                    result["codename"] = value.lower()
                elif key == "UBUNTU_CODENAME":
                    result["ubuntu_codename"] = value.lower()
        except OSError:
            pass
        return result

    @staticmethod
    def detect_wsl() -> bool:
        try:
            value = Path("/proc/version").read_text(encoding="utf-8", errors="replace").lower()
        except OSError:
            value = ""
        return "microsoft" in value or "wsl" in value or bool(os.environ.get("WSL_DISTRO_NAME"))

    @staticmethod
    def supported_distro(distro: dict[str, str]) -> bool:
        if distro["id"] == "kali":
            return True
        if distro["id"] != "ubuntu":
            return False
        try:
            major, minor = (int(part) for part in distro["version"].split(".")[:2])
        except (TypeError, ValueError):
            return False
        return (major, minor) >= (24, 4)

    def _extend_path(self) -> None:
        candidates = [
            Path("/usr/local/bin"),
            HOME / ".local" / "bin",
            HOME / ".cargo" / "bin",
        ]
        current = os.environ.get("PATH", "").split(os.pathsep)
        for candidate in reversed(candidates):
            value = str(candidate)
            if value not in current:
                current.insert(0, value)
        os.environ["PATH"] = os.pathsep.join(current)

    def run(
        self,
        command: list[str],
        *,
        sudo: bool = False,
        check: bool = True,
        capture: bool = False,
        cwd: Path | None = None,
        env: dict[str, str] | None = None,
        network: bool = False,
        timeout: int | None = None,
    ) -> subprocess.CompletedProcess[str]:
        final = list(command)
        if sudo and os.geteuid() != 0:
            final = ["sudo", *final]
        merged_env = os.environ.copy()
        if env:
            merged_env.update(env)
        attempts = NETWORK_ATTEMPTS if network else 1
        result: subprocess.CompletedProcess[str] | None = None
        for attempt in range(1, attempts + 1):
            if not capture:
                print("  $", shlex.join(final))
            try:
                result = subprocess.run(
                    final,
                    cwd=str(cwd) if cwd else None,
                    env=merged_env,
                    text=True,
                    stdout=subprocess.PIPE if capture else None,
                    stderr=subprocess.PIPE if capture else None,
                    timeout=timeout,
                )
            except subprocess.TimeoutExpired as exc:
                result = subprocess.CompletedProcess(final, 124, exc.stdout, exc.stderr)
            if result.returncode == 0:
                return result
            if attempt < attempts:
                delay = NETWORK_DELAYS[min(attempt - 1, len(NETWORK_DELAYS) - 1)]
                self.warn(f"command failed; retrying in {delay}s ({attempt}/{attempts})")
                time.sleep(delay)
        assert result is not None
        if check:
            raise subprocess.CalledProcessError(
                result.returncode,
                final,
                output=result.stdout,
                stderr=result.stderr,
            )
        return result

    @staticmethod
    def apt_env() -> dict[str, str]:
        return {"DEBIAN_FRONTEND": "noninteractive", "NEEDRESTART_MODE": "a"}

    @staticmethod
    def apt_options() -> list[str]:
        return [
            "-o", "Acquire::Retries=3",
            "-o", "Dpkg::Options::=--force-confold",
        ]

    def require_sudo(self) -> None:
        if os.geteuid() == 0:
            self.warn("running as root; user-scoped tools will be installed under /root")
            return
        if not self.command_exists("sudo"):
            raise RuntimeError("sudo is required. Install sudo first, or run from a root shell.")
        self.run(["sudo", "-v"])

    def preflight(self) -> None:
        if sys.platform != "linux":
            raise RuntimeError("this installer supports Linux and WSL only")
        if not self.command_exists("apt-get") or not self.command_exists("dpkg-query"):
            raise RuntimeError("apt-get and dpkg-query are required")
        if not self.supported_distro(self.distro):
            raise RuntimeError(
                f"unsupported distribution: {self.distro['name']} "
                f"(supported: Ubuntu 24.04+ and current Kali)"
            )
        self.require_sudo()
        free = shutil.disk_usage(HOME).free
        free_gib = free / (1024 ** 3)
        minimum_gib, recommended_gib = self.installation_space_limits()
        if free_gib < minimum_gib:
            raise RuntimeError(f"not enough free disk space: {free_gib:.1f} GiB")
        if free_gib < recommended_gib:
            self.warn(
                f"low disk space: {free_gib:.1f} GiB free; "
                f"{recommended_gib} GiB or more is recommended"
            )
        self.ok(
            f"{self.distro['name']} | {self.arch} | WSL={'yes' if self.is_wsl else 'no'} "
            f"| free={free_gib:.1f} GiB"
        )

    def package_installed(self, package: str) -> bool:
        if package in self._package_cache:
            return self._package_cache[package]
        result = self.run(
            ["dpkg-query", "-W", "-f=${Status}", package],
            capture=True,
            check=False,
        )
        installed = result.returncode == 0 and "install ok installed" in (result.stdout or "")
        self._package_cache[package] = installed
        return installed

    def package_available(self, package: str) -> bool:
        result = self.run(
            ["apt-cache", "--no-all-versions", "show", package],
            capture=True,
            check=False,
        )
        return result.returncode == 0 and bool((result.stdout or "").strip())

    def planned_apt_packages(self) -> list[str]:
        distro_packages = KALI_APT if self.distro["id"] == "kali" else []
        i386 = I386_APT if self.arch in {"x86_64", "amd64"} else []
        return list(dict.fromkeys([*REQUIRED_APT, *DAILY_APT, *CTF_APT, *distro_packages, *i386]))

    def installation_space_limits(self) -> tuple[int, int]:
        missing = sum(not self.package_installed(package) for package in self.planned_apt_packages())
        if missing >= 10:
            return 10, 15
        if missing or self.existing_python2() is None or not self.docker_ready():
            return 3, 5
        return 1, 3

    def apt_update(self, *, force: bool = False) -> bool:
        if self.apt_updated and not force:
            return True
        result: subprocess.CompletedProcess[str] | None = None
        self.apt_updated = False
        for attempt in range(1, NETWORK_ATTEMPTS + 1):
            result = self.run(
                ["apt-get", *self.apt_options(), "update"],
                sudo=True,
                check=False,
                capture=True,
                env=self.apt_env(),
            )
            output = (result.stdout or "") + (result.stderr or "")
            if output.strip():
                print(output, end="" if output.endswith("\n") else "\n")
            incomplete = any(pattern in output for pattern in APT_UPDATE_WARN_PATTERNS)
            if result.returncode == 0 and not incomplete:
                self.apt_updated = True
                break
            if attempt < NETWORK_ATTEMPTS:
                delay = NETWORK_DELAYS[min(attempt - 1, len(NETWORK_DELAYS) - 1)]
                self.warn(f"APT update incomplete; retrying in {delay}s ({attempt}/{NETWORK_ATTEMPTS})")
                time.sleep(delay)
        if not self.apt_updated:
            if "APT index update failed" not in self.failures:
                self.failures.append("APT index update failed")
        return self.apt_updated

    def enable_i386(self) -> list[str]:
        if self.arch not in {"x86_64", "amd64"}:
            self.skipped.append(f"i386 multilib skipped on {self.arch}")
            return []
        result = self.run(
            ["dpkg", "--print-foreign-architectures"],
            capture=True,
            check=False,
        )
        if "i386" not in (result.stdout or "").split():
            self.run(["dpkg", "--add-architecture", "i386"], sudo=True)
            self.apt_updated = False
        return I386_APT

    def apt_install(self, packages: Iterable[str], label: str, *, required: bool) -> bool:
        unique = list(dict.fromkeys(packages))
        missing = [package for package in unique if not self.package_installed(package)]
        if not missing:
            self.ok(f"{label}: already installed")
            return True
        if not self.apt_update():
            message = f"{label}: skipped because APT update failed"
            (self.failures if required else self.skipped).append(message)
            return False
        unavailable = [package for package in missing if not self.package_available(package)]
        for package in unavailable:
            message = f"APT package unavailable: {package}"
            (self.failures if required else self.skipped).append(message)
        if unavailable:
            missing = [package for package in missing if package not in unavailable]
        if not missing:
            return not unavailable
        available_ok = not unavailable
        self.info(f"installing {label}: {len(missing)} packages")
        result = self.run(
            [
                "apt-get", *self.apt_options(), "install", "-y", "--fix-missing",
                "--no-install-recommends", *missing,
            ],
            sudo=True,
            check=False,
            env=self.apt_env(),
        )
        self._package_cache.clear()
        if result.returncode == 0:
            return available_ok

        self.warn(f"batch install failed for {label}; retrying remaining packages individually")
        ok_all = available_ok
        for package in [p for p in missing if not self.package_installed(p)]:
            result = self.run(
                [
                    "apt-get", *self.apt_options(), "install", "-y", "--fix-missing",
                    "--no-install-recommends", package,
                ],
                sudo=True,
                check=False,
                env=self.apt_env(),
            )
            self._package_cache[package] = result.returncode == 0
            if result.returncode != 0:
                ok_all = False
                message = f"APT package failed: {package}"
                (self.failures if required else self.skipped).append(message)
        return ok_all

    def install_system_foundation(self) -> None:
        if self.distro["id"] == "ubuntu":
            if self.ubuntu_universe_enabled():
                self.ok("Ubuntu universe repository: already enabled")
            elif self.apt_install(
                ["software-properties-common"],
                "Ubuntu repository support",
                required=True,
            ):
                result = self.run(
                    ["add-apt-repository", "-y", "universe"],
                    sudo=True,
                    check=False,
                    network=True,
                    env=self.apt_env(),
                )
                if result.returncode != 0:
                    self.failures.append("failed to enable the Ubuntu universe repository")
                self.apt_updated = False
        i386 = self.enable_i386()
        distro_packages = KALI_APT if self.distro["id"] == "kali" else []
        self.apt_install(REQUIRED_APT, "system and development packages", required=True)
        self.apt_install(
            [*DAILY_APT, *distro_packages], "daily CLI tools", required=True
        )
        self.apt_install(CTF_APT, "CTF CLI tools", required=True)
        if i386:
            self.apt_install(i386, "32-bit development support", required=True)
        self.install_command_links()
        self.install_docker()

    @staticmethod
    def ubuntu_universe_enabled() -> bool:
        paths = [Path("/etc/apt/sources.list")]
        paths.extend(Path("/etc/apt/sources.list.d").glob("*.list"))
        paths.extend(Path("/etc/apt/sources.list.d").glob("*.sources"))
        for path in paths:
            try:
                lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
            except OSError:
                continue
            for line in lines:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if line.startswith("Components:") and "universe" in line.split()[1:]:
                    return True
                if line.startswith("deb ") and "universe" in line.split():
                    return True
        return False

    def install_command_links(self) -> None:
        for source, target in (("batcat", "bat"), ("fdfind", "fd"), ("7zz", "7z")):
            if shutil.which(target):
                continue
            executable = shutil.which(source)
            if executable is None:
                continue
            result = self.run(
                ["ln", "-sf", executable, f"/usr/local/bin/{target}"],
                sudo=True,
                check=False,
            )
            if result.returncode != 0:
                self.skipped.append(f"command link failed: {target}")

    def docker_repository(self) -> tuple[str, str]:
        if self.distro["id"] == "kali":
            return "debian", "trixie"
        suite = self.distro.get("ubuntu_codename") or self.distro.get("codename")
        if not suite and self.distro.get("version") == "24.04":
            suite = "noble"
        if not suite or not re.fullmatch(r"[a-z0-9][a-z0-9-]*", suite):
            raise RuntimeError("could not determine the Ubuntu codename for Docker")
        return "ubuntu", suite

    def docker_ready(self) -> bool:
        if not all(self.command_exists(command) for command in ("docker", "containerd")):
            return False
        for command in (
            ["docker", "--version"],
            ["docker", "buildx", "version"],
            ["docker", "compose", "version"],
            ["containerd", "--version"],
        ):
            if self.run(command, check=False, capture=True, timeout=30).returncode != 0:
                return False
        return True

    def setup_docker_repository(self) -> bool:
        family, suite = self.docker_repository()
        architecture = self.run(
            ["dpkg", "--print-architecture"], check=False, capture=True
        ).stdout.strip()
        if not architecture:
            self.failures.append("Docker repository setup failed: unknown architecture")
            return False
        source = (
            "Types: deb\n"
            f"URIs: https://download.docker.com/linux/{family}\n"
            f"Suites: {suite}\n"
            "Components: stable\n"
            f"Architectures: {architecture}\n"
            f"Signed-By: {DOCKER_KEYRING}\n"
        )
        try:
            current = DOCKER_SOURCE.read_text(encoding="utf-8")
        except OSError:
            current = ""
        if DOCKER_KEYRING.exists() and current == source:
            self.ok("Docker repository: already configured")
            return True

        key_file: Path | None = None
        source_file: Path | None = None
        try:
            key_handle = tempfile.NamedTemporaryFile(prefix="init-docker-key-", delete=False)
            key_handle.close()
            key_file = Path(key_handle.name)
            result = self.run(
                [
                    "curl", "-fsSL",
                    f"https://download.docker.com/linux/{family}/gpg",
                    "-o", str(key_file),
                ],
                check=False,
                network=True,
                timeout=60,
            )
            if result.returncode != 0 or key_file.stat().st_size < 100:
                self.failures.append("Docker repository key download failed")
                return False

            source_handle = tempfile.NamedTemporaryFile(
                mode="w", prefix="init-docker-source-", encoding="utf-8", delete=False
            )
            try:
                source_handle.write(source)
                source_file = Path(source_handle.name)
            finally:
                source_handle.close()

            commands = (
                ["install", "-m", "0755", "-d", str(DOCKER_KEYRING.parent)],
                ["install", "-m", "0644", str(key_file), str(DOCKER_KEYRING)],
                ["install", "-m", "0644", str(source_file), str(DOCKER_SOURCE)],
            )
            for command in commands:
                result = self.run(command, sudo=True, check=False)
                if result.returncode != 0:
                    self.failures.append("Docker repository setup failed")
                    return False
            self.apt_updated = False
            return True
        except OSError as exc:
            self.failures.append(f"Docker repository setup failed: {exc}")
            return False
        finally:
            for path in (key_file, source_file):
                if path is not None:
                    try:
                        path.unlink()
                    except OSError:
                        pass

    def install_docker(self) -> None:
        if self.docker_ready():
            self.ok("Docker Engine, Buildx and Compose: already installed")
            return
        if not self.setup_docker_repository():
            return

        conflicts = [package for package in DOCKER_CONFLICTS if self.package_installed(package)]
        if conflicts:
            self.info("replacing conflicting Docker packages: " + ", ".join(conflicts))
            result = self.run(
                ["apt-get", *self.apt_options(), "remove", "-y", *conflicts],
                sudo=True,
                check=False,
                env=self.apt_env(),
            )
            self._package_cache.clear()
            if result.returncode != 0:
                self.failures.append("failed to remove conflicting Docker packages")
                return

        if not self.apt_install(DOCKER_PACKAGES, "Docker CE", required=True):
            return
        if self.docker_ready():
            self.ok("Docker Engine, Buildx and Compose installed")
        else:
            self.failures.append("Docker installation failed verification")

    def python2_prefix(self) -> Path:
        return TOOLS_DIR / "pyenv" / "versions" / PYTHON2_VERSION

    def valid_python2(self, executable: Path | str) -> bool:
        result = self.run(
            [str(executable), "--version"], check=False, capture=True, timeout=30
        )
        output = (result.stdout or "") + (result.stderr or "")
        return result.returncode == 0 and output.strip().startswith("Python 2.7.")

    def existing_python2(self) -> Path | None:
        candidates = [shutil.which("python2"), str(self.python2_prefix() / "bin" / "python2.7")]
        for candidate in candidates:
            if candidate and Path(candidate).exists() and self.valid_python2(candidate):
                return Path(candidate)
        return None

    def python2_pip_ready(self, executable: Path | str) -> bool:
        result = self.run(
            [str(executable), "-m", "pip", "--version"],
            check=False,
            capture=True,
            timeout=30,
        )
        return result.returncode == 0 and "pip " in (result.stdout or "").lower()

    def configure_python2_runtime(self, python2: Path) -> bool:
        python2 = python2.resolve()
        if not self.python2_pip_ready(python2):
            self.info("Python 2 pip module is missing; bootstrapping it with ensurepip")
            ensurepip = self.run(
                [str(python2), "-m", "ensurepip", "--upgrade"],
                check=False,
                timeout=300,
            )
            if ensurepip.returncode != 0 or not self.python2_pip_ready(python2):
                return False

        for name in ("python2", "python2.7"):
            result = self.run(
                ["ln", "-sf", str(python2), str(PYTHON2_COMMAND_DIR / name)],
                sudo=True,
                check=False,
            )
            if result.returncode != 0:
                self.failures.append(f"Python 2 command link failed: {name}")
                return False

        wrapper: Path | None = None
        try:
            handle = tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                prefix="init-pip2-",
                suffix=".sh",
                delete=False,
            )
            wrapper = Path(handle.name)
            with handle:
                handle.write(
                    "#!/bin/sh\n"
                    f"exec {shlex.quote(str(python2))} -m pip \"$@\"\n"
                )
            install = self.run(
                [
                    "install", "-m", "0755", str(wrapper),
                    str(PYTHON2_COMMAND_DIR / "pip2"),
                ],
                sudo=True,
                check=False,
            )
            if install.returncode != 0:
                self.failures.append("Python 2 command installation failed: pip2")
                return False
        except OSError as exc:
            self.failures.append(f"Python 2 pip2 wrapper creation failed: {exc}")
            return False
        finally:
            if wrapper is not None:
                try:
                    wrapper.unlink()
                except OSError:
                    pass

        pip2_check = self.run(
            [str(PYTHON2_COMMAND_DIR / "pip2"), "--version"],
            check=False,
            capture=True,
            timeout=30,
        )
        if pip2_check.returncode != 0:
            self.failures.append("Python 2 pip2 command failed verification")
            return False
        return True

    def install_python2_legacy(self) -> None:
        existing = self.existing_python2()
        if existing is not None:
            if self.configure_python2_runtime(existing):
                self.ok(f"Python 2 legacy runtime and pip2: already configured ({existing})")
                return
            self.warn(
                f"existing Python 2 at {existing} has no usable pip; "
                "installing the isolated pyenv runtime"
            )
        if not self.clone_or_update("pyenv", PYENV_URL):
            self.failures.append("Python 2 legacy runtime installation failed")
            return

        pyenv = TOOLS_DIR / "pyenv" / "bin" / "pyenv"
        env = {"PYENV_ROOT": str(TOOLS_DIR / "pyenv"), "CFLAGS": "-std=c11"}
        result = self.run(
            [str(pyenv), "install", "-s", PYTHON2_VERSION],
            check=False,
            network=True,
            timeout=1800,
            env=env,
        )
        python2 = self.python2_prefix() / "bin" / "python2.7"
        if result.returncode != 0 or not python2.exists() or not self.valid_python2(python2):
            self.failures.append("Python 2 legacy runtime installation failed")
            return
        if not self.configure_python2_runtime(python2):
            if not any("Python 2" in failure for failure in self.failures):
                self.failures.append("Python 2 pip installation failed")
            return
        self.ok(
            "Python 2.7.18 legacy runtime and pip2 installed without changing system Python"
        )

    def install_python_tools(self) -> None:
        python = "/usr/bin/python3" if Path("/usr/bin/python3").exists() else "python3"
        probe_code = (
            "import importlib\n"
            f"modules = {PYTHON_IMPORTS!r}\n"
            "failed = []\n"
            "for module in modules:\n"
            "    try:\n"
            "        importlib.import_module(module)\n"
            "    except Exception:\n"
            "        failed.append(module)\n"
            "print('\\n'.join(failed))\n"
        )
        probe = self.run(
            [python, "-c", probe_code],
            check=False,
            capture=True,
        )
        if probe.returncode == 0:
            missing_modules = set((probe.stdout or "").splitlines())
            missing = [
                package for package, module in PYTHON_IMPORT_PACKAGES.items()
                if module in missing_modules
            ]
        else:
            missing = list(PYTHON_IMPORT_PACKAGES)
        missing.extend(
            package for package, commands in PYTHON_COMMAND_PACKAGES.items()
            if not any(self.command_exists(command) for command in commands)
        )
        if not missing:
            self.ok("Python tools: already installed")
            return
        result = self.run(
            [
                python, "-m", "pip", "install", "--break-system-packages",
                "--disable-pip-version-check", "--upgrade", *missing,
            ],
            sudo=True,
            check=False,
            network=True,
            env={"PIP_ROOT_USER_ACTION": "ignore"},
        )
        if result.returncode != 0:
            self.failures.append("Python CTF package installation failed")
        else:
            self.ok("Python CTF tools installed system-wide")

    def install_ruby_tools(self) -> None:
        if not self.command_exists("gem"):
            self.failures.append("RubyGems is unavailable")
            return
        missing = [gem for gem in RUBY_GEMS if not self.command_exists(gem)]
        if not missing:
            self.ok("Ruby CTF tools: already installed")
            return
        result = self.run(
            ["gem", "install", "--no-document", *missing],
            sudo=True,
            check=False,
            network=True,
        )
        self._extend_path()
        if result.returncode != 0:
            self.failures.append("Ruby CTF tool installation failed")

    @staticmethod
    def format_version(version: tuple[int, int, int]) -> str:
        return ".".join(str(part) for part in version)

    def radare2_version(self) -> tuple[int, int, int] | None:
        self._extend_path()
        if not self.command_exists("r2"):
            return None
        result = self.run(
            ["r2", "-v"],
            check=False,
            capture=True,
            timeout=30,
        )
        output = (result.stdout or "") + (result.stderr or "")
        match = re.search(r"\bradare2\s+(\d+)\.(\d+)\.(\d+)\b", output, re.IGNORECASE)
        if result.returncode != 0 or match is None:
            return None
        return tuple(int(part) for part in match.groups())

    def radare2_ready(self) -> bool:
        version = self.radare2_version()
        return (
            version is not None
            and version >= RADARE2_MIN_VERSION
            and self.command_exists("r2pm")
        )

    def install_radare2(self) -> bool:
        current = self.radare2_version()
        if (
            current is not None
            and current >= RADARE2_MIN_VERSION
            and self.command_exists("r2pm")
        ):
            self.ok(f"radare2 {self.format_version(current)}: already compatible")
            return True

        required = self.format_version(RADARE2_MIN_VERSION)
        if current is None:
            self.info(f"radare2 >= {required} is not installed; building the official Git version")
        else:
            self.warn(
                f"radare2 {self.format_version(current)} is too old; "
                f"r2ghidra requires >= {required}"
            )

        destination = TOOLS_DIR / "radare2"
        destination.parent.mkdir(parents=True, exist_ok=True)
        git_env = {"GIT_TERMINAL_PROMPT": "0", "GIT_ASKPASS": "true"}

        if (destination / ".git").exists():
            self.info("radare2: updating the existing official Git checkout")
            source = self.run(
                ["git", "-C", str(destination), "pull", "--ff-only", "origin", "master"],
                env=git_env,
                check=False,
                network=True,
                timeout=300,
            )
        elif destination.exists():
            self.failures.append(
                f"radare2 source path exists but is not a Git repository: {destination}"
            )
            return False
        else:
            self.info("radare2: cloning the official Git repository")
            source = self.run(
                ["git", "clone", "--depth", "1", RADARE2_URL, str(destination)],
                env=git_env,
                check=False,
                network=True,
                timeout=300,
            )

        if source.returncode != 0:
            self.failures.append("radare2 official source download/update failed")
            return False

        self.info("radare2: building and installing to /usr/local")
        build = self.run(
            ["sh", str(destination / "sys" / "install.sh"), "--install", "--without-pull"],
            cwd=destination,
            env={"MAKEFLAGS": f"-j{max(1, os.cpu_count() or 1)}"},
            check=False,
            timeout=1800,
        )
        self._extend_path()
        if build.returncode != 0:
            self.failures.append("radare2 official source build/install failed")
            return False

        installed = self.radare2_version()
        if (
            installed is None
            or installed < RADARE2_MIN_VERSION
            or not self.command_exists("r2pm")
        ):
            detected = "not found" if installed is None else self.format_version(installed)
            self.failures.append(
                f"radare2 source installation finished but compatible tools were not detected "
                f"(detected version: {detected}; required: >= {required})"
            )
            return False

        self.ok(
            f"radare2 {self.format_version(installed)} installed from the official Git source"
        )
        return True

    def r2ghidra_available(self) -> bool:
        if not self.command_exists("r2"):
            return False
        result = self.run(
            ["r2", "-q", "-c", "pdg?;q", "/bin/true"],
            check=False,
            capture=True,
            timeout=30,
        )
        output = ((result.stdout or "") + (result.stderr or "")).lower()
        return result.returncode == 0 and "native ghidra decompiler" in output

    def install_r2ghidra(self) -> None:
        if self.r2ghidra_available():
            self.ok("r2ghidra: already installed and loadable")
            return
        if not self.command_exists("r2pm"):
            self.failures.append(
                "r2ghidra installation failed: r2pm is unavailable; "
                "verify the radare2 package installation"
            )
            return

        self.info("r2ghidra: updating the r2pm package database")
        update = self.run(
            ["r2pm", "-U"],
            check=False,
            network=True,
            timeout=300,
        )
        if update.returncode != 0:
            self.failures.append(
                "r2ghidra installation failed: r2pm -U could not update the package database"
            )
            return

        self.info("r2ghidra: clean-building the plugin; this may take several minutes")
        install = self.run(
            ["r2pm", "-ci", "r2ghidra"],
            check=False,
            timeout=1800,
        )
        if install.returncode != 0:
            self.failures.append(
                "r2ghidra installation failed: r2pm -ci r2ghidra returned an error"
            )
            return

        if self.r2ghidra_available():
            self.ok("r2ghidra installed and verified with pdg?")
        else:
            self.failures.append(
                "r2ghidra installation finished but pdg was not loadable; "
                "check that radare2 and libradare2-dev have matching versions"
            )

    @staticmethod
    def system_python() -> str:
        return "/usr/bin/python3" if Path("/usr/bin/python3").exists() else "python3"

    def r2pipe_target_available(self) -> bool:
        probe_code = (
            "import sys\n"
            f"sys.path.insert(0, {str(PWNDBG_PYTHON_DIR)!r})\n"
            "import r2pipe\n"
            "from importlib.metadata import version\n"
            f"assert version('r2pipe') == {R2PIPE_VERSION!r}\n"
            "print(r2pipe.__file__)\n"
        )
        result = self.run(
            [self.system_python(), "-c", probe_code],
            check=False,
            capture=True,
            timeout=30,
        )
        return result.returncode == 0

    def install_r2pipe_for_pwndbg(self) -> bool:
        if self.r2pipe_target_available():
            self.ok(
                f"r2pipe {R2PIPE_VERSION} for Pwndbg: already installed "
                f"({PWNDBG_PYTHON_DIR})"
            )
            return True

        PWNDBG_PYTHON_DIR.mkdir(parents=True, exist_ok=True)
        self.info(
            f"installing r2pipe {R2PIPE_VERSION} into Pwndbg's fixed Python path"
        )
        result = self.run(
            [
                self.system_python(), "-m", "pip", "install",
                "--break-system-packages", "--disable-pip-version-check",
                "--upgrade", "--no-deps", "--target", str(PWNDBG_PYTHON_DIR),
                f"r2pipe=={R2PIPE_VERSION}",
            ],
            check=False,
            network=True,
            timeout=300,
            env={"PIP_ROOT_USER_ACTION": "ignore"},
        )
        if result.returncode != 0 or not self.r2pipe_target_available():
            self.failures.append(
                "Pwndbg r2pipe installation failed: the isolated package could not be imported"
            )
            return False
        self.ok(f"r2pipe {R2PIPE_VERSION} installed for Pwndbg")
        return True

    @staticmethod
    def write_text_if_changed(path: Path, content: str) -> bool:
        try:
            if path.read_text(encoding="utf-8") == content:
                return False
        except OSError:
            pass
        path.parent.mkdir(parents=True, exist_ok=True)
        mode = path.stat().st_mode if path.exists() else None
        handle = tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            prefix=f".{path.name}.",
            dir=path.parent,
            delete=False,
        )
        temporary = Path(handle.name)
        try:
            with handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            if mode is not None:
                temporary.chmod(stat.S_IMODE(mode))
            os.replace(temporary, path)
        finally:
            if temporary.exists():
                temporary.unlink()
        return True

    @staticmethod
    def pwndbg_bridge_source() -> str:
        return f'''# Generated by init. Local changes may be replaced on the next run.
import sys

import gdb


R2PIPE_PATH = {str(PWNDBG_PYTHON_DIR)!r}
if R2PIPE_PATH not in sys.path:
    sys.path.insert(0, R2PIPE_PATH)


class InitGhidraCommand(gdb.Command):
    """Decompile an address with Pwndbg, radare2 and r2ghidra."""

    def __init__(self):
        super().__init__("ghidra", gdb.COMMAND_USER)

    def invoke(self, argument, from_tty):
        expression = argument.strip() or "$pc"
        try:
            value = gdb.parse_and_eval(expression)
            if value.type.code == gdb.TYPE_CODE_FUNC:
                value = value.address
            address = int(value)
        except (gdb.error, ValueError, TypeError) as exc:
            print(f"ghidra: cannot resolve {{expression!r}}: {{exc}}")
            print("usage: ghidra [ADDRESS|SYMBOL]  (default: $pc)")
            return
        try:
            gdb.execute(f"r2pipe pdg @ {{address:#x}}", from_tty)
        except gdb.error as exc:
            print(f"ghidra: {{exc}}")
            print("check: r2 -q -c 'pdg?;q' /bin/true")


try:
    gdb.execute("help ghidra", to_string=True)
except gdb.error:
    InitGhidraCommand()
'''

    def configure_pwndbg_r2ghidra(self) -> bool:
        try:
            self.write_text_if_changed(PWNDBG_BRIDGE_SCRIPT, self.pwndbg_bridge_source())
            try:
                existing = GDBINIT.read_text(encoding="utf-8")
            except FileNotFoundError:
                existing = ""
            managed = (
                f"{GDBINIT_BEGIN}\n"
                f"source {PWNDBG_BRIDGE_SCRIPT}\n"
                f"{GDBINIT_END}"
            )
            pattern = re.compile(
                rf"(?ms)^{re.escape(GDBINIT_BEGIN)}$.*?^{re.escape(GDBINIT_END)}$"
            )
            if pattern.search(existing):
                updated = pattern.sub(managed, existing)
            else:
                updated = existing.rstrip("\n")
                if updated:
                    updated += "\n\n"
                updated += managed
            self.write_text_if_changed(GDBINIT, updated.rstrip("\n") + "\n")
        except OSError as exc:
            self.failures.append(f"Pwndbg r2ghidra configuration failed: {exc}")
            return False
        return True

    def pwndbg_r2ghidra_available(self) -> bool:
        pwndbg = self.find_command(["pwndbg", "pwndbg-gdb"])
        if pwndbg is None or not self.r2pipe_target_available():
            return False
        result = self.run(
            [
                pwndbg, "-q", "--batch",
                "-ex", "pi import r2pipe; print(r2pipe.__file__)",
                "-ex", "help ghidra",
                "-ex", "r2pipe pdg?",
                "/bin/true",
            ],
            check=False,
            capture=True,
            timeout=90,
        )
        output = ((result.stdout or "") + (result.stderr or "")).lower()
        return (
            result.returncode == 0
            and "could not import r2pipe" not in output
            and "decompile an address with pwndbg" in output
            and "native ghidra decompiler" in output
        )

    def install_pwndbg_r2ghidra_bridge(self) -> None:
        if not self.install_r2pipe_for_pwndbg():
            return
        if not self.configure_pwndbg_r2ghidra():
            return
        if self.pwndbg_r2ghidra_available():
            self.ok("Pwndbg r2ghidra bridge and ghidra command configured")
        else:
            self.failures.append(
                "Pwndbg r2ghidra bridge verification failed; run "
                "'pwndbg /bin/true' and check 'pi import r2pipe'"
            )

    def clone_or_update(self, name: str, url: str) -> bool:
        destination = TOOLS_DIR / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        env = {"GIT_TERMINAL_PROMPT": "0", "GIT_ASKPASS": "true"}
        if (destination / ".git").exists():
            self.ok(f"{name}: already installed")
            return True
        if destination.exists():
            self.failures.append(f"path exists but is not a Git repository: {destination}")
            return False
        result = self.run(
            ["git", "clone", "--depth", "1", url, str(destination)],
            env=env,
            check=False,
            network=True,
            timeout=300,
        )
        if result.returncode != 0:
            self.failures.append(f"repository clone failed: {name}")
            return False
        return True

    def install_helper_repositories(self) -> None:
        for name, url in HELPER_REPOS.items():
            if not self.clone_or_update(name, url):
                continue
            if name == "glibc-all-in-one":
                self.install_glibc_all_in_one()

    def install_glibc_all_in_one(self) -> None:
        project_file = GLIBC_AIO_DIR / "pyproject.toml"
        if not project_file.exists() and (GLIBC_AIO_DIR / ".git").exists():
            self.info("glibc-all-in-one: updating the legacy checkout to v2")
            update = self.run(
                [
                    "git", "-C", str(GLIBC_AIO_DIR), "pull", "--ff-only",
                    "origin", "master",
                ],
                check=False,
                network=True,
                timeout=300,
                env={"GIT_TERMINAL_PROMPT": "0", "GIT_ASKPASS": "true"},
            )
            if update.returncode != 0:
                self.failures.append("glibc-all-in-one v2 source update failed")
                return

        if not project_file.exists():
            self.failures.append(
                "glibc-all-in-one v2 metadata not found after repository installation"
            )
            return

        if not self.command_exists("glibc-aio"):
            self.info("glibc-all-in-one: installing the v2 glibc-aio command")
            install = self.run(
                [
                    self.system_python(), "-m", "pip", "install",
                    "--break-system-packages", "--disable-pip-version-check",
                    "--upgrade", "--editable", str(GLIBC_AIO_DIR),
                ],
                sudo=True,
                check=False,
                network=True,
                timeout=300,
                env={"PIP_ROOT_USER_ACTION": "ignore"},
            )
            self._extend_path()
            if install.returncode != 0 or not self.command_exists("glibc-aio"):
                self.failures.append("glibc-all-in-one v2 command installation failed")
                return
        else:
            self.ok("glibc-aio: already installed")

        libc_list = GLIBC_AIO_DIR / "list"
        if not (libc_list.exists() and libc_list.stat().st_size > 0):
            self.info("glibc-all-in-one: updating the libc package index")
            update_list = self.run(
                ["glibc-aio", "mirror", "update"],
                cwd=GLIBC_AIO_DIR,
                check=False,
                network=True,
                timeout=300,
            )
            if update_list.returncode != 0:
                self.failures.append("glibc-all-in-one libc index update failed")

    def download_installer(self, name: str, url: str) -> Path:
        parsed = urlparse(url)
        if parsed.scheme != "https" or parsed.hostname not in ALLOWED_INSTALLER_HOSTS:
            raise RuntimeError(f"unapproved installer URL for {name}: {url}")
        data: bytes | None = None
        last_error: Exception | None = None
        for attempt in range(1, NETWORK_ATTEMPTS + 1):
            try:
                request = urllib.request.Request(url, headers={"User-Agent": f"init/{VERSION}"})
                with urllib.request.urlopen(request, timeout=30) as response:
                    data = response.read(2 * 1024 * 1024 + 1)
                break
            except Exception as exc:
                last_error = exc
                if attempt < NETWORK_ATTEMPTS:
                    delay = NETWORK_DELAYS[min(attempt - 1, len(NETWORK_DELAYS) - 1)]
                    self.warn(f"{name} download failed; retrying in {delay}s ({attempt}/{NETWORK_ATTEMPTS})")
                    time.sleep(delay)
        if data is None:
            raise RuntimeError(f"download failed: {last_error}")
        if len(data) > 2 * 1024 * 1024:
            raise RuntimeError(f"installer is unexpectedly large: {name}")
        prefix = data.lstrip()[:100].lower()
        if len(data) < 40 or b"<html" in prefix or b"<!doctype html" in prefix:
            raise RuntimeError(f"invalid installer response: {name}")
        handle = tempfile.NamedTemporaryFile(prefix=f"init-{name}-", suffix=".sh", delete=False)
        try:
            handle.write(data)
            handle.flush()
            path = Path(handle.name)
        finally:
            handle.close()
        path.chmod(path.stat().st_mode | stat.S_IXUSR)
        return path

    def install_remote_tool(self, name: str, command_names: list[str]) -> None:
        if any(self.command_exists(command) for command in command_names):
            self.ok(f"{name}: already installed")
            return
        url, arguments = REMOTE_INSTALLERS[name]
        installer: Path | None = None
        try:
            installer = self.download_installer(name, url)
            result = self.run(
                ["bash", str(installer), *arguments],
                check=False,
                network=True,
                timeout=600,
            )
            self._extend_path()
            if result.returncode != 0 or not any(self.command_exists(c) for c in command_names):
                self.failures.append(f"{name} installation failed")
        except Exception as exc:
            self.failures.append(f"{name} installation failed: {exc}")
        finally:
            if installer is not None:
                try:
                    installer.unlink()
                except OSError:
                    pass

    def install_ctf_toolchain(self) -> None:
        self.install_python2_legacy()
        self.install_python_tools()
        self.install_ruby_tools()
        if self.install_radare2():
            self.install_r2ghidra()
        self.install_remote_tool("pwndbg", ["pwndbg", "pwndbg-gdb"])
        self.install_pwndbg_r2ghidra_bridge()
        self.install_helper_repositories()

    def find_command(self, names: list[str]) -> str | None:
        self._extend_path()
        for name in names:
            found = shutil.which(name)
            if found:
                return found
        return None

    def verify(self) -> bool:
        checks = [
            ("python3", ["python3"]),
            ("git", ["git"]),
            ("gcc", ["gcc"]),
            ("g++", ["g++"]),
            ("clang", ["clang"]),
            ("GNU make", ["make"]),
            ("cmake", ["cmake"]),
            ("ninja", ["ninja"]),
            ("meson", ["meson"]),
            ("GNU linker", ["ld"]),
            ("java", ["java"]),
            ("javac", ["javac"]),
            ("ruby", ["ruby"]),
            ("gem", ["gem"]),
            ("bundler", ["bundle", "bundler"]),
            ("perl", ["perl"]),
            ("bash", ["bash"]),
            ("zsh", ["zsh"]),
            ("gdb", ["gdb"]),
            ("gdb-multiarch", ["gdb-multiarch"]),
            ("checksec", ["checksec"]),
            ("patchelf", ["patchelf"]),
            ("xxd", ["xxd"]),
            ("qemu-user", ["qemu-x86_64"]),
            ("qemu-system", ["qemu-system-x86_64"]),
            ("bat", ["bat"]),
            ("fd", ["fd"]),
            ("7z", ["7z"]),
            ("hyfetch", ["hyfetch"]),
            ("nasm", ["nasm"]),
            ("yasm", ["yasm"]),
            ("valgrind", ["valgrind"]),
            ("apktool", ["apktool"]),
            ("steghide", ["steghide"]),
            ("stegseek", ["stegseek"]),
            ("binwalk", ["binwalk"]),
            ("zsteg", ["zsteg"]),
            ("exiftool", ["exiftool"]),
            ("foremost", ["foremost"]),
            ("tshark", ["tshark"]),
            ("hashcat", ["hashcat"]),
            ("john", ["john"]),
            ("ROPgadget", ["ROPgadget", "ropgadget"]),
            ("ropper", ["ropper"]),
            ("pwndbg", ["pwndbg", "pwndbg-gdb"]),
            ("one_gadget", ["one_gadget"]),
            ("seccomp-tools", ["seccomp-tools"]),
        ]
        ok_all = True
        for label, names in checks:
            found = self.find_command(names)
            if found:
                self.ok(f"{label}: {found}")
            else:
                ok_all = False
                message = f"verification failed: {label} not found"
                if message not in self.failures:
                    self.failures.append(message)
                self.error(message)

        radare2_version = self.radare2_version()
        if radare2_version is not None and radare2_version >= RADARE2_MIN_VERSION:
            self.ok(
                f"radare2: {self.find_command(['r2'])} "
                f"(version {self.format_version(radare2_version)})"
            )
        else:
            ok_all = False
            detected = (
                "not found"
                if radare2_version is None
                else self.format_version(radare2_version)
            )
            message = (
                f"verification failed: radare2 {detected}; "
                f">= {self.format_version(RADARE2_MIN_VERSION)} required"
            )
            if message not in self.failures:
                self.failures.append(message)
            self.error(message)

        r2pm = self.find_command(["r2pm"])
        if r2pm:
            self.ok(f"r2pm: {r2pm}")
        else:
            ok_all = False
            message = "verification failed: r2pm not found"
            if message not in self.failures:
                self.failures.append(message)
            self.error(message)

        python2 = self.existing_python2()
        if python2 is not None:
            self.ok(f"Python 2.7 legacy runtime: {python2}")
            pip2 = self.find_command(["pip2"])
            if pip2 and self.python2_pip_ready(python2):
                self.ok(f"Python 2 pip: {pip2}")
            else:
                ok_all = False
                message = "verification failed: Python 2 pip2 command unavailable"
                if message not in self.failures:
                    self.failures.append(message)
                self.error(message)
        else:
            ok_all = False
            message = "verification failed: working Python 2.7 runtime not found"
            if message not in self.failures:
                self.failures.append(message)
            self.error(message)

        if self.docker_ready():
            self.ok("Docker Engine, Buildx and Compose")
        else:
            ok_all = False
            message = "verification failed: Docker Engine, Buildx or Compose unavailable"
            if message not in self.failures:
                self.failures.append(message)
            self.error(message)

        python = self.system_python()
        pip3 = self.run(
            [python, "-m", "pip", "--version"],
            check=False,
            capture=True,
            timeout=30,
        )
        if pip3.returncode == 0:
            self.ok("Python 3 pip")
        else:
            ok_all = False
            message = "verification failed: Python 3 pip module unavailable"
            if message not in self.failures:
                self.failures.append(message)
            self.error(message)

        imports = self.run(
            [python, "-c", "; ".join(f"import {module}" for module in PYTHON_IMPORTS)],
            check=False,
            capture=True,
        )
        if imports.returncode == 0:
            self.ok("Python CTF libraries")
        else:
            ok_all = False
            message = "verification failed: Python CTF library import failed"
            if message not in self.failures:
                self.failures.append(message)
            self.error(message)

        if self.r2ghidra_available():
            self.ok("r2ghidra plugin")
        else:
            ok_all = False
            message = "verification failed: r2ghidra plugin not found"
            if message not in self.failures:
                self.failures.append(message)
            self.error(message)

        if self.r2pipe_target_available():
            self.ok(f"Pwndbg r2pipe {R2PIPE_VERSION}: {PWNDBG_PYTHON_DIR}")
        else:
            ok_all = False
            message = "verification failed: isolated Pwndbg r2pipe package not found"
            if message not in self.failures:
                self.failures.append(message)
            self.error(message)

        if self.pwndbg_r2ghidra_available():
            self.ok("Pwndbg r2ghidra integration and ghidra command")
        else:
            ok_all = False
            message = "verification failed: Pwndbg r2ghidra integration unavailable"
            if message not in self.failures:
                self.failures.append(message)
            self.error(message)

        managed_repositories = (
            ("glibc-all-in-one", GLIBC_AIO_DIR),
            ("libc-database", LIBC_DATABASE_DIR),
        )
        for label, path in managed_repositories:
            if (path / ".git").exists():
                self.ok(f"{label}: {path}")
            else:
                ok_all = False
                message = f"verification failed: {label} repository not found at {path}"
                if message not in self.failures:
                    self.failures.append(message)
                self.error(message)

        glibc_aio = self.find_command(["glibc-aio"])
        if glibc_aio:
            self.ok(f"glibc-aio: {glibc_aio}")
        else:
            ok_all = False
            message = "verification failed: glibc-aio command not found"
            if message not in self.failures:
                self.failures.append(message)
            self.error(message)

        return ok_all

    def summary(self) -> int:
        elapsed = self.format_duration(time.monotonic() - self.started_monotonic)
        if self.skipped:
            print("Skipped:")
            for item in self.skipped:
                print(f"  - {item}")
        if self.failures:
            print("Failures:")
            for item in self.failures:
                print(f"  - {item}")
            self.error(f"completed with {len(self.failures)} failure(s) in {elapsed}")
            return 1
        self.ok(f"CTF environment installation and verification completed in {elapsed}")
        return 0

    def install(self) -> int:
        print(self.colorize("36;1", f"init {VERSION}"))
        print("Target: CTF workstation | Mode: non-interactive")
        self.run_stage("Environment check", self.preflight)
        self.run_stage("System foundation", self.install_system_foundation)
        self.run_stage("CTF toolchain", self.install_ctf_toolchain)
        self.run_stage("Verification", self.verify)
        return self.summary()


def help_text() -> str:
    return f"""init {VERSION}

Usage:
  python3 init.py          Initialize and verify the CTF environment
  python3 init.py --help   Show this help

The default operation is safe to rerun. It does not run full-upgrade or autoremove.
""".strip()


def main(argv: list[str]) -> int:
    if argv in (["-h"], ["--help"]):
        print(help_text())
        return 0
    bootstrap = Bootstrap()
    if argv:
        print("unknown arguments: " + " ".join(argv), file=sys.stderr)
        print(help_text(), file=sys.stderr)
        return 2
    try:
        return bootstrap.install()
    except KeyboardInterrupt:
        print("\ninstallation cancelled", file=sys.stderr)
        return 130
    except Exception as exc:
        bootstrap.failures.append(str(exc))
        bootstrap.error(str(exc))
        return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
