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
from datetime import datetime
import threading # Added for concurrent running

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 100 * 1024 * 1024  # 100MB max file size

# 限定文件讀取的根目錄
# 請注意：如果此路徑不存在或無權限，程式將無法正常運作。
# 在部署前請確保此路徑是有效的。
BASE_DIRECTORY = "/media/norman/新增磁碟區"

# HTML模板
HTML_TEMPLATE = '''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Google Photos Style File Manager</title>
    <link href="https://fonts.googleapis.com/icon?family=Material+Icons" rel="stylesheet">
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: 'Roboto', sans-serif; background: #f8f9fa; color: #3c4043; }
        .header { background: #fff; color: #202124; padding: 16px 24px; border-bottom: 1px solid #dadce0; display: flex; align-items: center; justify-content: space-between; box-shadow: 0 1px 2px 0 rgba(60,64,67,0.3), 0 1px 3px 1px rgba(60,64,67,0.15); }
        .header h1 { font-size: 22px; font-weight: 400; display: flex; align-items: center; }
        .header h1 .material-icons { margin-right: 8px; font-size: 28px; color: #4285f4; }
        .container { max-width: 1400px; margin: 0 auto; padding: 20px; }
        .file-manager { background: #fff; border-radius: 8px; box-shadow: 0 1px 3px rgba(0,0,0,0.12), 0 1px 2px rgba(0,0,0,0.24); }
        .toolbar { padding: 16px 24px; border-bottom: 1px solid #dadce0; display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 10px; }
        .breadcrumb { font-size: 14px; color: #5f6368; display: flex; align-items: center; flex-wrap: wrap; }
        .breadcrumb a { color: #1a73e8; text-decoration: none; padding: 4px 0; }
        .breadcrumb a:hover { text-decoration: underline; }
        .breadcrumb .separator { margin: 0 8px; color: #bdc1c6; }

        .file-grid {
            padding: 20px;
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(180px, 1fr)); /* Adjusted for more items per row */
            gap: 16px; /* Spacing between items */
        }
        .file-item {
            background: #fff;
            border: 1px solid #dadce0;
            border-radius: 8px;
            overflow: hidden;
            display: flex;
            flex-direction: column;
            cursor: pointer;
            transition: box-shadow 0.2s, transform 0.2s;
            position: relative;
        }
        .file-item:hover {
            box-shadow: 0 4px 8px rgba(0,0,0,0.1);
            transform: translateY(-2px);
        }
        .file-thumbnail {
            width: 100%;
            height: 140px; /* Fixed height for thumbnails */
            background: #e8eaed;
            display: flex;
            align-items: center;
            justify-content: center;
            overflow: hidden;
            position: relative;
            flex-shrink: 0;
        }
        .file-thumbnail img {
            max-width: 100%;
            max-height: 100%;
            object-fit: contain; /* Use contain to show full image, even if it leaves empty space */
            display: block;
            margin: auto;
        }
        .file-thumbnail .folder-icon, .file-thumbnail .file-icon-placeholder {
            font-size: 60px;
            color: #5f6368;
        }
        .file-info-bottom {
            padding: 12px;
            text-align: left;
            flex-grow: 1;
            display: flex;
            flex-direction: column;
            justify-content: space-between;
        }
        .file-name {
            font-weight: 500;
            font-size: 15px;
            color: #202124;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
            margin-bottom: 4px;
        }
        .file-meta {
            font-size: 12px;
            color: #5f6368;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }
        .file-actions-overlay {
            position: absolute;
            top: 0;
            left: 0;
            right: 0;
            bottom: 0;
            background: rgba(0,0,0,0.6);
            display: flex;
            flex-direction: column;
            justify-content: center;
            align-items: center;
            gap: 10px;
            opacity: 0;
            transition: opacity 0.2s ease-in-out;
            border-radius: 8px;
        }
        .file-item:hover .file-actions-overlay {
            opacity: 1;
        }
        .btn {
            padding: 8px 16px;
            border: none;
            border-radius: 4px;
            cursor: pointer;
            text-decoration: none;
            font-size: 14px;
            white-space: nowrap;
            transition: background 0.2s, box-shadow 0.2s;
            display: flex;
            align-items: center;
            gap: 5px;
        }
        .btn-primary { background: #1a73e8; color: white; }
        .btn-primary:hover { background: #1764cc; box-shadow: 0 2px 4px rgba(0,0,0,0.2); }
        .btn-danger { background: #ea4335; color: white; }
        .btn-danger:hover { background: #d93025; box-shadow: 0 2px 4px rgba(0,0,0,0.2); }
        .btn-secondary { background: #f0f0f0; color: #3c4043; border: 1px solid #dadce0; }
        .btn-secondary:hover { background: #e8e8e8; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }
        
        /* Modals */
        .modal { display: none; position: fixed; top: 0; left: 0; width: 100%; height: 100%; background: rgba(0,0,0,0.7); z-index: 1000; overflow: auto; align-items: center; justify-content: center; }
        .modal-content { background: white; margin: auto; padding: 24px; border-radius: 8px; width: 90%; max-width: 500px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }
        .form-group { margin-bottom: 20px; }
        .form-group label { display: block; margin-bottom: 8px; font-weight: 500; color: #202124; }
        .form-group input[type="text"] { width: 100%; padding: 10px; border: 1px solid #dadce0; border-radius: 4px; font-size: 16px; }
        .form-actions { text-align: right; }
        .modal-content h3 { font-size: 20px; font-weight: 500; margin-bottom: 20px; color: #202124; }

        .image-modal-content {
            background: transparent;
            padding: 0;
            max-width: 95vw;
            max-height: 95vh;
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
        }
        .image-modal-content img {
            max-width: 100%;
            max-height: 100%;
            object-fit: contain;
            border-radius: 8px;
            box-shadow: 0 4px 10px rgba(0,0,0,0.3);
        }
        .image-modal-close {
            background: #fff;
            color: #3c4043;
            border-radius: 50%;
            width: 36px;
            height: 36px;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 24px;
            position: absolute;
            top: 20px;
            right: 20px;
            cursor: pointer;
            box-shadow: 0 2px 4px rgba(0,0,0,0.2);
            z-index: 1001;
        }
        .no-content {
            text-align: center;
            padding: 40px;
            color: #5f6368;
            font-size: 18px;
        }
        .upload-input {
            display: none; /* Hide the default file input */
        }
    </style>
</head>
<body>
    <div class="header">
        <h1><span class="material-icons">photo_library</span>Google Photos Style File Manager</h1>
        <div>
            <button class="btn btn-secondary" onclick="refreshFiles()"><span class="material-icons">refresh</span>Refresh</button>
            <input type="file" id="uploadFile" class="upload-input" onchange="uploadFile()" multiple>
            <button class="btn btn-primary" onclick="document.getElementById('uploadFile').click()"><span class="material-icons">cloud_upload</span>Upload File</button>
        </div>
    </div>

    <div class="container">
        <div class="file-manager" id="fileManager">
            <div class="toolbar">
                <div class="breadcrumb" id="breadcrumb"></div>
            </div>
            <div class="file-grid" id="fileList">
                <div class="no-content">Loading files...</div>
            </div>
        </div>
    </div>

    <div id="renameModal" class="modal">
        <div class="modal-content">
            <h3>Rename</h3>
            <div class="form-group">
                <label for="newFileName">New Name:</label>
                <input type="text" id="newFileName" />
            </div>
            <div class="form-actions">
                <button class="btn btn-secondary" onclick="closeModal('renameModal')">Cancel</button>
                <button class="btn btn-primary" onclick="confirmRename()">Confirm</button>
            </div>
        </div>
    </div>

    <div id="imageModal" class="modal">
        <div class="image-modal-close" onclick="closeModal('imageModal')"><span class="material-icons">close</span></div>
        <div class="modal-content image-modal-content">
            <img id="imagePreview" />
        </div>
    </div>

    <script>
        let currentPath = ''; // currentPath will be relative to BASE_DIRECTORY
        let renameTarget = ''; // Stores the full path of the item to be renamed

        // Load file list
        async function loadFiles() {
            try {
                const response = await fetch(`/api/files?path=${encodeURIComponent(currentPath)}`);
                const data = await response.json();
                
                if (data.error) {
                    document.getElementById('fileList').innerHTML = `<div class="no-content">Error: ${data.error}</div>`;
                    return;
                }
                updateBreadcrumb();
                displayFiles(data.files);
            } catch (error) {
                document.getElementById('fileList').innerHTML = '<div class="no-content">Error loading files.</div>';
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
                    html += `<span class="separator">/</span> <a href="#" onclick="navigateTo('${buildPath}')">${part}</a>`;
                });
            }
            breadcrumb.innerHTML = html;
        }

        // Display file list in a Google Photos-like grid
        function displayFiles(files) {
            const fileList = document.getElementById('fileList');
            let html = '';
            
            files.forEach(file => {
                const isImage = file.type === 'image';
                const fileExtension = file.name.split('.').pop().toLowerCase();
                let iconHtml = '';

                if (file.is_directory) {
                    iconHtml = `<span class="material-icons folder-icon">folder</span>`;
                } else if (isImage) {
                    // Use actual thumbnail for images
                    iconHtml = `<img src="/api/thumbnail?path=${encodeURIComponent(file.path)}" alt="${file.name}" onerror="this.onerror=null; this.src=''; this.style.display='none'; this.closest('.file-thumbnail').innerHTML='<span class=\\"material-icons file-icon-placeholder\\">image_not_supported</span>';">`;
                } else {
                    // Generic icons for other file types
                    const genericFileIcon = {
                        'pdf': 'picture_as_pdf',
                        'doc': 'article', 'docx': 'article',
                        'xls': 'grid_on', 'xlsx': 'grid_on',
                        'ppt': 'slideshow', 'pptx': 'slideshow',
                        'zip': 'folder_zip', 'rar': 'folder_zip', '7z': 'folder_zip',
                        'txt': 'description',
                        'mp3': 'music_note', 'wav': 'music_note',
                        'mp4': 'videocam', 'avi': 'videocam',
                        'json': 'data_object', 'xml': 'data_object', 'html': 'code', 'py': 'code', 'js': 'code', 'css': 'code'
                    }[fileExtension] || 'insert_drive_file'; // Default icon
                    iconHtml = `<span class="material-icons file-icon-placeholder">${genericFileIcon}</span>`;
                }

                html += `
                    <div class="file-item">
                        <div class="file-thumbnail" onclick="${file.is_directory ? `MapsTo('${file.path}')` : (isImage ? `previewImage('${file.path}')` : `downloadFile('${file.path}')`)}">
                            ${iconHtml}
                        </div>
                        <div class="file-info-bottom">
                            <div class="file-name" title="${file.name}">${file.name}</div>
                            <div class="file-meta">
                                ${file.is_directory ? 'Folder' : `${file.size}`}
                                ${file.modified ? `<br>${file.modified}` : ''}
                            </div>
                        </div>
                        <div class="file-actions-overlay">
                            ${file.is_directory ? 
                                `<button class="btn btn-primary" onclick="navigateTo('${file.path}')"><span class="material-icons">folder_open</span>Open</button>` :
                                `<button class="btn btn-primary" onclick="downloadFile('${file.path}')"><span class="material-icons">download</span>Download</button>`}
                            ${isImage ? `<button class="btn btn-secondary" onclick="previewImage('${file.path}')"><span class="material-icons">visibility</span>Preview</button>` : ''}
                            <button class="btn btn-secondary" onclick="renameFile('${file.path}', '${file.name}')"><span class="material-icons">edit</span>Rename</button>
                            <button class="btn btn-danger" onclick="deleteFile('${file.path}', '${file.name}')"><span class="material-icons">delete</span>Delete</button>
                        </div>
                    </div>
                `;
            });
            
            if (html === '') {
                html = '<div class="no-content">This folder is empty.</div>';
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
            const url = `/api/download?path=${encodeURIComponent(filePath)}`;
            window.open(url, '_blank');
        }

        // Preview image
        function previewImage(filePath) {
            const img = document.getElementById('imagePreview');
            img.src = `/api/download?path=${encodeURIComponent(filePath)}`;
            document.getElementById('imageModal').style.display = 'flex'; // Use flex to center
        }

        // Close modal
        function closeModal(modalId) {
            document.getElementById(modalId).style.display = 'none';
            if (modalId === 'imageModal') {
                document.getElementById('imagePreview').src = ''; // Clear image source
            }
        }

        // Rename file/folder
        function renameFile(filePath, currentName) {
            renameTarget = filePath;
            document.getElementById('newFileName').value = currentName;
            document.getElementById('renameModal').style.display = 'flex'; // Use flex to center
        }

        // Confirm rename
        async function confirmRename() {
            const newName = document.getElementById('newFileName').value.trim();
            if (!newName) {
                alert('New name cannot be empty.');
                return;
            }
            
            try {
                const response = await fetch('/api/rename', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
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

        // Delete file/folder
        async function deleteFile(filePath, fileName) {
            if (!confirm(`Are you sure you want to delete "${fileName}"?`)) return;
            
            try {
                const response = await fetch('/api/delete', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
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

        // Close modal when clicking outside
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
            loadFiles(); // Directly load files from the BASE_DIRECTORY
        });
    </script>
</body>
</html>
'''

def format_size(bytes_size):
    """Formats file size into human-readable format"""
    for unit in ['B', 'KB', 'MB', 'GB', 'TB', 'PB']: # Added PB
        if bytes_size < 1024.0:
            return f"{bytes_size:.1f} {unit}"
        bytes_size /= 1024.0
    return f"{bytes_size:.1f} EB" # Fallback for extremely large sizes

def get_file_info(full_path, base_directory):
    """Gets file information for a given path within the base directory"""
    try:
        stat = os.stat(full_path)
        is_dir = os.path.isdir(full_path)

        # Determine file type
        file_type = 'directory' if is_dir else 'file'
        if not is_dir:
            mime_type, _ = mimetypes.guess_type(full_path)
            if mime_type and mime_type.startswith('image/'):
                file_type = 'image'
        
        # Relative path for the UI (relative to BASE_DIRECTORY)
        relative_path = Path(full_path).relative_to(base_directory).as_posix()

        return {
            'name': os.path.basename(full_path), # Use only the filename for display name
            'path': relative_path, # Use relative path for UI actions
            'is_directory': is_dir,
            'size': format_size(stat.st_size) if not is_dir else '',
            'modified': datetime.fromtimestamp(stat.st_mtime).strftime('%Y-%m-%d %H:%M:%S'), # Format timestamp
            'type': file_type
        }
    except Exception as e:
        print(f"Error getting file info for {full_path}: {e}") # Debugging
        return None

def create_thumbnail(image_path, thumbnail_size=(300, 300)): # Increased thumbnail size for better grid display
    """Creates a thumbnail for an image"""
    try:
        with Image.open(image_path) as img:
            # Maintain aspect ratio by fitting within the thumbnail_size
            img.thumbnail(thumbnail_size, Image.Resampling.LANCZOS)
            # Convert to RGB to ensure compatibility for JPEG saving
            if img.mode in ('RGBA', 'LA', 'P'):
                img = img.convert('RGB')
            return img
    except Exception as e:
        print(f"Failed to create thumbnail for {image_path}: {e}")
        return None

@app.route('/')
def index():
    return render_template_string(HTML_TEMPLATE)

# 移除 api_usb_devices 路由，因為現在只處理一個固定目錄

@app.route('/api/files')
def api_files():
    relative_path_str = request.args.get('path', '')

    # 確保基本目錄存在且可訪問
    base_dir_path = Path(BASE_DIRECTORY).resolve()
    if not base_dir_path.is_dir():
        return jsonify({'error': f'Base directory not found or not accessible: {BASE_DIRECTORY}'}), 500

    # 解析目標目錄，並確保它在基本目錄內
    current_dir = (base_dir_path / unquote(relative_path_str)).resolve()

    try:
        current_dir.relative_to(base_dir_path)
    except ValueError:
        return jsonify({'error': 'Access denied: Path outside allowed directory'}), 403

    if not current_dir.is_dir():
        return jsonify({'error': 'Path is not a directory or does not exist'}), 404

    try:
        files = []
        for item in os.listdir(current_dir):
            full_item_path = current_dir / item
            file_info = get_file_info(str(full_item_path), str(base_dir_path)) # Pass base_dir_path
            if file_info:
                files.append(file_info)
        
        # Sort: directories first, then by name
        files.sort(key=lambda x: (not x['is_directory'], x['name'].lower()))
        
        return jsonify({'files': files})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/thumbnail')
def api_thumbnail():
    relative_path_str = request.args.get('path', '')

    if not relative_path_str:
        return '', 404

    base_dir_path = Path(BASE_DIRECTORY).resolve()
    full_path = (base_dir_path / unquote(relative_path_str)).resolve()

    # Security check: ensure the file is within the base directory
    try:
        full_path.relative_to(base_dir_path)
    except ValueError:
        return '', 403 # Forbidden

    if not full_path.is_file():
        return '', 404

    try:
        thumbnail = create_thumbnail(str(full_path))
        if thumbnail:
            from io import BytesIO
            img_io = BytesIO()
            # Save as JPEG for web display, ensure quality
            thumbnail.save(img_io, 'JPEG', quality=85)
            img_io.seek(0)
            return send_file(img_io, mimetype='image/jpeg')
    except Exception as e:
        print(f"Error serving thumbnail for {full_path}: {e}") # Debugging
        pass

    return '', 404 # If thumbnail creation fails or not an image

@app.route('/api/download')
def api_download():
    relative_path_str = request.args.get('path', '')

    if not relative_path_str:
        return jsonify({'error': 'Missing parameters'}), 400

    base_dir_path = Path(BASE_DIRECTORY).resolve()
    full_path = (base_dir_path / unquote(relative_path_str)).resolve()

    # Security check: ensure the file is within the base directory
    try:
        full_path.relative_to(base_dir_path)
    except ValueError:
        return jsonify({'error': 'Access denied: Path outside allowed directory'}), 403

    if not full_path.is_file() or full_path.is_dir(): # Ensure it's a file, not a directory
        return jsonify({'error': 'File not found or is a directory'}), 404

    return send_file(str(full_path), as_attachment=True, download_name=full_path.name) # Use download_name

@app.route('/api/rename', methods=['POST'])
def api_rename():
    data = request.json
    old_relative_path_str = data.get('oldPath', '')
    new_name = data.get('newName', '')

    if not all([old_relative_path_str, new_name]):
        return jsonify({'success': False, 'error': 'Missing parameters'})

    base_dir_path = Path(BASE_DIRECTORY).resolve()
    old_full_path = (base_dir_path / unquote(old_relative_path_str)).resolve()

    # Security check: ensure the file is within the base directory
    try:
        old_full_path.relative_to(base_dir_path)
    except ValueError:
        return jsonify({'success': False, 'error': 'Access denied: Path outside allowed directory'}), 403

    # Construct new full path
    # Use old_full_path.parent to ensure the new file is in the same directory
    new_full_path = (old_full_path.parent / new_name).resolve()

    # Security check: ensure the new path is also within the base directory
    try:
        new_full_path.relative_to(base_dir_path)
    except ValueError:
        return jsonify({'success': False, 'error': 'Access denied: New path outside allowed directory'}), 403

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
    relative_path_str = data.get('path', '')

    if not relative_path_str:
        return jsonify({'success': False, 'error': 'Missing parameters'})

    base_dir_path = Path(BASE_DIRECTORY).resolve()
    full_path = (base_dir_path / unquote(relative_path_str)).resolve()

    # Security check: ensure the file is within the base directory
    try:
        full_path.relative_to(base_dir_path)
    except ValueError:
        return jsonify({'success': False, 'error': 'Access denied: Path outside allowed directory'}), 403

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
    relative_path_str = request.form.get('path', '')

    base_dir_path = Path(BASE_DIRECTORY).resolve()
    target_dir = (base_dir_path / unquote(relative_path_str)).resolve()

    # Security check: ensure the target directory is within the base directory
    try:
        target_dir.relative_to(base_dir_path)
    except ValueError:
        return jsonify({'success': False, 'error': 'Access denied: Target path outside allowed directory'}), 403

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

# 通常在開發環境中直接運行，但在實際部署中可能會有不同的啟動方式
if __name__ == '__main__':
    # 檢查並創建基本目錄，如果它不存在
    if not os.path.exists(BASE_DIRECTORY):
        try:
            os.makedirs(BASE_DIRECTORY)
            print(f"Created base directory: {BASE_DIRECTORY}")
        except OSError as e:
            print(f"Error creating base directory {BASE_DIRECTORY}: {e}")
            print("Please ensure the directory exists and has correct permissions.")
            exit()
    
    # 使用 threading 模組來同時運行 Flask 應用
    # 這段代碼僅用於本地開發和測試，不建議用於生產環境
    # 在生產環境中，請使用 Gunicorn 或 uWSGI 等 WSGI 服務器
    print(f"Serving files from: {BASE_DIRECTORY}")
    print("Web server running at http://127.0.0.1:5000/")
    app.run(debug=True, host='0.0.0.0', port=5000)

