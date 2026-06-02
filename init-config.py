#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Apply portable init config from ./config into shell/GDB/tmux/Codex."""

from __future__ import annotations

import json
import os
import re
import shlex
import sys
import time
from pathlib import Path

VERSION = "2026-06-02.6"
ROOT = Path(__file__).resolve().parent
CONFIG = ROOT / "config"
STATE = ROOT / "state"
HOME = Path.home()

# This package is for fresh systems. Only init-* blocks are managed.
BLOCK_RE = re.compile(
    r"(?ms)^# >>> init-[A-Za-z0-9_-]+ >>>\n"
    r".*?"
    r"^# <<< init-[A-Za-z0-9_-]+ <<<\n?"
)
IDA_SECTION_RE = re.compile(r"(?ms)^\[mcp_servers\.ida\]\s*\n.*?(?=^\[|\Z)")


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


def require_config() -> None:
    required = [
        CONFIG / "shell.sh",
        CONFIG / "pwnnew.sh",
        CONFIG / "gdbinit",
        CONFIG / "tmux.conf",
        CONFIG / "templates" / "solve.py",
        CONFIG / "templates" / "AGENTS.md",
        CONFIG / "mcp" / "codex-ida.toml",
    ]
    missing = [p for p in required if not p.exists()]
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


def clean_codex(path: Path) -> bool:
    if not path.exists():
        return False
    old = read_text(path)
    new = BLOCK_RE.sub("", old).strip()
    if new:
        new += "\n"
    if new != old:
        write_text(path, new)
        return True
    return False


def apply_codex() -> None:
    src = CONFIG / "mcp" / "codex-ida.toml"
    dst = HOME / ".codex" / "config.toml"
    content = read_text(src).strip()
    if not content:
        warn(f"empty MCP config: {src}")
        return

    clean_codex(dst)
    current = read_text(dst)
    if IDA_SECTION_RE.search(current):
        warn("Codex already has an unmarked [mcp_servers.ida]; leaving it unchanged to avoid duplicate TOML sections.")
        warn("Edit ~/.codex/config.toml manually, or remove that section before rerunning config.")
        return

    old = current.rstrip()
    block = f"# >>> init-codex-ida >>>\n{content}\n# <<< init-codex-ida <<<\n"
    write_text(dst, (old + "\n\n" + block if old else block))
    ok("codex MCP -> ~/.codex/config.toml")


def apply() -> None:
    require_config()
    print(color("36", f"init-config {VERSION}"))
    print(f"package: {ROOT}")
    print(f"config : {CONFIG}")
    print()
    apply_shell()
    apply_gdb()
    apply_tmux()
    apply_codex()
    STATE.mkdir(exist_ok=True)
    state = {
        "version": VERSION,
        "time": time.time(),
        "root": str(ROOT),
        "config": str(CONFIG),
        "env": "INIT_HOME",
        "targets": ["~/.bashrc", "~/.zshrc", "~/.gdbinit", "~/.tmux.conf", "~/.codex/config.toml"],
    }
    write_text(STATE / "config-state.json", json.dumps(state, indent=2, ensure_ascii=False) + "\n")
    print()
    ok("done. Open a new terminal, or run: source ~/.bashrc / source ~/.zshrc")


def clean() -> None:
    changed: list[str] = []
    for path in (HOME / ".bashrc", HOME / ".zshrc", HOME / ".gdbinit", HOME / ".tmux.conf"):
        if remove_blocks(path):
            changed.append(str(path))
    codex = HOME / ".codex" / "config.toml"
    if clean_codex(codex):
        changed.append(str(codex))
    if changed:
        for p in changed:
            ok(f"cleaned: {p}")
    else:
        ok("nothing to clean")


def paths() -> None:
    rows = [
        ("config/shell.sh", "PATH, zsh, aliases, trashy aliases"),
        ("config/pwnnew.sh", "pwnnew workspace helper"),
        ("config/gdbinit", "GDB defaults"),
        ("config/tmux.conf", "tmux defaults"),
        ("config/templates/solve.py", "default exploit template"),
        ("config/templates/AGENTS.md", "AI assistant workspace notes"),
        ("config/mcp/codex-ida.toml", "Codex IDA MCP block; rerun config after edits"),
        ("config/mcp/ida-mcp-windows.md", "Windows-side IDA MCP notes"),
    ]
    print("package root:")
    print(f"  {ROOT}")
    print("\nedit these source files:")
    for rel, note in rows:
        print(f"  {ROOT / rel}\n    {note}")
    print("\napplied targets:")
    for p in ["~/.bashrc", "~/.zshrc", "~/.gdbinit", "~/.tmux.conf", "~/.codex/config.toml"]:
        print(f"  {p}")
    print("\nshell variable:")
    print("  INIT_HOME points to the package root after applying config.")


def help_text() -> str:
    return f"""
init-config {VERSION}

Usage:
  python3 init-config.py          Apply ./config to shell/GDB/tmux/Codex
  python3 init-config.py clean    Remove init hooks only; does not uninstall software
  python3 init-config.py paths    Show editable config paths
  python3 init-config.py -h       Show this help

Notes:
  - Config source stays inside this package: ./config/
  - nvm is left to its official installer; shell.sh only adds common user paths and aliases.
  - Most edits do not need rerunning this script; open a new shell/program.
  - After moving the package directory, rerun this script once to refresh paths.
""".strip()


def main(argv: list[str]) -> int:
    if not argv:
        apply()
        return 0
    cmd = argv[0]
    if cmd in {"-h", "--help", "help"}:
        print(help_text())
        return 0
    if cmd == "clean":
        clean()
        return 0
    if cmd == "paths":
        paths()
        return 0
    err(f"unknown command: {cmd}")
    print(help_text())
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
