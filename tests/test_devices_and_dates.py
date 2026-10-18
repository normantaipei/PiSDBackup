import os
import time
from datetime import datetime

from PIL import Image

from devices import BlockDevice, find_source_devices, find_backup_device, _parent_disk
from media_dates import get_capture_date_folder, _parse_exif_datetime


def test_parent_disk():
    assert _parent_disk("/dev/sda1") == "/dev/sda"
    assert _parent_disk("/dev/nvme0n1p2") == "/dev/nvme0n1"
    assert _parent_disk("/dev/mmcblk1p1") == "/dev/mmcblk1"


def test_source_selection_excludes_backup_disk_boot_card_and_system():
    devs = [
        BlockDevice("root", "/dev/mmcblk0p2", "/", "ext4"),
        BlockDevice("boot", "/dev/mmcblk0p1", "/boot/firmware", "vfat"),
        BlockDevice("ssd", "/dev/sda1", "/mnt/backup_drive", "ext4"),
        BlockDevice("ssd2", "/dev/sda2", "/media/pi/OTHER", "exfat"),          # same disk as backup
        BlockDevice("card", "/dev/sdb1", "/media/pi/NO NAME", "vfat", removable=True),
        BlockDevice("card2", "/dev/sdc1", "/media/pisdbackup/sdc1", "exfat", removable=True, read_only=True),
        BlockDevice("net", "/dev/sdd1", "/srv/nas", "ext4"),
    ]
    srcs = find_source_devices("/mnt/backup_drive", ["/media", "/mnt", "/run/media"], devs)
    assert [s.device_id for s in srcs] == ["card", "card2"]
    assert find_backup_device("/mnt/backup_drive", devs).device_id == "ssd"


def test_exif_date_preferred_over_mtime(tmp_path):
    img = Image.new("RGB", (10, 10))
    exif = Image.Exif()
    exif[0x0132] = "2022:08:09 10:11:12"
    ifd = exif.get_ifd(0x8769)
    ifd[0x9003] = "2021:12:24 18:00:00"
    path = tmp_path / "a.jpg"
    img.save(path, exif=exif.tobytes())
    old = time.mktime((2000, 1, 1, 0, 0, 0, 0, 0, -1))
    os.utime(path, (old, old))
    assert get_capture_date_folder(str(path)) == "2021-12-24"


def test_mtime_fallback(tmp_path):
    p = tmp_path / "clip.mts"
    p.write_bytes(b"x")
    ts = time.mktime((2023, 5, 6, 7, 8, 9, 0, 0, -1))
    os.utime(p, (ts, ts))
    assert get_capture_date_folder(str(p)) == "2023-05-06"


def test_parse_exif_datetime_rejects_garbage():
    assert _parse_exif_datetime("0000:00:00 00:00:00") is None
    assert _parse_exif_datetime(b"2020:01:02 03:04:05") == datetime(2020, 1, 2, 3, 4, 5)
