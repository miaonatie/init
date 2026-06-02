#!/usr/bin/env python3
from pwn import *
from pathlib import Path
import os
import sys

# Usage examples:
#   python3 solve.py
#   python3 solve.py GDB
#   python3 solve.py REMOTE HOST=host PORT=31337
#   python3 solve.py BIN=./chall LIBC=./libc.so.6 LD=./ld-linux-x86-64.so.2
# Pwntools also accepts magic args through environment, e.g. PWNLIB_NOTERM=1.

context.log_level = os.environ.get("LOG", "info")
if os.environ.get("TMUX"):
    context.terminal = ["tmux", "splitw", "-h"]


def kv_args():
    kv, flags = {}, set()
    for item in sys.argv[1:]:
        if "=" in item:
            k, v = item.split("=", 1)
            kv[k.lower()] = v
        else:
            flags.add(item.lower())
    return kv, flags


KV, FLAGS = kv_args()


def arg(name, default=None):
    return KV.get(name.lower()) or getattr(args, name.upper(), None) or default


def flag(name):
    return name.lower() in FLAGS or bool(getattr(args, name.upper(), False))


def is_elf(path: Path) -> bool:
    try:
        return path.is_file() and path.read_bytes()[:4] == b"\x7fELF"
    except Exception:
        return False


def auto_elf() -> Path:
    candidates = [p for p in Path(".").iterdir() if is_elf(p)]
    if not candidates:
        log.error("No ELF found. Use: python3 solve.py BIN=./chall")

    def score(p: Path):
        name = p.name.lower()
        s = 0
        if os.access(p, os.X_OK):
            s -= 30
        if name in {"chall", "challenge", "vuln", "pwn", "main", "baby", "app"}:
            s -= 20
        if name.startswith("libc") or name.startswith("ld-") or ".so" in name:
            s += 80
        return (s, len(name), name)

    return sorted(candidates, key=score)[0]


def auto_file(pred):
    for p in sorted(Path(".").iterdir()):
        if p.is_file() and pred(p.name.lower()):
            return str(p)
    return None


exe_path = Path(arg("bin") or auto_elf())
libc_path = arg("libc") or auto_file(lambda n: n.startswith("libc") and ".so" in n)
ld_path = arg("ld") or auto_file(lambda n: n.startswith("ld-") or n.startswith("ld-linux"))

context.binary = exe = ELF(str(exe_path), checksec=False)
libc = ELF(libc_path, checksec=False) if libc_path else None

HOST = arg("host", "127.0.0.1")
PORT = int(arg("port", 0) or 0)

# Tune this per challenge. For PIE, use pwndbg's start/entry helpers or add a runtime breakpoint.
gdbscript = arg("gdbscript") or """
set pagination off
set disassembly-flavor intel
# break *main
continue
""".strip()


def local_argv():
    if ld_path:
        return [ld_path, "--library-path", ".", str(exe_path)]
    return [str(exe_path)]


def local_env():
    env = {}
    if libc_path and not ld_path:
        env["LD_PRELOAD"] = libc_path
    return env


def start():
    if flag("remote") or flag("r"):
        if not PORT:
            log.error("Remote mode needs: python3 solve.py REMOTE HOST=<host> PORT=<port>")
        return remote(HOST, PORT)
    if flag("gdb") or flag("debug") or flag("d"):
        return gdb.debug(local_argv(), gdbscript=gdbscript, env=local_env())
    return process(local_argv(), env=local_env())


# Convenience wrappers. Use or delete as needed.
def sla(delim, data): return io.sendlineafter(delim, data)
def sa(delim, data): return io.sendafter(delim, data)
def sl(data=b""): return io.sendline(data)
def s(data): return io.send(data)
def ru(delim, drop=False): return io.recvuntil(delim, drop=drop)
def rl(): return io.recvline()
def ia(): return io.interactive()


def pack_addr(x):
    return p64(x) if context.bits == 64 else p32(x)


def leak_addr(data, bits=None):
    bits = bits or context.bits
    width = 8 if bits == 64 else 4
    return u64(data.ljust(8, b"\x00")) if width == 8 else u32(data.ljust(4, b"\x00"))


io = start()

# ---- exploit here ----
# Examples:
# rop = ROP(exe)
# payload = flat({offset: [rop.ret.address, exe.sym.win]})
# sl(payload)

ia()
