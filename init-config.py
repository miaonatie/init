#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Apply the portable init config from ./config."""

from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import sys
import time
from pathlib import Path

VERSION = "v1.0.2"
ROOT = Path(__file__).resolve().parent
CONFIG = ROOT / "config"
STATE = ROOT / "state"
HOME = Path.home()

BLOCK_RE = re.compile(
    r"(?ms)^# >>> init-[A-Za-z0-9_-]+ >>>\n"
    r".*?"
    r"^# <<< init-[A-Za-z0-9_-]+ <<<\n?"
)


def color(code: str, text: str) -> str:
    if not sys.stdout.isatty() or os.environ.get("NO_COLOR"):
        return text
    return f"\033[{code}m{text}\033[0m"


def ok(msg: str) -> None:
    print(color("32", "[OK]"), msg)


def warn(msg: str) -> None:
    print(color("33", "[WARN]"), msg)


def err(msg: str) -> None:
    print(color("31", "[ERR]"), msg, file=sys.stderr)


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="ignore") if path.exists() else ""


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def remove_blocks(path: Path) -> bool:
    if not path.exists():
        return False
    old = read_text(path)
    new = BLOCK_RE.sub("", old)
    if new != old:
        write_text(path, new.lstrip() if not new.strip() else new)
        return True
    return False


def upsert_block(path: Path, name: str, content: str) -> None:
    remove_blocks(path)
    old = read_text(path).rstrip()
    block = f"# >>> {name} >>>\n{content.rstrip()}\n# <<< {name} <<<\n"
    write_text(path, (old + "\n\n" + block if old else block))


def required_files() -> list[Path]:
    return [
        CONFIG / "shell.sh",
        CONFIG / "pwnnew.sh",
        CONFIG / "gdbinit",
        CONFIG / "tmux.conf",
        CONFIG / "templates" / "payload.py",
        CONFIG / "templates" / "AGENTS.md",
    ]


def require_config() -> None:
    missing = [p for p in required_files() if not p.exists()]
    if missing:
        raise SystemExit("missing config files:\n" + "\n".join(f"  - {p}" for p in missing))


def shell_hook() -> str:
    root = shlex.quote(str(ROOT))
    return f"""export INIT_HOME={root}
[ -f "$INIT_HOME/config/shell.sh" ] && . "$INIT_HOME/config/shell.sh"
[ -f "$INIT_HOME/config/pwnnew.sh" ] && . "$INIT_HOME/config/pwnnew.sh"
"""


def apply_shell() -> None:
    for rc in (HOME / ".bashrc", HOME / ".zshrc"):
        upsert_block(rc, "init-shell", shell_hook())
        ok(f"shell hook -> {rc}")


def apply_gdb() -> None:
    upsert_block(HOME / ".gdbinit", "init-gdb", f"source {CONFIG / 'gdbinit'}\n")
    ok("gdb hook -> ~/.gdbinit")


def apply_tmux() -> None:
    upsert_block(HOME / ".tmux.conf", "init-tmux", f"source-file {CONFIG / 'tmux.conf'}\n")
    ok("tmux hook -> ~/.tmux.conf")


def apply() -> None:
    require_config()
    print(color("36", f"init-config {VERSION}"))
    print(f"package: {ROOT}")
    print(f"config : {CONFIG}")
    print()
    apply_shell()
    apply_gdb()
    apply_tmux()
    STATE.mkdir(exist_ok=True)
    state = {
        "version": VERSION,
        "time": time.time(),
        "root": str(ROOT),
        "config": str(CONFIG),
        "env": "INIT_HOME",
        "targets": ["~/.bashrc", "~/.zshrc", "~/.gdbinit", "~/.tmux.conf"],
    }
    write_text(STATE / "config-state.json", json.dumps(state, indent=2, ensure_ascii=False) + "\n")
    print()
    ok("ready. Open a new terminal, or run: source ~/.bashrc / source ~/.zshrc")


def clean() -> None:
    changed: list[str] = []
    for path in (HOME / ".bashrc", HOME / ".zshrc", HOME / ".gdbinit", HOME / ".tmux.conf"):
        if remove_blocks(path):
            changed.append(str(path))
    if changed:
        for p in changed:
            ok(f"cleaned: {p}")
    else:
        ok("nothing to clean")


def paths() -> None:
    rows = [
        ("config/shell.sh", "PATH, zsh helper, aliases"),
        ("config/pwnnew.sh", "pwnnew workspace helper"),
        ("config/gdbinit", "GDB defaults"),
        ("config/tmux.conf", "tmux defaults"),
        ("config/templates/payload.py", "default pwntools payload"),
        ("config/templates/AGENTS.md", "workspace notes for AI assistants"),
    ]
    print("package root:")
    print(f"  {ROOT}")
    print("\nedit these source files:")
    for rel, note in rows:
        print(f"  {ROOT / rel}\n    {note}")
    print("\napplied targets:")
    for p in ["~/.bashrc", "~/.zshrc", "~/.gdbinit", "~/.tmux.conf"]:
        print(f"  {p}")
    print("\nshell variable:")
    print("  INIT_HOME points to the package root after applying config.")


def has_text(path: Path, *needles: str) -> bool:
    text = read_text(path)
    return bool(text) and all(n in text for n in needles)


def run_quiet(cmd: list[str], cwd: Path | None = None) -> bool:
    try:
        return subprocess.run(cmd, cwd=str(cwd) if cwd else None, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0
    except Exception:
        return False


def test_config() -> int:
    print(color("36", f"init-config {VERSION} test"))
    print(f"package: {ROOT}")
    print(f"config : {CONFIG}\n")
    ok_all = True

    print("Config source files:")
    for p in required_files():
        if p.exists():
            ok(str(p.relative_to(ROOT)))
        else:
            err(f"missing: {p.relative_to(ROOT)}")
            ok_all = False

    print("\nSyntax checks:")
    if run_quiet([sys.executable, "-m", "py_compile", str(CONFIG / "templates" / "payload.py")]):
        ok("payload.py compiles")
    else:
        err("payload.py compile failed")
        ok_all = False
    for rel in ["shell.sh", "pwnnew.sh"]:
        p = CONFIG / rel
        if run_quiet(["bash", "-n", str(p)]):
            ok(f"{rel} syntax")
        else:
            err(f"{rel} syntax failed")
            ok_all = False

    print("\nApplied hooks:")
    for rc in [HOME / ".bashrc", HOME / ".zshrc"]:
        if has_text(rc, "init-shell", "INIT_HOME", str(ROOT)):
            ok(f"shell hook: {rc}")
        else:
            warn(f"shell hook missing or points elsewhere: {rc}")
            ok_all = False
    if has_text(HOME / ".gdbinit", "init-gdb", str(CONFIG / "gdbinit")):
        ok("gdb hook: ~/.gdbinit")
    else:
        warn("gdb hook missing or points elsewhere: ~/.gdbinit")
        ok_all = False
    if has_text(HOME / ".tmux.conf", "init-tmux", str(CONFIG / "tmux.conf")):
        ok("tmux hook: ~/.tmux.conf")
    else:
        warn("tmux hook missing or points elsewhere: ~/.tmux.conf")
        ok_all = False

    print()
    if ok_all:
        ok("config test passed")
        return 0
    warn("config test found missing or stale items. Run: python3 init-config.py")
    return 1


def help_text() -> str:
    return f"""
init-config {VERSION}

Usage:
  python3 init-config.py           Apply ./config to shell, GDB, and tmux
  python3 init-config.py --test    Check config files and applied hooks
  python3 init-config.py clean     Remove init hooks; keep files and software
  python3 init-config.py paths     Show editable config files
  python3 init-config.py -h        Show help

Notes:
  - Edit files under ./config/ directly.
  - Rerun this script after moving the package directory.
""".strip()


def main(argv: list[str]) -> int:
    if not argv:
        apply()
        return 0
    cmd = argv[0]
    if cmd in {"-h", "--help", "help"}:
        print(help_text())
        return 0
    if cmd in {"--version", "version"}:
        print(VERSION)
        return 0
    if cmd in {"--test", "test"}:
        return test_config()
    if cmd in {"clean", "--clean"}:
        clean()
        return 0
    if cmd in {"paths", "--paths"}:
        paths()
        return 0
    err(f"unknown command: {cmd}")
    print(help_text())
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
