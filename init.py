#!/usr/bin/env python3
"""CTF 环境一键搭建（Debian 系：Ubuntu / Debian / Kali）。

    /usr/bin/python3 init.py

只做三件事：用 APT 装齐系统工具、补上 APT 没有的 Python 工具、真跑一遍确认能用。
不建 venv，不动已装的包，不升级，可重复执行。缺什么就装什么，装不了的报 skipped。
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
SYSTEM_PATH = "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"

# 装完必须能 import 的库。键是 APT 包名，值是一个或多个可接受的模块名
# （pycryptodome 在 Debian 里叫 Cryptodome，在 PyPI 里叫 Crypto）。
LIBRARIES = {
    "python3-pip": ("pip",),
    "python3-setuptools": ("setuptools",),
    "python3-wheel": ("wheel",),
    "python3-ipython": ("IPython",),
    "python3-magic": ("magic",),
    "python3-pil": ("PIL",),
    "python3-requests": ("requests",),
    "python3-sympy": ("sympy",),
    "python3-yaml": ("yaml",),
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

# 工具分为 5 组，装的位置决定谁会胜出，所以顺序固定。
GROUPS = {
    "系统 Python": (
        "python3", "python3-dev", *LIBRARIES, "python-is-python3",
    ),
    "日常工具": (
        "ca-certificates", "gnupg", "curl", "wget", "git", "rsync", "openssh-client",
        "zsh", "bash-completion", "shellcheck", "vim", "nano", "tmux", "tree",
        "bat", "fd-find", "ripgrep", "fzf", "zoxide", "duf", "btop", "htop", "ncdu",
        "jq", "yq", "fastfetch", "hyfetch", "bsdextrautils", "bc", "xmlstarlet",
        "iproute2", "net-tools", "bind9-dnsutils", "iputils-ping", "traceroute",
        "lsof", "tcpdump", "openssl",
    ),
    "编译与语言": (
        "build-essential", "pkg-config", "clang", "llvm", "lld", "cmake", "ninja-build",
        "meson", "autoconf", "automake", "libtool", "gawk", "bison", "flex", "gettext",
        "patch", "libssl-dev", "libffi-dev", "zlib1g-dev", "libbz2-dev", "liblzma-dev",
        "libsqlite3-dev", "libreadline-dev", "libncurses-dev",
        "perl", "ruby-full", "bundler", "default-jdk-headless", "nodejs", "npm",
        "golang-go", "rustc", "cargo", "rustfmt",
    ),
    "二进制与调试": (
        "file", "binutils", "elfutils", "xxd", "gdb", "gdb-multiarch", "strace", "ltrace",
        "patchelf", "nasm", "yasm", "valgrind", "qemu-user", "qemu-utils",
        "device-tree-compiler", "gdbserver", "socat", "netcat-openbsd", "libc6-dbg",
        "seccomp", "libseccomp-dev", "radare2",
    ),
    "Pwn 与取证": (
        "python3-pwntools", "python3-ropgadget", "checksec",
        "unzip", "zip", "xz-utils", "zstd", "tar", "gzip", "bzip2", "7zip", "cpio",
        "cabextract", "squashfs-tools", "libimage-exiftool-perl", "pngcheck",
        "sleuthkit", "sqlite3", "qpdf", "poppler-utils", "mediainfo", "ffmpeg", "sox",
        "tesseract-ocr", "qrencode", "zbar-tools", "foremost", "testdisk", "apktool",
        "steghide", "binwalk", "imagemagick", "libsox-fmt-all",
    ),
}

# APT 没打包、只能 pip 的 Python 工具。pwntools 在 24.04 之前的发行版里也要走这里。
PIP_TOOLS = {
    "pwntools": ("pwntools",),
    "ROPgadget": ("ROPgadget",),
    "ropper": ("filebytes-fix", "ropper"),
}
PWN_SUBCOMMANDS = ("checksec", "cyclic", "asm", "disasm", "shellcraft")
PWNLIB_NOTERM = "1"

# filebytes 0.10.2 用了 Python 3.14 移除的 ast.Str；这是上游修好的 commit。
FILEBYTES_FIX = (
    "filebytes @ https://codeload.github.com/sashs/filebytes/tar.gz/"
    "ff7492d750140288e2c3ff25b8a648719be470ce"
    "#sha256=38ccb58dc9d3d5076584232880208a08fc57e9db515d63f1f36e08a1579a922b"
    " ; python_version >= '3.14'"
)

# 命令名 -> 探测参数。装完逐个真跑，只看退出码。
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
    "default-jdk-headless": ("javac", "-version"),
    "nodejs": ("node", "--version"),
    "npm": ("npm", "--version"),
    "golang-go": ("go", "version"),
    "rustc": ("rustc", "--version"),
    "cargo": ("cargo", "--version"),
    "file": ("file", "--version"),
    "binutils": ("readelf", "--version"),
    "gdb": ("gdb", "-nx", "--version"),
    "strace": ("strace", "-V"),
    "qemu-user": ("qemu-aarch64", "--version"),
    "qemu-utils": ("qemu-img", "--version"),
    "device-tree-compiler": ("dtc", "--version"),
    "gdbserver": ("gdbserver", "--version"),
    "socat": ("socat", "-V"),
    "netcat-openbsd": ("nc", "-h"),
    "radare2": ("r2", "-v"),
    "7zip": (("7z", "7zz"), "-h"),
    "libimage-exiftool-perl": ("exiftool", "-ver"),
    "sqlite3": ("sqlite3", "--version"),
    "qpdf": ("qpdf", "--version"),
    "ffmpeg": ("ffmpeg", "-version"),
    "apktool": ("apktool", "--version"),
}

# 包名到替代包的映射（老发行版改名）。
ALTERNATIVES = {"7zip": "p7zip-full", "bind9-dnsutils": "dnsutils"}

# 旧版本残留的 shell 片段，重复运行时要清掉。
OLD_BLOCKS = (
    re.compile(rb"^# >>> init Python tools >>>\r?\n.*?^# <<< init Python tools <<<\r?\n?",
               re.MULTILINE | re.DOTALL),
    re.compile(rb"^# >>> init system tools >>>\r?\n.*?^# <<< init system tools <<<\r?\n?",
               re.MULTILINE | re.DOTALL),
)

PACKAGES = tuple(dict.fromkeys(p for group in GROUPS.values() for p in group))


def color(text, code):
    if sys.stdout.isatty() and not os.environ.get("NO_COLOR") and os.environ.get("TERM") != "dumb":
        return "\033[{}m{}\033[0m".format(code, text)
    return text


def say(label, message, code):
    line = "  {} {}".format(color("[{}]".format(label), code), message)
    encoding = sys.stdout.encoding
    if encoding:
        line = line.encode(encoding, errors="backslashreplace").decode(encoding)
    print(line, flush=True)


def section(number, name):
    print("\n" + color("{}. {}".format(number, name), "1;34"), flush=True)


def quote(part):
    return "'" + str(part).replace("'", "'\\''") + "'"


def preflight():
    if not sys.platform.startswith("linux"):
        raise RuntimeError("需要 Linux + APT")
    for command in ("apt-get", "apt-cache", "dpkg-query"):
        if not shutil.which(command, path=SYSTEM_PATH):
            raise RuntimeError("缺少系统命令: " + command)
    release = Path("/etc/os-release")
    lines = release.read_text(encoding="utf-8").splitlines() if release.is_file() else []
    name = next((l.partition("=")[2].strip('"') for l in lines if l.startswith("PRETTY_NAME=")), "Linux")
    say("ok", "{} / {} / Python {}".format(name, platform.machine(), PYTHON), "32")


def installed():
    result = subprocess.run(
        ["dpkg-query", "-W", "-f=${db:Status-Status}\t${Package}\n",
         *PACKAGES, *ALTERNATIVES.values()],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        encoding="utf-8", errors="replace")
    return {line.split("\t", 1)[1] for line in result.stdout.splitlines() if line.startswith("installed\t")}


def resolve(package, have, available):
    alt = ALTERNATIVES.get(package)
    if package not in have and (alt in have or (package not in available and alt in available)):
        return alt
    return package


def installable(packages):
    result = subprocess.run(["/usr/bin/apt-get", "-s", "install", "-y",
                             "--no-remove", "--no-install-recommends", *packages],
                            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    # 有 Remv 行说明会卸载别的包，这不是我们想要的。
    return result.returncode == 0 and not any(
        line.startswith(b"Remv ") for line in (result.stdout or b"").splitlines())


def apt(args, have):
    """装齐。返回新的已装集合。"""
    missing = [p for p in PACKAGES if resolve(p, have, set()) not in have]
    if not missing:
        return have

    candidates = missing + [ALTERNATIVES[p] for p in missing if p in ALTERNATIVES]

    def ask():
        out = subprocess.run(["apt-cache", "--no-all-versions", "show", *candidates],
                             stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                             encoding="utf-8", errors="replace")
        return {l[9:] for l in out.stdout.splitlines() if l.startswith("Package: ")}

    available = ask()
    # 索引是否健康，用一个必然存在的包来试；不能用"缺的包查不查得到"来判断——
    # 那个发行版可能本来就没有那些包（20.04 没 python3-zstandard、24.04 没 fastfetch），
    # 这时所有 missing 都查不到，available 为空，但那不是索引的问题。
    healthy = bool(subprocess.run(["apt-cache", "--no-all-versions", "show", "bash"],
                                  stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                  encoding="utf-8", errors="replace").stdout.strip())
    if not healthy:
        if os.geteuid() and not shutil.which("sudo", path=SYSTEM_PATH):
            raise RuntimeError("安装需要 root 或 sudo")
        say("update", "刷新 APT 索引", "36")
        subprocess.run([*args, "-o", "APT::Update::Error-Mode=any", "update"], check=True)
        available = ask()

    for title, packages in GROUPS.items():
        print(color(title, "1;34"), flush=True)
        pending = []
        for package in packages:
            resolved = resolve(package, have, available)
            if resolved in have:
                say("installed", package, "32")
            elif resolved in available:
                say("install", package, "36")
                pending.append(resolved)
            else:
                # 这个发行版没有这个包（24.04 没 fastfetch，20.04 没 python3-zstandard）。
                # 绝不能塞进 apt-get install，否则整批返回 100，别的包全装不上。
                say("unavailable", package, "33")

        if pending:
            # 老发行版的 npm 会拉进与系统 libssl 冲突的头文件，去掉它单独装。
            if "npm" in pending and not installable(pending):
                without = [p for p in pending if p != "npm"]
                if not without or installable(without):
                    pending = without
                    say("skipped", "npm 与系统 OpenSSL 头文件冲突", "33")
            subprocess.run([*args, "install", "-y", "--no-remove",
                            "--no-install-recommends", *pending], check=True)
            have = installed()
            # APT 说装上了但 dpkg 查不到，说明这批里有个包是虚的；报出来但不中断，
            # 后面的验证会把它标成 failed。
            for package in sorted(set(pending) - have):
                say("failed", "{} 装完查不到".format(package), "31")
    return have


def write_root_file(args, path, text):
    """用 install(1) 写系统文件：不需要 shell 重定向，天然幂等。"""
    with tempfile.TemporaryDirectory(prefix="init-cmd-") as directory:
        staged = Path(directory) / path.name
        staged.write_text(text, encoding="utf-8")
        prefix = ["sudo"] if args and args[0] == "sudo" else []
        subprocess.run([*prefix, "install", "-D", "-m", "0755", str(staged), str(path)], check=True)
    say("ok", "写入 {}".format(path), "32")


def python_minor():
    result = subprocess.run([PYTHON, "-c", "import sys;print('%d.%d'%sys.version_info[:2])"],
                            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                            encoding="utf-8", errors="replace")
    parts = (result.stdout or "").strip().split(".")
    return tuple(int(p) for p in parts) if len(parts) == 2 and all(p.isdigit() for p in parts) else None


def pip_install(args, name):
    flags = ["--break-system-packages"] if any(Path("/usr/lib").glob("python3*/EXTERNALLY-MANAGED")) else []
    requirement = PIP_TOOLS[name]
    packages = [FILEBYTES_FIX if r == "filebytes-fix" else r for r in requirement]
    prefix = ["sudo"] if args and args[0] == "sudo" else []
    result = subprocess.run(
        [*prefix, PYTHON, "-m", "pip", "install", "--disable-pip-version-check",
         "--no-warn-script-location", "--retries", "5", "--timeout", "60", *flags, *packages],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        encoding="utf-8", errors="replace", timeout=1200)
    return result.returncode == 0


def command_ok(command, arguments=("--help",)):
    executable = shutil.which(command, path=SYSTEM_PATH)
    if executable is None:
        return None
    try:
        result = subprocess.run([executable, *arguments], stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL, timeout=60,
                                env={**os.environ, "PATH": SYSTEM_PATH,
                                     "PWNLIB_NOTERM": PWNLIB_NOTERM})
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0


def python_tools(args):
    """补齐 APT 没给的 Python 命令行工具，并让 pwn 的入口点安静可用。

    APT 只在 24.04+ 提供 pwntools，更早的发行版靠 pip。
    """
    print(color("Python 工具", "1;34"), flush=True)

    version = python_minor()

    def pip_tool(name, probe_arguments):
        state = command_ok(name, probe_arguments)
        if state is True:
            say("installed", name, "32")
            return
        if state is False:
            say("repair", "{} 已坏，重装".format(name), "36")
        if version is not None and version < (3, 8):
            say("skipped", "{} 需要 Python 3.8+".format(name), "33")
            return
        if state is None:
            say("pip", name, "36")
        if pip_install(args, name):
            say("ok", name, "32")
        else:
            say("failed", "{} 安装失败".format(name), "31")

    pip_tool("pwntools", ("--help",))
    pip_tool("ROPgadget", ("--version",))
    pip_tool("ropper", ("--version",))

    pwn = shutil.which("pwn", path=SYSTEM_PATH)
    if pwn is None:
        say("skipped", "pwntools 未安装，跳过子命令", "33")
        return

    # APT 的 pwntools 只提供 /usr/bin/pwn；pip 的也是这样。补齐其余入口点。
    for name in PWN_SUBCOMMANDS:
        if name == "checksec" and Path("/usr/bin/checksec").exists():
            # APT 也有 checksec，但两者参数不同：写调度器，两种都收。
            write_root_file(args, Path("/usr/local/bin/checksec"),
                            CHECKSEC_DISPATCH.format(pwn=quote(pwn)))
            continue
        if shutil.which(name, path=SYSTEM_PATH) is None:
            write_root_file(args, Path("/usr/local/bin") / name,
                            LAUNCHER.format(pwn=quote(pwn), name=name))

    # 无 terminfo 的环境（容器/CI）导入 pwn 会打印 curses 告警，用包装抑制。
    if not writes_noterm(pwn):
        write_root_file(args, Path("/usr/local/bin/pwn"), PWN_QUIET.format(
            python=quote(PYTHON)))


LAUNCHER = '#!/bin/sh\nPWNLIB_NOTERM=1 exec {pwn} {name} "$@"\n'

PWN_QUIET = (
    '#!/bin/sh\n'
    'PWNLIB_NOTERM=1 exec {python} -c '
    "'import sys; from pwnlib.commandline.main import main; "
    "sys.argv[0]=\"pwn\"; sys.exit(main())' \"$@\"\n"
)

CHECKSEC_DISPATCH = """#!/bin/sh
# 统一 checksec：APT 风格（--file=x）走 checksec.sh，裸路径走 pwntools。
if [ $# -eq 0 ]; then
    exec /usr/bin/checksec
fi
for arg in "$@"; do
    case "$arg" in
        -*) exec /usr/bin/checksec "$@" ;;
    esac
done
PWNLIB_NOTERM=1 exec {pwn} checksec "$@"
"""


def writes_noterm(path):
    try:
        return b"PWNLIB_NOTERM" in Path(path).read_bytes()
    except OSError:
        return False


def verify(have):
    """逐个 import、逐个启动，失败就是失败，不是警告。"""
    ok = True
    print(color("Python 库", "1;34"), flush=True)
    for package, modules in LIBRARIES.items():
        label = "import " + " / ".join(modules)
        if package not in have:
            say("skipped", "{}（{} 未安装）".format(label, package), "33")
            continue
        probe = ("import importlib,sys\n"
                 "for n in {!r}:\n"
                 " try:\n"
                 "  importlib.import_module(n)\n"
                 " except ImportError:\n"
                 "  continue\n"
                 " sys.exit(0)\n"
                 "sys.exit(1)\n").format(list(modules))
        if subprocess.run([PYTHON, "-I", "-c", probe]).returncode != 0:
            say("failed", label, "31")
            ok = False
        else:
            say("ok", label, "32")

    print(color("命令行", "1;34"), flush=True)
    for package, (names, *arguments) in COMMAND_CHECKS.items():
        if resolve(package, have, set()) not in have:
            continue
        names = (names,) if isinstance(names, str) else names
        found = next((shutil.which(n, path=SYSTEM_PATH) for n in names
                      if shutil.which(n, path=SYSTEM_PATH)), None)
        if found is None:
            say("failed", "{} 不在 PATH".format(" / ".join(names)), "31")
            ok = False
            continue
        result = subprocess.run([found, *arguments], stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, encoding="utf-8",
                                errors="replace", timeout=60,
                                env={**os.environ, "PATH": SYSTEM_PATH})
        if result.returncode:
            say("failed", "{}".format(Path(found).name), "31")
            ok = False
        else:
            say("ok", Path(found).name, "32")

    for name in ("pwn", *PWN_SUBCOMMANDS):
        state = command_ok(name)
        if state is None:
            say("failed", "{} 缺失".format(name), "31")
            ok = False
        elif not state:
            say("failed", "{} 无法启动".format(name), "31")
            ok = False
        else:
            say("ok", name, "32")

    # 固件工具：镜像没建、源码没克隆都报 pending，不影响环境可用性。
    for name in ("firmae", "iot-help"):
        if shutil.which(name, path=SYSTEM_PATH) is None:
            say("skipped", "{} 未安装".format(name), "33")
    status = firmae_ready()
    if status == 0:
        say("ok", "FirmAE 镜像就绪", "32")
    elif status == 3:
        say("pending", "FirmAE 待构建（用的时候跑 firmae build）", "33")
    elif status == 1:
        # 源码没克隆也是这个值：这是可选的，不是环境坏。
        say("pending", "FirmAE 未就绪（跑 firmae build 或 --iot 见 README）", "33")
    else:
        say("skipped", "FirmAE 未安装", "33")
    return ok


def install_iot_assets(args):
    """把 iot/ 里的小工具装好（4 个文件 + 启动器），不联网、不建镜像。

    固件镜像要几百 MB 和几分钟构建，所以只在你真的用的时候手动 `firmae build`。
    """
    assets = Path(__file__).resolve().parent / "iot"
    runtime = Path.home() / ".local/share/init/iot"
    runtime.mkdir(parents=True, exist_ok=True)
    for name in ("lab.py", "Dockerfile", "entrypoint.sh", "USAGE.md"):
        source = assets / name
        if not source.is_file():
            raise RuntimeError("缺少 iot/{}，请用完整的 git checkout".format(name))
        target = runtime / name
        if not target.is_file() or target.read_bytes() != source.read_bytes():
            target.write_bytes(source.read_bytes())

    config = runtime / "config.json"
    expected = ('{{\n  "firmae": "{}",\n  "revision": "{}",\n  "qiling": "{}"\n}}\n').format(
        Path.home() / "tools/FirmAE",
        "653565b5d14e6d69a1dd242aa88ecfb4b090a74a",
        Path.home() / ".local/share/init/qiling")
    if not config.is_file() or config.read_text(encoding="utf-8") != expected:
        config.write_text(expected, encoding="utf-8")

    for name, command in (("firmae", []), ("iot-help", ["help"])):
        target = Path("/usr/local/bin") / name
        if target.is_file() and b"lab.py" in target.read_bytes():
            continue
        write_root_file(args, target,
                        "#!/bin/sh\nexec {} {} {} \"$@\"\n".format(
                            quote(PYTHON), quote(runtime / "lab.py"),
                            " ".join(command)))
    say("ok", "固件工具就绪（镜像按需 firmae build）", "32")


def firmae_ready():
    """0 就绪 / 3 待建 / 1 坏 / None 未安装。"""
    lab = Path.home() / ".local/share/init/iot/lab.py"
    if not lab.is_file():
        return None
    try:
        result = subprocess.run([PYTHON, str(lab), "status"],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                timeout=120)
    except (OSError, subprocess.SubprocessError):
        return None
    return result.returncode


def tidy_profiles(home):
    """清掉旧版本留下的 shell 片段。"""
    for filename in (".bashrc", ".zshrc"):
        profile = (home / filename).resolve()
        try:
            content = profile.read_bytes()
        except FileNotFoundError:
            continue
        updated = content
        for pattern in OLD_BLOCKS:
            updated = pattern.sub(b"", updated)
        if updated == content:
            continue
        with tempfile.TemporaryDirectory(prefix=".init-", dir=profile.parent) as directory:
            staged = Path(directory) / profile.name
            staged.write_bytes(updated)
            shutil.copymode(profile, staged)
            staged.replace(profile)
        say("ok", "清理 {}".format(profile), "32")


def main(args):
    if args not in ([], ["--check"]):
        print("用法: python3 init.py            # 安装\n"
              "      python3 init.py --check    # 只检查", file=sys.stderr)
        return 2
    started = time.monotonic()
    try:
        section(1, "环境")
        preflight()
        have = installed()

        if args == ["--check"]:
            section(2, "验证")
            if not verify(have):
                say("failed", "检查未通过", "31")
                return 1
            say("ok", "全部就绪（{:.1f}s）".format(time.monotonic() - started), "32")
            return 0

        section(2, "安装")
        apt_args = ["sudo"] if os.geteuid() else []
        apt_args += ["apt-get", "-o", "Acquire::Retries=2", "-o", "DPkg::Lock::Timeout=60"]
        have = apt(apt_args, have)
        python_tools(apt_args)
        install_iot_assets(apt_args)

        section(3, "验证")
        if not verify(have):
            say("failed", "验证未通过", "31")
            return 1
        tidy_profiles(Path.home())
    except (OSError, RuntimeError, subprocess.CalledProcessError) as error:
        say("failed", str(error), "31")
        return 1

    ready = sum(resolve(p, have, set()) in have for p in PACKAGES)
    say("ok", "{}/{} 个包就绪（{:.1f}s）".format(ready, len(PACKAGES), time.monotonic() - started), "32")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except KeyboardInterrupt:
        print("\n已取消", file=sys.stderr)
        sys.exit(130)
