"""Execute minimal foreign ELF programs; optional real FirmAE device/DB/extraction QA.

Run after --iot: python3 tests/smoke_iot.py [--firmae]
Uses only synthetic benign programs and a generated SquashFS filesystem.
"""
from pathlib import Path
import os
import shutil
import struct
import subprocess
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import init


def minimal_elf(arch):
    """A statically linked ELF that exits 42, without cross compiler dependencies."""
    wide = arch == "aarch64"
    endian = ">" if arch == "mips" else "<"
    machine, flags, instructions = {
        "mips": (8, 0x50001001, [0x24020FA1, 0x2404002A, 0x0000000C]),
        "mipsel": (8, 0x50001001, [0x24020FA1, 0x2404002A, 0x0000000C]),
        "arm": (40, 0x5000000, [0xE3A07001, 0xE3A0002A, 0xEF000000]),
        "aarch64": (183, 0, [0xD2800BA8, 0xD2800540, 0xD4000001]),
    }[arch]
    ident = b"\x7fELF" + bytes([2 if wide else 1, 2 if endian == ">" else 1, 1, 0]) + bytes(8)
    offset = 120 if wide else 84
    size = offset + len(instructions) * 4
    if wide:
        header = struct.pack(endian + "HHIQQQIHHHHHH", 2, machine, 1, 0x400000 + offset,
                             64, 0, flags, 64, 56, 1, 0, 0, 0)
        segment = struct.pack(endian + "IIQQQQQQ", 1, 5, 0, 0x400000, 0x400000, size, size, 4096)
    else:
        header = struct.pack(endian + "HHIIIIIHHHHHH", 2, machine, 1, 0x400000 + offset,
                             52, 0, flags, 52, 32, 1, 0, 0, 0)
        segment = struct.pack(endian + "IIIIIIII", 1, 0, 0x400000, 0x400000, size, size, 5, 4096)
    return ident + header + segment + struct.pack(endian + "I" * len(instructions), *instructions)


def exercise_qemu_qiling(qiling=True):
    b = init.Bootstrap()
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        for arch in ("mips", "mipsel", "arm", "aarch64"):
            binary = root / (arch + ".elf")
            binary.write_bytes(minimal_elf(arch))
            binary.chmod(0o755)
            for suffix in ("", "-static"):
                result = subprocess.run(["qemu-" + arch + suffix, str(binary)], timeout=20)
                assert result.returncode == 42, (arch, suffix, result.returncode)
            static = b.qemu_static_command(arch)
            assert static, "no genuine static QEMU for " + arch
            # Prove the emulator runs after copying into a rootfs with no host libraries.
            if os.geteuid() == 0:
                shutil.copy2(static, str(root / "qemu-run"))
                result = subprocess.run(["chroot", str(root), "/qemu-run", "/" + binary.name], timeout=20)
                assert result.returncode == 42, ("chroot", arch, result.returncode)
            if not qiling:
                continue
            # Load an ELF and emulate a real exit syscall through Qiling's OS layer.
            subprocess.run(["qiling-python", "-c",
                "from qiling import Qiling; import sys; "
                "q=Qiling([sys.argv[1]], sys.argv[2]); q.run(); "
                "assert q.os.exit_code == 42, q.os.exit_code", str(binary), str(root)],
                check=True, timeout=30)
        print("PASS: MIPS LE/BE, ARM and AArch64 ELF execution in QEMU and static/chroot" +
              (" and Qiling" if qiling else ""))


def exercise_squashfs():
    b = init.Bootstrap()
    assert b.find_usable_command(["unsquashfs"], init.IOT_PROBES["unsquashfs"]), b._probe_errors
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        source = root / "source"
        source.mkdir()
        (source / "marker").write_text("init-squashfs-ok")
        image, output = root / "fixture.squashfs", root / "output"
        subprocess.run(["mksquashfs", str(source), str(image), "-noappend", "-processors", "1"],
                       check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30)
        subprocess.run(["unsquashfs", "-d", str(output), str(image)],
                       check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30)
        assert (output / "marker").read_text() == "init-squashfs-ok"
    print("PASS: SquashFS version detection, image creation and actual extraction")


def exercise_firmae():
    subprocess.run(["firmae", "start"], check=True, timeout=60)
    try:
        subprocess.run(["firmae", "doctor"], check=True, timeout=30)
        # Validate actual loop partitioning, mounting, PostgreSQL and Python Binwalk scan API.
        script = r"""set -euo pipefail
cd /opt/FirmAE
mkdir -p /tmp/fixture-root/etc /tmp/fixture-out
echo init-iot-ok > /tmp/fixture-root/etc/marker
mksquashfs /tmp/fixture-root /tmp/fixture.squashfs -noappend -processors 1 >/dev/null
python3 - <<'PY'
import binwalk
modules = binwalk.scan('/tmp/fixture.squashfs', signature=True, quiet=True)
assert any('Squashfs' in result.description for module in modules for result in module.results)
PY
unsquashfs -d /tmp/fixture-out/rootfs /tmp/fixture.squashfs >/dev/null
grep -qx init-iot-ok /tmp/fixture-out/rootfs/etc/marker
truncate -s 32M /tmp/loop-fixture.raw
printf 'o\nn\np\n1\n\n\nw\n' | fdisk /tmp/loop-fixture.raw >/dev/null
device=$(losetup --find --show --partscan /tmp/loop-fixture.raw)
trap 'umount /tmp/fixture-mount 2>/dev/null || true; losetup -d "$device"' EXIT
mkfs.ext2 -F "${device}p1" >/dev/null
mkdir -p /tmp/fixture-mount
mount "${device}p1" /tmp/fixture-mount
echo mounted > /tmp/fixture-mount/marker
grep -qx mounted /tmp/fixture-mount/marker
echo PASS: FirmAE PostgreSQL, Binwalk scan, SquashFS and loop partition/mount
"""
        # Use the same persistent lab and Docker permission selection as the installed launcher.
        import importlib.util
        spec = importlib.util.spec_from_file_location("iot_smoke_lab", init.IOT_RUNTIME / "lab.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        instance = module.Lab()
        assert instance.execute(["bash", "-ec", script]) == 0
    finally:
        subprocess.run(["firmae", "stop"], check=True, timeout=60)


if __name__ == "__main__":
    exercise_squashfs()
    exercise_qemu_qiling(qiling="--qemu-only" not in sys.argv)
    if "--firmae" in sys.argv:
        exercise_firmae()
