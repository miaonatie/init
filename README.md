# init v1.0.2

Portable CTF pwn environment initializer for fresh WSL / Kali / Debian / Ubuntu systems.

Unpack the package, optionally edit `config/`, then run the installer. Release archives extract into an `init/` directory. The package directory is the config source. Short hooks load it from your shell, GDB, and tmux config.

## WSL basics

List Linux distributions available online:

```powershell
wsl --list --online
```

Install one distribution, for example Kali Linux:

```powershell
wsl --install -d kali-linux
```

Docker Desktop can install and manage its own Docker WSL distributions automatically. After installing Docker Desktop, you may see Docker entries in the WSL list.

Show installed WSL distributions and their versions/status:

```powershell
wsl -l -v
```

Set the default WSL distribution:

```powershell
wsl --set-default kali-linux
```

## Quick start

```bash
cd init
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
python3 init-config.py --test
```

Clean hooks without uninstalling software:

```bash
python3 init-config.py clean
```

## Files

```text
init/
├── VERSION
├── README.md
├── .gitignore
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
```

## Editing

Most edits take effect without rerunning `init-config.py`:

- `config/shell.sh`: open a new terminal, or run `source ~/.bashrc` / `source ~/.zshrc`
- `config/pwnnew.sh`: open a new terminal, or source your rc file
- `config/gdbinit`: next GDB start
- `config/tmux.conf`: new tmux session, or `tmux source-file ~/.tmux.conf`
- `config/templates/payload.py` and `AGENTS.md`: next `pwnnew` workspace

Rerun `python3 init-config.py` after moving the package directory.

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

## Optional: Windows IDA MCP notes

This package no longer writes Codex MCP config automatically. If you want IDA MCP, configure your assistant manually and run the MCP server on Windows.

WSL/Codex endpoint example:

```toml
[mcp_servers.ida]
url = "http://127.0.0.1:13337/mcp"
enabled = true
startup_timeout_sec = 30
tool_timeout_sec = 180
default_tools_approval_mode = "prompt"
```

Windows PowerShell example:

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
mkdir C:\tools
cd C:\tools
git clone https://github.com/mrexodia/ida-pro-mcp
cd C:\tools\ida-pro-mcp
uv run idalib-mcp --host 127.0.0.1 --port 13337 C:\ctf\babyrop\chall
```

Then in WSL:

```bash
cd /mnt/c/ctf/babyrop
codex
```

## Notes

- `clean` removes only marked `init-*` hooks. It does not uninstall apt, pip, gem, cargo, npm, or cloned tools.
- `config/shell.sh` does not load `nvm.sh`; nvm is handled by its own installer.
- `.gitignore` is for maintaining this package as a Git repository. It is not copied into challenge workspaces.
