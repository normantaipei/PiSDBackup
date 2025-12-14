# PiSDBackup
An auto backup sd card system for photographer

## 功能

*   **自動偵測與備份**：插入 SD 卡或 USB 讀卡機後，自動將照片和影片複製到指定的備份硬碟。
*   **智慧整理**：根據檔案的拍攝日期，自動創建 `年-月-日` 格式的資料夾進行歸檔。
*   **觸控螢幕介面**：在 Raspberry Pi 的觸控螢幕上即時顯示系統狀態、網路資訊和備份進度。
*   **網頁瀏覽器**：提供一個網頁介面，讓你可以透過手機或電腦瀏覽備份硬碟中的照片。

## 設定教學

### 1. 安裝相依套件

專案首次執行時會自動嘗試安裝必要的套件。你也可以手動執行：

```bash
pip install -r requirements.txt 
# 如果 requirements.txt 不存在，請手動安裝
pip install pygame psutil Flask Pillow qrcode
```

### 2. 設定備份硬碟 (重要！)

你需要一塊外部硬碟（建議為 SSD）來儲存備份。請依照以下步驟在 Raspberry Pi 上設定它。

**a. 連接硬碟並找出裝置名稱**

將硬碟連接到 Raspberry Pi，然後執行 `lsblk`。
```bash
lsblk
```
找到你的硬碟，名稱通常是 `/dev/sda1` 或 `/dev/nvme0n1p1`。

**b. 建立掛載點**

我們將硬碟掛載在 `/mnt/backup_drive`。
```bash
sudo mkdir /mnt/backup_drive
```

**c. 取得硬碟 UUID 和檔案系統類型**

使用上一步的裝置名稱執行 `blkid`。
```bash
sudo blkid /dev/your_device_partition
```
記下 `UUID="..."` 和 `TYPE="..."` 的值。如果 `TYPE` 是 `ntfs`，請先安裝驅動：`sudo apt install ntfs-3g`。

**d. 設定開機自動掛載**

編輯 `/etc/fstab` 檔案。
```bash
sudo nano /etc/fstab
```
在檔案最下方加入新的一行，並將 `YOUR_UUID_HERE` 和 `YOUR_USERNAME` 替換成你自己的資訊（你的使用者名稱是 `norman`）。
```fstab
# 範例 (NTFS 硬碟):
UUID=YOUR_UUID_HERE   /mnt/backup_drive   ntfs-3g   defaults,auto,users,rw,nofail,uid=YOUR_USERNAME,gid=YOUR_USERNAME   0   0
```
儲存檔案後，執行 `sudo mount -a` 來立即掛載。

### 3. 配置專案路徑

請確保專案中的路徑設定與你的掛載點一致。

*   `sd_copy_manager.py`：確認 `ssd_mount_point` 變數設定為 `/mnt/backup_drive`。
*   `web_file_manager.py`：確認 `BASE_DIRECTORY` 變數設定為 `/mnt/backup_drive`。

### 4. 執行專案

```bash
python3 main.py
```
