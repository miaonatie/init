# init v2

面向 WSL、Ubuntu、Debian、Kali 的 Pwn/CTF 环境初始化工具。

## 使用

```bash
git clone https://github.com/miaonatie/init.git
cd init
python3 init.py
```

不需要选择参数，也没有图形界面或交互菜单。脚本使用纯文本输出，并显示当前步骤和累计耗时；
它会自动完成安装、补装、配置同步和结果检查，重复运行是安全的。

更新后重新运行即可：

```bash
git pull
python3 init.py
```

删除配置钩子：

```bash
python3 init.py --clean
```

`--clean` 只删除本项目管理的 shell、GDB、tmux 配置，不卸载软件。

## 安装内容

- 编译调试：GCC/G++、GDB、gdb-multiarch、checksec、patchelf、binutils、strace、ltrace
- 多架构：i386/multilib、qemu-user
- Python：pwntools、ROPgadget、ropper、capstone、unicorn、keystone、z3、pyelftools、lief、IPython
- Pwn 工具：pwndbg、one_gadget、seccomp-tools、glibc-all-in-one、libc-database
- 终端工具：zsh、tmux、ripgrep、fzf、bat、btop、duf
- AI 工具：Codex CLI、Claude Code、cc-switch

Python 包使用系统 Python 的用户级目录安装：

```bash
python3 -m pip install --user --break-system-packages ...
```

支持该参数的 pip 会使用 `--break-system-packages`；Ubuntu 22.04 等旧版 pip
不认识该参数时会自动使用兼容模式。命令通常安装到 `~/.local/bin`。

项目配置同步到：

```text
~/.config/init
```

安装报告写入：

```text
~/.local/state/init/install-report.json
```

## 修改配置

直接编辑：

```text
config/shell.sh
config/gdbinit
config/tmux.conf
```

然后重新运行：

```bash
python3 init.py
```

## 说明

- 仅支持使用 APT 的 Ubuntu、Debian、Kali 和 WSL 环境。
- 不会执行 `apt full-upgrade` 或 `apt autoremove`。
- 请直接以普通用户运行；脚本会在需要时调用 `sudo`。
- i386/multilib 仅在 x86_64/amd64 上启用。
- Python 包不使用虚拟环境，会进入当前用户的系统 Python 环境；这更方便，但可能覆盖同名用户包。
- 不再包含 `pwnnew`、payload 模板和交互安装菜单。

从 `v2.0.0` 升级时，旧目录 `~/.local/share/init/venv` 不会自动删除；确认不再使用后可手动清理。
