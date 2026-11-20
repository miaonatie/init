## 使用

```bash
git clone https://github.com/miaonatie/init.git
cd init
python3 init.py
```

### Python 环境

普通终端默认使用系统 Python，各项目仍在 VS Code 选择自己的 `.venv/bin/python`。
init 的工具依赖与系统包分开：新建工具环境优先复用系统 Python（3.12 或更新），
较旧发行版才用 uv 管理的 3.12；已经能用的环境不会被重建。运行 `ctf_env` 进入工具
环境，`deactivate` 退出。Pwndbg 跟随 GDB，Qiling 保留独立兼容环境。

默认从 APT 安装系统 Python 2，供旧工具使用。Ubuntu 如果没有这个包会跳过；
不再另外编译 pyenv，也不安装 pip2。安装后可以用 `python3 init.py --check` 检查。

Kali 的 `/bin` 指向 `/usr/bin`，终端列出两个 `python` 路径不代表装了两套。
用 `command -v python` 查看当前实际使用的入口。init 不需要 `~/.local/bin/python3.13`；
它只是可选的命令链接。项目若直接使用 `~/.local/share/uv/python` 下的解释器，
可以移除不用的链接，但不要卸载项目仍在使用的 uv 运行时。
