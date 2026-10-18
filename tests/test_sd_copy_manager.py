import json
import os
import threading
import time
from pathlib import Path

import pytest

from config import Config
from devices import BlockDevice
from sd_copy_manager import SDCopyManager


def make_env(tmp_path, with_backup=True, card_files=None, card_id="card-uuid-1"):
    backup = tmp_path / "backup"
    backup.mkdir()
    card = tmp_path / "media" / "CARD"
    card.mkdir(parents=True)
    for rel, content in (card_files or {}).items():
        p = card / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(content)
    devices = []
    if with_backup:
        devices.append(BlockDevice("ssd-uuid", "/dev/sda1", str(backup), "ext4", "BACKUP"))
    devices.append(BlockDevice(card_id, "/dev/sdb1", str(card), "vfat", "CARD", removable=True))
    cfg = Config(backup_dir=str(backup), source_mount_prefixes=[str(tmp_path / "media")],
                 poll_interval=0.05, min_free_mib=0)
    return cfg, devices, backup, card


def run_until_done(mgr, timeout=10):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if mgr._copy_thread is not None and not mgr._copy_thread.is_alive():
            return
        time.sleep(0.02)
    raise AssertionError("copy did not finish")


def test_copies_media_only_and_sorts_by_date(tmp_path):
    cfg, devices, backup, card = make_env(tmp_path, card_files={
        "DCIM/100/DSC001.JPG": b"a" * 100,
        "DCIM/100/DSC001.ARW": b"b" * 200,
        "PRIVATE/M4ROOT/MEDIAPRO.XML": b"<xml/>",
        "AVF_INFO/AVIN0001.BNP": b"junk",
        ".Trashes/x.jpg": b"hidden",
    })
    mtime = time.mktime((2024, 3, 15, 12, 0, 0, 0, 0, -1))
    for f in (card / "DCIM/100").iterdir():
        os.utime(f, (mtime, mtime))
    mgr = SDCopyManager(cfg, device_lister=lambda: devices)
    assert mgr.start_copy()
    run_until_done(mgr)
    st = mgr.get_status()
    assert st["copied_files"] == 2 and st["error_files"] == 0
    assert sorted(p.name for p in (backup / "2024-03-15").iterdir()) == ["DSC001.ARW", "DSC001.JPG"]
    assert not list(backup.glob("**/*.XML"))
    assert not list(backup.glob("**/.*.part"))
    logs = list((backup / ".pisdbackup" / "logs").glob("*.jsonl"))
    assert len(logs) == 1
    events = [json.loads(l)["event"] for l in logs[0].read_text().splitlines()]
    assert events[0] == "start" and events[-1] == "end" and events.count("copy") == 2


def test_reinsert_skips_identical_without_hashing(tmp_path, monkeypatch):
    cfg, devices, backup, card = make_env(tmp_path, card_files={"A.JPG": b"x" * 10})
    mgr = SDCopyManager(cfg, device_lister=lambda: devices)
    mgr.start_copy(); run_until_done(mgr)
    assert mgr.get_status()["copied_files"] == 1

    calls = []
    orig = mgr._hash_file
    monkeypatch.setattr(mgr, "_hash_file", lambda p: calls.append(p) or orig(p))
    mgr.forget_device("card-uuid-1")
    mgr.start_copy(); run_until_done(mgr)
    st = mgr.get_status()
    assert st["skipped_files"] == 1 and st["copied_files"] == 0
    assert calls == []  # size+mtime match -> no hashing


def test_conflicting_name_gets_suffix(tmp_path):
    cfg, devices, backup, card = make_env(tmp_path, card_files={"A.JPG": b"new content"})
    date_dir = backup / SDCopyManager(cfg, device_lister=lambda: devices)._dest_folder(str(card / "A.JPG"))
    date_dir.mkdir(parents=True)
    (date_dir / "A.JPG").write_bytes(b"old")
    mgr = SDCopyManager(cfg, device_lister=lambda: devices)
    mgr.start_copy(); run_until_done(mgr)
    assert (date_dir / "A.JPG").read_bytes() == b"old"
    assert (date_dir / "A_1.JPG").read_bytes() == b"new content"


def test_stale_partial_is_removed_and_copy_is_atomic(tmp_path, monkeypatch):
    cfg, devices, backup, card = make_env(tmp_path, card_files={"A.JPG": b"data"})
    mgr = SDCopyManager(cfg, device_lister=lambda: devices)
    date_dir = backup / mgr._dest_folder(str(card / "A.JPG"))
    date_dir.mkdir(parents=True)
    (date_dir / ".A.JPG.part").write_bytes(b"half")
    # Simulate a verify failure: the destination must not appear.
    monkeypatch.setattr(mgr, "_hash_file", lambda p: "bogus")
    mgr.start_copy(); run_until_done(mgr)
    st = mgr.get_status()
    assert st["error_files"] == 1 and st["copied_files"] == 0
    assert list(date_dir.iterdir()) == []
    assert "checksum" in st["errors"][0]


def test_cancel_does_not_auto_restart(tmp_path):
    files = {f"DCIM/IMG{i:03d}.JPG": bytes([i]) * 50_000 for i in range(200)}
    cfg, devices, backup, card = make_env(tmp_path, card_files=files)
    mgr = SDCopyManager(cfg, device_lister=lambda: devices)
    stop = threading.Event()
    t = threading.Thread(target=mgr.main_loop, args=(stop,), daemon=True)
    t.start()
    deadline = time.time() + 5
    while not mgr.is_copying and time.time() < deadline:
        time.sleep(0.01)
    assert mgr.is_copying
    mgr.stop_copy()
    run_until_done(mgr)
    assert mgr.get_status()["last_result"].startswith("cancelled")
    copied_after_cancel = mgr.get_status()["copied_files"]
    time.sleep(0.4)  # several poll intervals
    assert not mgr.is_copying
    assert mgr.get_status()["copied_files"] == copied_after_cancel
    assert "re-insert" in mgr.get_status()["status_message"]
    stop.set()


def test_removal_and_swap_of_same_mountpoint_triggers_new_copy(tmp_path):
    cfg, devices, backup, card = make_env(tmp_path, card_files={"A.JPG": b"a"})
    current = {"devices": list(devices)}
    mgr = SDCopyManager(cfg, device_lister=lambda: current["devices"])
    stop = threading.Event()
    threading.Thread(target=mgr.main_loop, args=(stop,), daemon=True).start()
    deadline = time.time() + 5
    while mgr.get_status()["copied_files"] < 1 and time.time() < deadline:
        time.sleep(0.01)
    run_until_done(mgr)
    # Swap for a different card mounted at the same path within one poll.
    (card / "A.JPG").unlink(); (card / "B.JPG").write_bytes(b"b")
    current["devices"] = [devices[0], BlockDevice("card-uuid-2", "/dev/sdb1", str(card), "vfat", "CARD", removable=True)]
    deadline = time.time() + 5
    while not (backup.glob("**/B.JPG") and list(backup.glob("**/B.JPG"))) and time.time() < deadline:
        time.sleep(0.02)
    assert list(backup.glob("**/B.JPG"))
    stop.set()


def test_source_is_never_written(tmp_path):
    cfg, devices, backup, card = make_env(tmp_path, card_files={"A.JPG": b"a"})
    before = {p: p.stat().st_mtime_ns for p in card.rglob("*")}
    mgr = SDCopyManager(cfg, device_lister=lambda: devices)
    mgr.get_available_sources()
    mgr.start_copy(); run_until_done(mgr)
    after = {p: p.stat().st_mtime_ns for p in card.rglob("*")}
    assert before == after


def test_missing_backup_drive_blocks_copy(tmp_path):
    cfg, devices, backup, card = make_env(tmp_path, with_backup=False, card_files={"A.JPG": b"a"})
    mgr = SDCopyManager(cfg, device_lister=lambda: devices)
    mgr._tick()
    assert not mgr.is_copying
    assert "SSD" in mgr.get_status()["status_message"]


def test_not_enough_space_aborts(tmp_path, monkeypatch):
    cfg, devices, backup, card = make_env(tmp_path, card_files={"A.JPG": b"a" * 1000})
    mgr = SDCopyManager(cfg, device_lister=lambda: devices)
    monkeypatch.setattr(mgr, "_free_bytes", lambda: 10)
    mgr.start_copy(); run_until_done(mgr)
    st = mgr.get_status()
    assert st["copied_files"] == 0 and "space" in st["status_message"].lower()
