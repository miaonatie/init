## 安装

```bash
git clone https://github.com/miaonatie/init.git
cd init
/usr/bin/python3 init.py
```

脚本通过 APT 安装系统 Python 与全部库，并把 CTF 工具链补齐到系统路径。装完用
`/usr/bin/python3 init.py --check` 复核，`--check-python` 只核对解释器和库。

## 分层

| 阶段 | 内容 |
| --- | --- |
| 1/4 环境检查 | 确认 Linux + APT + `dpkg-query`，打印发行版与系统 Python 路径 |
| 2/4 系统基础 | 系统 Python、`python3-dev`、常用 Python 库、shell/网络诊断工具 |
| 3/4 实验工具 | 编译链、语言运行时、二进制调试、Pwn 与利用、取证与解包 |
| 4/4 验证 | 逐个 `import` 已装库、逐个启动 CLI、编译并运行一个 C 程序 |

第 3 阶段之后还有两组独立动作：**Python CTF 工具**（APT 缺的用 pip 补、给 pwn 补子命令）
和 **IoT 固件实验台**（把 `iot/` 资产装到 `~/.local/share/init/iot` 并写好 `firmae`/
`iot-help` 启动器）。

## Python 来源策略

1. 库一律走 APT（`python3-*`），解释器固定 `/usr/bin/python3`，不建 venv。
2. 命令行工具优先 APT：`python3-pwntools`、`python3-ropgadget`。
3. APT 没打包的（`ropper`，以及 24.04 之前发行版里的 `pwntools`/`ROPgadget`）才用 pip，
   且要求 Python ≥ 3.8；低于 3.8 记为 `skipped` 而不是失败。
4. 遇到 PEP 668（`EXTERNALLY-MANAGED`）自动追加 `--break-system-packages`。
5. Python 3.14 的 `ast.Str` 已被移除，`ropper` 依赖的 `filebytes` 需要上游补丁；
   脚本按 `python_version >= '3.14'` 条件注入该补丁地址。
6. APT 版 pwntools 只带 `/usr/bin/pwn`，不装 `checksec`/`cyclic`/`asm`/`disasm`/
   `shellcraft`。脚本在 `/usr/local/bin` 生成薄壳包装，并统一置 `PWNLIB_NOTERM=1`，
   避免无 terminfo 的环境（容器、CI）在导入时打印 curses 告警。

发行版实测（2026-11）：

| 发行版 | Python | pwntools | ROPgadget | ropper |
| --- | --- | --- | --- | --- |
| Ubuntu 20.04 | 3.8 | pip | pip | pip |
| Ubuntu 22.04 | 3.10 | pip | APT | pip |
| Ubuntu 24.04 | 3.12 | APT 4.12.0 | APT 7.4 | pip |
| Debian 13 | 3.13 | APT 4.14.1 | APT 7.6 | pip |
| Kali rolling | 3.14 | APT 4.15.0 | APT 7.7 | pip + filebytes 补丁 |
| Ubuntu 18.04 | 3.6 | skipped | skipped | skipped |

## 其它动作

```bash
/usr/bin/python3 init.py --check        # 只验证，不安装
/usr/bin/python3 init.py --check-python # 只验证 Python 层
/usr/bin/python3 init.py --doctor       # 诊断已有环境，什么都不改
/usr/bin/python3 init.py --iot          # 只安装/修复 IoT 固件实验台
/usr/bin/python3 init.py --iot-check    # 只验证 IoT 层
/usr/bin/python3 init.py --help         # 帮助
```

`--doctor` 检查的是包清单看不出来的问题：命令是否只靠 Windows PATH 解析、
一个名字是否存在多个实现、pip 副本是否盖住更新的 APT 副本、shell 启动耗时。
每条给出可执行建议。

## 同名命令的归属

同一个命令有多个实现时，"哪个胜出"决定行为，所以这里写明取舍：

| 命令 | 谁胜出 | 为什么 |
| --- | --- | --- |
| `checksec` | `/usr/local/bin/checksec` 调度器 | APT 的 `checksec.sh` 要 `--file=x`，pwntools 要裸路径；调度器两种都收 |
| `pwn` / `ROPgadget` / `ropper` | `/usr/local/bin` 包装 | 置 `PWNLIB_NOTERM=1`，避免无 terminfo 时打印 curses 告警 |
| `r2` / `radare2` | `/usr/local/bin`（源码 6.2.1） | 比 APT 的 6.0.5 新 |
| `node` / `python3` / `git` | `/usr/bin`（APT） | Linux 原生，不依赖 WSL interop |

## 已知的、不该"修"的现象

`--doctor` 会报告两条 warn，它们都是环境事实而不是故障：

**1. pip 副本盖住更新的 APT 副本（19 个模块）。**
`/usr/local/lib` 在 `sys.path` 里排在 `/usr/lib` 之前，而 Kali 上的 pip 工具
（netexec、impacket、wfuzz、unblob）钉死了较旧版本，例如 `sqlalchemy 1.3.22`
盖住 APT 的 `2.0.48`。这些是那些工具的依赖要求，**删掉会破坏它们**。
要判断影响范围看 `pip show <name> | grep Required-by`。

**2. 交互式 shell 启动约 1.1 秒。**
实测拆解：裸 `zsh -f` 10 ms，oh-my-zsh 约 1 秒。`ZSH_DISABLE_COMPFIX=true`
**无效**——在同一个进程里 `compinit -u` 和 `-C` 都是 0 ms，成本来自进程启动后加载
约 1200 个补全函数。只有精简插件或弃用 oh-my-zsh 才能改变，属于框架成本。

## 行为约束


- 只安装，不删除、不 `upgrade`、不 `autoremove`，可重复执行。
- 二次运行不应触发 `[update]`：`refresh_index` 只看本次真正要装的层，已装的层不再刷新索引。
- 可选包缺失报 `skipped` 并继续；必需项失败才返回非零。
- 验证失败时不动 `~/.bashrc`/`~/.zshrc`；成功后才清理旧的 `init Python tools` 激活块，
  并把 nvm 设为 `--no-use`、rustup 换成不抢 PATH 的写法，让系统运行时优先。
