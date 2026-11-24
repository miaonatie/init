# Emulation/debug only: no legacy analyzer/Chrome or host PostgreSQL dependency.
FROM ubuntu:20.04
ENV DEBIAN_FRONTEND=noninteractive USER=root
# The Ubuntu base image needs a CA bundle before APT can use HTTPS.
RUN apt_retry() { apt-get -o Acquire::Retries=3 -o Acquire::http::Timeout=30 -o Acquire::https::Timeout=30 "$@"; } \
    && apt_retry update \
    && apt_retry install -y --no-install-recommends ca-certificates \
    && sed -i 's|http://|https://|g' /etc/apt/sources.list \
    && apt_retry update \
    && apt_retry install -y --no-install-recommends \
    git wget curl python3 python3-pip python3-setuptools python3-magic \
    python3-psycopg2 python3-lzo postgresql postgresql-client \
    build-essential patch liblzma-dev liblzo2-dev zlib1g-dev liblz4-dev \
    file binutils bc psmisc ruby telnet socat net-tools iputils-ping iptables iproute2 \
    busybox-static bash-static fakeroot dmsetup kpartx netcat-openbsd nmap snmp \
    uml-utilities util-linux vlan e2fsprogs fdisk sudo \
    mtd-utils gzip bzip2 tar arj lhasa p7zip-full cabextract fusecram cramfsswap \
    squashfs-tools sleuthkit cpio lzop lzma srecord unzip \
    qemu-system-arm qemu-system-mips qemu-utils && rm -rf /var/lib/apt/lists/*
# Binwalk 3 has no Python scan API required by FirmAE; keep 2.3.4 inside this image.
RUN wget -q -t 3 -T 30 https://github.com/ReFirmLabs/binwalk/archive/refs/tags/v2.3.4.tar.gz -O /tmp/binwalk.tgz \
    && tar -xf /tmp/binwalk.tgz -C /tmp \
    && cd /tmp/binwalk-2.3.4 && python3 setup.py install \
    && rm -rf /tmp/binwalk*
# Vendor SquashFS variants; GCC 10's -fno-common otherwise breaks this old source.
# Ubuntu archives the original SquashFS 4.3 release tarball byte-for-byte.
RUN git clone https://github.com/devttys0/sasquatch.git /tmp/sasquatch \
    && cd /tmp/sasquatch && git checkout bd864a1b037bf57ca7d64a292a60ba0d6459611f \
    && sed -i 's/ -Werror/ -fcommon/g' patches/patch0.txt \
    && curl -fsSL --retry 3 --connect-timeout 15 --max-time 60 \
        https://archive.ubuntu.com/ubuntu/pool/main/s/squashfs-tools/squashfs-tools_4.3.orig.tar.gz \
        -o squashfs4.3.tar.gz \
    && echo '0d605512437b1eb800b4736791559295ee5f60177e102e4d4ccd0ee241a5f3f6  squashfs4.3.tar.gz' | sha256sum -c - \
    && bash -e ./build.sh && test -x /usr/local/bin/sasquatch && rm -rf /tmp/sasquatch
RUN python3 -m pip install --no-cache-dir 'ubi_reader==0.8.5' 'jefferson==0.4.5'
COPY FirmAE /opt/FirmAE
WORKDIR /opt/FirmAE
# Local database: do not use upstream FIRMAE_DOCKER's hardcoded host bridge IP.
RUN mkdir -p binaries images scratch /firmwares \
    && install -m 0755 core/unstuff /usr/local/bin/unstuff \
    && sed -i 's/wget -N/wget -t 3 -T 30 -N/' download.sh \
    && ./download.sh \
    && python3 -c 'import binwalk, magic, psycopg2' \
    && qemu-system-mipsel --version \
    && test -s binaries/vmlinux.mipsel.4 && test -s binaries/zImage.armel
COPY entrypoint.sh /usr/local/bin/init-firmae-entrypoint
RUN chmod 0755 /usr/local/bin/init-firmae-entrypoint
ENTRYPOINT ["/usr/local/bin/init-firmae-entrypoint"]
