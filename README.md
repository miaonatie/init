## 安装

```bash
git clone https://github.com/miaonatie/init.git
cd init
/usr/bin/python3 init.py
```

脚本通过 APT 将 Python 库安装到系统 Python。只检查解释器和库时，运行 `/usr/bin/python3 init.py --check-python`。检查会跳过未安装的可选库，必需库导入失败时返回非零退出码。
