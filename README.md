# init v1.0.4

Portable CTF pwn environment initializer for fresh WSL / Kali / Debian / Ubuntu systems.

```text
init-install.py   install tools
init-config.py    apply config from ./config
```

Edit files under `config/` directly. The package directory is the config source.

---

## Quick start

```bash
cd init-v1.0.4
python3 init-install.py
```

Interactive install:

```bash
python3 init-install.py --menu
```

Install tools only:

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

---

## Files

```text
init-v1.0.4/
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

## Default tools

```text
System:  gcc/g++, gdb, checksec, patchelf, binutils, seccomp, qemu, i386
Python:  pwntools, ROPgadget, ropper, capstone, unicorn, keystone, z3, lief
Ruby:    one_gadget, seccomp-tools
CLI:     zsh, oh-my-zsh, fzf, bat, eza, btop, duf, trashy
Repos:   pwndbg, glibc-all-in-one, libc-database
AI:      Codex CLI, Claude Code, cc-switch
```

The installer skips installed tools when possible. It is safe to rerun.

---

## Config

### `config/shell.sh`

Loaded by bash/zsh. Use it for PATH, zsh settings, aliases, and trashy aliases.

After editing:

```bash
source ~/.bashrc
# or
source ~/.zshrc
```

### `config/pwnnew.sh`

Defines `pwnnew`.

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

### `config/templates/payload.py`

Default pwntools template copied by `pwnnew`.

```bash
python3 payload.py
python3 payload.py GDB
python3 payload.py REMOTE HOST=example.com PORT=31337
python3 payload.py BIN=./chall LIBC=./libc.so.6 LD=./ld-linux-x86-64.so.2
```

### `config/templates/AGENTS.md`

Workspace note for Codex / Claude Code.

### `config/gdbinit`

Loaded by `~/.gdbinit`.

### `config/tmux.conf`

Loaded by `~/.tmux.conf`.

Reload tmux manually if needed:

```bash
tmux source-file ~/.tmux.conf
```

---

## Move the package

The config hook stores the package path. After moving the directory, run:

```bash
python3 init-config.py
```

---

## Clean

```bash
python3 init-config.py --clean
```

Removes marked `init-*` blocks from:

```text
~/.bashrc
~/.zshrc
~/.gdbinit
~/.tmux.conf
```

It does not uninstall software.

---

## Optional: IDA MCP with uv tool

Windows-side `idalib-mcp` setup for cc-switch / Codex / Claude Code.

### 1. Install uv

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

### 3. Activate IDA path

```powershell
$IdaDir = "E:\ida"
$ToolPy = "$(uv tool dir)\ida-pro-mcp\Scripts\python.exe"
& $ToolPy "$IdaDir\idalib\python\py-activate-idalib.py" -d "$IdaDir"
```

Change `E:\ida` to your IDA directory.

### 4. Get idalib-mcp path

```powershell
$IdalibMcp = "$(uv tool dir)\ida-pro-mcp\Scripts\idalib-mcp.exe"
Write-Host $IdalibMcp
```

Use the printed path in cc-switch / Codex / Claude Code.

### 5. MCP config

Type:

```text
Custom / stdio
```

Command:

```text
<path from step 4>
```

Arguments:

```text
--stdio-shared
```

JSON example:

```json
{
  "type": "stdio",
  "command": "C:\\Users\\<USER>\\AppData\\Roaming\\uv\\tools\\ida-pro-mcp\\Scripts\\idalib-mcp.exe",
  "args": ["--stdio-shared"]
}
```

Test in Codex / Claude Code:

```text
/mcp
```
