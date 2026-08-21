# init v2

面向 WSL、Ubuntu、Debian、Kali 的 Pwn/CTF 环境初始化工具。

## 使用

```bash
git clone https://github.com/miaonatie/init.git
cd init
python3 init.py
```

不需要选择参数。脚本会自动完成安装、补装、配置同步和结果检查，重复运行是安全的。

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
- Python：独立虚拟环境中的 pwntools、ROPgadget、ropper、capstone、unicorn、keystone、z3、lief
- Pwn 工具：pwndbg、one_gadget、seccomp-tools、glibc-all-in-one、libc-database
- 终端工具：zsh、tmux、ripgrep、fzf、bat、btop、duf
- AI 工具：Codex CLI、Claude Code、cc-switch

Python 工具安装在：

```text
~/.local/share/init/venv
```

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
- 不再包含 `pwnnew`、payload 模板和交互安装菜单。
