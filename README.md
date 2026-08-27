# init v3.22

面向 Ubuntu 24.04+ 和 Kali Linux/WSL 的 CTF 工作站初始化工具。

## 使用

```bash
git clone https://github.com/miaonatie/init.git
cd init
python3 init.py
```

脚本会在需要系统权限时自行调用 `sudo`。不要运行 `sudo python3 init.py`，否则无法可靠判断用户级工具和配置文件应该属于谁。

- 普通用户运行：用户级内容写入当前用户的 `~`，例如 `~/.vimrc`、`~/.zshrc`、`~/.oh-my-zsh` 和 `~/tools`。
- 直接登录 root 后运行：用户级内容写入 `/root`。
- APT 软件包、Docker 和 `/usr/local/bin` 命令是系统级安装。

默认模式会先做可用性检查，健康组件不会联网、重装或重写相同配置。需要更新脚本管理的 Git 仓库和语言工具链时使用：

```bash
python3 init.py --update
```

## HyFetch 和后端

脚本安装并验证：

- `hyfetch`：彩色系统信息前端。
- `neowofetch`：HyFetch 自带、仍在维护的 Neofetch 兼容实现。
- `fastfetch`：优先从发行版 APT 安装；APT 没有时使用官方 GitHub `.deb`，并校验包名和架构。

```bash
hyfetch
hyfetch --backend fastfetch
neowofetch
fastfetch
```

## Vim

脚本保留原有 `~/.vimrc`，只维护一个带边界标记的基础配置块，包括：

```vim
set tabstop=4
set shiftwidth=4
set softtabstop=4
set expandtab
set autoindent
```

同时启用行号、搜索高亮、智能缩进、语法高亮和文件类型缩进。可以继续使用 `vim ~/.vimrc` 添加个人配置；脚本复跑不会覆盖块外内容。

## Oh My Zsh

脚本从官方仓库安装 `~/.oh-my-zsh`，保留并合并现有 `.zshrc`，启用：

```text
git zsh-autosuggestions z extract web-search zsh-syntax-highlighting
```

`zsh-syntax-highlighting` 固定放在最后加载，并配置：

```zsh
alias py='python'
```

脚本还会把当前运行用户的默认 shell 设置为 zsh。安装结束后执行下面的命令立即进入，或重新打开终端：

```bash
exec zsh
```
