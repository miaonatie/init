# IDA MCP on Windows

WSL/Codex connects to:

```text
http://127.0.0.1:13337/mcp
```

PowerShell example:

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
mkdir C:\tools
cd C:\tools
git clone https://github.com/mrexodia/ida-pro-mcp
cd C:\tools\ida-pro-mcp
uv run idalib-mcp --host 127.0.0.1 --port 13337 C:\ctf\babyrop\chall
```

Then in WSL:

```bash
cd /mnt/c/ctf/babyrop
codex
```
