# init v3.26

面向 Ubuntu 24.04+ 和 Kali Linux/WSL 的 CTF 工作站初始化工具。

## 使用

```bash
git clone https://github.com/miaonatie/init.git
cd init
python3 init.py
```

脚本会在需要系统权限时自行调用 `sudo`。不要运行 `sudo python3 init.py`，否则无法可靠判断用户级工具和配置文件应该属于谁。

- 普通用户运行：用户级内容写入当前用户的 `~`，例如 `~/.vimrc`、`~/.zshrc`、`~/.oh-my-zsh` 和 `~/tools`。
- 直接登录 root 后运行：用户级内容写入 `/root`。
- APT 软件包、Docker 和 `/usr/local/bin` 命令是系统级安装。

默认模式会先做可用性检查，健康组件不会联网、重装或重写相同配置。需要更新脚本管理的 Git 仓库和语言工具链时使用：

```bash
python3 init.py --update
```

## 文件和配置变更

脚本只在需要时创建或修改以下用户级路径：

- `~/.vimrc`：基础 Vim 受管配置块。
- `~/.tmux.conf`：基础 Tmux 受管配置块。
- `~/.gdbinit`：系统 GDB 自动加载 Pwndbg、Debuginfod 和 r2ghidra 快捷命令。
- `~/.bashrc`、`~/.zshrc`：NVM、Rust 和 Oh My Zsh 配置；保留其他个人内容。
- `~/.oh-my-zsh`：Oh My Zsh 及两个外部插件。
- `~/.local/bin`、`~/.local/share/uv/tools/pwndbg`：uv 和 Pwndbg。
- `~/.local/share/init/gdb/r2ghidra.py`：Pwndbg 的 `ghidra` 快捷命令。
- `~/.cargo`、`~/.rustup`、`~/tools`：Rust、NVM、radare2、Python 2 和 libc 工具。

系统级变更包括 APT 软件包、Docker 软件源与软件包、必要的 `/usr/local/bin` 命令链接，以及把当前运行用户的默认 Shell 设置为 zsh。脚本不会创建 `~/.inputrc`、EXP 模板或 `pwn-exp-init` 命令。

## Pwndbg、GDB 和 r2ghidra

脚本使用当前官方支持的经典方案：

- 使用发行版的系统 `gdb`/`gdb-multiarch`。
- 使用 `uv tool` 隔离管理当前官方稳定版 Pwndbg 2026.07.29 的 Python 依赖。
- 同时比较系统 GDB 与系统 Python 的版本和 `INSTSONAME`，优先使用 ABI 完全匹配的系统 Python 绝对路径创建 Pwndbg 环境。
- 安装 Pwndbg 时通过 `--with r2pipe==1.9.8` 把 r2pipe 放入同一环境。
- 分开验证 uv 包、系统 GDB 导入和 r2ghidra 反编译；只有 GDB 无法导入 Pwndbg/r2pipe 时才修复 Python 环境。
- GDB 探测期间关闭 Debuginfod，避免下载调试源码超时后被误判成安装损坏。
- 已有 uv 工具需要切换 Python 时使用 `uv tool upgrade --python` 重建；健康复跑不会联网或重装。
- 修复安装只执行一次，隐藏 uv 的冗长包列表；超时和失败会保留有效错误，不会被输出类型异常覆盖。
- 在 `~/.gdbinit` 的受管块中自动加载 Pwndbg、启用 Debuginfod、配置 Intel 汇编格式并加载 `ghidra` 快捷命令。
- 编译临时 ELF，在 `main` 处真正执行 r2ghidra 反编译后才判定安装成功。

日常直接运行系统 GDB，Pwndbg 会自动启动：

```bash
gdb ./chall
```

也可以使用 uv 提供的入口：

```bash
pwndbg ./chall
```

需要完全跳过 `~/.gdbinit`、进入纯净系统 GDB 时：

```bash
gdb -nx ./chall
```

Pwndbg 中可以使用：

```gdb
start
r2pipe aaa
r2pipe pdg @ sym.main
ghidra
ghidra &main
```

从 v3.22 或更早版本升级时，普通 `python3 init.py` 会自动、一次性删除脚本管理的便携版目录、`pwndbg-ctf`、Shell 包装函数和独立 r2pipe 目录，然后迁移到 uv。只想清理旧便携版而暂时不安装新版本，可以运行：

```bash
python3 init.py --remove-portable-pwndbg
```

该操作只移除旧脚本的受管配置块和已确认属于官方便携版的链接/目录，保留 `.gdbinit`、`.bashrc` 和 `.zshrc` 中的其他个人配置。

## HyFetch 和后端

脚本安装并验证：

- `hyfetch`：彩色系统信息前端。
- `neowofetch`：HyFetch 自带、仍在维护的 Neofetch 兼容实现。
- `fastfetch`：优先从发行版 APT 安装；APT 没有时使用官方 GitHub `.deb`，并校验包名和架构。

```bash
hyfetch
hyfetch --backend fastfetch
neowofetch
fastfetch
```

## Vim

脚本保留原有 `~/.vimrc`，只维护一个带边界标记的基础配置块，包括：

```vim
set tabstop=4
set shiftwidth=4
set softtabstop=4
set expandtab
set autoindent
```

同时启用行号、搜索高亮、智能缩进、语法高亮和文件类型缩进。可以继续使用 `vim ~/.vimrc` 添加个人配置；脚本复跑不会覆盖块外内容。

## Tmux

脚本保留原有 `~/.tmux.conf`，只维护一个基础配置块：

```tmux
set -g mouse on
set -g history-limit 50000
```

只保留鼠标操作和调试输出历史两项通用设置，不改变 Escape 延迟或窗口/面板编号习惯。首次写入时会尝试静默重载正在运行的 Tmux；没有现有会话时，新会话会自动读取该配置。

## Oh My Zsh

脚本从官方仓库安装 `~/.oh-my-zsh`，保留并合并现有 `.zshrc`，启用：

```text
git zsh-autosuggestions z extract web-search zsh-syntax-highlighting
```

`zsh-syntax-highlighting` 固定放在最后加载，并配置：

```zsh
alias py='python'
```

脚本还会把当前运行用户的默认 shell 设置为 zsh。安装结束后执行下面的命令立即进入，或重新打开终端：

```bash
exec zsh
```
