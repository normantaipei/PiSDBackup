#!/bin/bash
# =============================================================================
#  PiSDBackup one-command installer for a fresh Raspberry Pi OS (Bookworm+)
#
#    curl -fsSL https://raw.githubusercontent.com/normantaipei/PiSDBackup/main/scripts/bootstrap.sh | sudo bash
#  or, from a clone:
#    sudo ./scripts/install.sh [options]
#
#  It is idempotent: run it again any time to repair or re-apply settings.
#
#  What it does (each step can be skipped, see --help):
#    packages  apt + Python venv + requirements
#    drive     find the backup SSD, add it to /etc/fstab by UUID, mount it
#    kiosk     boot to console (no desktop), no screen blanking, no splash,
#              hidden cursor, no first-boot wizard, no desktop automount pop-ups
#    system    hostname, SSH, I2C (battery gauge), Wi-Fi country + no power-save,
#              journal size cap, disable Bluetooth/ModemManager/apt timers
#    app       config, user groups, systemd service, read-only card automount
#              (udev), small 'pisdbackup' helper command
# =============================================================================
set -euo pipefail

# ----------------------------------------------------------------- defaults
APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUN_USER="${SUDO_USER:-${USER:-$(id -un)}}"
BACKUP_DIR="/mnt/backup_drive"
BACKUP_DEV=""
HOSTNAME_NEW="pisdbackup"
WIFI_COUNTRY=""
TIMEZONE=""
KEEP_DESKTOP=0
KEEP_BLUETOOTH=0
SKIP_DRIVE=0
SKIP_KIOSK=0
SKIP_SYSTEM=0
SKIP_PACKAGES=0
NO_REBOOT_PROMPT=0
UNINSTALL=0
ASSUME_YES=0

CONFIG_DIR=/etc/pisdbackup
CONFIG_FILE=$CONFIG_DIR/config.json
SERVICE_FILE=/etc/systemd/system/pisdbackup.service
UDEV_FILE=/etc/udev/rules.d/99-pisdbackup-automount.rules
SUDOERS_FILE=/etc/sudoers.d/pisdbackup
NM_CONF=/etc/NetworkManager/conf.d/pisdbackup-wifi.conf
JOURNAL_CONF=/etc/systemd/journald.conf.d/pisdbackup.conf
HELPER=/usr/local/bin/pisdbackup
NEEDS_REBOOT=0

usage() {
  sed -n '2,20p' "$0" | sed 's/^# \{0,2\}//'
  cat <<USAGE

Options:
  --backup-dev /dev/sdX1   Partition of the backup SSD (default: auto-detect)
  --backup-dir PATH        Mount point (default: $BACKUP_DIR)
  --user NAME              User that runs the service (default: $RUN_USER)
  --hostname NAME          Hostname, reachable as NAME.local (default: $HOSTNAME_NEW; "" keeps current)
  --wifi-country CC        Wi-Fi regulatory country, e.g. TW (default: keep current)
  --timezone ZONE          e.g. Asia/Taipei (default: keep current)
  --keep-desktop           Do not switch to console boot (experimental; kiosk mode is recommended)
  --keep-bluetooth         Leave Bluetooth enabled
  --skip-drive             Do not touch /etc/fstab (configure the SSD yourself)
  --skip-kiosk             Skip screen/boot tweaks
  --skip-system            Skip hostname/SSH/I2C/Wi-Fi/journal/service tweaks
  --skip-packages          Skip apt/pip (offline re-run)
  --yes                    Do not ask questions; pick sensible defaults
  --no-reboot-prompt       Never offer to reboot
  --uninstall              Remove service, udev rule, sudoers, helper (keeps data and OS tweaks)
  -h, --help
USAGE
}

while [ $# -gt 0 ]; do
  case "$1" in
    --backup-dev) BACKUP_DEV="$2"; shift 2 ;;
    --backup-dir) BACKUP_DIR="$2"; shift 2 ;;
    --user) RUN_USER="$2"; shift 2 ;;
    --hostname) HOSTNAME_NEW="$2"; shift 2 ;;
    --wifi-country) WIFI_COUNTRY="$2"; shift 2 ;;
    --timezone) TIMEZONE="$2"; shift 2 ;;
    --keep-desktop) KEEP_DESKTOP=1; shift ;;
    --keep-bluetooth) KEEP_BLUETOOTH=1; shift ;;
    --skip-drive) SKIP_DRIVE=1; shift ;;
    --skip-kiosk) SKIP_KIOSK=1; shift ;;
    --skip-system) SKIP_SYSTEM=1; shift ;;
    --skip-packages) SKIP_PACKAGES=1; shift ;;
    --yes|-y) ASSUME_YES=1; shift ;;
    --no-reboot-prompt) NO_REBOOT_PROMPT=1; shift ;;
    --uninstall) UNINSTALL=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1"; usage; exit 1 ;;
  esac
done

# ----------------------------------------------------------------- helpers
C_B=$'\033[1m'; C_G=$'\033[32m'; C_Y=$'\033[33m'; C_R=$'\033[31m'; C_0=$'\033[0m'
step()  { echo; echo "${C_B}==> $*${C_0}"; }
ok()    { echo "    ${C_G}✓${C_0} $*"; }
warn()  { echo "    ${C_Y}!${C_0} $*"; }
fail()  { echo "    ${C_R}✗ $*${C_0}" >&2; exit 1; }
have()  { command -v "$1" >/dev/null 2>&1; }
ask_yn() {  # ask_yn "question" default(y|n)
  local q="$1" d="${2:-n}" a
  if [ "$ASSUME_YES" = 1 ] || [ ! -t 0 ]; then [ "$d" = y ]; return; fi
  read -r -p "    $q [$([ "$d" = y ] && echo Y/n || echo y/N)] " a
  a="${a:-$d}"; [[ "$a" =~ ^[Yy] ]]
}
raspi() { have raspi-config || return 1; raspi-config nonint "$@" >/dev/null 2>&1; }
set_kv_file() {  # set_kv_file FILE KEY VALUE  (KEY=VALUE lines, creates file)
  local f="$1" k="$2" v="$3"
  mkdir -p "$(dirname "$f")"; touch "$f"
  if grep -qE "^#?\s*${k}=" "$f"; then sed -i -E "s|^#?\s*${k}=.*|${k}=${v}|" "$f"; else echo "${k}=${v}" >> "$f"; fi
}
cmdline_file() { [ -f /boot/firmware/cmdline.txt ] && echo /boot/firmware/cmdline.txt || echo /boot/cmdline.txt; }
cmdline_add() {  # cmdline_add key[=value] : adds (or replaces key=) in cmdline.txt
  local f; f="$(cmdline_file)"; [ -f "$f" ] || return 0
  local key="${1%%=*}" line new; line="$(tr -d '\n' < "$f")"
  if [[ " $line " =~ \ ${key}(=[^ ]*)?\  ]]; then
    new="$(echo "$line" | sed -E "s/(^| )${key}(=[^ ]*)?( |$)/\1$1\3/")"
  else
    new="$line $1"
  fi
  new="$(echo "$new" | tr -s ' ')"
  if [ "$new" != "$line" ]; then echo "$new" > "$f"; NEEDS_REBOOT=1; fi
}

[ "$(id -u)" = 0 ] || fail "Run with sudo:  sudo $0 $*"
id "$RUN_USER" >/dev/null 2>&1 || fail "User '$RUN_USER' does not exist (use --user)"
[ "$RUN_USER" != root ] || fail "Refusing to run the service as root; pass --user <name>"
RUN_UID="$(id -u "$RUN_USER")"; RUN_GID="$(id -g "$RUN_USER")"
RUN_HOME="$(getent passwd "$RUN_USER" | cut -d: -f6)"
export DEBIAN_FRONTEND=noninteractive

# ----------------------------------------------------------------- uninstall
if [ "$UNINSTALL" = 1 ]; then
  step "Uninstalling PiSDBackup (data and OS tweaks are kept)"
  systemctl disable --now pisdbackup.service 2>/dev/null || true
  rm -f "$SERVICE_FILE" "$UDEV_FILE" "$SUDOERS_FILE" "$HELPER" "$NM_CONF"
  systemctl daemon-reload; udevadm control --reload-rules || true
  ok "Removed service, udev rule, sudoers and helper. Config left in $CONFIG_DIR."
  exit 0
fi

echo "${C_B}PiSDBackup installer${C_0}  app=$APP_DIR  user=$RUN_USER  backup=$BACKUP_DIR"

# ----------------------------------------------------------------- packages
if [ "$SKIP_PACKAGES" = 0 ]; then
  step "Installing system packages"
  apt-get update -qq
  apt-get install -y -qq --no-install-recommends \
    python3 python3-venv python3-dev build-essential libjpeg-dev zlib1g-dev libfreetype6-dev \
    libsdl2-2.0-0 libsdl2-image-2.0-0 libsdl2-ttf-2.0-0 libsdl2-mixer-2.0-0 fonts-dejavu-core \
    network-manager exfatprogs ntfs-3g dosfstools i2c-tools util-linux udev curl git avahi-daemon >/dev/null
  ok "apt packages present"

  step "Python virtualenv ($APP_DIR/.venv)"
  if [ ! -x "$APP_DIR/.venv/bin/python" ]; then
    sudo -u "$RUN_USER" python3 -m venv "$APP_DIR/.venv"
  fi
  sudo -u "$RUN_USER" "$APP_DIR/.venv/bin/pip" install -q --upgrade pip wheel
  sudo -u "$RUN_USER" "$APP_DIR/.venv/bin/pip" install -q -r "$APP_DIR/requirements.txt"
  ok "Python dependencies installed"
fi
chown -R "$RUN_USER:$RUN_GID" "$APP_DIR" 2>/dev/null || true

# ----------------------------------------------------------------- backup drive
BACKUP_UUID=""
if [ "$SKIP_DRIVE" = 0 ]; then
  step "Backup drive"
  mkdir -p "$BACKUP_DIR"
  if [ -z "$BACKUP_DEV" ]; then
    BACKUP_UUID="$(findmnt -no UUID "$BACKUP_DIR" 2>/dev/null || true)"
    if [ -n "$BACKUP_UUID" ]; then
      ok "$BACKUP_DIR is already mounted (UUID=$BACKUP_UUID)"
    else
      # Candidates: partitions with a filesystem, not the boot SD card, not mounted as system.
      CANDS=(); CAND_DESC=()
      while IFS= read -r line; do
        eval "$line"   # sets NAME TYPE FSTYPE SIZE MOUNTPOINT LABEL (lsblk -P quotes values)
        [ "$TYPE" = part ] && [ -n "$FSTYPE" ] || continue
        [[ "$NAME" == *mmcblk0* ]] && continue
        [ -z "$MOUNTPOINT" ] || [[ "$MOUNTPOINT" == /media/* ]] || [[ "$MOUNTPOINT" == /mnt/* ]] || continue
        CANDS+=("$NAME"); CAND_DESC+=("$NAME  $FSTYPE  $SIZE  ${LABEL:-(no label)}  ${MOUNTPOINT:-(not mounted)}")
      done < <(lsblk -Ppno NAME,TYPE,FSTYPE,SIZE,MOUNTPOINT,LABEL)
      if [ ${#CANDS[@]} -eq 1 ]; then
        BACKUP_DEV="${CANDS[0]}"
        ok "Found one external partition: ${CAND_DESC[0]}"
      elif [ ${#CANDS[@]} -gt 1 ]; then
        echo "    Several external partitions found:"; i=1
        for c in "${CAND_DESC[@]}"; do echo "      [$i] $c"; i=$((i+1)); done
        if [ "$ASSUME_YES" = 1 ] || [ ! -t 0 ]; then
          BACKUP_DEV="$(lsblk -bpno NAME,SIZE "${CANDS[@]}" | sort -k2 -n -r | head -1 | awk '{print $1}')"
          warn "Non-interactive: picking the largest, $BACKUP_DEV"
        else
          read -r -p "    Which one is the backup SSD? [1-${#CANDS[@]}] " n
          BACKUP_DEV="${CANDS[$((n-1))]}"
        fi
      else
        warn "No external drive found. Plug in the SSD and re-run, or use --backup-dev / --skip-drive."
      fi
    fi
  fi
  if [ -n "$BACKUP_DEV" ]; then
    [ -b "$BACKUP_DEV" ] || fail "$BACKUP_DEV is not a block device"
    FSTYPE="$(blkid -o value -s TYPE "$BACKUP_DEV" || true)"
    BACKUP_UUID="$(blkid -o value -s UUID "$BACKUP_DEV" || true)"
    [ -n "$FSTYPE" ] && [ -n "$BACKUP_UUID" ] || fail "$BACKUP_DEV has no filesystem. Format it first (exFAT recommended: sudo mkfs.exfat -n BACKUP $BACKUP_DEV)"
    case "$FSTYPE" in
      exfat|vfat) OPTS="defaults,nofail,x-systemd.device-timeout=10,uid=$RUN_UID,gid=$RUN_GID,umask=022,noatime" ;;
      ntfs)       OPTS="defaults,nofail,x-systemd.device-timeout=10,uid=$RUN_UID,gid=$RUN_GID,umask=022,big_writes"; FSTYPE=ntfs-3g ;;
      *)          OPTS="defaults,nofail,x-systemd.device-timeout=10,noatime" ;;
    esac
    CUR_MP="$(findmnt -no TARGET "$BACKUP_DEV" || true)"
    if [ -n "$CUR_MP" ] && [ "$CUR_MP" != "$BACKUP_DIR" ]; then
      warn "$BACKUP_DEV is mounted at $CUR_MP (desktop automount); unmounting"
      umount "$BACKUP_DEV" || fail "Could not unmount $BACKUP_DEV"
    fi
    sed -i "\#[[:space:]]$BACKUP_DIR[[:space:]]#d" /etc/fstab
    sed -i "\#^UUID=$BACKUP_UUID[[:space:]]#d" /etc/fstab
    echo "UUID=$BACKUP_UUID  $BACKUP_DIR  $FSTYPE  $OPTS  0  0" >> /etc/fstab
    systemctl daemon-reload
    mount "$BACKUP_DIR" 2>/dev/null || mount -a || fail "Mounting $BACKUP_DIR failed; check 'journalctl -xe'"
    case "$FSTYPE" in exfat|vfat|ntfs-3g) ;; *) chown "$RUN_USER:$RUN_GID" "$BACKUP_DIR" ;; esac
    ok "$BACKUP_DEV ($FSTYPE, UUID=$BACKUP_UUID) mounted at $BACKUP_DIR and added to /etc/fstab"
  fi
  sudo -u "$RUN_USER" touch "$BACKUP_DIR/.pisdbackup_write_test" 2>/dev/null && rm -f "$BACKUP_DIR/.pisdbackup_write_test" \
    && ok "$RUN_USER can write to $BACKUP_DIR" || warn "$RUN_USER cannot write to $BACKUP_DIR yet (is the SSD mounted?)"
fi

# ----------------------------------------------------------------- kiosk tweaks
if [ "$SKIP_KIOSK" = 0 ]; then
  step "Kiosk mode: screen, boot and desktop"
  if [ "$KEEP_DESKTOP" = 0 ]; then
    raspi do_boot_behaviour B1 && ok "Boot to console (no desktop, no autologin shell)"
    for s in lightdm gdm3 sddm; do systemctl is-enabled "$s" >/dev/null 2>&1 && { systemctl disable "$s" >/dev/null 2>&1 || true; }; done
    systemctl set-default multi-user.target >/dev/null 2>&1 || true
  else
    warn "Keeping the desktop (experimental). Disabling desktop automount pop-ups."
    for cfg in "$RUN_HOME/.config/pcmanfm/LXDE-pi/pcmanfm.conf" "$RUN_HOME/.config/pcmanfm/default/pcmanfm.conf"; do
      mkdir -p "$(dirname "$cfg")"; touch "$cfg"
      grep -q '^\[volume\]' "$cfg" || printf '\n[volume]\n' >> "$cfg"
      for kv in mount_on_startup=0 mount_removable=0 autorun=0; do
        if grep -q "^${kv%%=*}=" "$cfg"; then sed -i "s/^${kv%%=*}=.*/$kv/" "$cfg"; else sed -i "/^\[volume\]/a $kv" "$cfg"; fi
      done
      chown -R "$RUN_USER:$RUN_GID" "$RUN_HOME/.config"
    done
    AUTOSTART="$RUN_HOME/.config/lxsession/LXDE-pi/autostart"
    mkdir -p "$(dirname "$AUTOSTART")"; touch "$AUTOSTART"
    for l in "@xset s off" "@xset -dpms" "@xset s noblank"; do grep -qxF "$l" "$AUTOSTART" || echo "$l" >> "$AUTOSTART"; done
    chown -R "$RUN_USER:$RUN_GID" "$RUN_HOME/.config"
  fi
  raspi do_blanking 1 && ok "Screen blanking disabled"
  raspi do_boot_splash 1 && ok "Boot splash disabled"
  cmdline_add consoleblank=0
  cmdline_add vt.global_cursor_default=0
  cmdline_add quiet
  cmdline_add logo.nologo
  ok "Console: no blanking, hidden cursor, quiet boot"
  rm -f /etc/xdg/autostart/piwiz.desktop && ok "First-boot wizard removed" || true
  systemctl disable --now userconfig.service >/dev/null 2>&1 || true
fi

# ----------------------------------------------------------------- system tweaks
if [ "$SKIP_SYSTEM" = 0 ]; then
  step "System settings"
  if [ -n "$HOSTNAME_NEW" ] && [ "$(hostname)" != "$HOSTNAME_NEW" ]; then
    raspi do_hostname "$HOSTNAME_NEW" || { hostnamectl set-hostname "$HOSTNAME_NEW"; sed -i "s/127.0.1.1.*/127.0.1.1\t$HOSTNAME_NEW/" /etc/hosts; }
    ok "Hostname set to $HOSTNAME_NEW (http://$HOSTNAME_NEW.local:5000)"; NEEDS_REBOOT=1
  fi
  raspi do_ssh 0 && ok "SSH enabled"
  raspi do_i2c 0 && ok "I2C enabled (battery gauge)"
  if [ -n "$WIFI_COUNTRY" ]; then raspi do_wifi_country "$WIFI_COUNTRY" && ok "Wi-Fi country $WIFI_COUNTRY"; fi
  if [ -n "$TIMEZONE" ]; then timedatectl set-timezone "$TIMEZONE" && ok "Timezone $TIMEZONE"; fi
  rfkill unblock wifi 2>/dev/null || true
  mkdir -p "$(dirname "$NM_CONF")"
  printf '[connection]\nwifi.powersave = 2\n\n[device]\nwifi.scan-rand-mac-address=no\n' > "$NM_CONF"
  systemctl enable --now NetworkManager >/dev/null 2>&1 || true
  ok "Wi-Fi power saving off (stable phone connection)"
  mkdir -p "$(dirname "$JOURNAL_CONF")"
  printf '[Journal]\nSystemMaxUse=50M\nStorage=persistent\n' > "$JOURNAL_CONF"
  systemctl restart systemd-journald >/dev/null 2>&1 || true
  ok "Journal capped at 50 MB (protects the SD card)"
  for s in apt-daily.timer apt-daily-upgrade.timer man-db.timer ModemManager.service cups.service cups-browsed.service triggerhappy.service; do
    systemctl list-unit-files "$s" >/dev/null 2>&1 && systemctl disable --now "$s" >/dev/null 2>&1 || true
  done
  if [ "$KEEP_BLUETOOTH" = 0 ]; then
    systemctl disable --now bluetooth.service hciuart.service >/dev/null 2>&1 || true
    ok "Bluetooth, ModemManager, printing and background apt timers disabled"
  fi
  systemctl enable --now avahi-daemon >/dev/null 2>&1 || true
fi

# ----------------------------------------------------------------- application
step "Application"
mkdir -p "$CONFIG_DIR" /media/pisdbackup
if [ ! -f "$CONFIG_FILE" ]; then
  sed "s#/mnt/backup_drive#${BACKUP_DIR}#" "$APP_DIR/config.example.json" > "$CONFIG_FILE"
  ok "Config written to $CONFIG_FILE"
else
  ok "Config kept: $CONFIG_FILE"
fi
for g in video render input netdev i2c plugdev; do
  getent group "$g" >/dev/null && usermod -aG "$g" "$RUN_USER"
done
cat > "$SUDOERS_FILE" <<SUDO
# PiSDBackup: only the debug-mode Restart button needs this.
$RUN_USER ALL=(root) NOPASSWD: /usr/bin/systemctl reboot
SUDO
chmod 440 "$SUDOERS_FILE"
ok "Groups and sudoers set for $RUN_USER"

MOUNT_UNIT="$(systemd-escape -p "$BACKUP_DIR").mount"
SVC_GROUPS=""; for g in video render input i2c; do getent group "$g" >/dev/null && SVC_GROUPS="$SVC_GROUPS $g"; done
sed -e "s#__USER__#${RUN_USER}#g" -e "s#__APP_DIR__#${APP_DIR}#g" -e "s#__MOUNT_UNIT__#${MOUNT_UNIT}#g" \
    -e "s#__GROUPS__#${SVC_GROUPS# }#g" "$APP_DIR/scripts/pisdbackup.service" > "$SERVICE_FILE"
if [ "$KEEP_DESKTOP" = 1 ]; then
  mkdir -p /etc/systemd/system/pisdbackup.service.d
  printf '[Unit]\nAfter=graphical.target\n[Service]\nEnvironment=DISPLAY=:0 XDG_RUNTIME_DIR=/run/user/%s WAYLAND_DISPLAY=wayland-0\n' "$RUN_UID" > /etc/systemd/system/pisdbackup.service.d/desktop.conf
else
  rm -f /etc/systemd/system/pisdbackup.service.d/desktop.conf
fi
ok "systemd unit installed"

UUID_FOR_RULE="${BACKUP_UUID:-$(findmnt -no UUID "$BACKUP_DIR" 2>/dev/null || true)}"
if [ -z "$UUID_FOR_RULE" ]; then
  warn "Backup SSD UUID unknown: the card automount rule will exclude nothing. Re-run the installer once the SSD is set up."
  UUID_FOR_RULE="UNKNOWN-RERUN-INSTALL"
fi
mkdir -p "$(dirname "$UDEV_FILE")"
sed -e "s#__BACKUP_UUID__#${UUID_FOR_RULE}#g" -e "s#__UID__#${RUN_UID}#g" -e "s#__GID__#${RUN_GID}#g" \
    "$APP_DIR/scripts/99-pisdbackup-automount.rules" > "$UDEV_FILE"
udevadm control --reload-rules || true
ok "Read-only card automount rule installed (/media/pisdbackup)"

install -m 755 "$APP_DIR/scripts/pisdbackupctl.sh" "$HELPER"
ok "Helper command: pisdbackup {status|logs|token|url|restart|stop|start|update|config}"

systemctl daemon-reload
systemctl enable pisdbackup.service >/dev/null 2>&1
systemctl restart pisdbackup.service || true
sleep 2
if systemctl is-active --quiet pisdbackup.service; then
  ok "pisdbackup.service is running"
else
  warn "Service is not running yet (normal on a desktop image until reboot). Check: pisdbackup logs"
fi

# ----------------------------------------------------------------- summary
TOKEN_FILE="$RUN_HOME/.config/pisdbackup/web_token"
IP="$(hostname -I 2>/dev/null | awk '{print $1}')"
echo
echo "${C_B}${C_G}Done.${C_0}"
echo "  Web UI:        http://${IP:-<pi-ip>}:5000/   or   http://${HOSTNAME_NEW:-$(hostname)}.local:5000/"
[ -f "$TOKEN_FILE" ] && echo "  Access code:   $(cat "$TOKEN_FILE")   (also shown on the screen / in the QR code)"
echo "  Config:        $CONFIG_FILE"
echo "  Logs:          pisdbackup logs"
echo "  Re-run anytime: sudo $APP_DIR/scripts/install.sh"
if [ "$NEEDS_REBOOT" = 1 ] || [ "$SKIP_KIOSK" = 0 ]; then
  echo
  if [ "$NO_REBOOT_PROMPT" = 0 ] && ask_yn "A reboot is needed to apply boot settings. Reboot now?" y; then
    reboot
  else
    echo "  Reboot later with:  sudo reboot"
  fi
fi
