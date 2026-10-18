import os
from pathlib import Path

import pytest
from PIL import Image

from config import Config
from web_file_manager import create_app


@pytest.fixture
def env(tmp_path):
    backup = tmp_path / "backup"
    day = backup / "2024-05-01"
    day.mkdir(parents=True)
    img = Image.new("RGB", (800, 600), (200, 30, 30))
    img.save(day / "DSC001.JPG", "JPEG")
    (day / "DSC001.ARW").write_bytes(b"raw")
    (day / "notes.txt").write_text("x")
    (backup / ".pisdbackup").mkdir()
    (backup / ".pisdbackup" / "secret.jpg").write_bytes(b"x")
    cfg = Config(backup_dir=str(backup), web_token="testtoken", file_list_cache_seconds=0)
    app = create_app(cfg)
    app.testing = True
    return cfg, app, backup


def test_requires_token(env):
    cfg, app, _ = env
    c = app.test_client()
    assert c.get("/").status_code == 401
    assert c.get("/api/files").status_code == 401
    r = c.get("/?token=wrong")
    assert r.status_code == 401
    r = c.get("/?token=testtoken")
    assert r.status_code == 302 and "pisd_token" in r.headers.get("Set-Cookie", "")
    assert c.get("/").status_code == 200
    assert c.get("/api/files").status_code == 200


def test_auth_can_be_disabled(tmp_path):
    cfg = Config(backup_dir=str(tmp_path), web_auth=False)
    app = create_app(cfg); app.testing = True
    assert app.test_client().get("/").status_code == 200


def test_listing_groups_by_folder_date_and_finds_raw(env):
    cfg, app, _ = env
    c = app.test_client(); c.get("/?token=testtoken")
    data = c.get("/api/files").get_json()
    assert data["count"] == 1
    item = data["grouped_files"][0]["days"][0]["items"][0]
    assert item["name"] == "DSC001.JPG"
    assert item["raw_path"] == "2024-05-01/DSC001.ARW"
    assert data["grouped_files"][0]["days"][0]["title_day"].endswith("May 01, 2024")


def test_thumbnail_is_cached_and_small(env):
    cfg, app, backup = env
    c = app.test_client(); c.get("/?token=testtoken")
    r = c.get("/api/thumbnail?path=2024-05-01/DSC001.JPG")
    assert r.status_code == 200 and r.mimetype == "image/jpeg"
    cached = list((backup / ".pisdbackup" / "cache" / "thumbs").rglob("*.jpg"))
    assert len(cached) == 1
    with Image.open(cached[0]) as im:
        assert max(im.size) <= cfg.thumbnail_size
    r2 = c.get("/api/preview?path=2024-05-01/DSC001.JPG")
    assert r2.status_code == 200


def test_path_traversal_and_private_dirs_are_blocked(env):
    cfg, app, backup = env
    c = app.test_client(); c.get("/?token=testtoken")
    assert c.get("/api/download?path=../../etc/passwd").status_code == 403
    assert c.get("/api/download?path=.pisdbackup/secret.jpg").status_code == 403
    assert c.get("/api/download?path=2024-05-01/missing.jpg").status_code == 404
    assert c.get("/api/download?path=").status_code == 400
    r = c.get("/api/download?path=2024-05-01/DSC001.ARW")
    assert r.status_code == 200 and "attachment" in r.headers["Content-Disposition"]


def test_write_endpoints_are_gone(env):
    cfg, app, _ = env
    c = app.test_client(); c.get("/?token=testtoken")
    for ep in ("/api/rename", "/api/delete", "/api/upload"):
        assert c.post(ep).status_code in (404, 405)


def test_page_has_no_external_resources(env):
    cfg, app, _ = env
    c = app.test_client(); c.get("/?token=testtoken")
    html = c.get("/").get_data(as_text=True)
    assert "googleapis" not in html and "http://" not in html.replace("http://www.w3.org", "")
