#!/bin/bash
# Fresh-Pi one-liner:
#   curl -fsSL https://raw.githubusercontent.com/normantaipei/PiSDBackup/main/scripts/bootstrap.sh | sudo bash
# Extra installer options can be appended:
#   curl -fsSL .../bootstrap.sh | sudo bash -s -- --wifi-country TW --timezone Asia/Taipei
set -euo pipefail
REPO="${PISD_REPO:-https://github.com/normantaipei/PiSDBackup.git}"
BRANCH="${PISD_BRANCH:-main}"
RUN_USER="${SUDO_USER:-${PISD_USER:-pi}}"
[ "$(id -u)" = 0 ] || { echo "Run with sudo"; exit 1; }
id "$RUN_USER" >/dev/null 2>&1 || RUN_USER="$(getent passwd 1000 | cut -d: -f1)"
HOME_DIR="$(getent passwd "$RUN_USER" | cut -d: -f6)"
APP_DIR="${PISD_APP_DIR:-$HOME_DIR/PiSDBackup}"

apt-get update -qq && apt-get install -y -qq git >/dev/null
if [ -d "$APP_DIR/.git" ]; then
  sudo -u "$RUN_USER" git -C "$APP_DIR" fetch -q origin "$BRANCH" && sudo -u "$RUN_USER" git -C "$APP_DIR" checkout -q "$BRANCH" && sudo -u "$RUN_USER" git -C "$APP_DIR" pull -q --ff-only
else
  sudo -u "$RUN_USER" git clone -q -b "$BRANCH" "$REPO" "$APP_DIR"
fi
exec env SUDO_USER="$RUN_USER" bash "$APP_DIR/scripts/install.sh" --user "$RUN_USER" --yes "$@"
