#!/bin/bash
# One-time installer for PiSDBackup on Raspberry Pi OS (Bookworm or newer).
# Run as the user that should own the service, e.g.:  ./scripts/install.sh
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUN_USER="${SUDO_USER:-$USER}"
BACKUP_DIR="${BACKUP_DIR:-/mnt/backup_drive}"

echo "==> Installing system packages"
sudo apt-get update -qq
sudo apt-get install -y -qq python3-venv python3-dev libjpeg-dev zlib1g-dev \
    libsdl2-2.0-0 libsdl2-image-2.0-0 libsdl2-ttf-2.0-0 fonts-dejavu-core \
    network-manager exfatprogs ntfs-3g i2c-tools

echo "==> Creating virtualenv in $APP_DIR/.venv"
python3 -m venv "$APP_DIR/.venv"
"$APP_DIR/.venv/bin/pip" install --upgrade pip wheel >/dev/null
"$APP_DIR/.venv/bin/pip" install -r "$APP_DIR/requirements.txt"

echo "==> Writing /etc/pisdbackup/config.json (existing file is kept)"
sudo mkdir -p /etc/pisdbackup
if [ ! -f /etc/pisdbackup/config.json ]; then
    sed "s#/mnt/backup_drive#${BACKUP_DIR}#" "$APP_DIR/config.example.json" | sudo tee /etc/pisdbackup/config.json >/dev/null
fi
sudo mkdir -p "$BACKUP_DIR" /media/pisdbackup

echo "==> Granting $RUN_USER access to video/input devices and Wi-Fi control"
sudo usermod -aG video,render,input,netdev "$RUN_USER"
# NetworkManager lets members of netdev manage Wi-Fi without sudo; nothing else needs root.
cat <<SUDO | sudo tee /etc/sudoers.d/pisdbackup >/dev/null
# Only needed for the debug-mode Restart button.
$RUN_USER ALL=(root) NOPASSWD: /usr/bin/systemctl reboot
SUDO
sudo chmod 440 /etc/sudoers.d/pisdbackup

echo "==> Installing systemd service"
sed -e "s#__USER__#${RUN_USER}#g" -e "s#__APP_DIR__#${APP_DIR}#g" \
    "$APP_DIR/scripts/pisdbackup.service" | sudo tee /etc/systemd/system/pisdbackup.service >/dev/null

echo "==> Installing read-only automount rule for SD cards"
BACKUP_UUID="$(findmnt -no UUID "$BACKUP_DIR" 2>/dev/null || true)"
if [ -z "$BACKUP_UUID" ]; then
    echo "    WARNING: $BACKUP_DIR is not mounted. Add it to /etc/fstab (see README) and re-run,"
    echo "    otherwise the backup SSD could be auto-mounted read-only as if it were a card."
    BACKUP_UUID="UNKNOWN-RERUN-INSTALL"
fi
sed -e "s#__BACKUP_UUID__#${BACKUP_UUID}#g" -e "s#__UID__#$(id -u "$RUN_USER")#g" -e "s#__GID__#$(id -g "$RUN_USER")#g" \
    "$APP_DIR/scripts/99-pisdbackup-automount.rules" | sudo tee /etc/udev/rules.d/99-pisdbackup-automount.rules >/dev/null
sudo udevadm control --reload-rules

sudo systemctl daemon-reload
sudo systemctl enable pisdbackup.service
echo
echo "Done. Start now with:  sudo systemctl start pisdbackup"
echo "Logs:                  journalctl -u pisdbackup -f"
echo "Config:                /etc/pisdbackup/config.json"
