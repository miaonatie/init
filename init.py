#!/usr/bin/env python3
"""Idempotent Pwn/CTF workstation bootstrap for Debian-family systems."""

from __future__ import annotations

import os
import platform
import shlex
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path
from typing import Iterable
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parent
HOME = Path.home()
TOOLS_DIR = HOME / "tools"
VERSION_FILE = ROOT / "VERSION"
VERSION = VERSION_FILE.read_text(encoding="utf-8").strip() if VERSION_FILE.exists() else "dev"

NETWORK_ATTEMPTS = 3
NETWORK_DELAYS = (2, 5)
SUPPORTED_DISTROS = {"ubuntu", "debian", "kali"}
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
    "unzip", "zip", "xz-utils", "zstd", "tar", "gzip", "bzip2", "p7zip-full",
    "cpio", "rpm2cpio",
    "pkg-config", "file", "vim", "nano", "tmux", "tree",
    "socat", "netcat-openbsd", "openssh-client",
    "build-essential", "libssl-dev", "libffi-dev", "dkms",
    "autoconf", "automake", "libtool", "cmake", "default-jdk",
    "python3", "python3-dev", "python3-pip", "python3-setuptools", "python3-wheel",
    "python3-venv", "python-is-python3",
    "ruby-full", "bundler",
    "gdb", "gdbserver", "gdb-multiarch", "patchelf", "binutils", "binutils-multiarch",
    "elfutils", "ltrace", "strace", "checksec", "libseccomp-dev", "seccomp", "libc6-dbg",
    "qemu-user", "qemu-system", "qemu-user-binfmt",
    "net-tools", "dnsutils", "iputils-ping", "traceroute", "mtr-tiny", "iperf3",
    "tcpdump", "nmap", "lsof", "fail2ban", "ufw",
]

OPTIONAL_APT = [
    "bat", "fd-find", "ripgrep", "fzf", "zoxide", "duf", "gdu", "btop",
    "htop", "ncdu", "jq", "yq", "hyfetch",
]

I386_APT = [
    "gcc-multilib", "g++-multilib", "libc6-i386", "libc6-dev-i386", "libc6-dbg:i386",
]

PYTHON_PACKAGES = [
    "pwntools", "ROPgadget", "ropper", "capstone", "unicorn", "keystone-engine",
    "z3-solver", "pyelftools", "lief",
]

RUBY_GEMS = ["one_gadget", "seccomp-tools"]

HELPER_REPOS = {
    "glibc-all-in-one": "https://github.com/matrix1001/glibc-all-in-one.git",
    "libc-database": "https://github.com/niklasb/libc-database.git",
}

REMOTE_INSTALLERS = {
    "pwndbg": ("https://install.pwndbg.re", ["-t", "pwndbg-gdb", "-u"]),
    "codex": ("https://chatgpt.com/codex/install.sh", []),
    "claude": ("https://claude.ai/install.sh", []),
    "cc-switch": (
        "https://github.com/SaladDay/cc-switch-cli/releases/latest/download/install.sh",
        [],
    ),
}

ALLOWED_INSTALLER_HOSTS = {
    "install.pwndbg.re", "chatgpt.com", "claude.ai", "github.com",
}


class Bootstrap:
    def __init__(self) -> None:
        self.failures: list[str] = []
        self.skipped: list[str] = []
        self.started_monotonic = time.monotonic()
        self.step = 0
        self.step_total = 5
        self.apt_updated = False
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

    @staticmethod
    def command_exists(command: str) -> bool:
        return shutil.which(command) is not None

    @staticmethod
    def detect_distro() -> dict[str, str]:
        result: dict[str, str] = {"id": "unknown", "name": "Unknown Linux", "version": ""}
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

    def _extend_path(self) -> None:
        candidates = [
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
        self.section("Preflight")
        if sys.platform != "linux":
            raise RuntimeError("this installer supports Linux and WSL only")
        if not self.command_exists("apt-get") or not self.command_exists("dpkg-query"):
            raise RuntimeError("apt-get and dpkg-query are required")
        if self.distro["id"] not in SUPPORTED_DISTROS:
            raise RuntimeError(
                f"unsupported distribution: {self.distro['name']} "
                f"(supported: Ubuntu, Debian, Kali)"
            )
        self.require_sudo()
        free = shutil.disk_usage(HOME).free
        free_gib = free / (1024 ** 3)
        if free_gib < 1:
            raise RuntimeError(f"not enough free disk space: {free_gib:.1f} GiB")
        if free_gib < 3:
            self.warn(f"low disk space: {free_gib:.1f} GiB free; 3 GiB or more is recommended")
        self.ok(
            f"{self.distro['name']} | {self.arch} | WSL={'yes' if self.is_wsl else 'no'} "
            f"| free={free_gib:.1f} GiB"
        )

    def package_installed(self, package: str) -> bool:
        result = self.run(
            ["dpkg-query", "-W", "-f=${Status}", package],
            capture=True,
            check=False,
        )
        return result.returncode == 0 and "install ok installed" in (result.stdout or "")

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
        self.info(f"installing {label}: {len(missing)} packages")
        result = self.run(
            [
                "apt-get", *self.apt_options(), "install", "-y", "--fix-missing",
                "--no-install-recommends", *missing,
            ],
            sudo=True,
            check=False,
            network=True,
            env=self.apt_env(),
        )
        if result.returncode == 0:
            return True

        self.warn(f"batch install failed for {label}; retrying remaining packages individually")
        ok_all = True
        for package in [p for p in missing if not self.package_installed(p)]:
            result = self.run(
                [
                    "apt-get", *self.apt_options(), "install", "-y", "--fix-missing",
                    "--no-install-recommends", package,
                ],
                sudo=True,
                check=False,
                network=True,
                env=self.apt_env(),
            )
            if result.returncode != 0:
                ok_all = False
                message = f"APT package failed: {package}"
                (self.failures if required else self.skipped).append(message)
        return ok_all

    def install_system_packages(self) -> None:
        self.section("System packages")
        if self.distro["id"] == "ubuntu":
            if self.apt_install(
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
        self.apt_install([*REQUIRED_APT, *i386], "required packages", required=True)
        self.apt_install(OPTIONAL_APT, "daily-use tools", required=False)
        self.install_command_links()

    def install_command_links(self) -> None:
        for source, target in (("batcat", "bat"), ("fdfind", "fd")):
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

    def install_python_tools(self) -> None:
        python = "/usr/bin/python3" if Path("/usr/bin/python3").exists() else "python3"
        help_result = self.run(
            [python, "-m", "pip", "install", "--help"],
            capture=True,
            check=False,
        )
        break_flag = (
            ["--break-system-packages"]
            if "--break-system-packages" in (help_result.stdout or "")
            else []
        )
        if not break_flag:
            self.warn("this pip version does not support --break-system-packages; continuing in compatibility mode")
        result = self.run(
            [
                python, "-m", "pip", "install", *break_flag,
                "--disable-pip-version-check", *PYTHON_PACKAGES,
            ],
            sudo=True,
            check=False,
            network=True,
            env={"PIP_ROOT_USER_ACTION": "ignore"},
        )
        if result.returncode != 0:
            self.failures.append("Python Pwn package installation failed")
        else:
            self.ok("Python tools installed system-wide")

    def install_ruby_tools(self) -> None:
        if not self.command_exists("gem"):
            self.failures.append("RubyGems is unavailable")
            return
        missing = [gem for gem in RUBY_GEMS if not self.command_exists(gem)]
        if not missing:
            self.ok("Ruby Pwn tools: already installed")
            return
        result = self.run(
            ["gem", "install", "--no-document", *missing],
            sudo=True,
            check=False,
            network=True,
        )
        self._extend_path()
        if result.returncode != 0:
            self.failures.append("Ruby Pwn tool installation failed")

    def clone_or_update(self, name: str, url: str) -> bool:
        destination = TOOLS_DIR / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        env = {"GIT_TERMINAL_PROMPT": "0", "GIT_ASKPASS": "true"}
        if (destination / ".git").exists():
            result = self.run(
                ["git", "pull", "--ff-only", "--quiet"],
                cwd=destination,
                env=env,
                check=False,
                network=True,
                timeout=180,
            )
            if result.returncode != 0:
                self.failures.append(f"repository update failed: {name}")
                return False
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
                update_list = TOOLS_DIR / name / "update_list"
                if update_list.exists():
                    result = self.run(
                        ["bash", "./update_list"],
                        cwd=update_list.parent,
                        check=False,
                        network=True,
                    )
                    if result.returncode != 0:
                        self.skipped.append("glibc-all-in-one list update failed")

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

    def install_pwn_tools(self) -> None:
        self.section("Pwn tools")
        self.install_python_tools()
        self.install_ruby_tools()
        self.install_remote_tool("pwndbg", ["pwndbg", "pwndbg-gdb"])
        self.install_helper_repositories()

    def install_ai_tools(self) -> None:
        self.section("AI tools")
        self.install_remote_tool("codex", ["codex"])
        self.install_remote_tool("claude", ["claude"])
        self.install_remote_tool("cc-switch", ["cc-switch"])

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
            ("gdb", ["gdb"]),
            ("checksec", ["checksec"]),
            ("patchelf", ["patchelf"]),
            ("ROPgadget", ["ROPgadget", "ropgadget"]),
            ("ropper", ["ropper"]),
            ("pwndbg", ["pwndbg", "pwndbg-gdb"]),
            ("one_gadget", ["one_gadget"]),
            ("seccomp-tools", ["seccomp-tools"]),
            ("codex", ["codex"]),
            ("claude", ["claude"]),
            ("cc-switch", ["cc-switch"]),
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
        self.ok(f"installation and verification completed in {elapsed}")
        return 0

    def install(self) -> int:
        print(self.colorize("36;1", f"init {VERSION}"))
        print("Mode: non-interactive")
        self.preflight()
        self.install_system_packages()
        self.install_pwn_tools()
        self.install_ai_tools()
        self.section("Verification")
        self.verify()
        return self.summary()


def help_text() -> str:
    return f"""init {VERSION}

Usage:
  python3 init.py          Install and verify
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
