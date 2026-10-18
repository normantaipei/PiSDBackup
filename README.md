# PiSDBackup

An automatic, verified SD-card backup box for photographers, built on a Raspberry Pi with a touch screen.

* **Insert a card, it gets backed up.** Photos and videos are copied to the backup SSD into `YYYY-MM-DD` folders based on the EXIF capture date (video creation time, or file date as fallback).
* **Safe by design.** The card is never written to. Every file is copied to a temporary file, flushed to disk, re-read and checksum-verified, then renamed into place, so a power cut can never leave a half-written photo that looks real. Already-backed-up files are skipped cheaply.
* **Touch UI** shows network, drives, progress and errors; lets you pick a Wi-Fi network and type its password with a full on-screen keyboard.
* **Phone browser.** Scan the QR code on the screen to browse and download JPG/RAW files over Wi-Fi. Access is protected by a code shown on the device; thumbnails are cached, and the page works offline (no CDN).

## Project layout

| File | Purpose |
| --- | --- |
| `main.py` | Entry point: starts the web server, the card watcher and the touch UI |
| `config.py` | All settings (file + environment overrides), token handling, logging |
| `sd_copy_manager.py` | Card detection loop and the verified copy engine |
| `devices.py` | Read-only block-device discovery (lsblk/psutil), UUID-based identity |
| `media_dates.py` | EXIF / MP4 capture date extraction |
| `web_file_manager.py` | Flask app served by waitress: token auth, cached index, thumbnails |
| `rpi_interface.py` | pygame touch interface |
| `wifi_manager.py` | Wi-Fi scan/connect via NetworkManager (`nmcli`), `wpa_cli` fallback |
| `data_collector.py` | IP, SSID, drive usage, temperature, battery |
| `display_manager.py` | Picks the SDL video driver (X11 / KMS-DRM / framebuffer) |
| `scripts/install.sh` | One-time installer (packages, venv, systemd, udev automount) |
| `tests/` | pytest suite (copy engine, web API, UI rendering, device selection) |

## Installation (Raspberry Pi OS Bookworm or newer)

### 1. Mount the backup SSD permanently

Find the partition and its UUID, then add it to `/etc/fstab` so it mounts at boot:

```bash
lsblk -f
sudo mkdir -p /mnt/backup_drive
# exFAT example (recommended: readable on Mac and Windows):
echo 'UUID=YOUR-UUID  /mnt/backup_drive  exfat  defaults,nofail,uid=1000,gid=1000,umask=022  0  0' | sudo tee -a /etc/fstab
# ext4 example:
# echo 'UUID=YOUR-UUID  /mnt/backup_drive  ext4  defaults,nofail  0  0' | sudo tee -a /etc/fstab
sudo mount -a && findmnt /mnt/backup_drive
```

For ext4 make the mount writable by your user once: `sudo chown $USER /mnt/backup_drive`.

### 2. Run the installer

```bash
git clone https://github.com/normantaipei/PiSDBackup.git
cd PiSDBackup
./scripts/install.sh
sudo systemctl start pisdbackup
```

The installer:

* installs system packages and a Python virtualenv in `.venv/`;
* writes `/etc/pisdbackup/config.json` (edit it to change paths, port, extensions…);
* installs `pisdbackup.service` running as your user (no root, no `sudo` needed at runtime except the optional debug Restart button);
* installs a udev rule that mounts inserted cards **read-only** under `/media/pisdbackup/` so backups work without a desktop session. The backup SSD is excluded by UUID, which is why step 1 must be done first.

Logs: `journalctl -u pisdbackup -f`. Per-session copy logs (one JSON line per file, including every error) are written to `<backup_dir>/.pisdbackup/logs/`.

### Running by hand (development)

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
cp config.example.json config.json   # optional; env vars like PISD_BACKUP_DIR also work
python main.py
pytest                                # 29 tests, no hardware needed
PISD_ALLOW_DUMMY_DISPLAY=1 python main.py   # headless smoke run
```

## Configuration

`config.json` keys (see `config.example.json`). Any key can be overridden with an environment variable `PISD_<KEY>` in upper case.

| Key | Default | Meaning |
| --- | --- | --- |
| `backup_dir` | `/mnt/backup_drive` | Mount point of the backup SSD |
| `media_extensions` | photo/RAW/video list | Only these are copied (camera database files are ignored) |
| `source_mount_prefixes` | `/media`, `/mnt`, `/run/media` | Where mounted cards are looked for |
| `verify_after_copy` | `true` | Re-read each copied file and compare its SHA-256 |
| `min_free_mib` | `512` | Abort before copying if the SSD would drop below this |
| `web_auth` / `web_token` | `true` / auto | Access code for the browser (shown on screen and in the QR code) |
| `web_port` | `5000` | Browser port |
| `thumbnail_size` / `preview_size` | `320` / `1600` | Cached image sizes |
| `page_size` | `200` | Photos per page; older pages load while scrolling |
| `warm_thumbnails` | `true` | Pre-generate thumbnails in the background after each backup and at startup |
| `max_concurrent_decodes` | `2` | Images decoded at once (protects CPU/RAM on large libraries) |
| `preview_cache_max_mib` | `1024` | LRU cap for the full-size preview cache (`0` = unlimited) |
| `wifi_interface` | `wlan0` | Interface used for scanning/connecting |
| `debug_mode` | `false` | Shows Refresh/Restart buttons; ESC quits |

## 設計說明 (Design notes)

* **來源唯讀**：偵測不再對記憶卡寫測試檔，寫保護的卡也能備份；udev 規則更直接以 `ro` 掛載。
* **原子寫入與驗證**：`.part` 暫存檔 → fsync → 重新讀取比對 SHA-256 → `rename`。殘留的 `.part` 會在下次自動清除。
* **重複判斷**：先比 size + mtime（FAT 容許 2 秒誤差），相同即跳過；只有大小相同但時間不同時才算 hash。檔名相同但內容不同會以 `_1`、`_2` 後綴保留兩份。
* **裝置識別**：以檔案系統 UUID 追蹤「已處理」的卡，換卡即使掛載路徑相同也會重新備份；拔卡後狀態清除。
* **取消**：按 Stop 會真正停止，且不會自動重跑；重新插卡才會續傳（已複製的檔案會被快速跳過）。
* **大量照片**（Issue #1）：網頁改為分頁載入（捲動到底再抓下一頁），縮圖在每次備份完成後於背景批次預產並存在 `.pisdbackup/cache/`，同時解碼數量有上限，已刪除照片的快取會自動清除，預覽圖快取有大小上限。
* **安全**：網頁需存取碼；路徑穿越與 `.pisdbackup` 內部目錄被擋下；以 waitress 取代 Flask 開發伺服器；服務不以 root 執行。
* **設定集中**：所有路徑、埠號、介面名稱都在 `config.json`，不再散落在各檔案。
