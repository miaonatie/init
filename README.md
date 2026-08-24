# init v3.9

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
- r2ghidra 使用官方 r2pm 用户级安装，不需要安装完整的 Ghidra GUI。

全新安装通常占用约 8–12 GiB（不含以后下载的 Docker 镜像），建议预留 15 GiB。
脚本会按缺失内容动态检查空间：完整安装至少 10 GiB，少量补装至少 3 GiB，纯复查至少 1 GiB。


## r2ghidra 安装与验证

脚本按官方顺序执行：

```bash
r2pm -U
r2pm -ci r2ghidra
```

第一条更新 r2pm 软件包数据库；第二条清理旧构建缓存，重新编译并安装适配当前 radare2 的 r2ghidra。安装后脚本还会执行 `pdg?`，确认插件能够被真正加载。

手动验证：

```bash
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

## 更新

更新后重新运行即可：

```bash
git pull
python3 init.py
```
