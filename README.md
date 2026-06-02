# init

Portable WSL / Kali / Debian / Ubuntu CTF pwn environment initializer.

This package is meant for a fresh system: unpack it, optionally edit `config/`, then run the installer once. Configuration stays inside this package directory and is applied through short source hooks.

## Files

- `init-install.py`: one-shot software installer. Default is full install; use `--menu` for interactive selection.
- `init-config.py`: config applier/cleaner. It does not install software; it only wires `./config/` into bash/zsh/GDB/tmux/Codex.
- `config/`: the source of all editable shell, template, GDB, tmux, and MCP configuration.
- `state/`: reports written by the scripts.

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

Set the default WSL distribution, for example Kali Linux:

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

Install software only, without applying config:

```bash
python3 init-install.py --no-config
```

Apply config only:

```bash
python3 init-config.py
```

Clean init hooks without uninstalling software:

```bash
python3 init-config.py clean
```

Show editable paths:

```bash
python3 init-config.py paths
```

## Config layout

```text
config/
├── shell.sh                    # PATH, zsh helper, aliases, trashy aliases
├── pwnnew.sh                   # pwnnew workspace helper
├── gdbinit                     # GDB defaults
├── tmux.conf                   # tmux defaults
├── templates/
│   ├── solve.py                # pwnnew default pwntools template
│   └── AGENTS.md               # AI assistant workspace notes
└── mcp/
    ├── codex-ida.toml          # Codex IDA MCP config block
    └── ida-mcp-windows.md      # Windows-side IDA MCP notes
```

## Editing config

Most edits do not require rerunning `init-config.py`:

- `config/shell.sh`: reopen terminal, or run `source ~/.bashrc` / `source ~/.zshrc`.
- `config/pwnnew.sh`: reopen terminal, or source your rc file.
- `config/gdbinit`: next GDB start.
- `config/tmux.conf`: new tmux session, or `tmux source-file ~/.tmux.conf`.
- `config/templates/solve.py` / `AGENTS.md`: next `pwnnew` workspace.

Rerun config after editing:

- `config/mcp/codex-ida.toml`, because it is merged into `~/.codex/config.toml`.
- after moving the whole package directory, because hooks store the package path.

## Node / nvm / pnpm

`config/shell.sh` does not source `nvm.sh`. nvm's official installer usually writes its own shell block, and loading it twice can duplicate PATH entries or slow shell startup.

`init-install.py` still sources nvm temporarily inside install commands when installing Codex. Long-term shell config only adds common user binary paths such as `~/.local/bin`, `~/.cargo/bin`, and Go bin directories.

## Hooks and cleanup

`init-config.py` writes short marked blocks into:

- `~/.bashrc`
- `~/.zshrc`
- `~/.gdbinit`
- `~/.tmux.conf`
- `~/.codex/config.toml`

Blocks use names like:

```text
# >>> init-shell >>>
...
# <<< init-shell <<<
```

`clean` removes only `init-*` blocks created by this package. It does not uninstall apt/pip/gem/cargo/npm software.
