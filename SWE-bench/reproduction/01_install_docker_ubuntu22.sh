#!/usr/bin/env bash
set -euo pipefail

DOCKER_VERSION=${DOCKER_VERSION:-29.1.3-0ubuntu3~22.04.2}
CONTAINERD_VERSION=${CONTAINERD_VERSION:-2.2.1-0ubuntu1~22.04.2}
RUNC_VERSION=${RUNC_VERSION:-1.3.4-0ubuntu1~22.04.1}
TARGET_USER=${TARGET_USER:-${SUDO_USER:-$USER}}

if ! grep -q '^VERSION_ID="22.04"' /etc/os-release; then
  echo "ERROR: this script is validated only on Ubuntu 22.04" >&2
  exit 1
fi

sudo -v
sudo env DEBIAN_FRONTEND=noninteractive apt-get install -y \
  "docker.io=$DOCKER_VERSION" \
  "containerd=$CONTAINERD_VERSION" \
  "runc=$RUNC_VERSION"
sudo systemctl enable --now containerd docker
sudo usermod -aG docker "$TARGET_USER"

docker --version || true
systemctl is-active containerd docker
stat -c '%U:%G %a %n' /var/run/docker.sock

echo "Docker installed. Log out and back in before running Docker as $TARGET_USER."
