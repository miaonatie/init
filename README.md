# init v3.8

Ubuntu 24.04+ / 最新 Kali 的一次性命令行 CTF 环境初始化工具。

## 使用

```bash
git clone https://github.com/miaonatie/init.git
cd init
python3 init.py
```

脚本分为 4 个阶段：环境检查、系统基础环境、CTF 工具链、最终验证。
系统软件包按系统开发、日常 CLI、CTF CLI、32 位支持分批处理，失败定位和重试更快。
已有的软件会先检查并跳过；可重复运行。
APT 会先排除当前软件源中不存在的包，避免一个无效包拖慢整批安装；十六进制查看统一使用 `xxd`。

- Python 3 工具直接安装到系统 Python（`--break-system-packages`）。
- Python 2.7 通过 pyenv 隔离安装，仅提供 `python2` / `pip2`，不会改变系统 `python`。
- Docker 安装 Engine、Buildx 和 Compose 插件；默认使用 `sudo docker ...`。

全新安装通常占用约 8–12 GiB（不含以后下载的 Docker 镜像），建议预留 15 GiB。
脚本会按缺失内容动态检查空间：完整安装至少 10 GiB，少量补装至少 3 GiB，纯复查至少 1 GiB。

更新后重新运行即可：

```bash
git pull
python3 init.py
```
