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
        .file-manager { background: #fff; border-radius: 8px; box-shadow: 0 1px 3px rgba(0,0,0,0.12), 0 1px 2px rgba(0,0,0,0.24); padding: 20px; } /* Adjusted padding */
        .toolbar { display: none; } /* Hide toolbar as breadcrumb is removed */
        .breadcrumb { font-size: 14px; color: #5f6368; display: flex; align-items: center; flex-wrap: wrap; }
        .breadcrumb a { color: #1a73e8; text-decoration: none; padding: 4px 0; }
        .breadcrumb a:hover { text-decoration: underline; }
        .breadcrumb .separator { margin: 0 8px; color: #bdc1c6; }

        /* New styles for grouping */
        .month-group { margin-bottom: 30px; } /* Reduced margin */
        .month-title { font-size: 24px; font-weight: 500; color: #202124; margin-bottom: 15px; padding-top: 20px; } /* Reduced margin */
        .day-group { margin-bottom: 15px; } /* Reduced margin */
        .day-title { font-size: 18px; font-weight: 500; color: #5f6368; margin-bottom: 8px; } /* Reduced margin */

        .file-grid {
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
            gap: 8px; /* Reduced gap */
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
            height: 140px; /* Set a fixed height for the thumbnail container */
        }
        .file-item:hover {
            box-shadow: 0 4px 8px rgba(0,0,0,0.1);
            transform: translateY(-2px);
        }
        .file-thumbnail {
            width: 100%;
            height: 100%; /* Fill the entire file-item height */
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
            object-fit: cover; /* Use cover to fill the thumbnail area while maintaining aspect ratio */
            display: block;
            margin: auto;
        }
        /* 隱藏 image_not_supported 圖示，只在 thumbnail 失敗時應用 */
        .file-thumbnail .file-icon-placeholder {
            display: none; /* 預設不顯示 */
        }
        .file-info-bottom {
            display: none; /* Hide file information */
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
            <button class="btn btn-secondary" onclick="refreshFiles()"><span class="material-icons">refresh</span>重新整理</button>
            <input type="file" id="uploadFile" class="upload-input" onchange="uploadFile()" multiple>
            <button class="btn btn-primary" onclick="document.getElementById('uploadFile').click()"><span class="material-icons">cloud_upload</span>上傳檔案</button>
        </div>
    </div>

    <div class="container">
        <div class="file-manager" id="fileManager">
            <div id="fileList">
                <div class="no-content">載入檔案中...</div>
            </div>
        </div>
    </div>

    <div id="renameModal" class="modal">
        <div class="modal-content">
            <h3>重新命名</h3>
            <div class="form-group">
                <label for="newFileName">新名稱:</label>
                <input type="text" id="newFileName" />
            </div>
            <div class="form-actions">
                <button class="btn btn-secondary" onclick="closeModal('renameModal')">取消</button>
                <button class="btn btn-primary" onclick="confirmRename()">確認</button>
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

        // Load file list
        async function loadFiles() {
            try {
                // 不再傳遞 path 參數，因為後端會遞迴掃描整個 BASE_DIRECTORY
                const response = await fetch(`/api/files`); 
                const data = await response.json();
                
                if (data.error) {
                    document.getElementById('fileList').innerHTML = `<div class="no-content">錯誤: ${data.error}</div>`;
                    return;
                }
                // updateBreadcrumb(); // 麵包屑導航已移除
                displayFiles(data.grouped_files);
            } catch (error) {
                document.getElementById('fileList').innerHTML = '<div class="no-content">載入檔案時發生錯誤。</div>';
                console.error("Error loading files:", error);
            }
        }

        // updateBreadcrumb 函數已移除

        // Display file list in a Google Photos-like grid
        function displayFiles(data) {
            const fileListContainer = document.getElementById('fileList');
            let html = '';

            if (!data || data.length === 0) {
                html = '<div class="no-content">這個資料夾沒有圖片。</div>';
                fileListContainer.innerHTML = html;
                return;
            }

            data.forEach(monthGroup => {
                html += `<div class="month-group">`;
                html += `<div class="month-title">${monthGroup.title_month}</div>`;

                monthGroup.days.forEach(dayGroup => {
                    html += `<div class="day-group">`;
                    html += `<div class="day-title">${dayGroup.title_day}</div>`;
                    html += `<div class="file-grid">`; // Start a new grid for each day

                    dayGroup.items.forEach(file => {
                        // 這裡我們已經假設 file 都是圖片了，因為後端已經篩選過
                        const fileExtension = file.name.split('.').pop().toLowerCase();
                        let iconHtml = '';

                        // 對於圖片，直接使用縮圖
                        // 改變了 onerror 行為，使其只隱藏圖片本身，不顯示替代圖示
                        iconHtml = `<img src="/api/thumbnail?path=${encodeURIComponent(file.path)}" alt="${file.name}" onerror="this.onerror=null; this.style.display='none';">`;
                        
                        html += `
                            <div class="file-item">
                                <div class="file-thumbnail" onclick="previewImage('${file.path}')">
                                    ${iconHtml}
                                </div>
                                <div class="file-actions-overlay">
                                    <button class="btn btn-primary" onclick="downloadFile('${file.path}')"><span class="material-icons">download</span>下載</button>
                                    <button class="btn btn-secondary" onclick="previewImage('${file.path}')"><span class="material-icons">visibility</span>預覽</button>
                                </div>
                            </div>
                        `;
                    });
                    html += `</div></div>`; // Close file-grid and day-group
                });
                html += `</div>`; // Close month-group
            });
            
            fileListContainer.innerHTML = html;
        }

        // Navigate to specified path (now only used to set the current upload path)
        function navigateTo(path) {
            // Since we are now searching all subdirectories for display,
            // this function's primary purpose shifts to setting the context for uploads.
            // For now, new uploads will go to the BASE_DIRECTORY root.
            currentPath = path; 
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

        // Rename file/folder - 這些函數現在沒有被調用，但仍然存在
        let renameTarget = ''; // 為了避免錯誤，保持這個變數的宣告
        function renameFile(filePath, currentName) {
            // 此功能已被移除，這裡可以放一個提示或不做任何事
            alert('此功能已被禁用。');
        }

        // Confirm rename - 這些函數現在沒有被調用，但仍然存在
        async function confirmRename() {
            // 此功能已被禁用
            alert('此功能已被禁用。');
        }

        // Delete file/folder - 這些函數現在沒有被調用，但仍然存在
        async function deleteFile(filePath, fileName) {
            // 此功能已被禁用
            alert('此功能已被禁用。');
        }

        // Upload file
        async function uploadFile() {
            const fileInput = document.getElementById('uploadFile');
            const files = fileInput.files;
            
            if (files.length === 0) return;
            
            const formData = new FormData();
            formData.append('path', currentPath); // currentPath 仍然用於指定上傳目標目錄
            
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
                    alert('上傳失敗: ' + result.error);
                }
            } catch (error) {
                alert('上傳時發生錯誤。');
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

@app.route('/api/files')
def api_files():
    # 由於要搜尋所有子資料夾，relative_path_str 在此路由下不再用於導航，
    # 但如果日後需要瀏覽特定子資料夾，可以重新啟用其功能。
    # 目前此請求始終返回 BASE_DIRECTORY 下的所有圖片。
    
    base_dir_path = Path(BASE_DIRECTORY).resolve()
    if not base_dir_path.is_dir():
        return jsonify({'error': f'Base directory not found or not accessible: {BASE_DIRECTORY}'}), 500

    files_info = []
    
    # 遞迴地遍歷基本目錄及其所有子目錄
    for root, dirs, files in os.walk(base_dir_path):
        # 為了安全和性能，可以選擇性地跳過某些目錄
        # 例如：dirs[:] = [d for d in dirs if d not in ['.git', '__pycache__']]

        for file_name in files:
            full_item_path = Path(root) / file_name
            
            # 確保檔案在 BASE_DIRECTORY 內，防止目錄遍歷攻擊
            try:
                full_item_path.relative_to(base_dir_path)
            except ValueError:
                # 檔案不在基本目錄內，跳過
                continue

            file_info = get_file_info(str(full_item_path), str(base_dir_path))
            
            # 僅包含圖片檔案
            if file_info and file_info['type'] == 'image':
                files_info.append(file_info)

    # Sort files by modification time, newest first
    files_info.sort(key=lambda x: datetime.strptime(x['modified'], '%Y-%m-%d %H:%M:%S'), reverse=True)

    grouped_files = {}
    for file in files_info:
        # Get the year and month for grouping (e.g., "2023年1月")
        modified_dt = datetime.strptime(file['modified'], '%Y-%m-%d %H:%M:%S')
        group_key_month = modified_dt.strftime('%Y年%m月')
        group_key_day = modified_dt.strftime('%Y年%m月%d日 %A') # e.g., "2023年1月2日 星期一"

        if group_key_month not in grouped_files:
            grouped_files[group_key_month] = {
                'title_month': group_key_month,
                'days': {}
            }
        
        if group_key_day not in grouped_files[group_key_month]['days']:
            grouped_files[group_key_month]['days'][group_key_day] = {
                'title_day': group_key_day,
                'items': []
            }
        
        grouped_files[group_key_month]['days'][group_key_day]['items'].append(file)

    # Convert grouped_files to a list for ordered iteration in Jinja2 (or JS)
    # Sort months in descending order
    ordered_grouped_files = []
    for month_key in sorted(grouped_files.keys(), reverse=True):
        month_data = grouped_files[month_key]
        # Sort days within each month in descending order
        ordered_days = []
        for day_key in sorted(month_data['days'].keys(), reverse=True):
            ordered_days.append(month_data['days'][day_key])
        month_data['days'] = ordered_days
        ordered_grouped_files.append(month_data)

    return jsonify({'grouped_files': ordered_grouped_files})

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

    # 由於前端已移除相關按鈕，這裡為了安全性仍然保留檢查，但會直接返回禁用錯誤
    return jsonify({'success': False, 'error': '此功能已被禁用。'}), 403 

@app.route('/api/delete', methods=['POST'])
def api_delete():
    data = request.json
    relative_path_str = data.get('path', '')

    # 由於前端已移除相關按鈕，這裡為了安全性仍然保留檢查，但會直接返回禁用錯誤
    return jsonify({'success': False, 'error': '此功能已被禁用。'}), 403

@app.route('/api/upload', methods=['POST'])
def api_upload():
    # currentPath 在前端用於指示上傳目標目錄。
    # 由於現在顯示的是所有圖片的扁平視圖，currentPath 通常為空字串，
    # 這意味著上傳會到 BASE_DIRECTORY 的根目錄。
    relative_path_str = request.form.get('path', '')

    base_dir_path = Path(BASE_DIRECTORY).resolve()
    target_dir = (base_dir_path / unquote(relative_path_str)).resolve()

    # Security check: ensure the target directory is within the base directory
    try:
        target_dir.relative_to(base_dir_path)
    except ValueError:
        return jsonify({'success': False, 'error': 'Access denied: Target path outside allowed directory'}), 403

    if not target_dir.is_dir():
        # 如果目標不是資料夾，或不存在，預設上傳到根目錄
        # 否則上傳會失敗。
        target_dir = base_dir_path
        print(f"Warning: Target upload path '{relative_path_str}' is not a directory or does not exist. Uploading to base directory: {target_dir}")


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