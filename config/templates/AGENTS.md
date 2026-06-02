# CTF pwn workspace

This workspace was created by `pwnnew`.

## Commands

- Local: `python3 payload.py`
- GDB: `python3 payload.py GDB`
- Remote: `python3 payload.py REMOTE HOST=<host> PORT=<port>`
- Select binary: `python3 payload.py BIN=./chall`
- Select libc/ld: `python3 payload.py LIBC=./libc.so.6 LD=./ld-linux-x86-64.so.2`

## Preferences

- Keep original challenge files unchanged.
- Prefer pwntools for scripting and pwndbg for debugging.
- Use `checksec`, `file`, `ldd`, `patchelf`, `ROPgadget`, `ropper`, `one_gadget`, `seccomp-tools`, `libc-database`, and `glibc-all-in-one` when useful.
- Record leaks, offsets, libc version, and important assumptions in the workspace.
- Keep the final exploit readable and reproducible.

## MCP

Default Codex IDA MCP endpoint:

```text
http://127.0.0.1:13337/mcp
```
