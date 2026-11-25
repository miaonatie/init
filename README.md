# init

CTF 环境一键搭建，Debian 系（Ubuntu / Debian / Kali）。

```bash
git clone https://github.com/miaonatie/init.git
cd init
/usr/bin/python3 init.py
```

## 就这一个命令

装完即用。不建 venv，不升级，不删包，可以反复跑——第二次运行十几秒、零下载。

```bash
python3 init.py            # 安装 + 验证
python3 init.py --check    # 只验证，什么都不改
```

只有两个用法，没有别的参数。

## 做什么

三段，每段都打印装了什么：

1. **环境** — 确认是 Linux + APT，打印发行版和系统 Python
2. **安装** — 159 个 APT 包，分 5 组；再补 APT 没有的 Python 工具
3. **验证** — 逐个 `import`、逐个启动命令、跑一次 `firmae status`

分组和内容：

| 组 | 内容 |
| --- | --- |
| 系统 Python | `python3` + 29 个库（pyelftools / zstandard / gmpy2 / capstone / unicorn / z3 / pycryptodome …） |
| 日常工具 | git curl vim tmux zsh bat fd rg fzf jq yq dig tcpdump … |
| 编译与语言 | build-essential clang cmake ninja perl ruby java node go rust |
| 二进制与调试 | gdb / gdb-multiarch / gdbserver xxd patchelf nasm valgrind qemu-user radare2 socat netcat |
| Pwn 与取证 | pwntools ropgadget checksec binwalk apktool steghide sleuthkit ffmpeg tesseract 7zip squashfs-tools … |

## Python 从哪来

**库只走 APT，解释器只 `/usr/bin/python3`。** APT 没打包的才用 pip，就一个 `ropper`。

三条实测出来的处理：

- **Python ≥ 3.8 才用 pip**。更低版本直接报 `skipped`，不制造半装状态。
- **PEP 668 自动加 `--break-system-packages`**。24.04 / Debian 13 / Kali 都有 `EXTERNALLY-MANAGED` 标记。
- **Python 3.14 注入 filebytes 补丁**。`ropper` 依赖的 `filebytes` 用了已移除的 `ast.Str`。

发行版实测（2026-11）：

| | Python | pwntools | ropper |
| --- | --- | --- | --- |
| Ubuntu 20.04 | 3.8 | pip | pip |
| Ubuntu 22.04 | 3.10 | pip | pip |
| Ubuntu 24.04 | 3.12 | APT 4.12 | pip |
| Debian 13 | 3.13 | APT 4.14 | pip |
| Kali | 3.14 | APT 4.15 | pip + 补丁 |

## 三个容易踩的坑，脚本已经处理

**`checksec` 有两个互不兼容的实现。** APT 的 `checksec.sh` 要 `--file=x`，pwntools 要裸路径。两者都装时后者会盖住前者，导致文档写法直接报错。脚本写一个调度器，两种语法都收：

```bash
checksec --file=/bin/true    # APT 完整表格
checksec /bin/true           # pwntools 精简表
```

**APT 的 pwntools 只给 `/usr/bin/pwn`。** `checksec`/`cyclic`/`asm`/`disasm`/`shellcraft` 全缺。脚本在 `/usr/local/bin` 补 5 个薄壳。

**没有 terminfo 的环境导入 pwn 会打印 curses 告警**（容器、CI 常见）。所有包装统一置 `PWNLIB_NOTERM=1`。

## 固件工具

`iot/` 的四份文件会装到 `~/.local/share/init/iot`，并写好 `firmae` / `iot-help` 两个命令。**不自动构建镜像**——那要几百 MB 和几分钟，等你真要用的时候：

```bash
firmae build                  # 构建镜像（一次）
firmae -c dlink ./firmware.bin
firmae web 192.168.0.1        # 浏览器开 http://127.0.0.1:18080
iot-help                      # 速查表
```

`firmae status` 看状态：`ready` / `pending`（镜像没建）/ `broken`。未构建只报 `pending`，不算失败。

需要 x86_64 Linux + Docker + TUN + loop 设备；不满足时 `firmae doctor` 会说。

## 不装的东西

- **不建 venv**，不装 pyenv/uv。系统 Python 就够。
- **不做源码编译**，不装 r2ghidra。radare2 用发行版的。
- **不装 pwndbg**。要的话 `pip install pwndbg` 或看官方 uv 安装方式。
- **不碰 nvm/rustup**。node/rust 用 APT 的，不劫持 PATH。

## 已知不修的

**Kali 上 pip 旧版会盖住更新的 APT 版（19 个模块）**，比如 `sqlalchemy 1.3.22` 盖住 `2.0.48`。这不是故障：

```
$ pip show sqlalchemy | grep Required-by
Required-by: alembic, netexec, SQLAlchemy-Utc
```

netexec / impacket / wfuzz 钉死了旧版，删了会坏。查影响范围用 `pip show <名> | grep Required-by`。

**交互式 zsh 启动约 1.1 秒**，是 oh-my-zsh 加载 ~1200 个补全函数。试过 `ZSH_DISABLE_COMPFIX=true`，无效——同一进程内 `compinit` 任何参数都是 0 ms。只有精简插件才有用。

## 验证

```bash
python3 -m unittest discover -s tests    # 30 项，0.15 秒，不联网
```

CI 在 6 个镜像上跑完整流程：`init.py` → `--check` → 单测 → 再跑一次，并断言第二次既无 `[update]` 也无 `[failed]`。

镜像矩阵：ubuntu 20.04 / 22.04 / 24.04 / 26.04、debian 13、kali-rolling。
Ubuntu 18.04（Python 3.6）不支持：pip 装 pwntools 时 `psutil` 编译失败，APT 也没有该包。
