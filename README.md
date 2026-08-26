# init v3.21

Ubuntu 24.04+ / 最新 Kali 的一次性命令行 CTF 环境初始化工具。

## 使用

```bash
git clone https://github.com/miaonatie/init.git
cd init
python3 init.py
```

不要使用 `sudo python3 init.py`；需要系统权限时脚本会自行调用 `sudo`，r2ghidra 等用户级工具会安装到当前用户目录。

脚本分为 4 个阶段：环境检查、系统基础环境、CTF 工具链、最终验证。
系统软件包按系统开发、日常 CLI、CTF CLI、32 位支持分批处理，失败定位更快。
默认是快速幂等模式：已有且通过实际探测的软件直接跳过，不再每次更新 Node、Rust、Pwndbg 和数据库仓库；需要主动更新时使用 `python3 init.py --update`。
每项安装都先检查包、命令或源码是否存在，再进行必要的轻量启动探测；同一轮中的 Docker、Node、Rust、r2ghidra、r2pipe、Pwndbg 和 glibc-aio 探测会复用结果。只有缺失、版本不兼容或实际不可用的组件才进入对应修复流程。
APT 会先排除当前软件源中不存在的包，避免一个无效包拖慢整批安装；十六进制查看统一使用 `xxd`。
网络操作最多只额外重试一次并等待 2 秒；pip、npm 等使用各自受限的下载重试，不会从头重复执行整条安装流程。APT 大批量安装失败时先按 8 个包分块定位，只有失败小块才逐包处理。

- Python 3 工具直接安装到系统 Python（`--break-system-packages`）。
- Python 2.7 通过 pyenv 隔离安装，分别验证运行时、pip 模块和 `pip2` 命令；检测到 Debian/Kali 禁用系统 Python 2 的 ensurepip 时会直接切换到 pyenv，不再做无效重试。
- Node.js 通过 `~/tools/nvm` 管理，安装当前 LTS、npm、Corepack、pnpm 和 Yarn，同时配置 Bash/Zsh；Node 已可用但包管理器缺失时只修复 Corepack/pnpm/Yarn，不重复安装 Node。
- Rust 通过官方 rustup 安装 stable、Cargo、rustfmt 和 Clippy，同时配置 Bash/Zsh。
- Docker 安装 Engine、Buildx 和 Compose 插件；默认使用 `sudo docker ...`。
- radare2 会验证最低版本 6.1.4；发行版软件源版本过旧时，自动从官方 Git 源码安装到 `/usr/local`。
- r2ghidra 使用官方 r2pm 用户级安装，不需要安装完整的 Ghidra GUI。
- r2pipe 固定安装到 `~/.local/share/pwndbg-python`，桥接脚本会按绝对路径装载它，不依赖便携版 Pwndbg 会覆盖的 `PYTHONPATH`。
- 自动生成 init 自定义的 `ghidra` 快捷命令和 `pwndbg-ctf` 启动器；优先复用 Pwndbg 官方的有状态 `r2pipe`，异常时自动降级到外部 radare2，兼容新版便携版 Pwndbg。
- 对主要命令执行实际启动探测，不再把“文件存在”误判成“工具可用”；Python/Ruby 命令损坏时会重新安装。
- 脚本主动克隆的源码和 CTF 数据库统一放在 `~/tools`，包管理器自己的标准目录不强行迁移。

全新安装通常占用约 10–14 GiB（不含以后下载的 Docker 镜像），建议预留 18 GiB。
脚本会按缺失内容动态检查空间：完整安装至少 12 GiB，少量补装至少 4 GiB，纯复查至少 1 GiB。

## 语言与构建环境

默认配置的是 CTF、Pwn、逆向和 Misc 常用语言环境，不额外安装与此用途关系较小的大型 SDK：

| 类别 | 已配置内容 | 主要用途 |
| --- | --- | --- |
| C/C++ | GCC、G++、Clang、LLVM、LLD、GNU ld、32 位 multilib | 编译题目、Exploit 辅助程序和逆向工具 |
| 汇编 | NASM、YASM、GNU binutils | x86/x86-64 汇编、链接、反汇编 |
| Python 3 | 系统 Python 3、pip、IPython、pwntools 等 CTF 库 | 当前脚本和主力 CTF 开发环境 |
| Python 2 | `~/tools/pyenv` 中的 2.7.18、`python2`、`pip2` | 仅运行旧 EXP、旧题目脚本 |
| Node.js | `~/tools/nvm` 中的当前 LTS、npm、Corepack、pnpm、Yarn | JavaScript/TypeScript 工具、Web 与部分 CTF 脚本 |
| Rust | rustup stable、Cargo、rustfmt、Clippy | Rust 题目、逆向辅助工具和高性能脚本 |
| Ruby | Ruby、RubyGems、Bundler、one_gadget、seccomp-tools、zsteg | Pwn 和 Misc 工具 |
| Java | 默认 JDK、JRE、`java`、`javac` | APK/Java 逆向及需要 JVM 的工具 |
| Perl | Perl | libc-database、系统脚本和文本处理 |
| Shell | Bash、Zsh、ShellCheck、bash-completion | 自动化脚本和日常终端环境 |
| 构建系统 | make、Autoconf、Automake、Libtool、CMake、Ninja、Meson | 编译 radare2、r2ghidra 和其他源码工具 |

Go、PHP、Lua 和 .NET 当前不默认安装：需要时可单独安装或使用 Docker。

### Node.js、pnpm 与 Yarn

Node 使用固定版本的 NVM 安装器，避免安装流程随远端脚本无提示变化；首次安装或 `--update` 模式会使用当前 LTS，并准备最新版 pnpm 和稳定版 Yarn。脚本会分别探测 Node/npm 运行时和 Corepack/pnpm/Yarn：后者单独损坏时不会触发 `nvm install`。NVM 安装锁最多等待 20 秒，并允许 NVM 自动接管超过 10 分钟的遗留锁，避免异常中断后再次运行卡住 600 秒。默认重复运行只做可用性检查：

脚本会先创建自定义的 `~/tools/nvm`。这一步不能省略：NVM 安装器在预设的 `NVM_DIR` 不存在时会直接退出。

```bash
nvm --version
node --version
npm --version
corepack --version
pnpm --version
yarn --version
```

常用更新和切换命令：

```bash
nvm install --lts
nvm alias default 'lts/*'
nvm use --lts
corepack install --global pnpm@latest
corepack install --global yarn@stable
```

脚本会以带起止标记的托管区块更新 `~/.bashrc` 和 `~/.zshrc`，不会覆盖原有配置。安装结束后新开终端即可使用；当前 Zsh 会话可执行 `source ~/.zshrc`，Bash 则执行 `source ~/.bashrc`。

### Rust 与 Cargo

Rust 使用官方 rustup 的默认 profile 和 stable 工具链，默认 profile 已包含常用开发组件，脚本还会显式确认 rustfmt 与 Clippy。默认重复运行不会再执行耗时的 `rustup update`；若 stable、Cargo 已可用而只缺 rustfmt/Clippy，仅修复组件，只有核心运行时缺失、损坏或使用 `--update` 时才更新整套工具链：

```bash
rustup show
rustc --version
cargo --version
rustfmt --version
cargo clippy --version
```

创建项目和更新 stable：

```bash
cargo new demo
cd demo
cargo run
rustup update stable
```

Rustup 使用自己的标准目录 `~/.rustup` 和 `~/.cargo`，避免破坏其升级、工具链覆盖及 Cargo 命令发现机制。

### Python 2 与 pip2

`pip2` 是一个稳定包装命令，内部始终调用同一套 Python 2：

```text
/usr/local/bin/python2  -> 检测到的 Python 2.7（默认是 ~/tools/pyenv/.../python2.7）
/usr/local/bin/pip2     -> 同一个 Python 2.7 执行 -m pip
```

重复运行会比较两个符号链接和 `pip2` 包装脚本的实际目标；内容与权限正确时不会再次执行 `ln` 或 `install`。

这样即使 pyenv 只生成 `pip`、没有生成名为 `pip2` 的可执行文件，也不会再出现 `command not found`。检查：

```bash
python2 --version
python2 -m pip --version
pip2 --version
```

Python 2 已停止维护，很多新软件包不再兼容，安装旧 EXP 依赖时通常需要锁定旧版本，例如：

```bash
pip2 install 'requests<2.28'
python2 old_exp.py
```


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

新版会同时解决便携版 Pwndbg 与系统 Python 隔离造成的 `Could not import r2pipe python library`，以及便携版启动器使用 `-nx`、不会读取 `~/.gdbinit` 的问题。Pwndbg 的启动器会重建 `PYTHONPATH`，所以仅在外部设置该变量并不可靠。已有 Pwndbg 不再只检查命令名，而会实际启动其 Python 并导入 `pwndbg`；损坏时才重新运行安装器：

- 将固定版本的 r2pipe 安装到 `~/.local/share/pwndbg-python`；
- 生成 `~/.local/share/init/gdb/r2ghidra.py`，先正常导入 r2pipe，失败时再从准确的包目录或单文件模块路径装载并注册到调试器 Python；
- `ghidra` 优先调用 Pwndbg 官方的有状态 `r2pipe`，同一调试目标只做一次完整分析，后续调用更快；
- 如果 Pwndbg 内部导入仍因未来版本布局变化而失败，`ghidra` 会直接启动外部 `r2`，并根据 `/proc/PID/maps` 自动选择主程序或共享库及其 PIE 基址；
- 安装 `/usr/local/bin/pwndbg-ctf`，用 `-x` 显式加载桥接脚本，不再依赖会被 Pwndbg 覆盖的 `PYTHONPATH`；
- 在 Bash/Zsh 配置中添加托管的 `pwndbg` 函数，使日常的 `pwndbg ./chall` 自动走上述启动器；
- `~/.gdbinit` 仍保留一段带起止标记的配置，供普通系统 GDB 使用，不改动其他个人设置；
- 安装完成后临时编译一个很小的测试 ELF，同时验证 Pwndbg 内部 `import r2pipe`、原生 `r2pipe` 命令和 `ghidra &main` 的真实反编译；只有外部 r2 兜底成功不再被判为完整成功，原生 r2pipe 异常时会强制修复一次。

Ubuntu、Kali、原生 Linux、WSL 和 Linux 虚拟机的用法相同：

```bash
source ~/.zshrc             # Bash 用户改为 source ~/.bashrc
type pwndbg                 # 应显示 pwndbg 是 shell function
pwndbg ./chall
```

进入 Pwndbg 后：

```text
start                 启动并停在程序入口附近
ghidra                反编译当前 $pc 所在地址
ghidra &main          反编译 main
ghidra 0x4011d6       反编译指定地址
r2pipe aaa            使用 Pwndbg 原生命令进行完整分析
r2pipe pdg @ sym.main 使用 Pwndbg 原生 r2pipe/r2ghidra 反编译
```

`ghidra` 输出的是接近 C 的反编译结果（不是普通反汇编）。第一次会运行完整分析，通常较慢；同一个 Pwndbg 会话中的后续调用会复用 r2pipe 进程。这里的 `ghidra` 是 init 提供的快捷命令，不是新版 Pwndbg 原生命令；新版 Pwndbg 对 r2ghidra 的原生入口是 `r2pipe`。

新版 Pwndbg 另有 `di install ghidra`、`di connect` 和 `decomp`，那是基于 decomp2dbg、需要完整 Ghidra GUI 和插件服务器的另一套官方集成，不等同于轻量的 r2ghidra。旧教程中的 `ctx-ghidra`、`set r2decompiler radare2` 和 `set context-ghidra` 已不适用于当前新版。

排错时依次检查：

```bash
r2 -q -c 'pdg?;q' /bin/true
pwndbg-ctf -q --batch /bin/true \
  -ex "pi import r2pipe; print(r2pipe.__file__)" \
  -ex 'r2pipe pdg?' \
  -ex 'help ghidra'
```

第一条和 Pwndbg 中的 `r2pipe pdg?` 都应包含 `Native Ghidra decompiler plugin`，Python 输出应位于 `~/.local/share/pwndbg-python`，`help ghidra` 应显示 `Decompile an address with Pwndbg, radare2 and r2ghidra`。重新执行 `python3 init.py` 时还会进行一次真实反编译。

## 安装位置与 CTF 数据库

脚本主动下载、需要用户直接查看的源码仓库统一放在 `~/tools`：

| 路径 | 内容 | 是否预下载大数据 |
| --- | --- | --- |
| `~/tools/radare2` | radare2 官方源码；编译后的命令安装到 `/usr/local` | 否 |
| `~/tools/pyenv` | 隔离的 Python 2.7.18 源码、版本和运行环境 | 仅 Python 2 运行时 |
| `~/tools/nvm` | NVM、Node.js LTS、npm、Corepack、pnpm 和 Yarn | 仅语言运行时与包管理器 |
| `~/tools/glibc-all-in-one` | glibc-all-in-one v2、libc 包索引和以后下载的 `libs/` | 只更新小型索引 |
| `~/tools/libc-database` | libc 指纹识别和偏移查询脚本；以后下载的数据仍保存在该目录 | 默认不下载全部 libc |

`glibc-all-in-one` 新版不再只是几段 shell 脚本。首次安装、Python 运行时损坏或 `--update` 模式会按上游 v2 的方式安装依赖和 editable 包；如果运行时健康但只有 libc 索引缺失，则只更新索引，不重复执行 pip：

```bash
cd ~/tools/glibc-all-in-one
python3 -m pip install --upgrade pyelftools zstandard
python3 -m pip install --editable .
```

随后生成 `/usr/local/bin/glibc-aio` 稳定包装命令，验证 Python 模块、`--version`、镜像列表和本地包索引。上游 v2 的 `list`、`libs/` 使用相对工作目录；包装命令会自动切换到仓库目录，同时把调用位置中真实存在的相对文件转换为绝对路径，因此可以直接在任意目录运行：

```bash
glibc-aio --version
glibc-aio mirror list
glibc-aio puts 0x80970 system 0x4f440
glibc-aio download 2.27-3ubuntu1_amd64
glibc-aio ./libc.so.6
```

`libc-database` 会配置四个可从任意目录使用的包装命令；默认重复运行不会拉取仓库，`--update` 时才执行快进更新：

```bash
libc-db-identify ./libc.so.6
libc-db-find puts 809c0
libc-db-download id
libc-db-dump id
```

原仓库脚本仍保留在 `~/tools/libc-database`，没有默认下载全部 libc 数据。

以下目录由对应工具自己管理，故意不塞进 `~/tools`，否则容易破坏升级和插件发现：

| 路径 | 管理者 |
| --- | --- |
| `~/.local/bin` | Pwndbg 用户级启动命令等 |
| `~/.local/share/radare2/r2pm`、radare2 用户插件目录 | r2pm 与 r2ghidra |
| `~/.local/share/pwndbg-python` | Pwndbg 桥接按绝对路径加载的 r2pipe 快路径 |
| `~/.local/share/init/gdb`、`~/.gdbinit` 托管区块 | 带 r2pipe 快路径和外部 r2 兜底的 `ghidra` 命令 |
| `/usr/local/bin/pwndbg-ctf`、Bash/Zsh 托管区块 | 显式加载桥接脚本的便携版 Pwndbg 启动入口 |
| `~/.cargo`、`~/.rustup` | Cargo 命令、Rust stable 工具链及 rustup 元数据 |
| `/usr/local/bin/glibc-aio`、`/usr/local/bin/libc-db-*` | 数据库工具的稳定全局包装命令 |
| `/var/lib/docker` | Docker 镜像、容器和卷 |

SecLists 当前不在默认安装内容中。完整版包含密码、目录、DNS、Fuzzing、Payload 和 WebShell 等大量列表，约 4.5GB，更偏 Web 渗透/SRC，而且在服务器上可能触发安全软件告警；直接加入会明显抬高初始化空间。需要时仍建议统一放进 `~/tools`：

```bash
git clone --depth 1 https://github.com/danielmiessler/SecLists.git ~/tools/SecLists
```

glibc 数据库也不会默认把所有 libc 下载完；只有索引会自动更新，具体版本按题目需要下载，避免环境初始化无谓占用数十 GB。

## 重复运行与更新

普通重复运行用于补齐缺失工具、修复配置并完成验证，速度更快：

```bash
git pull
python3 init.py
```

健康组件会直接跳过；检测到“包已安装但实际不可用”时只执行一次针对性修复，例如重新安装损坏的 Docker CE 包、修复 Rust 组件、重建 Pwndbg 或更新 glibc-aio 索引。相同的包装脚本、Shell 托管区块和符号链接不会重复写入。

需要主动更新托管内容时：

```bash
python3 init.py --update
```

`--update` 会刷新 Node.js LTS/Corepack/pnpm/Yarn、Rust stable、Pwndbg、glibc-all-in-one 和 libc-database，然后进行完整验证。它不会执行 `apt full-upgrade`、`autoremove`，也不会在现有 radare2 已满足 r2ghidra 版本要求时重新编译 radare2。
