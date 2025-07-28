import os
import shutil
import hashlib
import time
from datetime import datetime
import threading
import json
import psutil # 用於檢查掛載點

class SDCopyManager:
    """
    管理 SD 卡到 SSD 的檔案複製過程。
    偵測 SD 卡插入，依照建立日期將檔案複製到 SSD，
    並處理檔案重複與命名衝突。
    """
    # 將 SSD 掛載點更新為你的實際路徑
    def __init__(self, ssd_mount_point="/media/norman/新增磁碟區", sd_mount_point="/media/pi/SD_CARD"):
        self.ssd_mount_point = ssd_mount_point
        self.sd_mount_point = sd_mount_point
        self.is_copying = False
        self.current_file = ""
        self.progress_percent = 0.0
        self.total_files = 0
        self.copied_files = 0
        self.skipped_files = 0
        self.error_files = 0
        self.status_message = "Waiting for SD card..."
        self.copy_thread = None
        self.event_callback = None # 用於 UI 更新的回調函數

        # 確保 SSD 掛載點目錄存在 (如果必要，會建立父目錄)
        os.makedirs(self.ssd_mount_point, exist_ok=True)
        print(f"SDCopyManager initialized. SSD: {self.ssd_mount_point}, SD: {self.sd_mount_point}")
        self._update_ui() # 初始化時更新 UI

    def set_event_callback(self, callback):
        """設定一個回調函數，用於在複製過程中向 UI 發送更新。"""
        self.event_callback = callback
        self._update_ui() # 設定回調後立即發送初始狀態

    def _update_ui(self):
        """調用回調函數以更新 UI"""
        if self.event_callback:
            status_data = {
                'is_copying': self.is_copying,
                'current_file': self.current_file,
                'progress_percent': self.progress_percent,
                'total_files': self.total_files,
                'copied_files': self.copied_files,
                'skipped_files': self.skipped_files,
                'error_files': self.error_files,
                'status_message': self.status_message,
                'ssd_present': self.check_ssd_present() # 新增 SSD 存在狀態
            }
            self.event_callback(status_data)
        
        # 除錯輸出：直接印出 SSD 偵測狀態 (每 5 秒一次)
        if self.check_ssd_present():
            print(f"DEBUG: SSD STATUS: SSD is DETECTED and writable at '{self.ssd_mount_point}'!")
        else:
            print(f"DEBUG: SSD STATUS: SSD is NOT DETECTED or not writable at '{self.ssd_mount_point}'. Status message: {self.status_message}")

    def _get_file_hash(self, filepath):
        """計算檔案的 SHA256 雜湊值。"""
        hasher = hashlib.sha256()
        try:
            with open(filepath, 'rb') as f:
                while True:
                    chunk = f.read(4096)
                    if not chunk:
                        break
                    hasher.update(chunk)
            return hasher.hexdigest()
        except Exception as e:
            print(f"Error calculating hash for {filepath}: {e}")
            return None

    def _get_file_creation_date(self, filepath):
        """嘗試獲取檔案的建立日期（或修改日期作為備用）。"""
        try:
            timestamp = os.stat(filepath).st_birthtime
        except AttributeError:
            # 如果建立時間不可用 (例如在某些 Linux 檔案系統上)，則退回使用修改時間
            timestamp = os.stat(filepath).st_mtime
        return datetime.fromtimestamp(timestamp).strftime('%Y-%m-%d')

    def _copy_file(self, src_file_path, dest_dir):
        """
        複製單個檔案，處理命名衝突和內容重複。
        """
        filename = os.path.basename(src_file_path)
        dest_file_path = os.path.join(dest_dir, filename)
        
        os.makedirs(dest_dir, exist_ok=True) # 確保目標目錄存在

        if os.path.exists(dest_file_path):
            src_hash = self._get_file_hash(src_file_path)
            dest_hash = self._get_file_hash(dest_file_path)

            if src_hash == dest_hash:
                print(f"Skipping identical file: {filename}")
                self.skipped_files += 1
                return
            else:
                base, ext = os.path.splitext(filename)
                count = 1
                new_dest_file_path = dest_file_path
                while os.path.exists(new_dest_file_path):
                    new_filename = f"{base}_{count}{ext}"
                    new_dest_file_path = os.path.join(dest_dir, new_filename)
                    count += 1
                dest_file_path = new_dest_file_path
                print(f"Renaming and copying different file: {filename} to {os.path.basename(dest_file_path)}")
        try:
            shutil.copy2(src_file_path, dest_file_path)
            print(f"Copied: {src_file_path} to {dest_file_path}")
            self.copied_files += 1
        except Exception as e:
            print(f"Error copying {src_file_path} to {dest_file_path}: {e}")
            self.error_files += 1

    def check_sd_card_present(self):
        """檢查 SD 卡是否已掛載。"""
        # 檢查路徑是否存在且是一個掛載點
        return os.path.exists(self.sd_mount_point) and os.path.ismount(self.sd_mount_point)

    def check_ssd_present(self):
        """
        檢查 SSD 是否已掛載且可寫入。
        使用 psutil 檢查 SSD 掛載點是否為有效檔案系統的掛載點，
        並嘗試在其內部創建一個臨時檔案來檢查寫入權限。
        """
        print(f"DEBUG (check_ssd_present): 開始檢查 SSD: '{self.ssd_mount_point}'")

        # 1. 首先檢查掛載點路徑是否存在
        if not os.path.exists(self.ssd_mount_point):
            print(f"DEBUG (check_ssd_present): 步驟 1 失敗 - SSD 掛載點路徑不存在: '{self.ssd_mount_point}'")
            return False
        print(f"DEBUG (check_ssd_present): 步驟 1 成功 - 路徑存在: '{self.ssd_mount_point}'")


        # 2. 接著使用 psutil 檢查它是否確實是一個掛載點
        is_mounted = False
        print(f"DEBUG (check_ssd_present): 步驟 2 - 檢查 psutil.disk_partitions()...")
        found_mount_info = []
        for partition in psutil.disk_partitions():
            found_mount_info.append(f"  偵測到分割區: {partition.device}, 掛載點: {partition.mountpoint}, 檔案系統: {partition.fstype}")
            if partition.mountpoint == self.ssd_mount_point:
                is_mounted = True
                print(f"DEBUG (check_ssd_present): 步驟 2 成功 - psutil 偵測到 '{self.ssd_mount_point}' 為有效掛載點。")
                break
        
        if not is_mounted:
            print(f"DEBUG (check_ssd_present): 步驟 2 失敗 - psutil 未將此路徑識別為掛載點。偵測到的掛載點：")
            for info in found_mount_info:
                print(f"DEBUG (check_ssd_present): {info}")
            return False

        # 3. 最後，測試寫入權限
        test_file = os.path.join(self.ssd_mount_point, ".write_test_temp")
        print(f"DEBUG (check_ssd_present): 步驟 3 - 嘗試在 '{self.ssd_mount_point}' 建立測試檔案 '{test_file}' 進行寫入測試...")
        try:
            with open(test_file, 'w') as f:
                f.write("test")
            os.remove(test_file)
            print(f"DEBUG (check_ssd_present): 步驟 3 成功 - 寫入測試成功。")
            return True
        except IOError as e:
            print(f"DEBUG (check_ssd_present): 步驟 3 失敗 - SSD 寫入測試失敗: {e}")
            print(f"DEBUG (check_ssd_present): 這通常表示沒有足夠的寫入權限。")
            return False
        except Exception as e:
            print(f"DEBUG (check_ssd_present): 步驟 3 失敗 - SSD 寫入測試時發生意外錯誤: {e}")
            return False


    def _scan_and_copy_sd_card(self):
        """掃描 SD 卡並開始複製過程。"""
        if not self.check_sd_card_present():
            self.status_message = "SD card not mounted."
            self.is_copying = False
            self._update_ui()
            return
        
        if not self.check_ssd_present():
            self.status_message = "SSD not detected or not writable!"
            self.is_copying = False
            self._update_ui()
            return

        self.is_copying = True
        self.status_message = "Scanning SD card..."
        self.total_files = 0
        self.copied_files = 0
        self.skipped_files = 0
        self.error_files = 0
        self.progress_percent = 0.0
        self._update_ui()

        files_to_copy = []
        # 遍歷 SD 卡目錄中的所有檔案
        for root, _, files in os.walk(self.sd_mount_point):
            for file in files:
                file_path = os.path.join(root, file)
                # 忽略隱藏檔案 (以 '.' 開頭的檔案)
                if not os.path.basename(file_path).startswith('.'):
                    files_to_copy.append(file_path)
        
        self.total_files = len(files_to_copy)
        if self.total_files == 0:
            self.status_message = "No files found on SD card."
            self.is_copying = False
            self._update_ui()
            return

        self.status_message = "Copying files..."
        self._update_ui()

        for i, src_file_path in enumerate(files_to_copy):
            # 如果複製被取消，則停止
            if not self.is_copying:
                self.status_message = "Copying cancelled."
                break
            
            # 在複製每個檔案前重新檢查 SSD 的存在性和可寫入性，提高穩健性
            if not self.check_ssd_present():
                self.status_message = "SSD disconnected during copy!"
                self.is_copying = False
                self._update_ui()
                break # 如果 SSD 在複製過程中斷開，則停止複製
            
            creation_date = self._get_file_creation_date(src_file_path)
            dest_subdir = os.path.join(self.ssd_mount_point, creation_date)
            
            self.current_file = os.path.basename(src_file_path)
            self._copy_file(src_file_path, dest_subdir)
            
            # 更新進度百分比 (已處理檔案數 / 總檔案數)
            self.progress_percent = ((self.copied_files + self.skipped_files + self.error_files) / self.total_files) * 100
            self._update_ui()

        # 複製完成後的狀態更新
        if self.is_copying: # 檢查是否是正常完成 (沒有被取消)
            self.status_message = f"Copy complete! Copied: {self.copied_files}, Skipped: {self.skipped_files}, Errors: {self.error_files}"
            self.progress_percent = 100.0
        self.is_copying = False # 設置為非複製狀態
        self._update_ui()

    def start_copy(self):
        """在新的執行緒中啟動 SD 卡複製程序。"""
        if not self.is_copying:
            self.copy_thread = threading.Thread(target=self._scan_and_copy_sd_card, daemon=True)
            self.copy_thread.start()
            print("SD card copy process started.")
        else:
            print("Copy process already running.")

    def stop_copy(self):
        """停止複製程序。"""
        if self.is_copying:
            self.is_copying = False
            self.status_message = "Copying cancelled by user."
            print("SD card copy process requested to stop.")
            self._update_ui()

    def main_loop(self):
        """主循環，用於定期檢查 SD 卡和 SSD 並自動啟動複製。"""
        last_sd_state = False
        last_ssd_state = False
        while True:
            current_sd_state = self.check_sd_card_present()
            current_ssd_state = self.check_ssd_present()

            # 根據裝置狀態更新狀態訊息
            if not current_ssd_state and not self.is_copying:
                self.status_message = "Please insert SSD."
            elif current_ssd_state and not current_sd_state and not self.is_copying:
                self.status_message = "Waiting for SD card..."
            elif current_ssd_state and current_sd_state and not self.is_copying and last_sd_state and last_ssd_state:
                # 避免重複觸發，如果兩者都已經存在且程式不在複製狀態
                self.status_message = "Ready to copy (SD and SSD present)."

            # 偵測到 SD 卡和 SSD 都存在，且之前 SD 卡不存在，並且程式不在複製狀態時，啟動複製
            if current_sd_state and current_ssd_state and not last_sd_state and not self.is_copying:
                print("SD card and SSD detected! Starting copy process...")
                self.start_copy()
            # 偵測到 SD 卡被移除
            elif not current_sd_state and last_sd_state and not self.is_copying:
                print("SD card removed.")
            
            last_sd_state = current_sd_state
            last_ssd_state = current_ssd_state # 更新 SSD 的上次狀態
            self._update_ui() # 定期更新 UI，即使沒有在複製

            time.sleep(5) # 每 5 秒檢查一次

if __name__ == '__main__':
    def ui_update_callback(data):
        """這是 UI 更新的回調函數，用於在控制台印出狀態。"""
        print(f"\n--- UI Update ---")
        print(f"  Is Copying: {data['is_copying']}")
        print(f"  Current File: {data['current_file']}")
        print(f"  Progress: {data['progress_percent']:.2f}%")
        print(f"  Total Files: {data['total_files']}")
        print(f"  Copied Files: {data['copied_files']}")
        print(f"  Skipped Files: {data['skipped_files']}")
        print(f"  Error Files: {data['error_files']}")
        print(f"  Status: {data['status_message']}")
        print(f"  SSD Present: {data['ssd_present']}")
        print(f"-----------------\n")

    # 初始化 SDCopyManager
    # 請確保你的 Raspberry Pi 上，SSD 實際掛載在 /media/norman/新增磁碟區
    # SD 卡通常會自動掛載在 /media/pi/SD_CARD，但如果不同請修改
    manager = SDCopyManager(ssd_mount_point="/media/norman/新增磁碟區", sd_mount_point="/media/pi/SD_CARD")
    manager.set_event_callback(ui_update_callback)

    # --- 模擬資料區塊 (僅用於測試，實際運行時程式會讀取真實裝置) ---
    print("\n--- 模擬資料設定 (僅供測試目的) ---")
    print("這些模擬資料夾和檔案用於在沒有實體裝置時測試程式邏輯。")
    print("在實際 Raspberry Pi 上，請確保你的實體 SD 卡和 SSD 已經正確掛載。")
    
    mock_sd_path = "./mock_sd_card"
    mock_ssd_path = "./mock_ssd_data" # 這個路徑是模擬的 SSD，不會影響真實 SSD 的判斷

    os.makedirs(os.path.join(mock_sd_path, "2023-01-01"), exist_ok=True)
    os.makedirs(os.path.join(mock_sd_path, "2023-01-02"), exist_ok=True)
    
    with open(os.path.join(mock_sd_path, "2023-01-01", "photo1.jpg"), "w") as f: f.write("content1_photo1")
    with open(os.path.join(mock_sd_path, "2023-01-01", "photo2.jpg"), "w") as f: f.write("content2_photo2")
    with open(os.path.join(mock_sd_path, "2023-01-02", "video1.mp4"), "w") as f: f.write("video_content_a")
    
    # 這個檔案將在複製時觸發命名衝突（如果 photo1.jpg 已經存在且內容不同）
    with open(os.path.join(mock_sd_path, "2023-01-01", "photo1.jpg"), "w") as f: f.write("content1_diff") 
    
    print(f"已建立模擬 SD 卡資料夾： {mock_sd_path}")
    print(f"程式將嘗試寫入到實際的 SSD 掛載點： {manager.ssd_mount_point}")
    print("-----------------------------------\n")

    print("正在啟動 SDCopyManager 主循環。")
    print("請確保你的實體 SD 卡插入到 '/media/pi/SD_CARD'，且實體 SSD 掛載在 '/media/norman/新增磁碟區'。")
    
    # 在獨立的執行緒中啟動主循環，以保持程式的響應性
    threading.Thread(target=manager.main_loop, daemon=True).start()

    try:
        # 主執行緒保持活躍，以允許 daemon 執行緒繼續運行
        while True:
            time.sleep(1) 
    except KeyboardInterrupt:
        print("\nExiting SDCopyManager application.")