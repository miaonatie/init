# init v2

Portable CTF pwn environment initializer for fresh WSL / Kali / Debian / Ubuntu systems.

Unpack the package, optionally edit `config/`, then run the installer. The configuration source stays inside this directory; short hooks load it from your shell, GDB, tmux, and Codex config.

## Quick start

```bash
cd init-v2
python3 init-install.py
```

Interactive install:

```bash
python3 init-install.py --menu
```

Apply config only:

```bash
python3 init-config.py
```

Check status:

```bash
python3 init-install.py --test
# or config only
python3 init-config.py --test
```

Clean hooks without uninstalling software:

```bash
python3 init-config.py clean
```

## Files

```text
init-v2/
├── init-install.py      # software installer
├── init-config.py       # config applier / cleaner
├── config/              # editable source config
└── state/               # reports generated after running
```

`config/` contains:

```text
shell.sh                 # PATH, zsh helper, aliases
pwnnew.sh                # create pwn workspaces
gdbinit                  # GDB defaults
tmux.conf                # tmux defaults
templates/payload.py     # default pwntools payload
templates/AGENTS.md      # workspace notes for AI assistants
mcp/codex-ida.toml       # Codex IDA MCP block
mcp/ida-mcp-windows.md   # Windows-side IDA MCP notes
```

## Editing

Most edits take effect without rerunning `init-config.py`:

- `config/shell.sh`: open a new terminal, or run `source ~/.bashrc` / `source ~/.zshrc`
- `config/pwnnew.sh`: open a new terminal, or source your rc file
- `config/gdbinit`: next GDB start
- `config/tmux.conf`: new tmux session, or `tmux source-file ~/.tmux.conf`
- `config/templates/payload.py` and `AGENTS.md`: next `pwnnew` workspace

Rerun `python3 init-config.py` after:

- moving the package directory
- editing `config/mcp/codex-ida.toml`

## Commands

```bash
python3 init-install.py              # full install, then apply config
python3 init-install.py --menu       # interactive install
python3 init-install.py --no-config  # install software only
python3 init-install.py --test       # check software and config

python3 init-config.py               # apply ./config
python3 init-config.py --test        # check config and hooks
python3 init-config.py paths         # show editable files
python3 init-config.py clean         # remove init hooks only
```

## pwnnew

After applying config:

```bash
pwnnew babyrop
pwnnew babyrop ./chall ./libc.so.6 ./ld-linux-x86-64.so.2
pwnnew ./challenge.zip
pwnnew --no-extract ./challenge.zip
```

A new workspace contains:

```text
payload.py
AGENTS.md
```

## Notes

- `clean` removes only marked `init-*` hooks. It does not uninstall apt, pip, gem, cargo, npm, or cloned tools.
- `config/shell.sh` does not load `nvm.sh`; nvm is handled by its own installer.
- If you move the package, rerun `python3 init-config.py` once so hooks point to the new path.
