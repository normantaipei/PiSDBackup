"""Read-only photo browser for the backup drive.

* Token-based access (the QR code on the device carries the token).
* Works fully offline: no external fonts/icons.
* Thumbnails and previews are generated once and cached on the backup drive;
  after each backup the missing thumbnails are generated in the background
  (see ``thumbnail_cache``), and at most two images are decoded at a time.
* The file index is cached and rebuilt at most every ``file_list_cache_seconds``;
  the browser loads it page by page while scrolling instead of all at once.
* Served with waitress (production WSGI server) when available.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import mimetypes
import os
import re
import threading
import time
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Dict, List, Optional

from flask import Flask, abort, jsonify, make_response, redirect, render_template_string, request, send_file

from config import Config, RAW_EXTENSIONS, load_config
from thumbnail_cache import ThumbnailCache

log = logging.getLogger(__name__)

IMAGE_EXTS = (".jpg", ".jpeg", ".jpe", ".png")
DATE_DIR_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")
TOKEN_COOKIE = "pisd_token"

HTML_TEMPLATE = r'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>PiSDBackup</title>
<style>
  :root { --bg:#f8f9fa; --card:#fff; --fg:#202124; --dim:#5f6368; --line:#dadce0; --accent:#1a73e8; }
  @media (prefers-color-scheme: dark) { :root { --bg:#121212; --card:#1e1e1e; --fg:#e8eaed; --dim:#9aa0a6; --line:#3c4043; } }
  * { margin:0; padding:0; box-sizing:border-box; }
  body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Noto Sans", sans-serif; background:var(--bg); color:var(--fg); }
  .header { background:var(--card); padding:12px 16px; border-bottom:1px solid var(--line); display:flex; align-items:center; justify-content:space-between; position:sticky; top:0; z-index:10; }
  .header h1 { font-size:18px; font-weight:500; display:flex; align-items:center; gap:8px; }
  .header svg { width:22px; height:22px; fill:var(--accent); }
  .status { font-size:12px; color:var(--dim); margin-left:8px; }
  .container { max-width:1400px; margin:0 auto; padding:16px; }
  .month-title { font-size:22px; font-weight:500; margin:20px 0 10px; }
  .day-title { font-size:15px; color:var(--dim); margin:12px 0 6px; }
  .file-grid { display:grid; grid-template-columns:repeat(auto-fill, minmax(160px, 1fr)); gap:6px; }
  @media (max-width:768px) { .file-grid { grid-template-columns:repeat(3, 1fr); } }
  @media (max-width:480px) { .file-grid { grid-template-columns:repeat(2, 1fr); } }
  .file-item { position:relative; aspect-ratio:1; background:var(--card); border:1px solid var(--line); border-radius:6px; overflow:hidden; cursor:pointer; }
  .file-item img { width:100%; height:100%; object-fit:cover; display:block; }
  .file-item .name { position:absolute; left:0; right:0; bottom:0; font-size:10px; padding:2px 4px; background:rgba(0,0,0,.45); color:#fff; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
  .file-item .raw-badge { position:absolute; top:4px; left:4px; font-size:10px; padding:1px 5px; border-radius:3px; background:rgba(0,0,0,.6); color:#fff; }
  .btn { padding:8px 14px; border:none; border-radius:4px; cursor:pointer; font-size:14px; display:inline-flex; align-items:center; gap:6px; }
  .btn svg { width:16px; height:16px; fill:currentColor; }
  .btn-primary { background:var(--accent); color:#fff; }
  .btn-secondary { background:transparent; color:var(--fg); border:1px solid var(--line); }
  .modal { display:none; position:fixed; inset:0; background:rgba(0,0,0,.85); z-index:1000; align-items:center; justify-content:center; flex-direction:column; }
  .modal.open { display:flex; }
  .modal img { max-width:100vw; max-height:80vh; object-fit:contain; }
  .modal .bar { display:flex; gap:8px; padding:12px; flex-wrap:wrap; justify-content:center; }
  .modal .bar .btn-secondary { color:#fff; border-color:#888; }
  .modal .caption { color:#ddd; font-size:13px; padding:0 12px 8px; text-align:center; word-break:break-all; }
  .close { position:absolute; top:12px; right:12px; width:36px; height:36px; border-radius:50%; background:rgba(255,255,255,.9); color:#000; display:flex; align-items:center; justify-content:center; font-size:22px; cursor:pointer; }
  .no-content { text-align:center; padding:40px; color:var(--dim); }
</style>
</head>
<body>
<div class="header">
  <h1><svg viewBox="0 0 24 24"><path d="M21 19V5c0-1.1-.9-2-2-2H5c-1.1 0-2 .9-2 2v14c0 1.1.9 2 2 2h14c1.1 0 2-.9 2-2zM8.5 13.5l2.5 3.01L14.5 12l4.5 6H5l3.5-4.5z"/></svg>PiSDBackup<span class="status" id="status"></span></h1>
  <button class="btn btn-secondary" onclick="loadFiles(true)"><svg viewBox="0 0 24 24"><path d="M17.65 6.35A7.96 7.96 0 0 0 12 4a8 8 0 1 0 7.73 10h-2.08A6 6 0 1 1 12 6c1.66 0 3.14.69 4.22 1.78L13 11h7V4l-2.35 2.35z"/></svg>Refresh</button>
</div>
<div class="container"><div id="fileList"><div class="no-content">Loading…</div></div><div id="sentinel" style="height:1px"></div></div>

<div id="imageModal" class="modal">
  <div class="close" onclick="closeModal()">×</div>
  <img id="imagePreview" alt="">
  <div class="caption" id="caption"></div>
  <div class="bar">
    <button class="btn btn-primary" id="dlJpg">Download JPG</button>
    <button class="btn btn-secondary" id="dlRaw" style="display:none">Download RAW</button>
  </div>
</div>

<script>
(function () {
  const list = document.getElementById('fileList');
  const statusEl = document.getElementById('status');
  const modal = document.getElementById('imageModal');
  const preview = document.getElementById('imagePreview');
  const sentinel = document.getElementById('sentinel');
  const q = (p) => encodeURIComponent(p);
  let page = 0, pages = 1, loading = false, total = 0;
  let lastMonth = null, lastDay = null, currentGrid = null;

  function el(tag, cls, text) { const e = document.createElement(tag); if (cls) e.className = cls; if (text !== undefined) e.textContent = text; return e; }

  window.loadFiles = async function (refresh) {
    page = 0; pages = 1; lastMonth = lastDay = currentGrid = null;
    list.replaceChildren(el('div', 'no-content', 'Loading…'));
    await loadNextPage(refresh);
  };

  async function loadNextPage(refresh) {
    if (loading || page >= pages) return;
    loading = true;
    try {
      const r = await fetch('/api/files?page=' + (page + 1) + (refresh ? '&refresh=1' : ''), {cache: 'no-store'});
      if (r.status === 401) { location.reload(); return; }
      const data = await r.json();
      if (data.error) { list.replaceChildren(el('div', 'no-content', data.error)); return; }
      if (page === 0) list.replaceChildren();
      page = data.page; pages = data.pages; total = data.total;
      append(data.items);
      statusEl.textContent = total + ' photos' + (page < pages ? ' · scroll for more' : '');
      if (total === 0) list.replaceChildren(el('div', 'no-content', 'No photos on the backup drive yet.'));
    } catch (e) { list.appendChild(el('div', 'no-content', 'Error loading files.')); console.error(e); }
    finally { loading = false; }
  }

  function append(items) {
    for (const f of items) {
      if (f.month_key !== lastMonth) { list.appendChild(el('div', 'month-title', f.title_month)); lastMonth = f.month_key; lastDay = null; }
      if (f.day_key !== lastDay) { list.appendChild(el('div', 'day-title', f.title_day)); currentGrid = el('div', 'file-grid'); list.appendChild(currentGrid); lastDay = f.day_key; }
      const item = el('div', 'file-item');
      const img = document.createElement('img');
      img.loading = 'lazy'; img.decoding = 'async'; img.alt = f.name; img.src = '/api/thumbnail?path=' + q(f.path);
      img.onerror = () => { img.style.display = 'none'; };
      item.appendChild(img);
      if (f.raw_path) item.appendChild(el('span', 'raw-badge', 'RAW'));
      item.appendChild(el('div', 'name', f.name));
      item.onclick = () => openPreview(f);
      currentGrid.appendChild(item);
    }
  }

  // Load the next page when the sentinel at the bottom scrolls into view.
  new IntersectionObserver((entries) => { if (entries.some(e => e.isIntersecting)) loadNextPage(false); }, {rootMargin: '600px'}).observe(sentinel);

  function openPreview(f) {
    preview.src = '/api/preview?path=' + q(f.path);
    document.getElementById('caption').textContent = f.name + ' · ' + f.size + ' · ' + f.modified;
    document.getElementById('dlJpg').onclick = () => download(f.path);
    const raw = document.getElementById('dlRaw');
    raw.style.display = f.raw_path ? '' : 'none';
    raw.onclick = () => download(f.raw_path);
    modal.classList.add('open');
  }
  window.closeModal = function () { modal.classList.remove('open'); preview.src = ''; };
  function download(p) { window.location.href = '/api/download?path=' + q(p); }
  modal.addEventListener('click', (e) => { if (e.target === modal) closeModal(); });
  document.addEventListener('keydown', (e) => { if (e.key === 'Escape') closeModal(); });
  document.addEventListener('DOMContentLoaded', () => loadFiles(false));
})();
</script>
</body>
</html>'''

LOGIN_TEMPLATE = '''<!DOCTYPE html><html><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>PiSDBackup</title><style>body{font-family:sans-serif;display:flex;align-items:center;justify-content:center;height:100vh;margin:0;background:#f8f9fa}
form{background:#fff;padding:24px;border-radius:8px;box-shadow:0 1px 3px rgba(0,0,0,.2);text-align:center}input{font-size:18px;padding:8px;width:100%;margin:12px 0;box-sizing:border-box}
button{font-size:16px;padding:8px 16px;background:#1a73e8;color:#fff;border:none;border-radius:4px}</style></head>
<body><form method="get" action="/"><h2>PiSDBackup</h2><p>Scan the QR code on the device, or enter the access code shown on its screen.</p>
<input name="token" placeholder="Access code" autofocus autocomplete="off"><button type="submit">Open</button></form></body></html>'''


# --------------------------------------------------------------------------- helpers
def format_size(n: float) -> str:
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if n < 1024.0:
            return f"{n:.1f} {unit}"
        n /= 1024.0
    return f"{n:.1f} PB"


class FileIndex:
    """Cached, recursive listing of displayable images on the backup drive (newest first)."""

    def __init__(self, cfg: Config):
        self.cfg = cfg
        self._lock = threading.Lock()
        self._built_at = 0.0
        self._items: Optional[List[dict]] = None

    def invalidate(self) -> None:
        with self._lock:
            self._built_at = 0.0

    def items(self, force: bool = False) -> List[dict]:
        with self._lock:
            fresh = self._items is not None and (time.monotonic() - self._built_at) < self.cfg.file_list_cache_seconds
            if not fresh or force:
                self._items = self._build()
                self._built_at = time.monotonic()
            return self._items

    def page(self, number: int, force: bool = False) -> dict:
        items = self.items(force)
        size = max(1, self.cfg.page_size)
        pages = max(1, (len(items) + size - 1) // size)
        number = min(max(1, number), pages)
        chunk = items[(number - 1) * size: number * size]
        return {"items": chunk, "page": number, "pages": pages, "total": len(items), "has_more": number < pages,
                # kept for older clients
                "grouped_files": group(chunk), "count": len(items)}

    def _build(self) -> List[dict]:
        base = Path(self.cfg.backup_dir)
        raw_exts = set(RAW_EXTENSIONS)
        items: List[dict] = []
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames[:] = [d for d in dirnames if not d.startswith(".")]
            names_lower = {n.lower(): n for n in filenames}
            folder_date = DATE_DIR_RE.match(os.path.basename(dirpath))
            for name in filenames:
                if name.startswith(".") or not name.lower().endswith(IMAGE_EXTS):
                    continue
                full = Path(dirpath) / name
                try:
                    st = full.stat()
                except OSError:
                    continue
                dt = datetime.fromtimestamp(st.st_mtime)
                if folder_date:
                    try:
                        dt = datetime(int(folder_date[1]), int(folder_date[2]), int(folder_date[3]), dt.hour, dt.minute, dt.second)
                    except ValueError:
                        pass
                stem = os.path.splitext(name)[0].lower()
                raw_name = next((names_lower[stem + e] for e in raw_exts if stem + e in names_lower), None)
                items.append({
                    "name": name,
                    "path": full.relative_to(base).as_posix(),
                    "size": format_size(st.st_size),
                    "modified": dt.strftime("%Y-%m-%d %H:%M:%S"),
                    "month_key": dt.strftime("%Y-%m"),
                    "day_key": dt.strftime("%Y-%m-%d"),
                    "title_month": dt.strftime("%B %Y"),
                    "title_day": dt.strftime("%A, %B %d, %Y"),
                    "raw_path": (Path(dirpath) / raw_name).relative_to(base).as_posix() if raw_name else None,
                })
        items.sort(key=lambda x: (x["modified"], x["name"]), reverse=True)
        return items


def group(items: List[dict]) -> List[dict]:
    months: Dict[str, dict] = {}
    for it in items:
        month = months.setdefault(it["month_key"], {"title_month": it["title_month"], "days": {}})
        day = month["days"].setdefault(it["day_key"], {"title_day": it["title_day"], "items": []})
        day["items"].append(it)
    out = []
    for mk in sorted(months, reverse=True):
        m = months[mk]
        m["days"] = [m["days"][dk] for dk in sorted(m["days"], reverse=True)]
        out.append(m)
    return out


def _resolve_in_base(cfg: Config, relative: str) -> Path:
    """Resolves a user-supplied relative path and aborts on traversal / private dirs."""
    if not relative:
        abort(400)
    base = Path(cfg.backup_dir).resolve()
    try:
        full = (base / relative).resolve()
        full.relative_to(base)
    except (ValueError, OSError):
        abort(403)
    if any(part.startswith(".") for part in full.relative_to(base).parts):
        abort(403)
    return full


# --------------------------------------------------------------------------- app
def create_app(cfg: Optional[Config] = None, copy_manager=None) -> Flask:
    cfg = cfg or load_config()
    app = Flask(__name__)
    app.config["PISD"] = cfg
    app.config["COPY_MANAGER"] = copy_manager
    index = FileIndex(cfg)
    app.config["FILE_INDEX"] = index
    cache = ThumbnailCache(cfg, max_concurrent=cfg.max_concurrent_decodes)
    app.config["THUMBNAIL_CACHE"] = cache
    token = cfg.ensure_token() if cfg.web_auth else ""

    @app.before_request
    def _auth():
        if not cfg.web_auth:
            return None
        supplied = request.args.get("token")
        if supplied is not None:
            if hmac.compare_digest(supplied, token):
                resp = make_response(redirect(request.path))
                resp.set_cookie(TOKEN_COOKIE, token, max_age=365 * 24 * 3600, httponly=True, samesite="Lax")
                return resp
            return make_response(render_template_string(LOGIN_TEMPLATE), 401)
        if hmac.compare_digest(request.cookies.get(TOKEN_COOKIE, ""), token):
            return None
        if request.path.startswith("/api/"):
            return jsonify({"error": "unauthorised"}), 401
        return make_response(render_template_string(LOGIN_TEMPLATE), 401)

    @app.after_request
    def _headers(resp):
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("Referrer-Policy", "no-referrer")
        return resp

    @app.route("/")
    def home():
        return render_template_string(HTML_TEMPLATE)

    @app.route("/api/files")
    def api_files():
        if not Path(cfg.backup_dir).is_dir():
            return jsonify({"error": "Backup drive is not connected."}), 503
        try:
            page = int(request.args.get("page", 1))
        except ValueError:
            page = 1
        return jsonify(index.page(page, force=request.args.get("refresh") == "1"))

    @app.route("/api/status")
    def api_status():
        mgr = app.config.get("COPY_MANAGER")
        status = mgr.get_status() if mgr else {"available": False}
        status["thumbnail_warm"] = {"running": cache.is_warming(), **cache.last_warm_stats}
        return jsonify(status)

    @app.route("/api/thumbnail")
    def api_thumbnail():
        return _serve_scaled("thumbs")

    @app.route("/api/preview")
    def api_preview():
        return _serve_scaled("previews")

    def _serve_scaled(kind: str):
        full = _resolve_in_base(cfg, request.args.get("path", ""))
        if not full.is_file():
            abort(404)
        result = cache.get(full, kind)
        if result is None:
            abort(404)
        if isinstance(result, Path):
            return send_file(result, mimetype="image/jpeg", conditional=True, max_age=86400)
        return send_file(result, mimetype="image/jpeg")

    @app.route("/api/download")
    def api_download():
        full = _resolve_in_base(cfg, request.args.get("path", ""))
        if not full.is_file():
            abort(404)
        mime = mimetypes.guess_type(str(full))[0] or "application/octet-stream"
        return send_file(full, as_attachment=True, download_name=full.name, mimetype=mime, conditional=True)

    # Legacy endpoint kept for old clients: tells whether a RAW sibling exists.
    @app.route("/api/check_raw")
    def api_check_raw():
        full = _resolve_in_base(cfg, request.args.get("path", ""))
        if not full.is_file():
            return jsonify({"raw_path": None})
        for ext in RAW_EXTENSIONS:
            for cand in (full.with_suffix(ext), full.with_suffix(ext.upper())):
                if cand.is_file():
                    return jsonify({"raw_path": cand.relative_to(Path(cfg.backup_dir).resolve()).as_posix()})
        return jsonify({"raw_path": None})

    @app.errorhandler(403)
    def _forbidden(_):
        return jsonify({"error": "Access denied"}), 403

    @app.errorhandler(404)
    def _not_found(_):
        return jsonify({"error": "Not found"}), 404

    return app


def web_url(cfg: Config, ip: str) -> str:
    url = f"http://{ip}:{cfg.web_port}/"
    if cfg.web_auth:
        url += f"?token={cfg.ensure_token()}"
    return url


def run_server(app: Flask) -> None:
    cfg: Config = app.config["PISD"]
    try:
        from waitress import serve
        log.info("Serving web UI with waitress on %s:%s", cfg.web_host, cfg.web_port)
        serve(app, host=cfg.web_host, port=cfg.web_port, threads=6, _quiet=True)
    except ImportError:
        log.warning("waitress not installed; falling back to Flask's development server")
        app.run(host=cfg.web_host, port=cfg.web_port, debug=False, threaded=True, use_reloader=False)


if __name__ == "__main__":
    from config import setup_logging
    _cfg = load_config()
    setup_logging(_cfg)
    _app = create_app(_cfg)
    print(f"Open: {web_url(_cfg, '127.0.0.1')}")
    run_server(_app)
