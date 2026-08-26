# init v3.18

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
APT 会先排除当前软件源中不存在的包，避免一个无效包拖慢整批安装；十六进制查看统一使用 `xxd`。
网络操作最多只额外重试一次并等待 2 秒；pip、npm 等使用各自受限的下载重试，不会从头重复执行整条安装流程。APT 大批量安装失败时先按 8 个包分块定位，只有失败小块才逐包处理。

- Python 3 工具直接安装到系统 Python（`--break-system-packages`）。
- Python 2.7 通过 pyenv 隔离安装，分别验证运行时、pip 模块和 `pip2` 命令；检测到 Debian/Kali 禁用系统 Python 2 的 ensurepip 时会直接切换到 pyenv，不再做无效重试。
- Node.js 通过 `~/tools/nvm` 管理，安装当前 LTS、npm、Corepack、pnpm 和 Yarn，同时配置 Bash/Zsh；Node 已可用但包管理器缺失时只修复 Corepack/pnpm/Yarn，不重复安装 Node。
- Rust 通过官方 rustup 安装 stable、Cargo、rustfmt 和 Clippy，同时配置 Bash/Zsh。
- Docker 安装 Engine、Buildx 和 Compose 插件；默认使用 `sudo docker ...`。
- radare2 会验证最低版本 6.1.4；发行版软件源版本过旧时，自动从官方 Git 源码安装到 `/usr/local`。
- r2ghidra 使用官方 r2pm 用户级安装，不需要安装完整的 Ghidra GUI。
- r2pipe 固定安装到 `~/.local/share/pwndbg-python`，专供便携版 Pwndbg 使用，不污染系统 Python。
- 自动生成 Pwndbg 的 `ghidra` 快捷命令和 `pwndbg-ctf` 启动器；Bash/Zsh 中的 `pwndbg` 会显式加载桥接脚本，兼容使用 `-nx` 的新版便携版 Pwndbg。
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

Rust 使用官方 rustup 的默认 profile 和 stable 工具链，默认 profile 已包含常用开发组件，脚本还会显式确认 rustfmt 与 Clippy。默认重复运行不会再执行耗时的 `rustup update`，只有环境缺失、损坏或使用 `--update` 时才更新：

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

新版会同时解决便携版 Pwndbg 与系统 Python 隔离造成的 `Could not import r2pipe python library`，以及便携版启动器使用 `-nx`、不会读取 `~/.gdbinit` 的问题：

- 将固定版本的 r2pipe 安装到 `~/.local/share/pwndbg-python`；
- 生成 `~/.local/share/init/gdb/r2ghidra.py`，在 Pwndbg 会话中显式导入隔离目录里的 r2pipe；
- 安装 `/usr/local/bin/pwndbg-ctf`，预先设置专用 `PYTHONPATH` 并用 `-x` 显式加载桥接脚本；
- 在 Bash/Zsh 配置中添加托管的 `pwndbg` 函数，使日常的 `pwndbg ./chall` 自动走上述启动器；
- `~/.gdbinit` 仍保留一段带起止标记的配置，供普通系统 GDB 使用，不改动其他个人设置；
- 安装完成后用 Pwndbg 批处理模式实际验证 r2pipe、快捷命令和 `pdg`。

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
r2pipe pdg @ main     直接执行原始 r2pipe/r2ghidra 命令
```

排错时依次检查：

```bash
pwndbg-ctf -q --batch /bin/true \
  -ex "pi import r2pipe; print('INIT_R2PIPE_OK=' + r2pipe.__file__)" \
  -ex 'help ghidra' \
  -ex 'r2pipe pdg?'
```

第一条应显示 `~/.local/share/pwndbg-python` 下的路径，第二条应显示快捷命令帮助，第三条应包含 `Native Ghidra decompiler plugin`。`ctx-ghidra` 不是 Pwndbg 官方命令，也不是本项目配置的命令；这里统一使用 `ghidra`。

## 安装位置与 CTF 数据库

脚本主动下载、需要用户直接查看的源码仓库统一放在 `~/tools`：

| 路径 | 内容 | 是否预下载大数据 |
| --- | --- | --- |
| `~/tools/radare2` | radare2 官方源码；编译后的命令安装到 `/usr/local` | 否 |
| `~/tools/pyenv` | 隔离的 Python 2.7.18 源码、版本和运行环境 | 仅 Python 2 运行时 |
| `~/tools/nvm` | NVM、Node.js LTS、npm、Corepack、pnpm 和 Yarn | 仅语言运行时与包管理器 |
| `~/tools/glibc-all-in-one` | glibc-all-in-one v2、libc 包索引和以后下载的 `libs/` | 只更新小型索引 |
| `~/tools/libc-database` | libc 指纹识别和偏移查询脚本；以后下载的数据仍保存在该目录 | 默认不下载全部 libc |

`glibc-all-in-one` 新版不再只是几段 shell 脚本。首次安装、环境损坏或 `--update` 模式会按上游 v2 的方式安装依赖和 editable 包：

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
| `~/.local/share/pwndbg-python` | 专供便携版 Pwndbg 导入的 r2pipe |
| `~/.local/share/init/gdb`、`~/.gdbinit` 托管区块 | `ghidra` 快捷命令桥接配置 |
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

需要主动更新托管内容时：

```bash
python3 init.py --update
```

`--update` 会刷新 Node.js LTS/Corepack/pnpm/Yarn、Rust stable、Pwndbg、glibc-all-in-one 和 libc-database，然后进行完整验证。它不会执行 `apt full-upgrade`、`autoremove`，也不会在现有 radare2 已满足 r2ghidra 版本要求时重新编译 radare2。
