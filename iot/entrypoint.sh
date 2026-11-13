#!/bin/bash
set -euo pipefail
cd /opt/FirmAE
rm -f /tmp/init-firmae-ready
if [[ ! -c /dev/net/tun ]]; then
    echo 'Missing /dev/net/tun. Enable TUN in the Linux/WSL2 Docker host kernel.' >&2
    exit 1
fi
if ! losetup -f; then
    echo 'No loop device. Enable loop devices in the Docker host kernel (WSL2 may need a full Linux VM).' >&2
    exit 1
fi
service postgresql start
if ! runuser -u postgres -- psql -tAc "SELECT 1 FROM pg_roles WHERE rolname='firmadyne'" | grep -q 1; then
    runuser -u postgres -- psql -v ON_ERROR_STOP=1 -c "CREATE USER firmadyne WITH PASSWORD 'firmadyne';"
fi
if ! runuser -u postgres -- psql -tAc "SELECT 1 FROM pg_database WHERE datname='firmware'" | grep -q 1; then
    runuser -u postgres -- createdb -O firmadyne firmware
fi
export PGPASSWORD=firmadyne
if [[ $(psql -h 127.0.0.1 -U firmadyne -d firmware -tAc "SELECT to_regclass('public.image') IS NOT NULL;") != t ]]; then
    psql -v ON_ERROR_STOP=1 -h 127.0.0.1 -U firmadyne -d firmware < database/schema
fi
touch /tmp/init-firmae-ready
trap 'service postgresql stop; exit 0' TERM INT
sleep infinity &
wait $!
