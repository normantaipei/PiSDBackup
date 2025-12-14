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

# Root directory for file operations.
# IMPORTANT: If this path doesn't exist or isn't accessible, the application will not function correctly.
# Ensure this path is valid before deployment.
# 請將此路徑更改為您要掃描圖片的實際目錄
BASE_DIRECTORY = "/mnt/backup_drive" 

# Define common RAW file extensions.
# We will check both lowercase and uppercase versions dynamically.
RAW_EXTENSIONS = ['.arw', '.cr2', '.cr3', '.dng', '.nef', '.orf', '.rw2', '.raf', '.pef', '.srw', '.kdc', '.mos', '.3fr', '.erf', '.mef', '.nrw', '.qtk', '.x3f']


# HTML Template (包含手機螢幕兩張圖片一行的 CSS 調整)
HTML_TEMPLATE = '''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>PiSDBackup by Norman</title>
    <link href="https://fonts.googleapis.com/icon?family=Material+Icons" rel="stylesheet">
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: 'Roboto', sans-serif; background: #f8f9fa; color: #3c4043; }
        .header { background: #fff; color: #202124; padding: 16px 24px; border-bottom: 1px solid #dadce0; display: flex; align-items: center; justify-content: space-between; box-shadow: 0 1px 2px 0 rgba(60,64,67,0.3), 0 1px 3px 1px rgba(60,64,67,0.15); }
        .header h1 { font-size: 22px; font-weight: 400; display: flex; align-items: center; }
        .header h1 .material-icons { margin-right: 8px; font-size: 28px; color: #4285f4; }
        .container { max-width: 1400px; margin: 0 auto; padding: 20px; }
        .file-manager { background: #fff; border-radius: 8px; box-shadow: 0 1px 3px rgba(0,0,0,0.12), 0 1px 2px rgba(0,0,0,0.24); padding: 20px; }
        .toolbar { display: none; }
        .breadcrumb { font-size: 14px; color: #5f6368; display: flex; align-items: center; flex-wrap: wrap; }
        .breadcrumb a { color: #1a73e8; text-decoration: none; padding: 4px 0; }
        .breadcrumb a:hover { text-decoration: underline; }
        .breadcrumb .separator { margin: 0 8px; color: #bdc1c6; }

        .month-group { margin-bottom: 30px; }
        .month-title { font-size: 24px; font-weight: 500; color: #202124; margin-bottom: 15px; padding-top: 20px; }
        .day-group { margin-bottom: 15px; }
        .day-title { font-size: 18px; font-weight: 500; color: #5f6368; margin-bottom: 8px; }

        .file-grid {
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
            gap: 8px;
        }
        /* Mobile specific styles for 2 columns */
        @media (max-width: 768px) { /* Adjust breakpoint as needed for "mobile screen size" */
            .file-grid {
                grid-template-columns: repeat(2, 1fr); /* Two columns for smaller screens */
            }
            .file-item {
                height: 120px; /* Slightly reduce height for smaller screens if needed */
            }
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
            height: 140px;
        }
        .file-item:hover {
            box-shadow: 0 4px 8px rgba(0,0,0,0.1);
            transform: translateY(-2px);
        }
        .file-thumbnail {
            width: 100%;
            height: 100%;
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
            object-fit: cover;
            display: block;
            margin: auto;
        }
        .file-thumbnail .file-icon-placeholder {
            display: none;
        }
        .file-info-bottom {
            display: none;
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
            display: none;
        }
    </style>
</head>
<body>
    <div class="header">
        <h1><span class="material-icons">photo_library</span>PiSDBackup by Norman</h1>
        <div>
            <button class="btn btn-secondary" onclick="refreshFiles()"><span class="material-icons">refresh</span>Refresh</button>
            </div>
    </div>

    <div class="container">
        <div class="file-manager" id="fileManager">
            <div id="fileList">
                <div class="no-content">Loading files...</div>
            </div>
        </div>
    </div>

    <div id="renameModal" class="modal">
        <div class="modal-content">
            <h3>Rename</h3>
            <div class="form-group">
                <label for="newFileName">New name:</label>
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

    <div id="rawDownloadModal" class="modal">
        <div class="modal-content">
            <h3>Download Option</h3>
            <p>This image has a RAW version available. Which version would you like to download?</p>
            <div class="form-actions" style="margin-top: 20px; display: flex; justify-content: space-around;">
                <button class="btn btn-secondary" onclick="closeModal('rawDownloadModal')">Cancel</button>
                <button class="btn btn-primary" id="downloadJpgBtn"><span class="material-icons">download</span>Download JPG</button>
                <button class="btn btn-primary" id="downloadRawBtn"><span class="material-icons">download</span>Download RAW</button>
            </div>
        </div>
    </div>

    <script>
        let currentPath = ''; // currentPath will be relative to BASE_DIRECTORY
        let currentDownloadFilePath = ''; // To store the path for download choice

        // Load file list
        async function loadFiles() {
            try {
                // No 'path' parameter is passed as the backend recursively scans the entire BASE_DIRECTORY
                const response = await fetch(`/api/files`); 
                const data = await response.json();
                
                if (data.error) {
                    document.getElementById('fileList').innerHTML = `<div class="no-content">Error: ${data.error}</div>`;
                    return;
                }
                displayFiles(data.grouped_files);
            } catch (error) {
                document.getElementById('fileList').innerHTML = '<div class="no-content">Error loading files.</div>';
                console.error("Error loading files:", error);
            }
        }

        // Display file list in a Google Photos-like grid
        function displayFiles(data) {
            const fileListContainer = document.getElementById('fileList');
            let html = '';

            if (!data || data.length === 0) {
                html = '<div class="no-content">No images found in this directory.</div>';
                fileListContainer.innerHTML = html;
                return;
            }

            data.forEach(monthGroup => {
                html += `<div class="month-group">`;
                html += `<div class="month-title">${monthGroup.title_month}</div>`;

                monthGroup.days.forEach(dayGroup => {
                    html += `<div class="day-group">`;
                    html += `<div class="day-title">${dayGroup.title_day}</div>`;
                    html += `<div class="file-grid">`;

                    dayGroup.items.forEach(file => {
                        const fileExtension = file.name.split('.').pop().toLowerCase();
                        let iconHtml = '';

                        iconHtml = `<img src="/api/thumbnail?path=${encodeURIComponent(file.path)}" alt="${file.name}" onerror="this.onerror=null; this.style.display='none';">`;
                        
                        // Modified download button to call handleDownloadClick
                        html += `
                            <div class="file-item">
                                <div class="file-thumbnail" onclick="previewImage('${file.path}')">
                                    ${iconHtml}
                                </div>
                                <div class="file-actions-overlay">
                                    <button class="btn btn-primary" onclick="handleDownloadClick('${file.path}')"><span class="material-icons">download</span>Download</button>
                                    <button class="btn btn-secondary" onclick="previewImage('${file.path}')"><span class="material-icons">visibility</span>Preview</button>
                                </div>
                            </div>
                        `;
                    });
                    html += `</div></div>`;
                });
                html += `</div>`;
            });
            
            fileListContainer.innerHTML = html;
        }

        // Navigate to specified path (now only used to set the current upload path)
        function navigateTo(path) {
            currentPath = path; 
        }

        // Refresh files
        function refreshFiles() {
            loadFiles();
        }

        // New function to handle download click and check for RAW
        async function handleDownloadClick(filePath) {
            currentDownloadFilePath = filePath;
            try {
                const response = await fetch(`/api/check_raw?path=${encodeURIComponent(filePath)}`);
                const data = await response.json();

                if (data.raw_path) {
                    // If RAW version exists, show the choice modal
                    document.getElementById('rawDownloadModal').style.display = 'flex';
                    // Set up event listeners for the download buttons in the modal
                    document.getElementById('downloadJpgBtn').onclick = () => {
                        downloadFile(filePath); // Download JPG version
                        closeModal('rawDownloadModal');
                    };
                    document.getElementById('downloadRawBtn').onclick = () => {
                        downloadFile(data.raw_path); // Download RAW version
                        closeModal('rawDownloadModal');
                    };
                } else {
                    // No RAW version, directly download JPG
                    downloadFile(filePath);
                }
            } catch (error) {
                console.error("Error checking for RAW file:", error);
                // If there's an error, just default to downloading the original file
                downloadFile(filePath);
            }
        }

        // Download file - now takes an optional type parameter for RAW download
        function downloadFile(filePath) {
            const url = `/api/download?path=${encodeURIComponent(filePath)}`;
            window.open(url, '_blank');
        }

        // Preview image
        function previewImage(filePath) {
            const img = document.getElementById('imagePreview');
            img.src = `/api/download?path=${encodeURIComponent(filePath)}`;
            document.getElementById('imageModal').style.display = 'flex';
        }

        // Close modal
        function closeModal(modalId) {
            document.getElementById(modalId).style.display = 'none';
            if (modalId === 'imageModal') {
                document.getElementById('imagePreview').src = '';
            }
        }

        // Rename file/folder - These functions are no longer called and will show an alert
        let renameTarget = ''; 
        function renameFile(filePath, currentName) {
            alert('This feature has been disabled.');
        }

        // Confirm rename - These functions are no longer called and will show an alert
        async function confirmRename() {
            alert('This feature has been disabled.');
        }

        // Delete file/folder - These functions are no longer called and will show an alert
        async function deleteFile(filePath, fileName) {
            alert('This feature has been disabled.');
        }

        // Upload file - This function is no longer called as the button is removed
        async function uploadFile() {
            alert('Upload feature has been disabled.');
            // Original upload logic (commented out as it's not needed)
            /*
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
                    fileInput.value = '';
                } else {
                    alert('Upload failed: ' + result.error);
                }
            } catch (error) {
                alert('An error occurred during upload.');
            }
            */
        }

        // Close modal when clicking outside
        window.onclick = function(event) {
            const renameModal = document.getElementById('renameModal');
            const imageModal = document.getElementById('imageModal');
            const rawDownloadModal = document.getElementById('rawDownloadModal'); // New modal
            
            if (event.target === renameModal) {
                closeModal('renameModal');
            }
            if (event.target === imageModal) {
                closeModal('imageModal');
            }
            if (event.target === rawDownloadModal) { // New modal
                closeModal('rawDownloadModal');
            }
        }

        // Initialize on page load
        document.addEventListener('DOMContentLoaded', function() {
            loadFiles();
        });
    </script>
</body>
</html>
'''

def format_size(bytes_size):
    """Formats file size into human-readable format"""
    for unit in ['B', 'KB', 'MB', 'GB', 'TB', 'PB']:
        if bytes_size < 1024.0:
            return f"{bytes_size:.1f} {unit}"
        bytes_size /= 1024.0
    return f"{bytes_size:.1f} EB"

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
            'name': os.path.basename(full_path),
            'path': relative_path,
            'is_directory': is_dir,
            'size': format_size(stat.st_size) if not is_dir else '',
            'modified': datetime.fromtimestamp(stat.st_mtime).strftime('%Y-%m-%d %H:%M:%S'),
            'type': file_type
        }
    except Exception as e:
        print(f"Error getting file info for {full_path}: {e}")
        return None

def create_thumbnail(image_path, thumbnail_size=(300, 300)):
    """Creates a thumbnail for an image"""
    try:
        with Image.open(image_path) as img:
            img.thumbnail(thumbnail_size, Image.Resampling.LANCZOS)
            if img.mode in ('RGBA', 'LA', 'P'):
                img = img.convert('RGB')
            return img
    except Exception as e:
        print(f"Failed to create thumbnail for {image_path}: {e}")
        return None

@app.route('/')
def index():
    return render_template_string(HTML_TEMPLATE)

@app.route('/api/files')
def api_files():
    base_dir_path = Path(BASE_DIRECTORY).resolve()
    if not base_dir_path.is_dir():
        return jsonify({'error': f'Base directory not found or not accessible: {BASE_DIRECTORY}'}), 500

    files_info = []
    
    for root, dirs, files in os.walk(base_dir_path):
        for file_name in files:
            full_item_path = Path(root) / file_name
            
            try:
                full_item_path.relative_to(base_dir_path)
            except ValueError:
                continue

            # Only process JPG/JPEG for display in the grid
            if file_name.lower().endswith(('.jpg', '.jpeg')):
                file_info = get_file_info(str(full_item_path), str(base_dir_path))
                
                if file_info and file_info['type'] == 'image':
                    files_info.append(file_info)

    files_info.sort(key=lambda x: datetime.strptime(x['modified'], '%Y-%m-%d %H:%M:%S'), reverse=True)

    grouped_files = {}
    for file in files_info:
        modified_dt = datetime.strptime(file['modified'], '%Y-%m-%d %H:%M:%S')
        group_key_month = modified_dt.strftime('%Y-%m') # e.g., "2023-01"
        group_key_day = modified_dt.strftime('%Y-%m-%d %A') # e.g., "2023-01-02 Monday"

        if group_key_month not in grouped_files:
            grouped_files[group_key_month] = {
                'title_month': modified_dt.strftime('%B %Y'), # English month name + Year
                'days': {}
            }
        
        if group_key_day not in grouped_files[group_key_month]['days']:
            grouped_files[group_key_month]['days'][group_key_day] = {
                'title_day': modified_dt.strftime('%A, %B %d, %Y'), # English day, month, date, year
                'items': []
            }
        
        grouped_files[group_key_month]['days'][group_key_day]['items'].append(file)

    ordered_grouped_files = []
    for month_key in sorted(grouped_files.keys(), reverse=True):
        month_data = grouped_files[month_key]
        ordered_days = []
        for day_key in sorted(month_data['days'].keys(), reverse=True):
            ordered_days.append(month_data['days'][day_key])
        month_data['days'] = ordered_days
        ordered_grouped_files.append(month_data)

    return jsonify({'grouped_files': ordered_grouped_files})

@app.route('/api/check_raw')
def api_check_raw():
    """
    Checks if a given image file (JPG/JPEG) has a corresponding RAW file in the same directory.
    Returns the path of the RAW file if found, otherwise None.
    Handles both lowercase and uppercase RAW extensions.
    """
    relative_path_str = request.args.get('path', '')

    if not relative_path_str:
        return jsonify({'error': 'Missing parameters'}), 400

    base_dir_path = Path(BASE_DIRECTORY).resolve()
    full_jpg_path = (base_dir_path / unquote(relative_path_str)).resolve()

    try:
        # Crucial security check: Ensure the resolved path is within the base directory
        full_jpg_path.relative_to(base_dir_path)
    except ValueError:
        return jsonify({'error': 'Access denied: Path outside allowed directory'}), 403

    # Ensure it's a file and a JPG/JPEG
    if not full_jpg_path.is_file() or not full_jpg_path.suffix.lower() in ('.jpg', '.jpeg'):
        return jsonify({'raw_path': None}) 

    # Get the base name (stem) of the JPG file and its parent directory
    stem = full_jpg_path.stem 
    parent_dir = full_jpg_path.parent 

    # Iterate through all potential RAW extensions to find a matching file
    for raw_ext in RAW_EXTENSIONS:
        # Check for lowercase version
        potential_raw_path_lower = parent_dir / (stem + raw_ext)
        if potential_raw_path_lower.is_file():
            relative_raw_path = potential_raw_path_lower.relative_to(base_dir_path).as_posix()
            return jsonify({'raw_path': relative_raw_path})
        
        # Check for uppercase version
        potential_raw_path_upper = parent_dir / (stem + raw_ext.upper())
        if potential_raw_path_upper.is_file():
            relative_raw_path = potential_raw_path_upper.relative_to(base_dir_path).as_posix()
            return jsonify({'raw_path': relative_raw_path})
            
    # If no RAW file is found after checking all extensions (both cases)
    return jsonify({'raw_path': None})

@app.route('/api/thumbnail')
def api_thumbnail():
    relative_path_str = request.args.get('path', '')

    if not relative_path_str:
        return '', 404

    base_dir_path = Path(BASE_DIRECTORY).resolve()
    full_path = (base_dir_path / unquote(relative_path_str)).resolve()

    try:
        full_path.relative_to(base_dir_path)
    except ValueError:
        return '', 403

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
        print(f"Error serving thumbnail for {full_path}: {e}")
        pass

    return '', 404

@app.route('/api/download')
def api_download():
    relative_path_str = request.args.get('path', '')

    if not relative_path_str:
        return jsonify({'error': 'Missing parameters'}), 400

    base_dir_path = Path(BASE_DIRECTORY).resolve()
    full_path = (base_dir_path / unquote(relative_path_str)).resolve()

    try:
        full_path.relative_to(base_dir_path)
    except ValueError:
        return jsonify({'error': 'Access denied: Path outside allowed directory'}), 403

    if not full_path.is_file() or full_path.is_dir():
        return jsonify({'error': 'File not found or is a directory'}), 404

    return send_file(str(full_path), as_attachment=True, download_name=full_path.name)

@app.route('/api/rename', methods=['POST'])
def api_rename():
    # This functionality is disabled.
    return jsonify({'success': False, 'error': 'This feature has been disabled.'}), 403 

@app.route('/api/delete', methods=['POST'])
def api_delete():
    # This functionality is disabled.
    return jsonify({'success': False, 'error': 'This feature has been disabled.'}), 403

@app.route('/api/upload', methods=['POST'])
def api_upload():
    # This functionality is disabled.
    return jsonify({'success': False, 'error': 'Upload feature has been disabled.'}), 403

if __name__ == '__main__':
    if not os.path.exists(BASE_DIRECTORY):
        try:
            os.makedirs(BASE_DIRECTORY)
            print(f"Created base directory: {BASE_DIRECTORY}")
        except OSError as e:
            print(f"Error creating base directory {BASE_DIRECTORY}: {e}")
            print("Please ensure the directory exists and has correct permissions.")
            exit()
    
    print(f"Serving files from: {BASE_DIRECTORY}")
    print("Web server running at http://127.0.0.1:5000/")
    # 設置 host='0.0.0.0' 以允許從其他設備訪問，debug=True 方便開發
    app.run(debug=True, host='0.0.0.0', port=5000)