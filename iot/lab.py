#!/usr/bin/env python3
"""Persistent FirmAE lab; compatible with the Ubuntu 18.04 host Python."""
import argparse
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parent


def run(command, capture=False, check=True, timeout=None):
    return subprocess.run(command, stdout=subprocess.PIPE if capture else None,
                          stderr=subprocess.PIPE if capture else None,
                          universal_newlines=True, encoding="utf-8", errors="replace",
                          check=check, timeout=timeout)


class Lab:
    def __init__(self, root=ROOT):
        self.root = root
        self.config = json.loads((root / "config.json").read_text())
        self.source = Path(self.config["firmae"])
        self.revision = self.config["revision"]
        fingerprint = hashlib.sha256(self.revision.encode())
        for name in ("Dockerfile", "entrypoint.sh"):
            fingerprint.update((root / name).read_bytes())
        self.image = "init-firmae:" + fingerprint.hexdigest()[:16]
        self.name = "init-firmae-" + str(os.getuid())
        self.docker = None

    def connect(self):
        if self.docker is not None:
            return True
        if not shutil.which("docker"):
            return False
        candidates = [["docker"]]
        if os.geteuid() != 0 and shutil.which("sudo"):
            candidates.append(["sudo", "-n", "docker"])
        for command in candidates:
            try:
                if run(command + ["info"], capture=True, check=False, timeout=10).returncode == 0:
                    self.docker = command
                    return True
            except subprocess.TimeoutExpired:
                continue
        return False

    def require_docker(self):
        if not self.connect():
            raise RuntimeError("Docker daemon unavailable. Start Docker Engine/WSL integration; "
                               "if permission is denied run sudo -v, then retry (no sudo firmae needed).")

    def dc(self, args, **kwargs):
        self.require_docker()
        return run(self.docker + args, **kwargs)

    def source_ready(self):
        return (self.source / ".git").exists() and run(
            ["git", "-C", str(self.source), "cat-file", "-e", self.revision + "^{commit}"],
            capture=True, check=False, timeout=15).returncode == 0

    def image_ready(self):
        return self.dc(["image", "inspect", self.image], capture=True, check=False).returncode == 0

    def check(self):
        if not self.source_ready():
            raise RuntimeError("Pinned FirmAE source missing; rerun python3 init.py --iot")
        if not self.connect():
            print("FirmAE source prepared; Docker image/runtime pending (daemon unavailable).")
            return 3
        if not self.image_ready():
            raise RuntimeError("FirmAE image missing/outdated; run firmae build")
        print("FirmAE pinned source and container image ready: " + self.image)
        return 0

    def build(self, if_available=False):
        if platform.machine().lower() not in ("x86_64", "amd64"):
            raise RuntimeError("This FirmAE image requires an x86_64 Linux host.")
        if not self.source_ready():
            raise RuntimeError("Pinned FirmAE source missing; rerun python3 init.py --iot")
        if if_available and not self.connect():
            print("Docker daemon unavailable; deferred image build. Run firmae build later.")
            return 3
        self.require_docker()
        if self.image_ready():
            print("FirmAE image already built: " + self.image)
            return 0
        # Export the pinned tree, not the user's working tree or generated images.
        with tempfile.TemporaryDirectory(prefix="init-firmae-") as directory:
            context = Path(directory)
            source = context / "FirmAE"
            source.mkdir()
            archive = context / "source.tar"
            run(["git", "-C", str(self.source), "archive", "--format=tar",
                 "--output", str(archive), self.revision])
            run(["tar", "-xf", str(archive), "-C", str(source)])
            archive.unlink()
            for name in ("Dockerfile", "entrypoint.sh"):
                shutil.copy2(str(self.root / name), str(context / name))
            self.dc(["build", "--tag", self.image, str(context)])
        self.dc(["run", "--rm", "--network", "none", "--entrypoint", "bash", self.image,
                 "-ec", "python3 -c 'import binwalk, psycopg2, magic'; "
                 "qemu-system-mipsel --version; test -s binaries/vmlinux.mipsel.4"])
        print("FirmAE image built and dependency smoke test passed.")
        return 0

    def inspect_container(self):
        result = self.dc(["inspect", self.name], capture=True, check=False)
        return json.loads(result.stdout)[0] if result.returncode == 0 else None

    def start(self):
        self.require_docker()
        if not self.image_ready():
            raise RuntimeError("Run firmae build first")
        container = self.inspect_container()
        if container:
            configured = container["Config"]["Image"]
            if configured != self.image:
                raise RuntimeError("Container uses an older image; run firmae stop, then firmae recreate "
                                   "(database/images/scratch volumes are preserved).")
            if not container["State"]["Running"]:
                self.dc(["start", self.name])
        else:
            self.dc(["run", "-d", "--name", self.name, "--privileged",
                     "--mount", "type=bind,source=/dev,target=/dev",
                     "--mount", "type=volume,source=" + self.name + "-db,target=/var/lib/postgresql",
                     "--mount", "type=volume,source=" + self.name + "-images,target=/opt/FirmAE/images",
                     "--mount", "type=volume,source=" + self.name + "-scratch,target=/opt/FirmAE/scratch",
                     "--mount", "type=volume,source=" + self.name + "-firmwares,target=/firmwares",
                     "-p", "127.0.0.1:18080:18080", self.image])
        for _ in range(30):
            if self.dc(["exec", self.name, "test", "-f", "/tmp/init-firmae-ready"],
                       check=False, capture=True).returncode == 0:
                print("FirmAE running; firmware UI forwarding: firmae web <firmware-ip>")
                return
            state = self.inspect_container()
            if not state or not state["State"]["Running"]:
                self.dc(["logs", "--tail", "30", self.name], check=False)
                raise RuntimeError("FirmAE failed to start; see device/database diagnostics above.")
            time.sleep(0.5)
        raise RuntimeError("FirmAE startup timed out; run firmae logs")

    def require_running(self):
        container = self.inspect_container()
        if not container or not container["State"]["Running"]:
            raise RuntimeError("Run firmae start first")

    def execute(self, args):
        self.require_running()
        flags = ["-i"] + (["-t"] if sys.stdin.isatty() else [])
        return self.dc(["exec"] + flags + [self.name] + args, check=False).returncode

    def emulate(self, mode, brand, filename):
        if not re.fullmatch(r"[A-Za-z0-9_.-]+", brand):
            raise ValueError("Use a simple brand, e.g. dlink, netgear, tplink or auto")
        firmware = Path(filename).expanduser().resolve()
        if not firmware.is_file():
            raise ValueError("Firmware file not found: " + str(firmware))
        digest = hashlib.sha256()
        with firmware.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
        self.start()
        # A safe stable path avoids upstream run.sh's unquoted shell arguments.
        destination = "/firmwares/" + digest.hexdigest() + ".bin"
        self.dc(["cp", str(firmware), self.name + ":" + destination])
        return self.execute(["./run.sh", mode, brand, destination])

    def doctor(self):
        status = self.check()
        print("Host: " + platform.machine() + "; container: " + self.name)
        print("Runtime needs Linux TUN, loop devices and privileged local Docker.")
        print("WSL2: keep files in Linux home; Docker Desktop devices may differ from WSL's.")
        if status:
            return status
        # Read-only check in an existing container, never start one from doctor.
        container = self.inspect_container()
        if not container or not container["State"]["Running"]:
            print("Container stopped/not created; run firmae start to validate TUN/loop/database.")
            return 0
        return self.execute(["bash", "-ec", "test -c /dev/net/tun; losetup -f; "
                             "PGPASSWORD=firmadyne psql -h 127.0.0.1 -U firmadyne -d firmware "
                             "-tAc 'SELECT COUNT(*) FROM image;'"])


def main(argv=None):
    parser = argparse.ArgumentParser(description="FirmAE emulation/debug lab (iot-help for examples)")
    parser.add_argument("command", nargs="?", default="help",
                        choices=("help", "build", "check", "doctor", "start", "stop", "recreate",
                                 "shell", "logs", "web", "-c", "-r", "-d", "-b"))
    parser.add_argument("arguments", nargs="*")
    parser.add_argument("--if-available", action="store_true", help=argparse.SUPPRESS)
    # Keep familiar FirmAE mode flags, but let argparse handle --help normally.
    values = list(sys.argv[1:] if argv is None else argv)
    if values and values[0] in ("-c", "-r", "-d", "-b"):
        values.insert(0, "--")
    args = parser.parse_args(values)
    if args.command == "help":
        sys.stdout.buffer.write((ROOT / "USAGE.md").read_bytes())
        return 0
    lab = Lab()
    if args.command == "build":
        return lab.build(args.if_available)
    if args.command == "check":
        return lab.check()
    if args.command == "doctor":
        return lab.doctor()
    if args.command == "start":
        lab.start()
    elif args.command == "stop":
        lab.dc(["stop", lab.name])
    elif args.command == "recreate":
        container = lab.inspect_container()
        if container and container["State"]["Running"]:
            raise RuntimeError("Stop the lab first: firmae stop")
        if container:
            lab.dc(["rm", lab.name])  # No -v: persistent volumes survive.
        lab.start()
    elif args.command == "shell":
        return lab.execute(["bash"])
    elif args.command == "logs":
        lab.dc(["logs", "--tail", "100", lab.name])
    elif args.command == "web":
        if len(args.arguments) not in (1, 2):
            parser.error("web requires <firmware-ip> [http-port]")
        address = str(ipaddress.IPv4Address(args.arguments[0]))
        port = int(args.arguments[1]) if len(args.arguments) == 2 else 80
        if not 1 <= port <= 65535:
            parser.error("port must be between 1 and 65535")
        print("Open http://127.0.0.1:18080 (forwarding remains active until firmae stop)", flush=True)
        return lab.execute(["socat", "TCP-LISTEN:18080,reuseaddr,fork", "TCP:" + address + ":" + str(port)])
    elif args.command in ("-c", "-r", "-d", "-b"):
        if len(args.arguments) != 2:
            parser.error("mode requires <brand> <firmware-file>")
        return lab.emulate(args.command, *args.arguments)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
        print("FirmAE: " + str(exc), file=sys.stderr)
        sys.exit(1)
