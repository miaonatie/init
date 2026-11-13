# IoT 固件分析与复现速查

在 init 仓库中：`git pull && python3 init.py --iot` 仅补装本模块；
`python3 init.py --iot-check` 只检查。正常 `python3 init.py` 也会安装。
随时运行 `iot-help` 查看本页。适用 Ubuntu 18.04+ / Kali；推荐较新的 Kali WSL2。

| 工具 | 用途 | 最短用法 |
| --- | --- | --- |
| Binwalk | 识别/解包固件 | `binwalk firmware.bin`，`binwalk -eM firmware.bin` |
| file / readelf | 判断架构、端序、解释器 | `file squashfs-root/bin/busybox`，`readelf -l squashfs-root/bin/busybox` |
| unsquashfs / UBI 工具 | 提取文件系统 | `unsquashfs rootfs.squashfs`；FirmAE 容器另带 sasquatch、ubireader、jefferson |
| QEMU user | 跑一个异架构 Linux 程序 | `qemu-mipsel -L ./squashfs-root ./squashfs-root/bin/busybox ls` |
| QEMU static + chroot | 程序需要完整的绝对路径布局时运行 | 见下方，需 root |
| QEMU system / FirmAE | 启动内核、rootfs 和 Web 服务 | `firmae -c dlink ./firmware.bin` |
| Qiling | Python 模拟、hook、补系统调用或 NVRAM | `qltool run -f ./squashfs-root/bin/busybox --rootfs ./squashfs-root --args ls` |
| GDB multiarch | 跨架构断点调试 | `gdb-multiarch ./squashfs-root/bin/busybox` |
| tcpdump / curl | 抓包、验证 Web 接口 | `curl -i http://127.0.0.1:18080/` |

## 1. 解包、定位与运行

```bash
mkdir -p ~/iot/lab1
cd ~/iot/lab1
# 把下载的 firmware.bin 放到这里
binwalk firmware.bin
binwalk -eM firmware.bin
find . -type d -name 'squashfs-root'
# 以下示例假定已把提取目录整理成 ./squashfs-root
file squashfs-root/bin/busybox
readelf -l squashfs-root/bin/busybox
rg -n 'password|system\(|popen\(' squashfs-root/etc squashfs-root/www
qemu-mipsel -L ./squashfs-root ./squashfs-root/bin/busybox ls
```

根据 `file` 的输出，MIPS 小端用 `qemu-mipsel`，大端用 `qemu-mips`，
32 位 ARM 用 `qemu-arm`，64 位 ARM 用 `qemu-aarch64`；这些架构均装有 `-static` 版本。
`-L` 指向固件 rootfs，为动态解释器/库提供前缀，不能提供完整的 chroot 语义。
如果程序硬编码 `/etc`、`/www` 等路径，使用工作副本上的 chroot 或 Qiling：

```bash
cp /usr/bin/qemu-mipsel-static ./squashfs-root/
sudo chroot ./squashfs-root /qemu-mipsel-static /bin/busybox ls /
```

这条命令显式调用 QEMU，不依赖 WSL 是否启用了 binfmt_misc。
Binwalk 2/3 的提取器不同；提取失败先看缺失工具提示。
固件是压缩包时先 `unzip`/`7z x`，再选择其中真正的固件镜像。

## 2. QEMU 单程序调试

终端一：

```bash
qemu-mipsel -L ./squashfs-root -g 1234 ./squashfs-root/bin/busybox ls
```

终端二：

```bash
gdb-multiarch ./squashfs-root/bin/busybox
```

GDB 中：

```gdb
set sysroot ./squashfs-root
target remote 127.0.0.1:1234
break main
continue
```

二进制被 strip 时 `main` 断点不可用，可用 `info files` 查看入口地址。
QEMU user 复用宿主内核，适合用户态 CVE；内核漏洞需匹配目标内核的系统仿真。

## 3. Qiling：运行、调试、编写 hook

```bash
qltool run -f ./squashfs-root/bin/busybox --rootfs ./squashfs-root --args ls
# 调试模式；另一个终端用 gdb-multiarch 连接 127.0.0.1:9999
qltool run -f ./squashfs-root/bin/busybox --rootfs ./squashfs-root --gdb 127.0.0.1:9999 --args ls
# 自己写的 Qiling 脚本用此解释器运行，不需要激活虚拟环境
qiling-python demo.py
```

`demo.py` 最小模板（把地址替换为你在反汇编中确认的运行地址）：

```python
from qiling import Qiling

ql = Qiling(["./squashfs-root/bin/busybox", "ls"], "./squashfs-root")

def on_address(ql):
    print(hex(ql.arch.regs.arch_pc))

# ql.hook_address(on_address, 0x400000)
ql.run()
```

Qiling 已用独立 Python 3.12 安装，包含 CLI，不会混用 pwntools 的依赖。
rootfs 使用自己的固件目录；不会默认下载大体积示例库。
缺库、`/dev`、ioctl 或 NVRAM 时，仍需按目标程序补环境/hook。

## 4. FirmAE：整机仿真

```bash
firmae doctor
firmae build                       # 初次安装已自动构建；Docker 当时未启动才需补跑
firmae -c dlink ./firmware.bin      # 提取并检查网络/Web，结束后退出仿真
firmae -r dlink ./firmware.bin      # 持续运行，输出固件 IP
# 另一个终端：把 IP 替换成上一步输出的真实值
firmae web 192.168.0.1             # 浏览器打开 http://127.0.0.1:18080
firmae -d dlink ./firmware.bin      # 调试菜单；不要与 -r 同时跑同一固件
firmae -b dlink ./firmware.bin      # 查看启动/内核调试信息
firmae stop                        # 停止整套容器和仿真进程，保留数据
```

厂商可改为 `netgear` / `tplink` 等；推荐明确给出，`auto` 识别有可能失败。
`firmae shell` 进入容器；工作目录 `/opt/FirmAE`，日志在 `scratch/<IID>/`，
包括 `qemu.initial.serial.log`、`makeImage.log`、`makeNetwork.log`，`ip` 文件记录固件 IP。
`firmae logs` 查看容器初始化诊断；固件结果/日志请在 shell 中查看。

数据库、固件、images、scratch 分别放在持久 Docker volumes 中，`stop` 不删除。
`firmae build` 使用固定源码和构建缓存；升级提示镜像变化时，依次执行
`firmae stop`、`firmae recreate`，会保留这些数据卷。
主机只绑定本机 `18080` 端口，网络/数据库留在容器内。

此镜像提供 FirmAE 的 `-c/-r/-d/-b` 仿真与调试，不含依赖过旧的自动扫描器 `-a`，
也不安装 EMBA、Chrome 或宿主 PostgreSQL。自己用 curl/代理/脚本验证 CVE 即可。
FirmAE 常见支持范围是 ARM32、MIPS32 小端/大端，并非所有固件均能成功启动；
加密固件、新 SoC、64 位固件、特殊驱动和内核漏洞需要额外适配。

## WSL2 与运行条件

- QEMU user 与 Qiling 可先用；无需 KVM，也无需嵌套虚拟化。
- FirmAE 要求 x86_64、可连接的 Docker daemon、TUN 和 loop devices；启动时会实测。
- 使用特权容器并共享 `/dev` 供镜像分区/挂载使用，请放在专用研究环境运行。
- WSL2 里没有 systemd 时先启动本地 Docker，或启用 Docker Desktop 的 WSL integration。
- Docker Desktop 的内核/设备与 WSL 发行版可能不同；TUN/loop 报错先看 `firmae logs`。
  如果当前内核不支持，使用 Ubuntu x86_64 虚拟机跑 FirmAE 更省事。
- 文件尽量放在 `~/iot`，避免 `/mnt/c` 的权限/符号链接/性能问题。
- 完整 bootstrap 适合首次安装；已有环境只运行 `--iot`，可反复补装与检查。

参考：FirmAE https://github.com/pr0v3rbs/FirmAE ，
Qiling https://docs.qiling.io/ ，QEMU https://www.qemu.org/docs/master/user/main.html 。
