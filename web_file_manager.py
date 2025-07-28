# web_file_manager.py

import os
import json
import shutil
import mimetypes
from pathlib import Path
from urllib.parse import unquote
from PIL import Image
import psutil
from flask import Flask, render_template_string, request, jsonify, send_file, redirect, url_for
import threading # Added for concurrent running

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 100 * 1024 * 1024  # 100MB max file size

# HTML模板
# 注意: 为了避免Python字符串中的引号冲突和提高可读性，这里使用三重引号，
# 并且因为HTML内容较长，我们将它放在一个单独的字符串变量中。

HTML_TEMPLATE = '''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>USB File Manager</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: 'Segoe UI', Arial, sans-serif; background: #f5f5f5; }
        .header { background: #2c3e50; color: white; padding: 1rem; }
        .container { max-width: 1200px; margin: 0 auto; padding: 20px; }
        .usb-selector { background: white; padding: 20px; border-radius: 8px; margin-bottom: 20px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }
        .file-manager { background: white; border-radius: 8px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }
        .toolbar { padding: 20px; border-bottom: 1px solid #eee; display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 10px;}
        .breadcrumb { font-size: 14px; color: #666; }
        .breadcrumb a { color: #3498db; text-decoration: none; }
        .breadcrumb a:hover { text-decoration: underline; }
        .file-list { padding: 20px; }
        .file-item { display: flex; align-items: center; padding: 12px; border-bottom: 1px solid #f0f0f0; transition: background 0.2s; }
        .file-item:hover { background: #f8f9fa; }
        .file-icon { width: 40px; height: 40px; margin-right: 15px; display: flex; align-items: center; justify-content: center; font-size: 24px;}
        .file-icon img { max-width: 40px; max-height: 40px; border-radius: 4px; object-fit: cover; }
        .file-info { flex: 1; }
        .file-name { font-weight: 500; margin-bottom: 4px; }
        .file-meta { font-size: 12px; color: #666; }
        .file-actions { display: flex; gap: 10px; flex-wrap: wrap; justify-content: flex-end;}
        .btn { padding: 6px 12px; border: none; border-radius: 4px; cursor: pointer; text-decoration: none; font-size: 12px; white-space: nowrap; }
        .btn-primary { background: #3498db; color: white; }
        .btn-danger { background: #e74c3c; color: white; }
        .btn-secondary { background: #95a5a6; color: white; }
        .modal { display: none; position: fixed; top: 0; left: 0; width: 100%; height: 100%; background: rgba(0,0,0,0.5); z-index: 1000; overflow: auto; }
        .modal-content { background: white; margin: 10% auto; padding: 20px; width: 80%; max-width: 500px; border-radius: 8px; }
        .form-group { margin-bottom: 15px; }
        .form-group label { display: block; margin-bottom: 5px; font-weight: 500; }
        .form-group input[type="text"] { width: 100%; padding: 8px; border: 1px solid #ddd; border-radius: 4px; }
        .no-usb { text-align: center; padding: 40px; color: #666; }
        .loading { text-align: center; padding: 20px; }
        .image-preview { max-width: 100%; height: auto; display: block; margin: 10px auto; border-radius: 4px; } /* Changed max-height to auto */
        .modal-content.image-modal { max-width: 95%; max-height: 95%; width: auto; display: flex; flex-direction: column; justify-content: center; align-items: center; } /* Adjusted image modal content for better centering */
        .modal-content.image-modal .image-preview { flex-shrink: 0; }
    </style>
</head>
<body>
    <div class="header">
        <div class="container">
            <h1>🗂️ USB File Manager</h1>
        </div>
    </div>

    <div class="container">
        <div class="usb-selector">
            <h3>Select USB Device</h3>
            <div id="usbList">Loading...</div>
        </div>

        <div class="file-manager" id="fileManager" style="display: none;">
            <div class="toolbar">
                <div class="breadcrumb" id="breadcrumb"></div>
                <div>
                    <button class="btn btn-primary" onclick="refreshFiles()">🔄 Refresh</button>
                    <input type="file" id="uploadFile" style="display: none;" onchange="uploadFile()" multiple>
                    <button class="btn btn-secondary" onclick="document.getElementById('uploadFile').click()">📤 Upload File</button>
                </div>
            </div>
            <div class="file-list" id="fileList"></div>
        </div>
    </div>

    <div id="renameModal" class="modal">
        <div class="modal-content">
            <h3>Rename</h3>
            <div class="form-group">
                <label>New Name:</label>
                <input type="text" id="newFileName" />
            </div>
            <div style="text-align: right; margin-top: 20px;">
                <button class="btn btn-secondary" onclick="closeModal('renameModal')">Cancel</button>
                <button class="btn btn-primary" onclick="confirmRename()">Confirm</button>
            </div>
        </div>
    </div>

    <div id="imageModal" class="modal">
        <div class="modal-content image-modal">
            <div style="text-align: right; width: 100%; margin-bottom: 10px;">
                <button class="btn btn-secondary" onclick="closeModal('imageModal')">✕ Close</button>
            </div>
            <img id="imagePreview" class="image-preview" />
        </div>
    </div>

    <script>
        let currentUSB = '';
        let currentPath = '';
        let renameTarget = '';

        // Load USB device list
        async function loadUSBDevices() {
            try {
                const response = await fetch('/api/usb-devices');
                const devices = await response.json();
                const usbList = document.getElementById('usbList');
                
                if (devices.length === 0) {
                    usbList.innerHTML = '<div class="no-usb">No USB devices detected.</div>';
                    return;
                }
                
                let html = '<div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(250px, 1fr)); gap: 15px;">';
                devices.forEach(device => {
                    html += `
                        <div class="file-item" style="border: 1px solid #ddd; border-radius: 8px; cursor: pointer;" 
                             onclick="selectUSB('${device.mountpoint}')">
                            <div class="file-icon">💾</div>
                            <div class="file-info">
                                <div class="file-name">${device.device}</div>
                                <div class="file-meta">Capacity: ${device.size} | Filesystem: ${device.fstype}</div>
                                <div class="file-meta">Mountpoint: ${device.mountpoint}</div>
                            </div>
                        </div>
                    `;
                });
                html += '</div>';
                usbList.innerHTML = html;
            } catch (error) {
                document.getElementById('usbList').innerHTML = '<div class="no-usb">Error loading USB devices.</div>';
                console.error("Error loading USB devices:", error);
            }
        }

        // Select USB device
        function selectUSB(mountpoint) {
            currentUSB = mountpoint;
            currentPath = '';
            document.getElementById('fileManager').style.display = 'block';
            loadFiles();
        }

        // Load file list
        async function loadFiles() {
            try {
                const response = await fetch(`/api/files?usb=${encodeURIComponent(currentUSB)}&path=${encodeURIComponent(currentPath)}`);
                const data = await response.json();
                
                if (data.error) {
                    document.getElementById('fileList').innerHTML = `<div class="no-usb">Error: ${data.error}</div>`;
                    return;
                }
                updateBreadcrumb();
                displayFiles(data.files);
            } catch (error) {
                document.getElementById('fileList').innerHTML = '<div class="no-usb">Error loading files.</div>';
                console.error("Error loading files:", error);
            }
        }

        // Update breadcrumb navigation
        function updateBreadcrumb() {
            const breadcrumb = document.getElementById('breadcrumb');
            let html = `<a href="#" onclick="navigateTo('')">🏠 Root</a>`;
            
            if (currentPath) {
                const parts = currentPath.split('/').filter(p => p);
                let buildPath = '';
                parts.forEach(part => {
                    buildPath += '/' + part;
                    html += ` > <a href="#" onclick="navigateTo('${buildPath.substring(1)}')">${part}</a>`;
                });
            }
            breadcrumb.innerHTML = html;
        }

        // Display file list
        function displayFiles(files) {
            const fileList = document.getElementById('fileList');
            let html = '';
            
            files.forEach(file => {
                const isImage = file.type === 'image';
                const iconHtml = isImage ? 
                    `<img src="/api/thumbnail?usb=${encodeURIComponent(currentUSB)}&path=${encodeURIComponent(file.path)}" alt="thumbnail" onerror="this.style.display='none'; this.closest('.file-icon').innerHTML='🖼️'">` :
                    (file.is_directory ? '📁' : '📄');
                
                html += `
                    <div class="file-item">
                        <div class="file-icon">${iconHtml}</div>
                        <div class="file-info">
                            <div class="file-name">${file.name}</div>
                            <div class="file-meta">
                                ${file.is_directory ? 'Folder' : `Size: ${file.size}`}
                                ${file.modified ? ` | Modified: ${file.modified}` : ''}
                            </div>
                        </div>
                        <div class="file-actions">
                            ${file.is_directory ? 
                                `<button class="btn btn-primary" onclick="navigateTo('${file.path}')">Open</button>` :
                                `<button class="btn btn-primary" onclick="downloadFile('${file.path}')">Download</button>`}
                            ${isImage ? `<button class="btn btn-secondary" onclick="previewImage('${file.path}')">Preview</button>` : ''}
                            <button class="btn btn-secondary" onclick="renameFile('${file.path}', '${file.name}')">Rename</button>
                            <button class="btn btn-danger" onclick="deleteFile('${file.path}', '${file.name}')">Delete</button>
                        </div>
                    </div>
                `;
            });
            
            if (html === '') {
                html = '<div class="no-usb">This folder is empty.</div>';
            }
            
            fileList.innerHTML = html;
        }

        // Navigate to specified path
        function navigateTo(path) {
            currentPath = path;
            loadFiles();
        }

        // Refresh files
        function refreshFiles() {
            loadFiles();
        }

        // Download file
        function downloadFile(filePath) {
            const url = `/api/download?usb=${encodeURIComponent(currentUSB)}&path=${encodeURIComponent(filePath)}`;
            window.open(url, '_blank');
        }

        // Preview image
        function previewImage(filePath) {
            const img = document.getElementById('imagePreview');
            img.src = `/api/download?usb=${encodeURIComponent(currentUSB)}&path=${encodeURIComponent(filePath)}`;
            document.getElementById('imageModal').style.display = 'block';
            document.querySelector('#imageModal .modal-content').style.display = 'flex'; // Ensure flex for centering
        }

        // Close modal
        function closeModal(modalId) {
            document.getElementById(modalId).style.display = 'none';
            if (modalId === 'imageModal') {
                document.getElementById('imagePreview').src = ''; // Clear image source
            }
        }

        // Rename file
        function renameFile(filePath, currentName) {
            renameTarget = filePath;
            document.getElementById('newFileName').value = currentName;
            document.getElementById('renameModal').style.display = 'block';
        }

        // Confirm rename
        async function confirmRename() {
            const newName = document.getElementById('newFileName').value.trim();
            if (!newName) return;
            
            try {
                const response = await fetch('/api/rename', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        usb: currentUSB,
                        oldPath: renameTarget,
                        newName: newName
                    })
                });
                
                const result = await response.json();
                if (result.success) {
                    closeModal('renameModal');
                    loadFiles();
                } else {
                    alert('Rename failed: ' + result.error);
                }
            } catch (error) {
                alert('An error occurred during rename.');
            }
        }

        // Delete file
        async function deleteFile(filePath, fileName) {
            if (!confirm(`Are you sure you want to delete "${fileName}"?`)) return;
            
            try {
                const response = await fetch('/api/delete', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        usb: currentUSB,
                        path: filePath
                    })
                });
                
                const result = await response.json();
                if (result.success) {
                    loadFiles();
                } else {
                    alert('Delete failed: ' + result.error);
                }
            } catch (error) {
                alert('An error occurred during deletion.');
            }
        }

        // Upload file
        async function uploadFile() {
            const fileInput = document.getElementById('uploadFile');
            const files = fileInput.files;
            
            if (files.length === 0) return;
            
            const formData = new FormData();
            formData.append('usb', currentUSB);
            formData.append('path', currentPath);
            
            for (let i = 0; i < files.length; i++) {
                formData.append('files', files[i]);
            }
            
            try {
                const response = await fetch('/api/upload', {
                    method: 'POST',
                    body: formData
                });
                
                const result = await response.json();
                if (result.success) {
                    loadFiles();
                    fileInput.value = ''; // Clear selected files
                } else {
                    alert('Upload failed: ' + result.error);
                }
            } catch (error) {
                alert('An error occurred during upload.');
            }
        }

        // Click outside modal to close
        window.onclick = function(event) {
            const renameModal = document.getElementById('renameModal');
            const imageModal = document.getElementById('imageModal');
            if (event.target === renameModal) {
                closeModal('renameModal');
            }
            if (event.target === imageModal) {
                closeModal('imageModal');
            }
        }

        // Initialize on page load
        document.addEventListener('DOMContentLoaded', function() {
            loadUSBDevices();
        });
    </script>
</body>
</html>
'''

def get_usb_devices():
    """Gets all USB devices"""
    usb_devices = []
    partitions = psutil.disk_partitions()

    for partition in partitions:
        # Filter for USB devices (usually mounted under /media or /mnt)
        # Added a check for common removable drive types and if the device is actually mounted
        if 'removable' in partition.opts or any(keyword in partition.mountpoint.lower() for keyword in ['/media', '/mnt']):
            try:
                # Ensure the mountpoint is accessible before attempting disk_usage
                if os.path.exists(partition.mountpoint):
                    usage = psutil.disk_usage(partition.mountpoint)
                    usb_devices.append({
                        'device': partition.device,
                        'mountpoint': partition.mountpoint,
                        'fstype': partition.fstype,
                        'size': format_size(usage.total)
                    })
            except Exception as e:
                # print(f"Error accessing partition {partition.mountpoint}: {e}") # Debugging
                continue

    return usb_devices

def format_size(bytes_size):
    """Formats file size into human-readable format"""
    for unit in ['B', 'KB', 'MB', 'GB', 'TB', 'PB']: # Added PB
        if bytes_size < 1024.0:
            return f"{bytes_size:.1f} {unit}"
        bytes_size /= 1024.0
    return f"{bytes_size:.1f} EB" # Fallback for extremely large sizes

def get_file_info(base_path, file_name):
    """Gets file information for a given path within a base path"""
    full_path = os.path.join(base_path, file_name)
    
    try:
        stat = os.stat(full_path)
        is_dir = os.path.isdir(full_path)

        # Determine file type
        file_type = 'directory' if is_dir else 'file'
        if not is_dir:
            mime_type, _ = mimetypes.guess_type(full_path)
            if mime_type and mime_type.startswith('image/'):
                file_type = 'image'
        
        # Relative path for the UI
        relative_path = os.path.relpath(full_path, base_path).replace('\\', '/')
        if relative_path == ".": # If it's the root of the USB, path should be empty for correct UI navigation
            relative_path = ""

        return {
            'name': file_name, # Use only the filename for display name
            'path': relative_path, # Use relative path for UI actions
            'is_directory': is_dir,
            'size': format_size(stat.st_size) if not is_dir else '',
            'modified': datetime.fromtimestamp(stat.st_mtime).strftime('%Y-%m-%d %H:%M:%S'), # Format timestamp
            'type': file_type
        }
    except Exception as e:
        # print(f"Error getting file info for {full_path}: {e}") # Debugging
        return None

def create_thumbnail(image_path, thumbnail_size=(100, 100)):
    """Creates a thumbnail for an image"""
    try:
        with Image.open(image_path) as img:
            img.thumbnail(thumbnail_size, Image.Resampling.LANCZOS)
            # Convert to RGB to ensure compatibility for JPEG saving
            if img.mode in ('RGBA', 'LA', 'P'):
                img = img.convert('RGB')
            return img
    except Exception as e:
        print(f"Failed to create thumbnail: {e}")
        return None

@app.route('/')
def index():
    return render_template_string(HTML_TEMPLATE)

@app.route('/api/usb-devices')
def api_usb_devices():
    return jsonify(get_usb_devices())

@app.route('/api/files')
def api_files():
    usb_path = request.args.get('usb', '')
    relative_path = request.args.get('path', '')

    if not usb_path:
        return jsonify({'error': 'USB path not specified'}), 400

    # Sanitize and validate paths
    usb_path = Path(unquote(usb_path)).resolve()
    if not usb_path.is_dir():
        return jsonify({'error': 'Invalid USB path'}), 400

    current_dir = (usb_path / unquote(relative_path)).resolve()

    # Ensure the current directory is still within the selected USB device
    try:
        current_dir.relative_to(usb_path)
    except ValueError:
        return jsonify({'error': 'Access denied: Path outside USB device'}), 403

    if not current_dir.is_dir():
        return jsonify({'error': 'Path is not a directory or does not exist'}), 404

    try:
        files = []
        for item in os.listdir(current_dir):
            file_info = get_file_info(str(usb_path), str(current_dir / item)) # Pass usb_path as base
            if file_info:
                files.append(file_info)
        
        # Sort: directories first, then by name
        files.sort(key=lambda x: (not x['is_directory'], x['name'].lower()))
        
        return jsonify({'files': files})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/thumbnail')
def api_thumbnail():
    usb_path_str = request.args.get('usb', '')
    relative_path_str = request.args.get('path', '')

    if not usb_path_str or not relative_path_str:
        return '', 404

    usb_path = Path(unquote(usb_path_str)).resolve()
    full_path = (usb_path / unquote(relative_path_str)).resolve()

    # Security check: ensure the file is within the USB mountpoint
    try:
        full_path.relative_to(usb_path)
    except ValueError:
        return '', 403 # Forbidden

    if not full_path.is_file():
        return '', 404

    try:
        thumbnail = create_thumbnail(str(full_path))
        if thumbnail:
            from io import BytesIO
            img_io = BytesIO()
            thumbnail.save(img_io, 'JPEG', quality=85)
            img_io.seek(0)
            return send_file(img_io, mimetype='image/jpeg')
    except Exception as e:
        print(f"Error serving thumbnail for {full_path}: {e}") # Debugging
        pass

    return '', 404

@app.route('/api/download')
def api_download():
    usb_path_str = request.args.get('usb', '')
    relative_path_str = request.args.get('path', '')

    if not usb_path_str or not relative_path_str:
        return jsonify({'error': 'Missing parameters'}), 400

    usb_path = Path(unquote(usb_path_str)).resolve()
    full_path = (usb_path / unquote(relative_path_str)).resolve()

    # Security check: ensure the file is within the USB mountpoint
    try:
        full_path.relative_to(usb_path)
    except ValueError:
        return jsonify({'error': 'Access denied: Path outside USB device'}), 403

    if not full_path.is_file() or full_path.is_dir(): # Ensure it's a file, not a directory
        return jsonify({'error': 'File not found or is a directory'}), 404

    return send_file(str(full_path), as_attachment=True)

@app.route('/api/rename', methods=['POST'])
def api_rename():
    data = request.json
    usb_path_str = data.get('usb', '')
    old_relative_path_str = data.get('oldPath', '')
    new_name = data.get('newName', '')

    if not all([usb_path_str, old_relative_path_str, new_name]):
        return jsonify({'success': False, 'error': 'Missing parameters'})

    usb_path = Path(unquote(usb_path_str)).resolve()
    old_full_path = (usb_path / unquote(old_relative_path_str)).resolve()

    # Security check: ensure the file is within the USB mountpoint
    try:
        old_full_path.relative_to(usb_path)
    except ValueError:
        return jsonify({'success': False, 'error': 'Access denied: Path outside USB device'}), 403

    # Construct new full path
    new_full_path = (old_full_path.parent / new_name).resolve()

    # Security check: ensure the new path is also within the USB mountpoint
    try:
        new_full_path.relative_to(usb_path)
    except ValueError:
        return jsonify({'success': False, 'error': 'Access denied: New path outside USB device'}), 403

    if not old_full_path.exists():
        return jsonify({'success': False, 'error': 'Original file/folder not found'})

    if new_full_path.exists():
        return jsonify({'success': False, 'error': 'Target file/folder already exists'})

    try:
        os.rename(str(old_full_path), str(new_full_path))
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/delete', methods=['POST'])
def api_delete():
    data = request.json
    usb_path_str = data.get('usb', '')
    relative_path_str = data.get('path', '')

    if not usb_path_str or not relative_path_str:
        return jsonify({'success': False, 'error': 'Missing parameters'})

    usb_path = Path(unquote(usb_path_str)).resolve()
    full_path = (usb_path / unquote(relative_path_str)).resolve()

    # Security check: ensure the file is within the USB mountpoint
    try:
        full_path.relative_to(usb_path)
    except ValueError:
        return jsonify({'success': False, 'error': 'Access denied: Path outside USB device'}), 403

    if not full_path.exists():
        return jsonify({'success': False, 'error': 'File/folder not found'})

    try:
        if full_path.is_dir():
            shutil.rmtree(str(full_path))
        else:
            os.remove(str(full_path))
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/upload', methods=['POST'])
def api_upload():
    usb_path_str = request.form.get('usb', '')
    relative_path_str = request.form.get('path', '')

    if not usb_path_str:
        return jsonify({'success': False, 'error': 'USB path not specified'})

    usb_path = Path(unquote(usb_path_str)).resolve()
    target_dir = (usb_path / unquote(relative_path_str)).resolve()

    # Security check: ensure the target directory is within the USB mountpoint
    try:
        target_dir.relative_to(usb_path)
    except ValueError:
        return jsonify({'success': False, 'error': 'Access denied: Target path outside USB device'}), 403

    if not target_dir.is_dir():
        return jsonify({'success': False, 'error': 'Target directory not found or is not a directory'})

    files = request.files.getlist('files')
    if not files:
        return jsonify({'success': False, 'error': 'No files selected for upload'})

    try:
        for file in files:
            if file.filename:
                # Basic filename sanitization to prevent directory traversal issues
                filename = Path(file.filename).name # Get only the filename, discard any path info
                file_path = target_dir / filename
                file.save(str(file_path))
        
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

# No __name__ == '__main__' block here, as it will be run from main.py
