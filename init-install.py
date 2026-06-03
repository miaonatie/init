#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""One-shot CTF pwn environment installer for fresh WSL/Linux systems."""

from __future__ import annotations

import json
import os
import re
import shutil
import shlex
import subprocess
import sys
import tempfile
import termios
import textwrap
import time
import tty
import urllib.request
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Iterable, Optional

VERSION = "v1.0.5"
ROOT = Path(__file__).resolve().parent
STATE = ROOT / "state"

CORE_APT = [
    "ca-certificates", "curl", "wget", "git", "sudo", "gnupg", "lsb-release",
    "unzip", "zip", "xz-utils", "zstd", "tar", "gzip", "bzip2", "p7zip-full",
    "rpm2cpio", "cpio", "make", "pkg-config", "file", "vim", "nano", "tmux",
    "less", "jq", "tree", "ripgrep", "fd-find", "socat", "netcat-openbsd",
    "openssh-client", "rlwrap", "htop", "net-tools", "python-is-python3",
    "build-essential", "gcc", "g++", "libssl-dev", "libffi-dev",
    "autoconf", "automake", "libtool", "cmake",
    "python3", "python3-dev", "python3-pip", "python3-venv", "python3-setuptools", "python3-wheel",
    "gdb", "gdbserver", "gdb-multiarch", "patchelf", "binutils", "binutils-multiarch",
    "elfutils", "ltrace", "strace", "checksec", "libseccomp-dev", "seccomp", "libc6-dbg",
]
I386_APT = ["gcc-multilib", "g++-multilib", "libc6-i386", "libc6-dev-i386", "libc6-dbg:i386"]
QEMU_APT = ["qemu-user", "qemu-user-static", "qemu-user-binfmt", "qemu-utils"]
RUBY_APT = ["ruby-full", "bundler"]
DEFAULT_JRE_APT = ["default-jre"]
SHELL_APT = ["zsh"]
MODERN_CLI_APT = ["bat", "fzf", "btop", "duf"]
PYTHON_PWN = ["pwntools", "ROPgadget", "ropper", "capstone", "unicorn", "keystone-engine", "z3-solver", "pyelftools", "lief", "ipython"]
RUBY_GEMS = ["one_gadget", "seccomp-tools"]
HELPER_REPOS = {
    "glibc-all-in-one": "https://github.com/matrix1001/glibc-all-in-one.git",
    "libc-database": "https://github.com/niklasb/libc-database.git",
}
NVM_VERSION = "v0.40.4"
CC_SWITCH_INSTALL = "https://github.com/SaladDay/cc-switch-cli/releases/latest/download/install.sh"
CLAUDE_INSTALL = "https://claude.ai/install.sh"
NETWORK_ATTEMPTS = 4
NETWORK_RETRY_DELAYS = [2, 5, 10]
PROBE_ATTEMPTS = 3
APT_UPDATE_WARN_PATTERNS = [
    "Failed to fetch", "Some index files failed", "Unable to connect", "Could not connect",
    "Connection timed out", "Temporary failure resolving", "does not have a Release file",
    "NO_PUBKEY", "Hash Sum mismatch",
]


@dataclass
class Distro:
    id: str = "unknown"
    name: str = "Unknown Linux"
    version: str = ""
    is_wsl: bool = False


@dataclass
class Choices:
    chsrc: bool = False
    extra_apt_repo: bool = True
    apt_upgrade: bool = True
    core_apt: bool = True
    i386: bool = True
    qemu: bool = True
    language_env: bool = True
    shell_ui: bool = True
    modern_cli: bool = True
    trashy: bool = True
    codex_cli: bool = True
    claude_code: bool = True
    cc_switch: bool = True
    python_pwn: bool = True
    ruby_tools: bool = True
    pwndbg: bool = True
    helper_repos: bool = True
    libc_get_common: bool = False
    libc_get_all: bool = False
    glibc_download: bool = False
    glibc_versions: list[str] = field(default_factory=list)


class UI:
    def __init__(self) -> None:
        color = sys.stdout.isatty() and not os.environ.get("NO_COLOR")
        self.reset = "\033[0m" if color else ""
        self.bold = "\033[1m" if color else ""
        self.dim = "\033[2m" if color else ""
        self.blue = "\033[34m" if color else ""
        self.cyan = "\033[36m" if color else ""
        self.green = "\033[32m" if color else ""
        self.yellow = "\033[33m" if color else ""
        self.red = "\033[31m" if color else ""
        self.step_no = 0
        self.step_total = 1
        self.started = time.monotonic()

    def banner(self, distro: Distro) -> None:
        print(self.cyan + "=" * 70 + self.reset)
        print(f"  {self.bold}init-install {VERSION}{self.reset}")
        print("  WSL / Kali / Debian / Ubuntu CTF pwn environment installer")
        print(f"  Detected: {distro.name} | WSL: {'yes' if distro.is_wsl else 'no'}")
        print(self.cyan + "=" * 70 + self.reset)

    @staticmethod
    def human_time(seconds: float) -> str:
        seconds = max(0, int(seconds))
        h, r = divmod(seconds, 3600)
        m, s = divmod(r, 60)
        return f"{h}h{m:02d}m" if h else (f"{m}m{s:02d}s" if m else f"{s}s")

    def set_total(self, total: int) -> None:
        self.step_no = 0
        self.step_total = max(1, total)
        self.started = time.monotonic()

    def section(self, title: str) -> None:
        self.step_no += 1
        print()
        print(f"{self.bold}{self.blue}==> [{self.step_no:02d}/{self.step_total:02d}] {title}{self.reset}")
        print(f"    elapsed {self.human_time(time.monotonic() - self.started)}")

    def task(self, msg: str) -> None: print(f"{self.cyan}  ->{self.reset} {msg}")
    def cmd(self, cmd: list[str]) -> None: print(f"  $ {' '.join(cmd)}")
    def ok(self, msg: str) -> None: print(f"{self.green}[OK]{self.reset} {msg}")
    def warn(self, msg: str) -> None: print(f"{self.yellow}[WARN]{self.reset} {msg}")
    def err(self, msg: str) -> None: print(f"{self.red}[ERR]{self.reset} {msg}", file=sys.stderr)

    def ask_key(self, prompt: str, default: bool) -> str:
        suffix = "Y/n" if default else "y/N"
        text = f"{prompt} [{suffix}]: "
        if not sys.stdin.isatty():
            try: ans = input(text).strip().lower()
            except EOFError: return "yes" if default else "no"
            if ans in {"q", "quit", "exit"}: return "quit"
            if ans in {"b", "back"}: return "back"
            if not ans: return "yes" if default else "no"
            return "yes" if ans in {"y", "yes", "1", "true", "on"} else "no"
        print(text, end="", flush=True)
        old = termios.tcgetattr(sys.stdin)
        try:
            tty.setcbreak(sys.stdin.fileno())
            ch = sys.stdin.read(1).lower()
        finally:
            termios.tcsetattr(sys.stdin, termios.TCSADRAIN, old)
        print(ch if ch not in {"\n", "\r"} else "Enter")
        if ch in {"q", "\x03"}: return "quit"
        if ch in {"b", "\x7f"}: return "back"
        if ch in {"\n", "\r", " "}: return "yes" if default else "no"
        if ch == "y": return "yes"
        if ch == "n": return "no"
        return "yes" if default else "no"


class Installer:
    def __init__(self, choices: Optional[Choices] = None, no_config: bool = False) -> None:
        self.ui = UI()
        self.home = Path.home()
        self.tools_dir = self.home / "tools"
        self.choices = choices or Choices()
        self.no_config = no_config
        self.distro = self.detect_distro()
        self.apt_updated = False
        self.apt_ok = True
        self.github_ok = False
        self.github_proxy_ok = False
        self.pypi_ok = False
        self.rubygems_ok = False
        self.nodejs_ok = False
        self.npm_ok = False
        self.npm_registry_url = "https://registry.npmjs.org/"
        self.npm_registry_name = "official"
        self.claude_ok = False
        self.rustup_ok = False
        self.go_ok = False
        self.pwndbg_installer_ok = False
        self.failures: list[str] = []
        self.skipped: list[str] = []
        self._pip_names: Optional[set[str]] = None
        self._tmp_path_env()

    def _tmp_path_env(self) -> None:
        for d in [self.home / ".local" / "bin", self.home / ".cargo" / "bin", self.home / ".local" / "go" / "bin", self.home / "go" / "bin"]:
            ds = str(d)
            if ds not in os.environ.get("PATH", "").split(os.pathsep):
                os.environ["PATH"] = ds + os.pathsep + os.environ.get("PATH", "")

    @staticmethod
    def exists(cmd: str) -> bool: return shutil.which(cmd) is not None

    def detect_distro(self) -> Distro:
        data: dict[str, str] = {}
        try:
            for line in Path("/etc/os-release").read_text(errors="ignore").splitlines():
                if "=" in line:
                    k, v = line.split("=", 1)
                    data[k] = v.strip().strip('"')
        except OSError:
            pass
        try: procver = Path("/proc/version").read_text(errors="ignore").lower()
        except OSError: procver = ""
        return Distro(
            id=data.get("ID", "unknown").lower(),
            name=data.get("PRETTY_NAME", data.get("NAME", "Unknown Linux")),
            version=data.get("VERSION_ID", ""),
            is_wsl="microsoft" in procver or "wsl" in procver or bool(os.environ.get("WSL_DISTRO_NAME")),
        )

    def run(self, cmd: list[str], *, sudo: bool = False, check: bool = True, capture: bool = False, cwd: Optional[Path] = None, env: Optional[dict[str,str]] = None, input_text: Optional[str] = None, network: bool = False, timeout: Optional[int] = None) -> subprocess.CompletedProcess[str]:
        final = list(cmd)
        if sudo and os.geteuid() != 0:
            final = ["sudo", *final]
        merged = os.environ.copy()
        if env: merged.update(env)
        attempts = NETWORK_ATTEMPTS if network else 1
        last = None
        for i in range(1, attempts + 1):
            if not capture: self.ui.cmd(final)
            try:
                last = subprocess.run(final, cwd=str(cwd) if cwd else None, env=merged, input=input_text, text=True, stdout=subprocess.PIPE if capture else None, stderr=subprocess.PIPE if capture else None, timeout=timeout)
            except subprocess.TimeoutExpired as exc:
                last = subprocess.CompletedProcess(final, 124, stdout=getattr(exc, "stdout", None), stderr=getattr(exc, "stderr", None))
                self.ui.warn(f"timeout: {timeout}s")
            if last.returncode == 0:
                return last
            if i < attempts:
                wait = NETWORK_RETRY_DELAYS[min(i - 1, len(NETWORK_RETRY_DELAYS) - 1)]
                self.ui.warn(f"failed, retry in {wait}s ({i}/{attempts})")
                time.sleep(wait)
        assert last is not None
        if check and last.returncode != 0:
            raise subprocess.CalledProcessError(last.returncode, final, output=last.stdout, stderr=last.stderr)
        return last

    def require_sudo(self) -> None:
        if os.geteuid() == 0: return
        if not self.exists("sudo"):
            raise RuntimeError("sudo not found. Install sudo first or run as root.")
        self.run(["sudo", "-v"])

    def http_ok(self, url: str, timeout: int = 8) -> bool:
        if self.exists("curl"):
            cmd = ["curl", "-fsSL", "--connect-timeout", "5", "--max-time", str(timeout), "-o", "/dev/null", url]
            if subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0:
                return True
        try:
            req = urllib.request.Request(url, headers={"User-Agent": f"init/{VERSION}"})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return 200 <= getattr(resp, "status", 200) < 400
        except Exception:
            return False

    def probe_urls(self, label: str, urls: list[str], quiet: bool = False, attempts: int = PROBE_ATTEMPTS) -> bool:
        for a in range(1, attempts + 1):
            for u in urls:
                if self.http_ok(u):
                    if not quiet: self.ui.ok(f"{label}: reachable" + (f" (retry {a})" if a > 1 else ""))
                    return True
            if a < attempts: time.sleep(1 + a)
        if not quiet: self.ui.warn(f"{label}: not reachable")
        return False

    def detect_network(self) -> None:
        self.ui.section("network preflight")
        self.github_ok = self.probe_urls("GitHub", ["https://github.com/"])
        self.github_proxy_ok = self.probe_urls("GitHub proxy", ["https://gh.xmly.dev/https://github.com/"])
        self.pypi_ok = self.probe_urls("PyPI", ["https://pypi.org/simple/"])
        self.rubygems_ok = self.probe_urls("RubyGems", ["https://rubygems.org/"])
        self.nodejs_ok = self.probe_urls("Node.js", ["https://nodejs.org/dist/"])
        self.claude_ok = self.probe_urls("Claude Code", [CLAUDE_INSTALL])
        self.rustup_ok = self.probe_urls("rustup", ["https://sh.rustup.rs/"])
        self.go_ok = self.probe_urls("Go", ["https://go.dev/dl/"])
        self.pwndbg_installer_ok = self.probe_urls("pwndbg installer", ["https://install.pwndbg.re/"])
        self.npm_ok, self.npm_registry_url, self.npm_registry_name = self.npm_registry_probe()
        self.ui.ok(f"npm registry: reachable ({self.npm_registry_name})") if self.npm_ok else self.ui.warn("npm registry: not reachable")

    def npm_registry_probe(self) -> tuple[bool, str, str]:
        candidates = [("official", "https://registry.npmjs.org/"), ("npmmirror", "https://registry.npmmirror.com/")]
        for name, base in candidates:
            if self.probe_urls(f"npm {name}", [base, base.rstrip("/") + "/-/ping"], quiet=True):
                return True, base, name
        if self.exists("npm"):
            for name, base in candidates:
                r = subprocess.run(["npm", "--registry", base, "ping", "--fetch-timeout", "15000"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, text=True)
                if r.returncode == 0:
                    return True, base, name
        return False, candidates[0][1], candidates[0][0]

    def gh(self, url: str) -> str:
        if self.github_ok: return url
        if self.github_proxy_ok: return "https://gh.xmly.dev/" + url
        return url

    def ensure_github(self) -> bool:
        if self.github_ok or self.github_proxy_ok: return True
        self.github_ok = self.probe_urls("GitHub", ["https://github.com/"], quiet=True)
        self.github_proxy_ok = self.probe_urls("GitHub proxy", ["https://gh.xmly.dev/https://github.com/"], quiet=True)
        return self.github_ok or self.github_proxy_ok

    def ensure_pypi(self) -> bool:
        if self.pypi_ok: return True
        self.pypi_ok = self.probe_urls("PyPI", ["https://pypi.org/simple/"], quiet=True)
        return self.pypi_ok

    def ensure_rubygems(self) -> bool:
        if self.rubygems_ok: return True
        self.rubygems_ok = self.probe_urls("RubyGems", ["https://rubygems.org/"], quiet=True)
        return self.rubygems_ok

    def apt_env(self) -> dict[str, str]: return {"DEBIAN_FRONTEND": "noninteractive", "NEEDRESTART_MODE": "a"}
    def apt_install_opts(self) -> list[str]: return ["-o", "Dpkg::Options::=--force-confold"]
    def apt_update_opts(self) -> list[str]: return ["-o", "Acquire::Retries=3"]

    def apt_update_output_bad(self, output: str) -> bool:
        return any(p in output for p in APT_UPDATE_WARN_PATTERNS)

    def apt_update(self) -> bool:
        if self.apt_updated: return self.apt_ok
        final = ["apt-get", *self.apt_update_opts(), "update"]
        for attempt in range(1, NETWORK_ATTEMPTS + 1):
            r = self.run(final, sudo=True, env=self.apt_env(), capture=True, check=False)
            out = (r.stdout or "") + (r.stderr or "")
            if out.strip(): print(out, end="" if out.endswith("\n") else "\n")
            if r.returncode == 0 and not self.apt_update_output_bad(out):
                self.apt_updated = True; self.apt_ok = True; return True
            if attempt < NETWORK_ATTEMPTS:
                wait = NETWORK_RETRY_DELAYS[min(attempt - 1, len(NETWORK_RETRY_DELAYS) - 1)]
                self.ui.warn(f"APT update incomplete, retry in {wait}s")
                time.sleep(wait)
        self.apt_ok = False
        self.failures.append("APT update failed or incomplete")
        return False

    def pkg_installed(self, pkg: str) -> bool:
        r = self.run(["dpkg-query", "-W", "-f=${Status}", pkg], capture=True, check=False)
        return r.returncode == 0 and "install ok installed" in (r.stdout or "")

    def apt_install(self, packages: Iterable[str], label: str) -> None:
        pkgs = list(dict.fromkeys(packages))
        missing = [p for p in pkgs if not self.pkg_installed(p)]
        if not missing:
            self.ui.ok(f"{label}: already installed")
            return
        if not self.apt_update():
            self.skipped.append(f"APT skipped: {label}")
            return
        self.ui.task(f"APT install: {label} ({len(missing)})")
        for i, pkg in enumerate(missing, 1):
            self.ui.task(f"[{i}/{len(missing)}] {pkg}")
            try:
                self.run(["apt-get", *self.apt_install_opts(), "install", "-y", "--fix-missing", "--no-install-recommends", pkg], sudo=True, env=self.apt_env(), network=True)
            except subprocess.CalledProcessError:
                self.failures.append(f"APT package failed: {pkg}")
                self.ui.warn(f"skip failed package: {pkg}")

    def configure_apt_defaults(self) -> None:
        self.ui.section("APT defaults")
        conf = """Acquire::Retries \"3\";
Acquire::http::Timeout \"20\";
Acquire::https::Timeout \"20\";
Acquire::IndexTargets::deb::Contents-deb::DefaultEnabled \"false\";
Acquire::IndexTargets::deb::Contents-udeb::DefaultEnabled \"false\";
"""
        target = Path("/etc/apt/apt.conf.d/99init")
        with tempfile.NamedTemporaryFile("w", delete=False) as tmp:
            tmp.write(conf); tmp_path = Path(tmp.name)
        try:
            self.run(["install", "-m", "0644", "-o", "root", "-g", "root", str(tmp_path), str(target)], sudo=True, check=False)
        finally:
            try: tmp_path.unlink()
            except OSError: pass

    def configure_extra_apt_repo(self) -> None:
        if not self.choices.extra_apt_repo or self.distro.id != "ubuntu": return
        self.ui.section("Ubuntu universe")
        self.apt_install(["software-properties-common"], "ubuntu-universe-helper")
        if self.apt_ok:
            self.run(["add-apt-repository", "-y", "universe"], sudo=True, check=False, env=self.apt_env())
            self.apt_updated = False
            self.apt_update()

    def configure_chsrc(self) -> None:
        if not self.choices.chsrc: return
        self.ui.section("chsrc mirror switch")
        if not self.exists("chsrc"):
            r = self.run(["bash", "-lc", "curl -fsSL https://chsrc.run/posix | bash"], sudo=True, network=True, check=False)
            if r.returncode != 0:
                self.failures.append("chsrc install failed"); return
        distro_target = {"kali":"kali", "ubuntu":"ubuntu", "debian":"debian"}.get(self.distro.id)
        targets = ([distro_target] if distro_target else []) + ["pypi", "ruby", "rust", "npm", "nodejs", "go"]
        for t in targets:
            self.run(["chsrc", "set", t, "ustc/ali/mirrorz"], sudo=True, check=False, network=True)
        self.apt_updated = False

    def system_full_upgrade(self) -> None:
        if not self.choices.apt_upgrade: return
        self.ui.section("system full-upgrade")
        if not self.apt_update(): return
        self.run(["apt-get", *self.apt_install_opts(), "full-upgrade", "-y"], sudo=True, env=self.apt_env(), network=True, check=False)
        self.run(["apt-get", *self.apt_install_opts(), "autoremove", "-y"], sudo=True, env=self.apt_env(), network=True, check=False)

    def install_i386_qemu(self) -> None:
        if self.choices.i386:
            self.ui.section("i386 / multilib")
            if self.apt_update():
                r = self.run(["dpkg", "--print-foreign-architectures"], capture=True, check=False)
                if "i386" not in (r.stdout or "").split():
                    self.run(["dpkg", "--add-architecture", "i386"], sudo=True)
                    self.apt_updated = False
                self.apt_install(I386_APT, "i386")
        if self.choices.qemu:
            self.ui.section("qemu-user")
            self.apt_install(QEMU_APT, "qemu")

    def install_core_apt(self) -> None:
        if self.choices.core_apt:
            self.ui.section("core APT packages")
            self.apt_install(CORE_APT, "core")

    def install_language_env(self) -> None:
        if not self.choices.language_env: return
        self.ui.section("language runtimes")
        self.install_ruby_base(); self.install_rust_base(); self.install_go_base(); self.install_java_runtime()

    def install_ruby_base(self) -> None:
        if self.exists("ruby") and (self.exists("bundle") or self.exists("bundler")): self.ui.ok("Ruby already available"); return
        self.apt_install(RUBY_APT, "ruby")

    def install_rust_base(self) -> None:
        if self.exists("rustc") and self.exists("cargo"): self.ui.ok("Rust already available"); return
        if self.rustup_ok or self.probe_urls("rustup", ["https://sh.rustup.rs/"], quiet=True):
            r = self.run(["bash", "-lc", "curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y --profile minimal --default-toolchain stable"], network=True, check=False)
            if r.returncode == 0: self._tmp_path_env(); return
        self.apt_install(["rustc", "cargo"], "rust")

    def install_go_base(self) -> None:
        if self.exists("go") or (self.home / ".local" / "go" / "bin" / "go").exists(): self.ui.ok("Go already available"); return
        self.apt_install(["golang-go"], "go")

    def install_java_runtime(self) -> None:
        if self.exists("java"): self.ui.ok("Java already available"); return
        self.apt_install(DEFAULT_JRE_APT, "java")

    @staticmethod
    def norm_pkg(name: str) -> str: return name.lower().replace("_", "-")
    def pip_break_flag(self) -> list[str]:
        r = self.run(["python3", "-m", "pip", "install", "--help"], capture=True, check=False)
        return ["--break-system-packages"] if "--break-system-packages" in (r.stdout or "") else []

    def pip_names(self) -> set[str]:
        if self._pip_names is not None: return self._pip_names
        try:
            r = subprocess.run(["python3", "-m", "pip", "list", "--format=json"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=20)
            data = json.loads(r.stdout) if r.returncode == 0 and r.stdout.strip() else []
            self._pip_names = {self.norm_pkg(x.get("name", "")) for x in data if x.get("name")}
        except Exception: self._pip_names = set()
        return self._pip_names

    def pip_install(self, packages: list[str], label: str) -> None:
        if not self.ensure_pypi(): self.skipped.append(f"pip skipped: {label}"); return
        missing = [p for p in packages if self.norm_pkg(p) not in self.pip_names()]
        if not missing: self.ui.ok(f"{label}: already installed"); return
        flags = self.pip_break_flag()
        for i, p in enumerate(missing, 1):
            self.ui.task(f"pip [{i}/{len(missing)}] {p}")
            r = self.run(["python3", "-m", "pip", "install", "--user", *flags, p], network=True, check=False)
            if r.returncode == 0: self._pip_names = None
            else: self.failures.append(f"pip package failed: {p}")

    def install_python_pwn(self) -> None:
        if not self.choices.python_pwn: return
        self.ui.section("Python pwn packages")
        self.apt_install(["python3", "python3-dev", "python3-pip", "python3-venv", "python3-setuptools", "python3-wheel", "python-is-python3"], "python")
        self.pip_install(PYTHON_PWN, "python-pwn")
        local_py = self.home / ".local" / "bin" / "py"
        if not local_py.exists():
            try:
                local_py.parent.mkdir(parents=True, exist_ok=True)
                local_py.symlink_to("/usr/bin/python3")
            except OSError: pass

    def install_ruby_tools(self) -> None:
        if not self.choices.ruby_tools: return
        self.ui.section("Ruby pwn tools")
        self.apt_install(RUBY_APT, "ruby")
        if not self.ensure_rubygems(): self.skipped.append("gem skipped"); return
        for g in [g for g in RUBY_GEMS if not self.exists(g)]:
            r = self.run(["gem", "install", "--no-document", g], sudo=True, network=True, check=False)
            if r.returncode != 0: self.failures.append(f"gem failed: {g}")

    def clone_or_pull(self, url: str, dest: Path) -> bool:
        if not self.ensure_github(): self.skipped.append(f"git skipped: {dest.name}"); return False
        dest.parent.mkdir(parents=True, exist_ok=True)
        env = {"GIT_TERMINAL_PROMPT":"0", "GIT_ASKPASS":"true"}
        if (dest / ".git").exists():
            r = self.run(["git", "pull", "--ff-only", "--quiet"], cwd=dest, env=env, check=False, network=True, timeout=90)
            if r.returncode != 0: self.skipped.append(f"git update skipped: {dest.name}")
            return True
        if dest.exists(): self.failures.append(f"path exists but not git repo: {dest}"); return False
        r = self.run(["git", "clone", "--depth", "1", self.gh(url), str(dest)], env=env, check=False, network=True, timeout=180)
        if r.returncode != 0: self.failures.append(f"git clone failed: {dest.name}"); return False
        return True

    def install_pwndbg(self) -> None:
        if not self.choices.pwndbg: return
        self.ui.section("pwndbg")
        if self.exists("pwndbg") or self.exists("pwndbg-gdb"): self.ui.ok("pwndbg already available"); return
        if self.pwndbg_installer_ok or self.probe_urls("pwndbg installer", ["https://install.pwndbg.re/"], quiet=True):
            r = self.run(["bash", "-lc", "curl -qsL https://install.pwndbg.re | sh -s -- -t pwndbg-gdb"], network=True, check=False)
            if r.returncode == 0: return
        repo = self.tools_dir / "pwndbg"
        if self.clone_or_pull("https://github.com/pwndbg/pwndbg.git", repo):
            r = self.run(["./setup.sh"], cwd=repo, network=True, check=False)
            if r.returncode != 0: self.failures.append("pwndbg setup failed")

    def install_helper_repos(self) -> None:
        if not self.choices.helper_repos: return
        self.ui.section("glibc helper repos")
        for n, u in HELPER_REPOS.items(): self.clone_or_pull(u, self.tools_dir / n)
        glibc = self.tools_dir / "glibc-all-in-one"
        libcdb = self.tools_dir / "libc-database"
        if (glibc / "update_list").exists(): self.run(["bash", "./update_list"], cwd=glibc, check=False, network=True)
        if self.choices.libc_get_all and (libcdb / "get").exists(): self.run(["bash", "./get", "all"], cwd=libcdb, check=False, network=True)
        elif self.choices.libc_get_common and (libcdb / "get").exists():
            self.run(["bash", "./get", "ubuntu"], cwd=libcdb, check=False, network=True)
            self.run(["bash", "./get", "debian"], cwd=libcdb, check=False, network=True)
        if self.choices.glibc_versions and (glibc / "download").exists():
            for v in self.choices.glibc_versions: self.run(["bash", "./download", v], cwd=glibc, check=False, network=True)

    def install_shell_ui(self) -> None:
        if not self.choices.shell_ui: return
        self.ui.section("zsh / oh-my-zsh / hyfetch")
        self.apt_install(SHELL_APT, "zsh")
        self.pip_install(["hyfetch"], "hyfetch")
        oh = self.home / ".oh-my-zsh"
        if not oh.exists() and self.ensure_github():
            raw = self.gh("https://raw.githubusercontent.com/ohmyzsh/ohmyzsh/master/tools/install.sh")
            self.run(["bash", "-lc", f"RUNZSH=no CHSH=no KEEP_ZSHRC=yes sh -c \"$(curl -fsSL {raw})\""], network=True, check=False)
        plug = Path(os.environ.get("ZSH_CUSTOM", str(oh / "custom"))) / "plugins"
        self.clone_or_pull("https://github.com/zsh-users/zsh-autosuggestions.git", plug / "zsh-autosuggestions")
        self.clone_or_pull("https://github.com/zsh-users/zsh-syntax-highlighting.git", plug / "zsh-syntax-highlighting")

    def cargo_available(self) -> bool: return self.exists("cargo") or (self.home / ".cargo" / "bin" / "cargo").exists()
    def cargo_tool_exists(self, cmd: str) -> bool: return self.exists(cmd) or (self.home / ".cargo" / "bin" / cmd).exists()
    def install_cargo_tool(self, crate: str, cmd: Optional[str] = None) -> bool:
        cmd = cmd or crate
        self._tmp_path_env()
        if self.cargo_tool_exists(cmd): self.ui.ok(f"{cmd} already available"); return True
        if not self.cargo_available(): self.failures.append(f"cargo unavailable: {crate}"); return False
        q = shlex.quote(crate)
        script = f"set -e\n. \"$HOME/.cargo/env\" 2>/dev/null || true\nexport PATH=\"$HOME/.cargo/bin:$PATH\"\ncargo install {q} --locked || cargo install {q}"
        self.run(["bash", "-lc", script], network=True, check=False)
        if self.cargo_tool_exists(cmd): return True
        force = f"set -e\n. \"$HOME/.cargo/env\" 2>/dev/null || true\nexport PATH=\"$HOME/.cargo/bin:$PATH\"\ncargo install {q} --locked --force || cargo install {q} --force"
        self.run(["bash", "-lc", force], network=True, check=False)
        if self.cargo_tool_exists(cmd): return True
        self.failures.append(f"cargo install failed: {crate}"); return False

    def install_modern_cli(self) -> None:
        if not self.choices.modern_cli: return
        self.ui.section("modern CLI")
        self.apt_install(MODERN_CLI_APT, "modern-cli")
        self.install_cargo_tool("eza", "eza")

    def install_trashy(self) -> None:
        if not self.choices.trashy: return
        self.ui.section("trashy")
        self.install_cargo_tool("trashy", "trash")

    def nvm_shell(self, script: str) -> str:
        return "\n".join(["set -e", 'export NVM_DIR="$HOME/.nvm"', '[ -s "$NVM_DIR/nvm.sh" ] && . "$NVM_DIR/nvm.sh"', 'export PNPM_HOME="$HOME/.local/bin"', 'export PATH="$PNPM_HOME:$HOME/.local/bin:$PATH"', script])

    def codex_available(self) -> bool:
        if self.exists("codex") or (self.home / ".local" / "bin" / "codex").exists(): return True
        if (self.home / ".nvm" / "nvm.sh").exists():
            return subprocess.run(["bash", "-lc", self.nvm_shell("command -v codex")], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0
        return False

    def install_codex_cli(self) -> None:
        if not self.choices.codex_cli: return
        self.ui.section("Codex CLI")
        if not self.ensure_github(): self.skipped.append("Codex skipped: GitHub unavailable"); return
        if not (self.nodejs_ok or self.probe_urls("Node.js", ["https://nodejs.org/dist/"], quiet=True)): self.skipped.append("Codex skipped: Node.js unavailable"); return
        nvm_sh = self.home / ".nvm" / "nvm.sh"
        if not nvm_sh.exists():
            raw = self.gh(f"https://raw.githubusercontent.com/nvm-sh/nvm/{NVM_VERSION}/install.sh")
            r = self.run(["bash", "-lc", f"curl -fsSL {raw} | PROFILE=\"$HOME/.bashrc\" bash"], network=True, check=False)
            if r.returncode != 0 or not nvm_sh.exists(): self.failures.append("nvm install failed"); return
        for title, script in [("Node.js LTS", "nvm install --lts"), ("default Node", "nvm alias default 'lts/*'"), ("use default Node", "nvm use default")]:
            r = self.run(["bash", "-lc", self.nvm_shell(script)], network=True, check=False)
            if r.returncode != 0: self.failures.append(f"{title} failed"); return
        self.npm_ok, self.npm_registry_url, self.npm_registry_name = self.npm_registry_probe()
        if not self.npm_ok: self.skipped.append("Codex skipped: npm unavailable"); return
        reg = shlex.quote(self.npm_registry_url)
        for script in [f"npm config set registry {reg}", f"COREPACK_NPM_REGISTRY={reg} corepack enable", f"COREPACK_NPM_REGISTRY={reg} corepack prepare pnpm@latest --activate", 'pnpm config set global-bin-dir "$HOME/.local/bin"', f"pnpm config set registry {reg}"]:
            r = self.run(["bash", "-lc", self.nvm_shell(script)], network=True, check=False)
            if r.returncode != 0: self.failures.append(f"node setup failed: {script}"); return
        if self.codex_available(): self.ui.ok("codex already available"); return
        r = self.run(["bash", "-lc", self.nvm_shell(f"pnpm add -g @openai/codex@latest --registry {reg}")], network=True, check=False)
        if r.returncode != 0: self.failures.append("Codex CLI install failed")

    def claude_available(self) -> bool: return self.exists("claude") or (self.home / ".local" / "bin" / "claude").exists()
    def install_claude_code(self) -> None:
        if not self.choices.claude_code: return
        self.ui.section("Claude Code")
        if self.claude_available(): self.ui.ok("claude already available"); return
        if not (self.claude_ok or self.probe_urls("Claude Code", [CLAUDE_INSTALL], quiet=True)): self.skipped.append("Claude skipped: unavailable"); return
        r = self.run(["bash", "-lc", f"curl -fsSL {CLAUDE_INSTALL} | bash"], network=True, check=False)
        if r.returncode != 0: self.failures.append("Claude Code install failed")

    def cc_switch_available(self) -> bool: return self.exists("cc-switch") or (self.home / ".local" / "bin" / "cc-switch").exists()
    def install_cc_switch(self) -> None:
        if not self.choices.cc_switch: return
        self.ui.section("cc-switch-cli")
        if self.cc_switch_available(): self.ui.ok("cc-switch already available"); return
        if not self.ensure_github(): self.skipped.append("cc-switch skipped: GitHub unavailable"); return
        r = self.run(["bash", "-lc", f"curl -fsSL {CC_SWITCH_INSTALL} | bash"], network=True, check=False)
        if r.returncode != 0: self.failures.append("cc-switch install failed")


    def find_cmd(self, names: list[str]) -> Optional[str]:
        for name in names:
            found = shutil.which(name)
            if found:
                return found
            if "/" not in name:
                for d in [self.home / ".local" / "bin", self.home / ".cargo" / "bin", self.home / ".local" / "go" / "bin", self.home / "go" / "bin"]:
                    candidate = d / name
                    if candidate.exists() and os.access(candidate, os.X_OK):
                        return str(candidate)
        return None

    def check_cmd(self, label: str, names: list[str], required: bool = True) -> bool:
        found = self.find_cmd(names)
        if found:
            self.ui.ok(f"{label}: {found}")
            return True
        (self.ui.err if required else self.ui.warn)(f"{label}: missing")
        return not required

    def check_apt_group(self, label: str, packages: list[str], required: bool = True) -> bool:
        missing = [pkg for pkg in packages if not self.pkg_installed(pkg)]
        if not missing:
            self.ui.ok(f"APT {label}: all installed ({len(packages)})")
            return True
        msg = f"APT {label}: missing {len(missing)}/{len(packages)}: " + ", ".join(missing[:12]) + (" ..." if len(missing) > 12 else "")
        (self.ui.err if required else self.ui.warn)(msg)
        return not required

    def check_python_packages(self, packages: list[str]) -> bool:
        installed = self.pip_names()
        missing = [p for p in packages if self.norm_pkg(p) not in installed]
        if not missing:
            self.ui.ok(f"Python packages: all installed ({len(packages)})")
            return True
        self.ui.err("Python packages missing: " + ", ".join(missing))
        return False

    def check_repos(self) -> bool:
        ok_all = True
        for name in HELPER_REPOS:
            path = self.tools_dir / name
            if (path / ".git").exists():
                self.ui.ok(f"repo {name}: {path}")
            else:
                self.ui.warn(f"repo {name}: missing at {path}")
                ok_all = False
        return ok_all

    def test(self) -> int:
        self._tmp_path_env()
        self.ui.banner(self.distro)
        print()
        print(self.ui.cyan + "Software checks" + self.ui.reset)
        ok_all = True

        for label, pkgs in [
            ("core", CORE_APT), ("i386", I386_APT), ("qemu", QEMU_APT),
            ("ruby", RUBY_APT), ("java", DEFAULT_JRE_APT), ("modern-cli", MODERN_CLI_APT),
        ]:
            ok_all = self.check_apt_group(label, pkgs) and ok_all

        print("\nCommands:")
        command_checks = [
            ("python3", ["python3"], True), ("pip3", ["pip3"], True), ("git", ["git"], True),
            ("curl", ["curl"], True), ("gcc", ["gcc"], True), ("g++", ["g++"], True),
            ("gdb", ["gdb"], True), ("gdb-multiarch", ["gdb-multiarch"], True),
            ("checksec", ["checksec"], True), ("patchelf", ["patchelf"], True),
            ("ROPgadget", ["ROPgadget", "ropgadget"], True), ("ropper", ["ropper"], True),
            ("pwndbg", ["pwndbg", "pwndbg-gdb"], True),
            ("one_gadget", ["one_gadget"], True), ("seccomp-tools", ["seccomp-tools"], True),
            ("qemu", ["qemu-x86_64", "qemu-i386"], True), ("zsh", ["zsh"], True),
            ("hyfetch", ["hyfetch"], True), ("trash", ["trash"], True),
            ("bat", ["bat", "batcat"], True), ("eza", ["eza"], True),
            ("fzf", ["fzf"], True), ("btop", ["btop"], True), ("duf", ["duf"], True),
            ("rustc", ["rustc"], True), ("cargo", ["cargo"], True),
            ("go", ["go"], True), ("java", ["java"], True),
            ("node", ["node"], True), ("npm", ["npm"], True), ("pnpm", ["pnpm"], True),
            ("codex", ["codex"], True), ("claude", ["claude"], True), ("cc-switch", ["cc-switch"], True),
        ]
        for label, names, required in command_checks:
            ok_all = self.check_cmd(label, names, required) and ok_all

        print("\nPython packages:")
        ok_all = self.check_python_packages(PYTHON_PWN) and ok_all

        print("\nHelper repositories:")
        ok_all = self.check_repos() and ok_all

        print("\nConfig checks:")
        cfg = ROOT / "init-config.py"
        if cfg.exists():
            r = subprocess.run([sys.executable, str(cfg), "--test"])
            ok_all = (r.returncode == 0) and ok_all
        else:
            self.ui.err("init-config.py missing")
            ok_all = False

        print()
        if ok_all:
            self.ui.ok("test passed")
            return 0
        self.ui.warn("test found missing items. Re-run installer, or inspect state/install-report.txt.")
        return 1

    def install_config(self) -> None:
        if self.no_config: return
        self.ui.section("apply init config")
        cfg = ROOT / "init-config.py"
        if not cfg.exists(): self.ui.warn("init-config.py not found, skip config"); return
        r = self.run([sys.executable, str(cfg)], check=False)
        if r.returncode != 0: self.failures.append("config apply failed")

    def estimate_steps(self) -> int:
        c = self.choices
        total = 4 + sum(int(x) for x in [c.chsrc, c.extra_apt_repo and self.distro.id == "ubuntu", c.apt_upgrade, c.core_apt, c.i386, c.qemu, c.language_env, c.shell_ui, c.modern_cli, c.trashy, c.codex_cli, c.claude_code, c.cc_switch, c.python_pwn, c.ruby_tools, c.pwndbg, c.helper_repos])
        return max(1, total)

    def install(self) -> int:
        self.require_sudo()
        self.ui.set_total(self.estimate_steps())
        self.ui.banner(self.distro)
        self.configure_apt_defaults()
        self.configure_chsrc()
        self.configure_extra_apt_repo()
        self.system_full_upgrade()
        self.detect_network()
        self.install_core_apt()
        self.install_i386_qemu()
        self.install_language_env()
        self.install_shell_ui()
        self.install_modern_cli()
        self.install_trashy()
        self.install_codex_cli()
        self.install_claude_code()
        self.install_cc_switch()
        self.install_python_pwn()
        self.install_ruby_tools()
        self.install_pwndbg()
        self.install_helper_repos()
        self.install_config()
        self.write_report()
        self.summary()
        return 1 if self.failures else 0

    def write_report(self) -> None:
        STATE.mkdir(exist_ok=True)
        state = {"version": VERSION, "time": time.time(), "distro": asdict(self.distro), "choices": asdict(self.choices), "skipped": self.skipped, "failures": self.failures}
        (STATE / "install-state.json").write_text(json.dumps(state, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        report = [f"init-install {VERSION}", f"distro: {self.distro.name}", f"wsl: {self.distro.is_wsl}", f"tools_dir: {self.tools_dir}", "", "skipped:", *(self.skipped or ["none"]), "", "failures:", *(self.failures or ["none"])]
        (STATE / "install-report.txt").write_text("\n".join(report) + "\n", encoding="utf-8")

    def summary(self) -> None:
        print("\n" + self.ui.cyan + "Result" + self.ui.reset)
        if not self.failures and not self.skipped: self.ui.ok("No recorded failures or skips."); return
        if self.skipped:
            self.ui.warn("Skipped:")
            for i in self.skipped: print(f"  - {i}")
        if self.failures:
            self.ui.warn("Failures:")
            for i in self.failures: print(f"  - {i}")


def menu() -> Choices:
    ui = UI()
    c = Choices()
    distro = Installer(Choices(), no_config=True).distro

    def yes_if(cond):
        return lambda _: cond

    items = [
        ("System", "chsrc", "Mirror switch with chsrc", "Optional. Use only when default mirrors are slow.", False, yes_if(True)),
        ("System", "extra_apt_repo", "Enable Ubuntu universe", "Ubuntu only.", True, yes_if(distro.id == "ubuntu")),
        ("System", "apt_upgrade", "APT full-upgrade", "Update system packages before installing tools.", True, yes_if(True)),

        ("Core", "core_apt", "Core build/debug/pwn tools", "gcc, gdb, checksec, patchelf, binutils, seccomp.", True, yes_if(True)),
        ("Core", "i386", "i386 / multilib support", "For 32-bit ELF challenges.", True, yes_if(True)),
        ("Core", "qemu", "qemu-user multi-arch support", "For foreign-architecture ELF challenges.", True, yes_if(True)),
        ("Core", "language_env", "Ruby / Rust / Go / Java", "Runtime support for common tools.", True, yes_if(True)),

        ("Shell", "shell_ui", "zsh / oh-my-zsh / hyfetch", "Terminal UI helpers.", True, yes_if(True)),
        ("Shell", "modern_cli", "bat / eza / fzf / btop / duf", "Daily CLI tools.", True, yes_if(True)),
        ("Shell", "trashy", "trashy recycle-bin command", "Safe rm-like workflow with trash put/list/restore.", True, yes_if(True)),

        ("AI", "codex_cli", "Codex CLI", "OpenAI Codex CLI with nvm / pnpm.", True, yes_if(True)),
        ("AI", "claude_code", "Claude Code", "Anthropic Claude Code CLI.", True, yes_if(True)),
        ("AI", "cc_switch", "cc-switch-cli", "CLI profile switch helper.", True, yes_if(True)),

        ("Pwn", "python_pwn", "Python pwn packages", "pwntools, ROPgadget, ropper, z3, lief, etc.", True, yes_if(True)),
        ("Pwn", "ruby_tools", "one_gadget / seccomp-tools", "Ruby-based pwn helpers.", True, yes_if(True)),
        ("Pwn", "pwndbg", "pwndbg", "GDB plugin for pwn debugging.", True, yes_if(True)),
        ("Pwn", "helper_repos", "glibc helper repositories", "glibc-all-in-one and libc-database.", True, yes_if(True)),

        ("Libc data", "libc_get_common", "Download common libc-database data", "Optional. Takes extra time and disk space.", False, lambda x: x.helper_repos),
        ("Libc data", "libc_get_all", "Download all libc-database data", "Large download. Usually not needed.", False, lambda x: x.helper_repos),
        ("Libc data", "glibc_download", "Download specific glibc versions", "Enter versions after the menu.", False, lambda x: x.helper_repos),
    ]

    for _, key, _, _, default, _ in items:
        setattr(c, key, default)
    if distro.id != "ubuntu":
        c.extra_apt_repo = False

    def visible():
        return [item for item in items if item[5](c)]

    def cleanup(key: str) -> None:
        if key == "helper_repos" and not c.helper_repos:
            c.libc_get_common = False
            c.libc_get_all = False
            c.glibc_download = False
            c.glibc_versions = []
        if key == "libc_get_common" and c.libc_get_common:
            c.libc_get_all = False
        if key == "libc_get_all" and c.libc_get_all:
            c.libc_get_common = False
        if key == "glibc_download" and not c.glibc_download:
            c.glibc_versions = []

    print(ui.cyan + "Interactive install menu" + ui.reset)
    print("  Enter/Space=default   y=yes   n=no   b=back   q=quit")
    if distro.id != "ubuntu":
        print("  Ubuntu universe is hidden on this distro; APT sources are not changed.")

    i = 0
    last_cat = None
    while True:
        v = visible()
        if i >= len(v):
            break
        cat, key, label, desc, _, _ = v[i]
        if cat != last_cat:
            print()
            print(ui.bold + ui.blue + f"[{cat}]" + ui.reset)
            last_cat = cat
        print(ui.dim + f"  {desc}" + ui.reset)
        default = bool(getattr(c, key))
        ans = ui.ask_key(f"  [{i + 1:02d}/{len(v):02d}] {label}", default)
        if ans == "quit":
            raise KeyboardInterrupt
        if ans == "back":
            if i > 0:
                i -= 1
                last_cat = None
            else:
                ui.warn("already at first item")
            continue
        setattr(c, key, ans == "yes")
        cleanup(key)
        i += 1

    if c.glibc_download:
        raw = input("glibc versions, separated by comma/space: ").strip()
        c.glibc_versions = [x for x in re.split(r"[,\s]+", raw) if x]

    print()
    print(ui.cyan + "Selected modules" + ui.reset)
    selected = []
    for cat, key, label, _, _, cond in items:
        if cond(c) and bool(getattr(c, key)):
            selected.append((cat, label))
    if not selected:
        print("  none")
    else:
        cur = None
        for cat, label in selected:
            if cat != cur:
                print(f"  {cat}:")
                cur = cat
            print(f"    - {label}")
    if c.glibc_versions:
        print("    - glibc versions: " + ", ".join(c.glibc_versions))

    ans = ui.ask_key("Start install with this selection", True)
    if ans in {"quit", "no"}:
        raise KeyboardInterrupt
    return c


def help_text() -> str:
    return f"""
init-install {VERSION}

Usage:
  python3 init-install.py              Install tools, then apply config
  python3 init-install.py --menu       Interactive install menu
  python3 init-install.py --no-config  Install tools only
  python3 init-install.py --test       Check tools and config
  python3 init-install.py --version    Show version
  python3 init-install.py -h           Show help

Config files live in ./config/.
""".strip()


def main(argv: list[str]) -> int:
    if "-h" in argv or "--help" in argv:
        print(help_text()); return 0
    if "--version" in argv:
        print(VERSION); return 0
    if "--test" in argv:
        extra = [a for a in argv if a != "--test"]
        if extra:
            print("--test cannot be combined with other options", file=sys.stderr)
            print(help_text()); return 2
        return Installer(Choices(), no_config=True).test()
    allowed = {"--menu", "--no-config"}
    unknown = [a for a in argv if a not in allowed]
    if unknown:
        print("unknown args: " + " ".join(unknown), file=sys.stderr)
        print(help_text()); return 2
    try:
        c = menu() if "--menu" in argv else Choices()
        return Installer(c, no_config="--no-config" in argv).install()
    except KeyboardInterrupt:
        UI().warn("cancelled")
        return 130
    except Exception as exc:
        UI().err(str(exc))
        return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
