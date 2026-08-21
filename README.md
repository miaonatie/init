# init v3

面向 WSL、Ubuntu、Debian、Kali 的 Pwn/CTF 环境初始化工具。

## 使用

```bash
git clone https://github.com/miaonatie/init.git
cd init
python3 init.py
```

不需要选择参数，也没有图形界面或交互菜单。脚本在终端中使用简洁的彩色输出，
并显示当前步骤和累计耗时；输出重定向到文件时会自动关闭颜色。
它会自动完成安装、补装和结果检查，不修改 shell、GDB 或 tmux 配置。

安装流程只有 5 个阶段：

```text
1. 系统检查
2. 系统与基础软件包
3. Pwn 工具（Python、Ruby、pwndbg、glibc 工具仓库）
4. AI 工具（Codex、Claude、cc-switch）
5. 最终验证
```

更新后重新运行即可：

```bash
git pull
python3 init.py
```

## 安装内容

- 编译调试：GCC/G++、GDB、gdb-multiarch、checksec、patchelf、binutils、strace、ltrace
- 多架构：i386/multilib、qemu-user
- Python：pwntools、ROPgadget、ropper、capstone、unicorn、keystone、z3、pyelftools、lief
- Pwn 工具：pwndbg、one_gadget、seccomp-tools、glibc-all-in-one、libc-database
- 终端工具：tmux
- AI 工具：Codex CLI、Claude Code、cc-switch

Python 包使用系统 Python 的用户级目录安装：

```bash
python3 -m pip install --user --break-system-packages ...
```

支持该参数的 pip 会使用 `--break-system-packages`；Ubuntu 22.04 等旧版 pip
不认识该参数时会自动使用兼容模式。命令通常安装到 `~/.local/bin`。

## 说明

- 仅支持使用 APT 的 Ubuntu、Debian、Kali 和 WSL 环境。
- 不会执行 `apt full-upgrade` 或 `apt autoremove`。
- 请直接以普通用户运行；脚本会在需要时调用 `sudo`。
- i386/multilib 仅在 x86_64/amd64 上启用。
- Python 包不使用虚拟环境，会进入当前用户的系统 Python 环境；这更方便，但可能覆盖同名用户包。
- 不包含配置写入、安装日志、`pwnnew`、payload 模板或交互菜单。
