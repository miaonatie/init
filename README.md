# init v3.12

Ubuntu 24.04+ / 最新 Kali 的一次性命令行 CTF 环境初始化工具。

## 使用

```bash
git clone https://github.com/miaonatie/init.git
cd init
python3 init.py
```

不要使用 `sudo python3 init.py`；需要系统权限时脚本会自行调用 `sudo`，r2ghidra 等用户级工具会安装到当前用户目录。

脚本分为 4 个阶段：环境检查、系统基础环境、CTF 工具链、最终验证。
系统软件包按系统开发、日常 CLI、CTF CLI、32 位支持分批处理，失败定位和重试更快。
已有的软件会先检查并跳过；可重复运行。
APT 会先排除当前软件源中不存在的包，避免一个无效包拖慢整批安装；十六进制查看统一使用 `xxd`。

- Python 3 工具直接安装到系统 Python（`--break-system-packages`）。
- Python 2.7 通过 pyenv 隔离安装，仅提供 `python2` / `pip2`，不会改变系统 `python`。
- Docker 安装 Engine、Buildx 和 Compose 插件；默认使用 `sudo docker ...`。
- radare2 会验证最低版本 6.1.4；发行版软件源版本过旧时，自动从官方 Git 源码安装到 `/usr/local`。
- r2ghidra 使用官方 r2pm 用户级安装，不需要安装完整的 Ghidra GUI。
- r2pipe 固定安装到 `~/.local/share/pwndbg-python`，专供便携版 Pwndbg 使用，不污染系统 Python。
- 自动生成 Pwndbg 的 `ghidra` 快捷命令，并以托管区块安全写入 `~/.gdbinit`。
- 脚本主动克隆的源码和 CTF 数据库统一放在 `~/tools`，包管理器自己的标准目录不强行迁移。

全新安装通常占用约 8–12 GiB（不含以后下载的 Docker 镜像），建议预留 15 GiB。
脚本会按缺失内容动态检查空间：完整安装至少 10 GiB，少量补装至少 3 GiB，纯复查至少 1 GiB。


## radare2 与 r2ghidra 安装

当前 r2ghidra 要求 radare2 不低于 6.1.4。脚本不再使用可能过旧的发行版 radare2 包，而是先检查实际版本；不足时按 radare2 官方方式执行：

```bash
git clone --depth 1 https://github.com/radareorg/radare2.git ~/tools/radare2
cd ~/tools/radare2
sh sys/install.sh --install --without-pull
```

新版会安装到 `/usr/local`，通常会优先于旧的 `/usr/bin/r2`。确认版本合格后，再按官方顺序安装 r2ghidra：

```bash
r2pm -U
r2pm -ci r2ghidra
```

第一条更新 r2pm 软件包数据库；第二条清理旧构建缓存，重新编译并安装适配当前 radare2 的 r2ghidra。安装后脚本还会执行 `pdg?`，确认插件能够被真正加载。

手动验证：

```bash
which r2
r2 -v
r2pm -l
r2 -q -c 'pdg?;q' /bin/true
```

看到 `Native Ghidra decompiler plugin` 即表示可用。

## r2ghidra 基本使用

`pdf` 查看当前函数的汇编，`pdg` 查看 r2ghidra 生成的接近 C 代码的反编译结果：

```bash
r2 -AA ./chall
```

进入 radare2 后：

```text
afl          列出函数
s main       跳到 main
pdf          查看当前函数的反汇编
pdg          反编译当前函数
pdga         汇编与反编译对照
pdgj         以 JSON 输出反编译结果
q            退出
```

当前位置还未识别成函数时，先执行 `af`，再执行 `pdg`；分析不完整可执行 `aaa` 后重试。

## 在 Pwndbg 中直接反编译

新版会解决便携版 Pwndbg 与系统 Python 隔离造成的 `Could not import r2pipe python library`：

- 将固定版本的 r2pipe 安装到 `~/.local/share/pwndbg-python`；
- 生成 `~/.local/share/init/gdb/r2ghidra.py`；
- 在 `~/.gdbinit` 中只维护一段带起止标记的配置，不改动其他个人设置；
- 安装完成后用 Pwndbg 批处理模式实际验证 r2pipe、快捷命令和 `pdg`。

Ubuntu、Kali、原生 Linux、WSL 和 Linux 虚拟机的用法相同：

```bash
pwndbg ./chall
```

进入 Pwndbg 后：

```text
start                 启动并停在程序入口附近
ghidra                反编译当前 $pc 所在地址
ghidra &main          反编译 main
ghidra 0x4011d6       反编译指定地址
r2pipe pdg @ main     直接执行原始 r2pipe/r2ghidra 命令
```

排错时依次检查：

```text
pwndbg> pi import r2pipe; print(r2pipe.__file__)
pwndbg> help ghidra
pwndbg> r2pipe pdg?
```

第一条应显示 `~/.local/share/pwndbg-python` 下的路径，第二条应显示快捷命令帮助，第三条应包含 `Native Ghidra decompiler plugin`。`ctx-ghidra` 不是 Pwndbg 官方命令，也不是本项目配置的命令；这里统一使用 `ghidra`。

## 安装位置与 CTF 数据库

脚本主动下载、需要用户直接查看的源码仓库统一放在 `~/tools`：

| 路径 | 内容 | 是否预下载大数据 |
| --- | --- | --- |
| `~/tools/radare2` | radare2 官方源码；编译后的命令安装到 `/usr/local` | 否 |
| `~/tools/pyenv` | 隔离的 Python 2.7.18 源码、版本和运行环境 | 仅 Python 2 运行时 |
| `~/tools/glibc-all-in-one` | glibc-all-in-one v2、libc 包索引和以后下载的 `libs/` | 只更新小型索引 |
| `~/tools/libc-database` | libc 指纹识别和偏移查询脚本；以后下载的数据仍保存在该目录 | 默认不下载全部 libc |

`glibc-all-in-one` 新版不再只是几段 shell 脚本。安装器会从 `~/tools/glibc-all-in-one` 以 editable 方式安装 `glibc-aio` 命令，并执行一次索引更新：

```bash
glibc-aio puts 0x80970 system 0x4f440
glibc-aio download 2.27-3ubuntu1_amd64
glibc-aio ./libc.so.6
```

`libc-database` 保持仓库原生用法：

```bash
cd ~/tools/libc-database
./identify /path/to/libc.so.6
./find puts 809c0
./download id
```

以下目录由对应工具自己管理，故意不塞进 `~/tools`，否则容易破坏升级和插件发现：

| 路径 | 管理者 |
| --- | --- |
| `~/.local/bin` | Pwndbg 用户级启动命令等 |
| `~/.local/share/radare2/r2pm`、radare2 用户插件目录 | r2pm 与 r2ghidra |
| `~/.local/share/pwndbg-python` | 专供便携版 Pwndbg 导入的 r2pipe |
| `~/.local/share/init/gdb`、`~/.gdbinit` 托管区块 | `ghidra` 快捷命令桥接配置 |
| `/var/lib/docker` | Docker 镜像、容器和卷 |

SecLists 当前不在默认安装内容中。完整版包含密码、目录、DNS、Fuzzing、Payload 和 WebShell 等大量列表，约 4.5GB，更偏 Web 渗透/SRC，而且在服务器上可能触发安全软件告警；直接加入会明显抬高初始化空间。需要时仍建议统一放进 `~/tools`：

```bash
git clone --depth 1 https://github.com/danielmiessler/SecLists.git ~/tools/SecLists
```

glibc 数据库也不会默认把所有 libc 下载完；只有索引会自动更新，具体版本按题目需要下载，避免环境初始化无谓占用数十 GB。

## 更新

更新后重新运行即可：

```bash
git pull
python3 init.py
```
