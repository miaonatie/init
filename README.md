# init v1.0.3

Portable CTF pwn environment initializer for fresh WSL / Kali / Debian / Ubuntu systems.

`init` has two small scripts:

```text
init-install.py   install pwn tools and packages
init-config.py    apply shell, GDB, and tmux config from ./config
```

The package directory is the config source. Edit files under `config/` directly.

---

## Quick start

```bash
cd init-v1.0.3
python3 init-install.py
```

This installs the default environment and then applies config automatically.

Interactive install:

```bash
python3 init-install.py --menu
```

Install software only:

```bash
python3 init-install.py --no-config
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

Clean config hooks:

```bash
python3 init-config.py --clean
```

Show editable files:

```bash
python3 init-config.py --paths
```

Help:

```bash
python3 init-install.py -h
python3 init-config.py -h
```

---

## Files

```text
init-v1.0.3/
├── VERSION
├── README.md
├── .gitignore
├── init-install.py
├── init-config.py
└── config/
    ├── shell.sh
    ├── pwnnew.sh
    ├── gdbinit
    ├── tmux.conf
    └── templates/
        ├── payload.py
        └── AGENTS.md
```

---

## What gets installed

Default install includes common pwn tooling:

```text
System:
  build-essential, gcc/g++, gdb, gdbserver, gdb-multiarch,
  checksec, patchelf, binutils, ltrace, strace, seccomp,
  qemu-user, i386/multilib support

Python:
  pwntools, ROPgadget, ropper, capstone, unicorn,
  keystone-engine, z3-solver, pyelftools, lief, ipython

Ruby:
  one_gadget, seccomp-tools

CLI:
  zsh, oh-my-zsh, fzf, bat, eza, btop, duf, trashy

Repos:
  pwndbg, glibc-all-in-one, libc-database

AI CLI:
  Codex CLI, Claude Code, cc-switch
```

The installer is safe to rerun. It skips installed tools when possible and records skipped/failed items under `state/`.

---

## Config source

All long-term editable config lives in `config/`.

### `config/shell.sh`

Loaded by bash/zsh after running `init-config.py`.

Use it for:

```text
PATH
zsh / oh-my-zsh helper
aliases
trashy aliases
```

After editing:

```bash
source ~/.bashrc
# or
source ~/.zshrc
```

No need to rerun `init-config.py`.

---

### `config/pwnnew.sh`

Defines the `pwnnew` command.

Examples:

```bash
pwnnew babyrop
pwnnew babyrop ./chall ./libc.so.6 ./ld-linux-x86-64.so.2
pwnnew ./challenge.zip
pwnnew --no-extract ./challenge.zip
pwnnew --help
```

A new workspace contains:

```text
payload.py
AGENTS.md
```

After editing `pwnnew.sh`, open a new terminal or source your shell rc file.

---

### `config/templates/payload.py`

Default pwntools payload template copied by `pwnnew`.

Examples:

```bash
python3 payload.py
python3 payload.py GDB
python3 payload.py REMOTE HOST=example.com PORT=31337
python3 payload.py BIN=./chall LIBC=./libc.so.6 LD=./ld-linux-x86-64.so.2
```

Edit this file to change the default template for future challenges.

Existing challenge directories are not modified.

---

### `config/templates/AGENTS.md`

Default workspace note for Codex / Claude Code.

Edit it to match your own workflow.

---

### `config/gdbinit`

Loaded by `~/.gdbinit`.

Default settings:

```text
Intel disassembly
no pagination
no confirm prompts
pretty printing
fork-following defaults
```

After editing, restart GDB.

---

### `config/tmux.conf`

Loaded by `~/.tmux.conf`.

Default settings:

```text
mouse on
larger history limit
```

Reload manually if needed:

```bash
tmux source-file ~/.tmux.conf
```

---

## Moving the package

`init-config.py` writes the package path into shell, GDB, and tmux hooks.

After moving the whole directory, run:

```bash
python3 init-config.py
```

from the new location.

---

## Clean

Remove hooks written by this package:

```bash
python3 init-config.py --clean
```

This removes only marked `init-*` blocks from:

```text
~/.bashrc
~/.zshrc
~/.gdbinit
~/.tmux.conf
```

It does not uninstall software.

---

## Optional: IDA MCP with uv tool

This is a minimal Windows-side setup for `idalib-mcp`.

Goal:

```text
Install idalib-mcp with uv tool.
Activate your local IDA path.
Use idalib-mcp.exe in cc-switch / Codex / Claude Code as stdio MCP.
```

### 1. Install uv

PowerShell:

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

Reopen PowerShell:

```powershell
uv --version
```

### 2. Install ida-pro-mcp

```powershell
uv tool install "ida-pro-mcp @ https://github.com/mrexodia/ida-pro-mcp/archive/refs/heads/main.zip"
```

Optional check:

```powershell
uv tool list
```

Expected entry:

```text
ida-pro-mcp
- idalib-mcp
```

### 3. Activate IDA path

Set your IDA directory:

```powershell
$IdaDir = "E:\ida"
```

Change `E:\ida` to your real IDA install path.

Run:

```powershell
$ToolPy = "$(uv tool dir)\ida-pro-mcp\Scripts\python.exe"
& $ToolPy "$IdaDir\idalib\python\py-activate-idalib.py" -d "$IdaDir"
```

### 4. Get idalib-mcp path

```powershell
$IdalibMcp = "$(uv tool dir)\ida-pro-mcp\Scripts\idalib-mcp.exe"
Write-Host $IdalibMcp
```

Copy the printed path.

Example:

```text
C:\Users\<USER>\AppData\Roaming\uv\tools\ida-pro-mcp\Scripts\idalib-mcp.exe
```

### 5. cc-switch config

Type:

```text
Custom / stdio
```

Command:

```text
<the idalib-mcp.exe path from step 4>
```

Arguments:

```text
--stdio-shared
```

Equivalent JSON:

```json
{
  "type": "stdio",
  "command": "C:\\Users\\<USER>\\AppData\\Roaming\\uv\\tools\\ida-pro-mcp\\Scripts\\idalib-mcp.exe",
  "args": ["--stdio-shared"]
}
```

### 6. Test

In Codex / Claude Code:

```text
/mcp
```

If `idalib-mcp` appears, it is ready.

---

## Notes

- `init` does not write Codex MCP config automatically.
- `config/shell.sh` does not load `nvm.sh`; nvm is handled by its own installer.
- `.gitignore` is for maintaining this package as a Git repository. It is not copied into challenge workspaces.
