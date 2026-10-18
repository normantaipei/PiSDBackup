import threading
import time
from pathlib import Path

from PIL import Image

from config import Config
from thumbnail_cache import ThumbnailCache
from web_file_manager import create_app


def make_photos(backup: Path, n: int, day="2024-01-01", size=(640, 480)):
    d = backup / day
    d.mkdir(parents=True, exist_ok=True)
    img = Image.new("RGB", size, (10, 20, 30))
    for i in range(n):
        img.save(d / f"IMG{i:04d}.JPG", "JPEG")


def test_warm_generates_all_thumbnails_once_and_prunes_orphans(tmp_path):
    backup = tmp_path / "backup"
    make_photos(backup, 12)
    cfg = Config(backup_dir=str(backup), thumbnail_size=100)
    cache = ThumbnailCache(cfg)

    stats = cache.warm(delay=0)
    assert stats["generated"] == 12 and stats["failed"] == 0
    thumbs = sorted((backup / ".pisdbackup/cache/thumbs/2024-01-01").glob("*.jpg"))
    assert len(thumbs) == 12 and thumbs[0].name == "IMG0000.JPG.jpg"
    with Image.open(thumbs[0]) as im:
        assert max(im.size) <= 100

    # Second run is a no-op.
    stats = cache.warm(delay=0)
    assert stats["generated"] == 0 and stats["skipped"] == 12

    # Deleting a photo removes its cached thumbnail on the next warm.
    (backup / "2024-01-01" / "IMG0003.JPG").unlink()
    stats = cache.warm(delay=0)
    assert stats["pruned"] == 1
    assert not (backup / ".pisdbackup/cache/thumbs/2024-01-01/IMG0003.JPG.jpg").exists()


def test_warm_pauses_while_copying_and_can_be_cancelled(tmp_path):
    backup = tmp_path / "backup"
    make_photos(backup, 5)
    cfg = Config(backup_dir=str(backup), thumbnail_size=64)
    cache = ThumbnailCache(cfg)
    copying = {"v": True}
    assert cache.start_warm(pause_while=lambda: copying["v"])
    assert not cache.start_warm()  # already running
    time.sleep(0.3)
    assert len(list((backup / ".pisdbackup").rglob("*.jpg"))) == 0  # paused: nothing generated yet
    copying["v"] = False
    cache._warm_thread.join(timeout=10)
    assert cache.last_warm_stats["generated"] == 5


def test_preview_cache_size_cap(tmp_path):
    backup = tmp_path / "backup"
    make_photos(backup, 6, size=(1200, 900))
    cfg = Config(backup_dir=str(backup), preview_size=1000, preview_cache_max_mib=0)  # 0 = unlimited
    cache = ThumbnailCache(cfg)
    for p in cache.iter_images():
        assert isinstance(cache.get(p, "previews"), Path)
    previews = list((backup / ".pisdbackup/cache/previews").rglob("*.jpg"))
    assert len(previews) == 6
    total = sum(p.stat().st_size for p in previews)
    # Cap to roughly half: the oldest previews must go, newest stay.
    cache._enforce_size_cap(backup / ".pisdbackup/cache/previews", total // 2)
    remaining = list((backup / ".pisdbackup/cache/previews").rglob("*.jpg"))
    assert 0 < len(remaining) < 6
    assert sum(p.stat().st_size for p in remaining) <= total // 2


def test_concurrent_requests_are_throttled(tmp_path):
    backup = tmp_path / "backup"
    make_photos(backup, 8)
    cfg = Config(backup_dir=str(backup), thumbnail_size=64)
    cache = ThumbnailCache(cfg, max_concurrent=2)
    active, peak, lock = [0], [0], threading.Lock()
    orig = cache._render

    def slow_render(*a, **k):
        with lock:
            active[0] += 1; peak[0] = max(peak[0], active[0])
        time.sleep(0.05)
        try:
            return orig(*a, **k)
        finally:
            with lock:
                active[0] -= 1
    cache._render = slow_render
    threads = [threading.Thread(target=cache.get, args=(p, "thumbs")) for p in cache.iter_images()]
    for t in threads: t.start()
    for t in threads: t.join()
    assert peak[0] <= 2
    assert len(list((backup / ".pisdbackup/cache/thumbs").rglob("*.jpg"))) == 8


def test_api_files_is_paginated(tmp_path):
    backup = tmp_path / "backup"
    make_photos(backup, 7, day="2024-02-02", size=(32, 32))
    make_photos(backup, 5, day="2024-01-01", size=(32, 32))
    cfg = Config(backup_dir=str(backup), web_auth=False, page_size=5, file_list_cache_seconds=0)
    app = create_app(cfg); app.testing = True
    c = app.test_client()
    p1 = c.get("/api/files").get_json()
    assert p1["total"] == 12 and p1["pages"] == 3 and p1["page"] == 1 and p1["has_more"]
    assert len(p1["items"]) == 5 and all(i["day_key"] == "2024-02-02" for i in p1["items"])
    p2 = c.get("/api/files?page=2").get_json()
    assert [i["day_key"] for i in p2["items"]] == ["2024-02-02"] * 2 + ["2024-01-01"] * 3
    p3 = c.get("/api/files?page=3").get_json()
    assert len(p3["items"]) == 2 and not p3["has_more"]
    assert c.get("/api/files?page=99").get_json()["page"] == 3
    assert c.get("/api/files?page=abc").status_code == 200
    names = [i["path"] for p in (p1, p2, p3) for i in p["items"]]
    assert len(set(names)) == 12
