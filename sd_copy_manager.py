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
    管理外接 USB 儲存裝置到 SSD 的檔案複製過程。
    偵測 USB 裝置插入，依照建立日期將檔案複製到 SSD，
    並處理檔案重複與命名衝突。
    """
    # 將 SSD 掛載點更新為你的實際路徑
    def __init__(self, ssd_mount_point="/media/norman/新增磁碟區"):
        self.ssd_mount_point = ssd_mount_point
        self.active_usb_source_mount_point = None # 當前正在複製的 USB 來源掛載點
        self.is_copying = False
        self.current_file = ""
        self.progress_percent = 0.0
        self.total_files = 0
        self.copied_files = 0
        self.skipped_files = 0
        self.error_files = 0
        self.status_message = "Waiting for external USB device or SSD..."
        self.copy_thread = None
        self.event_callback = None # 用於 UI 更新的回調函數
        self._last_ssd_status = None # 追蹤 SSD 的上次偵測狀態 (True/False)

        # 確保 SSD 掛載點目錄存在 (如果必要，會建立父目錄)
        os.makedirs(self.ssd_mount_point, exist_ok=True)
        print(f"SDCopyManager initialized. SSD: {self.ssd_mount_point}")
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
                'ssd_present': self.check_ssd_present(verbose=False), # _update_ui 調用時不印出冗餘 DEBUG
                'active_usb_source': self.active_usb_source_mount_point # 新增當前活動的 USB 來源
            }
            self.event_callback(status_data)
        
        # 這裡的 SSD 狀態輸出會由 check_ssd_present 內部控制，只在狀態變化時印出
        # 移除了原有的固定 DEBUG 輸出

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
    
    def get_available_usb_source_devices(self):
        """
        偵測所有非 SSD 的外接 USB 儲存裝置掛載點。
        它會排除系統分割區和已知的 SSD 掛載點。
        """
        usb_devices = []
        # 定義常見的系統掛載點前綴，我們不希望從這些地方複製
        system_mount_point_prefixes = ['/', '/boot', '/etc', '/dev', '/proc', '/sys', '/run', '/tmp', '/var']

        # 這裡的偵測日誌輸出維持不變，因為它們對於排查 USB 裝置偵測問題很重要
        # print("\nDEBUG (get_available_usb_source_devices): 開始掃描所有磁碟分割區...")
        for partition in psutil.disk_partitions():
            mountpoint = partition.mountpoint
            device_name = partition.device
            fstype = partition.fstype # 新增：列印檔案系統類型

            # print(f"DEBUG: 正在檢查分割區: 裝置={device_name}, 掛載點={mountpoint}, 檔案系統={fstype}")

            # 1. 排除系統掛載點
            is_system_mount = False
            for prefix in system_mount_point_prefixes:
                if mountpoint.startswith(prefix) and len(mountpoint) > len(prefix):
                    is_system_mount = True
                    break
            if is_system_mount and mountpoint != self.ssd_mount_point:
                # print(f"DEBUG: 跳過（系統掛載點或子目錄）: {mountpoint}")
                continue

            # 2. 排除本身就是 SSD 的掛載點 (如果設定的 SSD 掛載點在系統路徑內，此處也需避免排除)
            if mountpoint == self.ssd_mount_point:
                # print(f"DEBUG: 跳過（這是目標 SSD）: {mountpoint}")
                continue

            # 3. 檢查是否為可移除裝置 (例如 USB 隨身碟, SD 卡)。
            # 在 Linux 上，這些通常會掛載在 /media 或 /mnt 或 /run/media 下。
            # 並且裝置名稱通常是 /dev/sdX 或 /dev/mmcblkX (SD 卡)。
            is_removable_device_path = (mountpoint.startswith('/media/') or mountpoint.startswith('/mnt/') or mountpoint.startswith('/run/media/'))
            is_removable_device_type = (device_name.startswith('/dev/sd') or device_name.startswith('/dev/mmcblk'))

            if is_removable_device_path and is_removable_device_type:
                # print(f"DEBUG: 符合潛在外接裝置條件: {mountpoint} ({device_name})")
                # 額外檢查掛載點是否可讀寫，並且不是只讀的
                if os.access(mountpoint, os.R_OK) and os.access(mountpoint, os.W_OK):
                    # 嘗試在掛載點創建一個臨時檔案來檢查寫入權限
                    test_file = os.path.join(mountpoint, f".write_test_{os.getpid()}")
                    try:
                        with open(test_file, 'w') as f:
                            f.write("test")
                        os.remove(test_file)
                        usb_devices.append(mountpoint)
                        # 只有在成功偵測到可用來源時才印出
                        print(f"偵測到外接 USB 來源裝置: {mountpoint} ({device_name})")
                    except IOError as e:
                        print(f"警告: 偵測到外接裝置 {mountpoint} 但無法寫入 (只讀或權限不足): {e}")
                    except Exception as e:
                        print(f"警告: 偵測到外接裝置 {mountpoint} 但寫入測試時發生意外錯誤: {e}")
                else:
                    print(f"警告: 偵測到外接裝置 {mountpoint} 但不可讀寫或只讀。")
            # else:
                # print(f"DEBUG: 跳過（不符合外接裝置路徑或裝置類型）：{mountpoint} ({device_name})")
        
        # print(f"DEBUG (get_available_usb_source_devices): 掃描結束。找到的 USB 裝置列表: {usb_devices}")
        return usb_devices


    def check_ssd_present(self, verbose=True):
        """
        檢查 SSD 是否已掛載且可寫入。
        使用 psutil 檢查 SSD 掛載點是否為有效檔案系統的掛載點，
        並嘗試在其內部創建一個臨時檔案來檢查寫入權限。
        verbose 參數控制是否在每次檢查時都印出詳細的 DEBUG 訊息。
        """
        current_status = False # 假設 SSD 不存在，直到證明為止
        
        # 1. 首先檢查掛載點路徑是否存在
        if not os.path.exists(self.ssd_mount_point):
            if verbose or self._last_ssd_status is not False: # 如果狀態從有變無，或首次偵測到無
                print(f"錯誤: SSD 掛載點路徑不存在: '{self.ssd_mount_point}'")
            self._last_ssd_status = False
            return False

        # 2. 接著使用 psutil 檢查它是否確實是一個掛載點
        is_mounted = False
        found_mount_info = []
        for partition in psutil.disk_partitions():
            if partition.mountpoint == self.ssd_mount_point:
                is_mounted = True
                break
            found_mount_info.append(f"  偵測到分割區: {partition.device}, 掛載點: {partition.mountpoint}, 檔案系統: {partition.fstype}")
        
        if not is_mounted:
            if verbose or self._last_ssd_status is not False:
                print(f"錯誤: psutil 未將 '{self.ssd_mount_point}' 識別為有效掛載點。")
                print("已偵測到的掛載點列表:")
                for info in found_mount_info:
                    print(f"  {info}")
            self._last_ssd_status = False
            return False

        # 3. 最後，測試寫入權限
        test_file = os.path.join(self.ssd_mount_point, ".write_test_temp")
        try:
            with open(test_file, 'w') as f:
                f.write("test")
            os.remove(test_file)
            current_status = True
            if verbose or self._last_ssd_status is not True: # 如果狀態從無變有，或首次偵測到有
                print(f"SSD 已偵測到並可寫入: '{self.ssd_mount_point}'")
        except IOError as e:
            if verbose or self._last_ssd_status is not False:
                print(f"錯誤: SSD 寫入測試失敗 (權限不足或只讀): {e}")
                print(f"請檢查 '{self.ssd_mount_point}' 的寫入權限。")
            current_status = False
        except Exception as e:
            if verbose or self._last_ssd_status is not False:
                print(f"錯誤: SSD 寫入測試時發生意外錯誤: {e}")
            current_status = False

        self._last_ssd_status = current_status # 更新 SSD 上次狀態
        return current_status


    def _scan_and_copy_from_usb_source(self):
        """從偵測到的 USB 來源裝置掃描並開始複製過程。"""
        if not self.active_usb_source_mount_point:
            self.status_message = "No active USB source device selected or detected."
            self.is_copying = False
            self._update_ui()
            return
        
        if not self.check_ssd_present(): # 這裡呼叫 check_ssd_present 會根據 verbose 參數控制輸出
            self.status_message = "SSD not detected or not writable! Copy aborted."
            self.is_copying = False
            self._update_ui()
            return

        self.is_copying = True
        self.status_message = f"Scanning USB device: {self.active_usb_source_mount_point}..."
        self.total_files = 0
        self.copied_files = 0
        self.skipped_files = 0
        self.error_files = 0
        self.progress_percent = 0.0
        self._update_ui()

        files_to_copy = []
        # 遍歷當前活動的 USB 來源裝置目錄中的所有檔案
        for root, _, files in os.walk(self.active_usb_source_mount_point):
            for file in files:
                file_path = os.path.join(root, file)
                # 忽略隱藏檔案 (以 '.' 開頭的檔案)
                if not os.path.basename(file_path).startswith('.'):
                    files_to_copy.append(file_path)
        
        self.total_files = len(files_to_copy)
        if self.total_files == 0:
            self.status_message = f"No files found on {self.active_usb_source_mount_point}."
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
            if not self.check_ssd_present(): # 這裡的檢查也會減少冗餘輸出
                self.status_message = "SSD disconnected during copy! Copy aborted."
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
        self.active_usb_source_mount_point = None # 複製完成後清除活動來源
        self._update_ui()

    def start_copy(self):
        """在新的執行緒中啟動 USB 裝置複製程序。"""
        if not self.is_copying:
            available_usb_sources = self.get_available_usb_source_devices()
            if not available_usb_sources:
                self.status_message = "No external USB devices found to copy from."
                self._update_ui()
                print("No external USB devices found to copy from.")
                return

            # 為了簡化，這裡選擇找到的第一個 USB 裝置作為來源。
            # 您可以修改此處，讓用戶選擇或實現更複雜的邏輯。
            self.active_usb_source_mount_point = available_usb_sources[0]
            print(f"Selected USB source device: {self.active_usb_source_mount_point}")

            self.copy_thread = threading.Thread(target=self._scan_and_copy_from_usb_source, daemon=True)
            self.copy_thread.start()
            print("USB device copy process started.")
        else:
            print("Copy process already running.")

    def stop_copy(self):
        """停止複製程序。"""
        if self.is_copying:
            self.is_copying = False
            self.status_message = "Copying cancelled by user."
            print("USB device copy process requested to stop.")
            self._update_ui()

    def main_loop(self):
        """主循環，用於定期檢查 USB 裝置和 SSD 並自動啟動複製。"""
        last_usb_devices_present = False
        # last_ssd_state 已經由 self._last_ssd_status 管理
        while True:
            current_usb_devices = self.get_available_usb_source_devices()
            current_usb_devices_present = bool(current_usb_devices) # 判斷是否有任何 USB 裝置存在
            current_ssd_state = self.check_ssd_present(verbose=False) # 在 main_loop 中檢查不應產生冗餘 DEBUG

            # 根據裝置狀態更新狀態訊息
            if not current_ssd_state and not self.is_copying:
                self.status_message = "Please insert SSD."
            elif current_ssd_state and not current_usb_devices_present and not self.is_copying:
                self.status_message = "Waiting for external USB device..."
            elif current_ssd_state and current_usb_devices_present and not self.is_copying and last_usb_devices_present and current_ssd_state:
                # 避免重複觸發，如果兩者都已經存在且程式不在複製狀態
                # 這裡的 last_ssd_state 已經不再需要，因為 SSD 的狀態變化由 check_ssd_present 內部控制
                self.status_message = f"Ready to copy (USB device(s) {current_usb_devices} and SSD present)."

            # 偵測到 USB 裝置和 SSD 都存在，且之前沒有 USB 裝置，並且程式不在複製狀態時，啟動複製
            if current_usb_devices_present and current_ssd_state and not last_usb_devices_present and not self.is_copying:
                print(f"External USB device(s) {current_usb_devices} and SSD detected! Starting copy process...")
                self.start_copy()
            # 偵測到 USB 裝置被移除
            elif not current_usb_devices_present and last_usb_devices_present and not self.is_copying:
                print("External USB device removed.")
            
            last_usb_devices_present = current_usb_devices_present
            # last_ssd_state 移除了，因為狀態變化由 check_ssd_present 內部管理
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
        print(f"  Active USB Source: {data['active_usb_source']}")
        print(f"-----------------\n")

    # 初始化 SDCopyManager
    # 請確保你的 Raspberry Pi 上，SSD 實際掛載在 /media/norman/新增磁碟區
    manager = SDCopyManager(ssd_mount_point="/media/norman/新增磁碟區")
    manager.set_event_callback(ui_update_callback)

    # --- 模擬資料區塊 (僅用於測試，實際運行時程式會讀取真實裝置) ---
    print("\n--- 模擬資料設定 (僅供測試目的) ---")
    print("這些模擬資料夾和檔案用於在沒有實體裝置時測試程式邏輯。")
    print("在實際 Raspberry Pi 上，請確保你的實體 USB 裝置和 SSD 已經正確掛載。")
    
    # 這裡的 mock_sd_path 現在會被 get_available_usb_source_devices 偵測到
    mock_usb_path = "./mock_usb_device_A" 
    mock_usb_path_B = "./mock_usb_device_B" # 模擬第二個 USB 裝置
    mock_ssd_path = "./mock_ssd_data" # 這個路徑是模擬的 SSD，不會影響真實 SSD 的判斷

    os.makedirs(os.path.join(mock_usb_path, "2023-01-01"), exist_ok=True)
    os.makedirs(os.path.join(mock_usb_path, "2023-01-02"), exist_ok=True)
    os.makedirs(os.path.join(mock_usb_path_B, "2024-03-15"), exist_ok=True)
    
    with open(os.path.join(mock_usb_path, "2023-01-01", "photo1.jpg"), "w") as f: f.write("content1_photo1")
    with open(os.path.join(mock_usb_path, "2023-01-01", "photo2.jpg"), "w") as f: f.write("content2_photo2")
    with open(os.path.join(mock_usb_path, "2023-01-02", "video1.mp4"), "w") as f: f.write("video_content_a")
    
    with open(os.path.join(mock_usb_path_B, "2024-03-15", "document.pdf"), "w") as f: f.write("pdf_content")

    # 這個檔案將在複製時觸發命名衝突（如果 photo1.jpg 已經存在且內容不同）
    with open(os.path.join(mock_usb_path, "2023-01-01", "photo1.jpg"), "w") as f: f.write("content1_diff") 
    
    print(f"已建立模擬 USB 裝置資料夾： {mock_usb_path} 和 {mock_usb_path_B}")
    print(f"程式將嘗試寫入到實際的 SSD 掛載點： {manager.ssd_mount_point}")
    print("-----------------------------------\n")

    print("正在啟動 SDCopyManager 主循環。")
    print("請確保你的實體 USB 裝置插入到類似 '/media/pi/YOUR_USB_LABEL' 的位置，且實體 SSD 掛載在 '/media/norman/新增磁碟區'。")
    
    # 在獨立的執行緒中啟動主循環，以保持程式的響應性
    threading.Thread(target=manager.main_loop, daemon=True).start()

    try:
        # 主執行緒保持活躍，以允許 daemon 執行緒繼續運行
        while True:
            time.sleep(1) 
    except KeyboardInterrupt:
        print("\nExiting SDCopyManager application.")