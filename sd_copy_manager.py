import os
import shutil
import hashlib
import time
from datetime import datetime
import threading
import json
import psutil # Added for checking mount points

class SDCopyManager:
    """
    管理 SD 卡到 SSD 的檔案複製過程。
    偵測 SD 卡插入，依照建立日期將檔案複製到 SSD，
    並處理檔案重複與命名衝突。
    """
    def __init__(self, ssd_mount_point="/mnt/ssd", sd_mount_point="/media/pi/SD_CARD"):
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
        self.event_callback = None # Callback function for UI updates

        # Ensure SSD mount point exists (creates parent dirs if necessary)
        os.makedirs(self.ssd_mount_point, exist_ok=True)
        print(f"SDCopyManager initialized. SSD: {self.ssd_mount_point}, SD: {self.sd_mount_point}")
        self._update_ui() # Initial UI update for SSD status

    def set_event_callback(self, callback):
        """設定一個回調函數，用於在複製過程中向 UI 發送更新。"""
        self.event_callback = callback
        self._update_ui() # Send initial status when callback is set

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
                'ssd_present': self.check_ssd_present() # Added SSD presence status
            }
            self.event_callback(status_data)

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
            timestamp = os.stat(filepath).st_mtime
        return datetime.fromtimestamp(timestamp).strftime('%Y-%m-%d')

    def _copy_file(self, src_file_path, dest_dir):
        """
        複製單個檔案，處理命名衝突和內容重複。
        """
        filename = os.path.basename(src_file_path)
        dest_file_path = os.path.join(dest_dir, filename)
        
        os.makedirs(dest_dir, exist_ok=True)

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
        return os.path.exists(self.sd_mount_point) and os.path.ismount(self.sd_mount_point)

    def check_ssd_present(self):
        """
        檢查 SSD 是否已掛載且可寫入。
        我們使用 psutil 檢查 SSD 掛載點是否為有效檔案系統的掛載點，
        並嘗試在其內部創建一個臨時檔案來檢查寫入權限。
        """
        if not os.path.exists(self.ssd_mount_point):
            return False

        # Check if it's an actual mount point (more robust than just path existence)
        is_mounted = False
        for partition in psutil.disk_partitions():
            if partition.mountpoint == self.ssd_mount_point:
                is_mounted = True
                break
        
        if not is_mounted:
            return False

        # Test write permission
        test_file = os.path.join(self.ssd_mount_point, ".write_test")
        try:
            with open(test_file, 'w') as f:
                f.write("test")
            os.remove(test_file)
            return True
        except IOError as e:
            print(f"SSD write test failed: {e}")
            return False
        except Exception as e:
            print(f"Unexpected error during SSD write test: {e}")
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
        for root, _, files in os.walk(self.sd_mount_point):
            for file in files:
                file_path = os.path.join(root, file)
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
            if not self.is_copying:
                self.status_message = "Copying cancelled."
                break
            
            # Re-check SSD presence/writability before each file copy for robustness
            if not self.check_ssd_present():
                self.status_message = "SSD disconnected during copy!"
                self.is_copying = False
                self._update_ui()
                break # Stop copy if SSD becomes unavailable
            
            creation_date = self._get_file_creation_date(src_file_path)
            dest_subdir = os.path.join(self.ssd_mount_point, creation_date)
            
            self.current_file = os.path.basename(src_file_path)
            self._copy_file(src_file_path, dest_subdir)
            
            self.progress_percent = (self.copied_files + self.skipped_files + self.error_files) / self.total_files * 100
            self._update_ui()

        if self.is_copying:
            self.status_message = f"Copy complete! Copied: {self.copied_files}, Skipped: {self.skipped_files}, Errors: {self.error_files}"
            self.progress_percent = 100.0
        self.is_copying = False
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

            # Update status message if SSD is not present
            if not current_ssd_state and not self.is_copying:
                self.status_message = "Please insert SSD."
            elif current_ssd_state and not current_sd_state and not self.is_copying:
                self.status_message = "Waiting for SD card..."

            if current_sd_state and current_ssd_state and not last_sd_state and not self.is_copying:
                print("SD card and SSD detected! Starting copy process...")
                self.start_copy()
            elif not current_sd_state and last_sd_state and not self.is_copying:
                print("SD card removed.")
            
            last_sd_state = current_sd_state
            last_ssd_state = current_ssd_state # Update last SSD state
            self._update_ui() # Periodically update UI for SSD status even when not copying
            time.sleep(5) # Check every 5 seconds

if __name__ == '__main__':
    def ui_update_callback(data):
        print(f"\nUI Update: {json.dumps(data, indent=2)}")

    # Make sure to create these mock directories for testing
    # Use real paths if you're testing on a Raspberry Pi with actual devices
    manager = SDCopyManager(ssd_mount_point="./mock_ssd_data", sd_mount_point="./mock_sd_card")
    manager.set_event_callback(ui_update_callback)

    # Create some mock data for testing
    os.makedirs("./mock_sd_card/2023-01-01", exist_ok=True)
    os.makedirs("./mock_sd_card/2023-01-02", exist_ok=True)
    with open("./mock_sd_card/2023-01-01/photo1.jpg", "w") as f: f.write("content1")
    with open("./mock_sd_card/2023-01-01/photo2.jpg", "w") as f: f.write("content2")
    with open("./mock_sd_card/2023-01-02/video1.mp4", "w") as f: f.write("video_content_a")
    with open("./mock_sd_card/2023-01-02/video1_diff.mp4", "w") as f: f.write("video_content_b_diff") # Renamed for mock test
    # Simulate a file that will have a name collision
    with open("./mock_sd_card/2023-01-01/photo1.jpg", "w") as f: f.write("content1_diff") # This will trigger rename if 'content1' already copied

    print("Created mock SD card data and mock SSD destination: ./mock_ssd_data")
    print("Starting SDCopyManager main loop. Insert/remove mock SD card (by creating/deleting ./mock_sd_card directory) to test.")
    
    # You might need to manually create/delete ./mock_ssd_data to test SSD presence logic
    # e.g., before running: `rm -rf ./mock_ssd_data` to simulate no SSD
    # then `mkdir ./mock_ssd_data` to simulate SSD insertion

    threading.Thread(target=manager.main_loop, daemon=True).start()

    try:
        while True:
            time.sleep(1) 
    except KeyboardInterrupt:
        print("\nExiting SDCopyManager test.")