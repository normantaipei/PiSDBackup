import os
import shutil
import hashlib
import time
from datetime import datetime
import threading
import json
import psutil # Used for checking mount points

class SDCopyManager:
    """
    Manages the file copying process from external USB storage devices to an SSD.
    Detects USB device insertion, copies files to the SSD based on creation date,
    and handles file duplicates and naming conflicts.
    """
    # Update the SSD mount point to your actual path
    def __init__(self, ssd_mount_point="/mnt/backup_drive"):
        self.ssd_mount_point = ssd_mount_point
        self.active_usb_source_mount_point = None # Current USB source mount point being copied from
        self.is_copying = False
        self.current_file = ""
        self.progress_percent = 0.0
        self.total_files = 0
        self.copied_files = 0
        self.skipped_files = 0
        self.error_files = 0
        self.status_message = "Waiting for external USB device or SSD..."
        self.copy_thread = None
        self.event_callback = None # Callback function for UI updates
        self._last_ssd_status = None # Tracks the last detected status of the SSD (True/False)
        self._processed_usb_devices = set() # Tracks USB devices that have been processed/copied

        # Ensure the SSD mount point directory exists
        # This will create it if it doesn't exist, but it won't mount the drive.
        os.makedirs(self.ssd_mount_point, exist_ok=True)
        print(f"SDCopyManager initialized. SSD: {self.ssd_mount_point}")
        self._update_ui() # Update UI on initialization

    def set_event_callback(self, callback):
        """Sets a callback function for sending updates to the UI during copying."""
        self.event_callback = callback
        self._update_ui() # Send initial status immediately after setting callback

    def _update_ui(self):
        """Invokes the callback function to update the UI"""
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
                'ssd_present': self.check_ssd_present(verbose=False),
                'active_usb_source': self.active_usb_source_mount_point
            }
            self.event_callback(status_data)
        
    def _get_file_hash(self, filepath):
        """Calculates the SHA256 hash of a file."""
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
        """Attempts to get the file's creation date (or modification date as fallback)."""
        try:
            timestamp = os.stat(filepath).st_birthtime
        except AttributeError:
            # Fallback to modification time if creation time is not available (e.g., on some Linux file systems)
            timestamp = os.stat(filepath).st_mtime
        return datetime.fromtimestamp(timestamp).strftime('%Y-%m-%d')

    def _copy_file(self, src_file_path, dest_dir):
        """
        Copies a single file, handling naming conflicts and content duplication.
        """
        filename = os.path.basename(src_file_path)
        dest_file_path = os.path.join(dest_dir, filename)
        
        os.makedirs(dest_dir, exist_ok=True) # Ensure the destination directory exists

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
        Detects all external USB storage device mount points that are not the SSD.
        It excludes system partitions and the known SSD mount point.
        """
        usb_devices = []
        # Define common system mount point prefixes that we don't want to copy from
        system_mount_point_prefixes = ['/', '/boot', '/etc', '/dev', '/proc', '/sys', '/run', '/tmp', '/var']

        print("\nDEBUG (get_available_usb_source_devices): Starting scan for all disk partitions...")
        for partition in psutil.disk_partitions():
            mountpoint = partition.mountpoint
            device_name = partition.device
            fstype = partition.fstype

            print(f"DEBUG: Checking partition: Device={device_name}, Mountpoint={mountpoint}, FileSystem={fstype}")

            # 1. Exclude system mount points
            is_system_mount = False
            for prefix in system_mount_point_prefixes:
                if mountpoint == prefix or mountpoint.startswith(prefix + os.sep):
                    is_system_mount = True
                    break
            if is_system_mount and mountpoint != self.ssd_mount_point:
                print(f"DEBUG: Skipping (system mount point or subdirectory): {mountpoint}")
                continue

            # 2. Exclude the SSD mount point itself
            if mountpoint == self.ssd_mount_point:
                print(f"DEBUG: Skipping (this is the target SSD): {mountpoint}")
                continue

            # 3. Check if it's a removable device (e.g., USB stick, SD card).
            # On Linux, these are usually mounted under /media or /mnt or /run/media.
            # And device names are typically /dev/sdX or /dev/mmcblkX (SD card).
            is_removable_device_path = (mountpoint.startswith('/media/') or mountpoint.startswith('/mnt/') or mountpoint.startswith('/run/media/'))
            is_removable_device_type = (device_name.startswith('/dev/sd') or device_name.startswith('/dev/mmcblk') or device_name.startswith('/dev/loop')) # Added /dev/loop

            if is_removable_device_path and is_removable_device_type:
                print(f"DEBUG: Candidate external device found: {mountpoint} ({device_name})")
                # Additionally check if the mount point is readable and writable, and not read-only
                if os.access(mountpoint, os.R_OK) and os.access(mountpoint, os.W_OK):
                    test_file = os.path.join(mountpoint, f".write_test_{os.getpid()}")
                    try:
                        with open(test_file, 'w') as f:
                            f.write("test")
                        os.remove(test_file)
                        usb_devices.append(mountpoint)
                        print(f"Detected external USB source device: {mountpoint} ({device_name}) - writable")
                    except IOError as e:
                        print(f"Warning: Detected external device {mountpoint} but cannot write (read-only or permission denied): {e}")
                    except Exception as e:
                        print(f"Warning: Detected external device {mountpoint} but an unexpected error occurred during write test: {e}")
                else:
                    print(f"Warning: Detected external device {mountpoint} but it's not readable/writable or is read-only.")
            else:
                print(f"DEBUG: Skipping (does not match external device path or type): {mountpoint} ({device_name})")
        
        print(f"DEBUG (get_available_usb_source_devices): Scan finished. Found USB devices: {usb_devices}")
        return usb_devices


    def check_ssd_present(self, verbose=True):
        """
        Checks if the SSD is mounted and writable.
        Uses psutil to verify the SSD mount point is a valid filesystem mount point,
        and attempts to create a temporary file inside it to check write permissions.
        The verbose parameter controls whether detailed DEBUG messages are printed on each check.
        """
        current_status = False
        
        # 1. First, check if the mount point path exists
        if not os.path.exists(self.ssd_mount_point):
            if verbose or self._last_ssd_status is not False:
                print(f"ERROR: SSD mount point path does not exist: '{self.ssd_mount_point}'")
            self._last_ssd_status = False
            return False

        # 2. Then use psutil to check if it's actually a mount point
        is_mounted = False
        for partition in psutil.disk_partitions():
            if partition.mountpoint == self.ssd_mount_point:
                is_mounted = True
                break
        
        if not is_mounted:
            if verbose or self._last_ssd_status is not False:
                print(f"ERROR: psutil does not identify '{self.ssd_mount_point}' as a valid mount point.")
                print("List of detected mount points (for reference):")
                if verbose:
                    for p in psutil.disk_partitions():
                        print(f"   Device: {p.device}, Mountpoint: {p.mountpoint}, FileSystem: {p.fstype}")
            self._last_ssd_status = False
            return False

        # 3. Finally, test write permissions
        test_file = os.path.join(self.ssd_mount_point, ".write_test_temp")
        try:
            # Ensure the parent directory (SSD mount point) exists and is accessible for creating the test file
            # This is already handled by os.makedirs in __init__, but added here for robustness
            os.makedirs(os.path.dirname(test_file), exist_ok=True) 
            with open(test_file, 'w') as f:
                f.write("test")
            os.remove(test_file)
            current_status = True
            if verbose or self._last_ssd_status is not True:
                print(f"SSD detected and writable: '{self.ssd_mount_point}'")
        except FileNotFoundError as e:
            if verbose or self._last_ssd_status is not False:
                print(f"ERROR: SSD write test failed (directory not found or path error): {e}")
                print(f"Please confirm '{self.ssd_mount_point}' is the actual SSD mount point.")
            current_status = False
        except IOError as e:
            if verbose or self._last_ssd_status is not False:
                print(f"ERROR: SSD write test failed (permission denied or read-only): {e}")
                print(f"Please check write permissions for '{self.ssd_mount_point}'.")
            current_status = False
        except Exception as e:
            if verbose or self._last_ssd_status is not False:
                print(f"ERROR: An unexpected error occurred during SSD write test: {e}")
            current_status = False

        self._last_ssd_status = current_status
        return current_status


    def _scan_and_copy_from_usb_source(self):
        """Scans and starts the copying process from the detected USB source device."""
        if not self.active_usb_source_mount_point:
            self.status_message = "No active USB source device selected or detected."
            self.is_copying = False
            self._update_ui()
            return
        
        if not self.check_ssd_present():
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
        for root, _, files in os.walk(self.active_usb_source_mount_point):
            for file in files:
                file_path = os.path.join(root, file)
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
            if not self.is_copying: # Check if copy was cancelled
                self.status_message = "Copying cancelled."
                break
            
            # Re-check SSD presence and writability before copying each file for robustness
            if not self.check_ssd_present():
                self.status_message = "SSD disconnected during copy! Copy aborted."
                self.is_copying = False
                self._update_ui()
                break # Stop copying if SSD disconnects
            
            creation_date = self._get_file_creation_date(src_file_path)
            dest_subdir = os.path.join(self.ssd_mount_point, creation_date)
            
            self.current_file = os.path.basename(src_file_path)
            self._copy_file(src_file_path, dest_subdir)
            
            # Update progress percentage (processed files / total files)
            self.progress_percent = ((self.copied_files + self.skipped_files + self.error_files) / self.total_files) * 100
            self._update_ui()

        # Status update after copying is finished
        if self.is_copying: # Check if it completed normally (not cancelled)
            self.status_message = f"Copy complete! Copied: {self.copied_files}, Skipped: {self.skipped_files}, Errors: {self.error_files}"
            self.progress_percent = 100.0
            # Add the successfully copied device to the processed set
            if self.active_usb_source_mount_point:
                self._processed_usb_devices.add(self.active_usb_source_mount_point)

        self.is_copying = False # Set to not copying state
        self.active_usb_source_mount_point = None # Clear active source after copy
        self._update_ui()

    def start_copy(self):
        """Starts the USB device copying process in a new thread."""
        if not self.is_copying:
            # If active_usb_source_mount_point is not set yet (e.g., initial call)
            if not self.active_usb_source_mount_point:
                available_usb_sources = self.get_available_usb_source_devices()
                unprocessed_usb_sources = [dev for dev in available_usb_sources if dev not in self._processed_usb_devices]
                if not unprocessed_usb_sources:
                    self.status_message = "No external USB devices found to copy from or all have been processed."
                    self._update_ui()
                    print("No external USB devices found to copy from or all have been processed.")
                    return
                self.active_usb_source_mount_point = unprocessed_usb_sources[0] # Select the first unprocessed device

            print(f"Selected USB source device: {self.active_usb_source_mount_point}")

            self.copy_thread = threading.Thread(target=self._scan_and_copy_from_usb_source, daemon=True)
            self.copy_thread.start()
            print("USB device copy process started.")
        else:
            print("Copy process already running.")

    def stop_copy(self):
        """Stops the copying process."""
        if self.is_copying:
            self.is_copying = False
            self.status_message = "Copying cancelled by user."
            print("USB device copy process requested to stop.")
            self._update_ui()

    def main_loop(self):
        """Main loop for periodically checking USB devices and SSD and automatically starting copy."""
        last_usb_devices_present = False
        
        # Perform an initial detection at the start of the loop and set initial state
        current_usb_devices = self.get_available_usb_source_devices()
        last_usb_devices_present = bool(current_usb_devices)
        self.check_ssd_present(verbose=True) # Print SSD status verbosely on first check

        while True:
            current_usb_devices = self.get_available_usb_source_devices()
            current_usb_devices_present = bool(current_usb_devices)
            current_ssd_state = self.check_ssd_present(verbose=False) # Check without verbose DEBUG output in loop

            # Update status message based on device states
            if self.is_copying:
                # If currently copying, the status message is handled by _scan_and_copy_from_usb_source
                pass
            elif not current_ssd_state:
                self.status_message = "Please insert SSD."
            elif current_ssd_state and not current_usb_devices_present:
                self.status_message = "Waiting for external USB device..."
            elif current_ssd_state and current_usb_devices_present:
                unprocessed_usb_devices = [dev for dev in current_usb_devices if dev not in self._processed_usb_devices]
                if unprocessed_usb_devices:
                    self.status_message = f"Ready to copy (new USB device(s) {unprocessed_usb_devices} and SSD present)."
                else:
                    self.status_message = f"USB device(s) {current_usb_devices} and SSD present (no copying needed)."
            
            # Detect and start copying logic
            # Trigger if USB devices and SSD are present, and not currently copying,
            # and there are unprocessed USB devices.
            if current_usb_devices_present and current_ssd_state and not self.is_copying:
                unprocessed_usb_devices_now = [dev for dev in current_usb_devices if dev not in self._processed_usb_devices]

                if unprocessed_usb_devices_now:
                    self.active_usb_source_mount_point = unprocessed_usb_devices_now[0] # Select the first unprocessed device
                    print(f"Detected new/unprocessed external USB device {self.active_usb_source_mount_point} and SSD! Starting copy process...")
                    self.start_copy() # start_copy will use active_usb_source_mount_point
            
            # Detect USB device removal
            # When USB devices are removed, clear them from the processed list so they can be re-copied on re-insertion
            if not current_usb_devices_present and last_usb_devices_present:
                print("External USB device removed.")
                self._processed_usb_devices.clear() # Clear all processed USB devices
                self.active_usb_source_mount_point = None
                self.total_files = 0
                self.copied_files = 0
                self.skipped_files = 0
                self.error_files = 0
                self.progress_percent = 0.0
                self.current_file = ""
            
            last_usb_devices_present = current_usb_devices_present
            
            self._update_ui() # Periodically update UI

            time.sleep(5) # Check every 5 seconds

if __name__ == '__main__':
    def ui_update_callback(data):
        """This is the UI update callback function for printing status to the console."""
        print(f"\n--- UI Update ---")
        print(f"   Is Copying: {data['is_copying']}")
        print(f"   Current File: {data['current_file']}")
        print(f"   Progress: {data['progress_percent']:.2f}%")
        print(f"   Total Files: {data['total_files']}")
        print(f"   Copied Files: {data['copied_files']}")
        print(f"   Skipped Files: {data['skipped_files']}")
        print(f"   Error Files: {data['error_files']}")
        print(f"   Status: {data['status_message']}")
        print(f"   SSD Present: {data['ssd_present']}")
        print(f"   Active USB Source: {data['active_usb_source']}")
        print(f"-----------------\n")

    # Initialize SDCopyManager
    # IMPORTANT: Ensure your SSD is actually mounted at this path on your Raspberry Pi!
    manager = SDCopyManager(ssd_mount_point="/mnt/backup_drive") 
    manager.set_event_callback(ui_update_callback)

    # --- Mock Data Block (for testing purposes only, the program reads real devices during actual run) ---
    print("\n--- Mock Data Setup (for testing purposes only) ---")
    print("These mock folders and files are used to test program logic without physical devices.")
    print("On an actual Raspberry Pi, please ensure your physical USB device and SSD are correctly mounted.")
    
    mock_usb_path = "./mock_usb_device_A" 
    mock_usb_path_B = "./mock_usb_device_B"

    os.makedirs(os.path.join(mock_usb_path, "2023-01-01"), exist_ok=True)
    os.makedirs(os.path.join(mock_usb_path, "2023-01-02"), exist_ok=True)
    os.makedirs(os.path.join(mock_usb_path_B, "2024-03-15"), exist_ok=True)
    
    with open(os.path.join(mock_usb_path, "2023-01-01", "photo1.jpg"), "w") as f: f.write("content1_photo1")
    with open(os.path.join(mock_usb_path, "2023-01-01", "photo2.jpg"), "w") as f: f.write("content2_photo2")
    with open(os.path.join(mock_usb_path, "2023-01-02", "video1.mp4"), "w") as f: f.write("video_content_a")
    
    with open(os.path.join(mock_usb_path_B, "2024-03-15", "document.pdf"), "w") as f: f.write("pdf_content")

    with open(os.path.join(mock_usb_path, "2023-01-01", "photo1.jpg"), "w") as f: f.write("content1_diff") 
    
    print(f"Mock USB device folders created: {mock_usb_path} and {mock_usb_path_B}")
    print(f"The program will attempt to write to the actual SSD mount point: {manager.ssd_mount_point}")
    print("-----------------------------------\n")

    print("Starting SDCopyManager main loop.")
    print("Please ensure your physical USB device is inserted into a location like '/media/pi/YOUR_USB_LABEL' and your physical SSD is mounted at '/mnt/backup_drive'.")
    
    threading.Thread(target=manager.main_loop, daemon=True).start()

    try:
        while True:
            time.sleep(1) 
    except KeyboardInterrupt:
        print("\nExiting SDCopyManager application.")