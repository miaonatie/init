# init v3.2

面向 Ubuntu 24.04+、对应 WSL 和最新 Kali 的个人 Pwn/CTF 环境初始化工具。

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

- 基础终端：curl、wget、git、rsync、vim、nano、tmux、tree
- 日常工具：bat、fd、ripgrep、fzf、zoxide、duf、gdu、btop、htop、ncdu、jq、yq、hyfetch
- 编译开发：GCC/G++、make、CMake、Autoconf、Automake、Libtool、DKMS、默认 JDK
- 调试逆向：GDB、gdb-multiarch、checksec、patchelf、binutils、strace、ltrace
- 多架构：i386/multilib、qemu-user、qemu-system、binfmt
- 网络安全：net-tools、dnsutils、ping、traceroute、mtr、iperf3、tcpdump、socat、nmap、lsof、fail2ban、ufw
- 压缩处理：zip、unzip、7zip、zstd、cpio、rpm2cpio
- Python：pwntools、ROPgadget、ropper、capstone、unicorn、keystone、z3、pyelftools、lief
- Pwn 工具：pwndbg、one_gadget、seccomp-tools、glibc-all-in-one、libc-database
- AI 工具：Codex CLI、Claude Code、cc-switch

Python Pwn 包直接安装到系统 Python，不使用虚拟环境或用户目录：

```bash
sudo python3 -m pip install --break-system-packages ...
```

Ubuntu 24.04 和当前 Kali 的 pip 会固定使用 `--break-system-packages`。
Ruby 工具同样使用系统级安装，安装后可直接执行。

Ubuntu 会自动安装 `software-properties-common` 并启用 `universe` 软件源。
`batcat` 和 `fdfind` 会分别建立为系统命令 `bat`、`fd`。
清单内软件全部作为必装项处理；`gdu` 仅在提供该包的 Kali 上安装。

## 说明

- 仅支持 Ubuntu 24.04 及以上版本、对应 WSL，以及当前 Kali。
- 不会执行 `apt full-upgrade` 或 `apt autoremove`。
- 请直接以普通用户运行；脚本会在需要时调用 `sudo`。
- i386/multilib 仅在 x86_64/amd64 上启用。
- Python 包直接修改系统 Python；不创建或使用虚拟环境。
- 为避免误删已有依赖，脚本不会自动执行 `apt autoremove`。
- 不包含配置写入、安装日志、`pwnnew`、payload 模板或交互菜单。
