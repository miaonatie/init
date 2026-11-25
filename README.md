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
/usr/bin/python3 init.py --iot          # 只安装/修复 IoT 固件实验台
/usr/bin/python3 init.py --iot-check    # 只验证 IoT 层
/usr/bin/python3 init.py --help         # 帮助
```

IoT 动作会 `apt` 装 QEMU/system、`squashfs-tools`、`mtd-utils`，把 `iot/` 资产复制到
`~/.local/share/init/iot`，写入 `config.json`（FirmAE 固定 revision），并克隆
`pr0v3rbs/FirmAE` 到 `~/tools/FirmAE`。Docker daemon 可用时构建镜像，不可用时记为
`skipped`，之后手动 `firmae build`。固件分析速查见 `iot/USAGE.md`，装好后 `iot-help` 直接看。

## 行为约束

- 只安装，不删除、不 `upgrade`、不 `autoremove`，可重复执行。
- 二次运行不应触发 `[update]`：`refresh_index` 只看本次真正要装的层，已装的层不再刷新索引。
- 可选包缺失报 `skipped` 并继续；必需项失败才返回非零。
- 验证失败时不动 `~/.bashrc`/`~/.zshrc`；成功后才清理旧的 `init Python tools` 激活块，
  并把 nvm 设为 `--no-use`、rustup 换成不抢 PATH 的写法，让系统运行时优先。
