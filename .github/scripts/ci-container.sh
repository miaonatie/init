#!/usr/bin/env bash
set -euo pipefail

if [[ $1 != --inside-container ]]; then
    image=$1
    shift
    exec docker run --rm \
        -e TERM=xterm -e PYTHONUNBUFFERED=1 -e PYTHONDONTWRITEBYTECODE=1 \
        -e DEBIAN_FRONTEND=noninteractive \
        -v "$PWD:/src:ro" \
        -v /etc/ssl/certs/ca-certificates.crt:/tmp/host-ca.crt:ro \
        -w /src "$image" bash /src/.github/scripts/ci-container.sh --inside-container "$@"
fi
shift

prepare_container() {
    local source
    local apt_options=(
        -o Acquire::Retries=3
        -o Acquire::http::Timeout=30
        -o Acquire::https::Timeout=30
        -o Acquire::https::CaInfo=/tmp/host-ca.crt
    )
    for source in /etc/apt/sources.list /etc/apt/sources.list.d/*.sources; do
        if [[ -f $source ]]; then
            sed -i 's|http://archive.ubuntu.com|https://archive.ubuntu.com|g; s|http://security.ubuntu.com|https://security.ubuntu.com|g' "$source"
        fi
    done
    apt-get "${apt_options[@]}" update -qq
    apt-get "${apt_options[@]}" install -y --no-install-recommends python3 ca-certificates "$@"
}

case "$1" in
    environment)
        prepare_container curl sudo
        if [[ $2 == tester ]]; then
            useradd -m -s /bin/bash tester
            printf '%s\n' 'tester ALL=(ALL) NOPASSWD: ALL' > /etc/sudoers.d/tester
            chmod 440 /etc/sudoers.d/tester
            runuser -u tester -- env HOME=/home/tester python3 tests/smoke_environment.py
        else
            python3 init.py --help
            python3 -m unittest discover -s tests -q
            python3 tests/smoke_environment.py
        fi
        ;;
    qemu)
        prepare_container binutils qemu-user squashfs-tools
        qemu_setup='from init import Bootstrap; b=Bootstrap(); assert b.install_qemu_static(), b.failures'
        python3 -c "$qemu_setup"
        python3 tests/smoke_iot.py --qemu-only
        python3 -c "$qemu_setup"
        ;;
    legacy-iot)
        prepare_container curl git
        iot_setup='from init import Bootstrap; b=Bootstrap(); b.install_iot_environment(); b.verify_iot(); assert not b.failures, b.failures'
        python3 -c "$iot_setup"
        python3 tests/smoke_iot.py
        python3 -c "$iot_setup"
        ;;
    *)
        printf 'Unknown CI container check: %s\n' "$1" >&2
        exit 2
        ;;
esac
