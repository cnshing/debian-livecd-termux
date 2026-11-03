#!/usr/bin/env python3
"""Check how /dev/videoN looks to an ordinary program, without streaming.

Usage: v4l2-compat.py N [expected-sysfs-name]
Prints PASS or FAIL per check and exits 1 if any fail.
"""
import os
import stat
import sys

n = int(sys.argv[1])
dev = f"/dev/video{n}"
want = sys.argv[2] if len(sys.argv) > 2 else None
results = []


def check(label, fn):
    try:
        ok, detail = fn()
    except OSError as exc:
        ok, detail = False, exc.strerror
    results.append(ok)
    print(f"{'PASS' if ok else 'FAIL'} {label}: {detail}")


def stat_device():
    st = os.stat(dev)
    ok = stat.S_ISCHR(st.st_mode) and os.major(st.st_rdev) == 81 and os.minor(st.st_rdev) == n
    return ok, f"{stat.filemode(st.st_mode)} {os.major(st.st_rdev)}:{os.minor(st.st_rdev)}"


def listing():
    names = sorted(e for e in os.listdir("/dev") if e.startswith(("video", "v4l-subdev", "media")))
    return f"video{n}" in names and all(x.startswith("video") for x in names), " ".join(names) or "(none)"


def scandir_type():
    # is_file() and is_dir() come from the directory entry's type; stat() from lstat.
    for entry in os.scandir("/dev"):
        if entry.name == f"video{n}":
            special = not entry.is_file() and not entry.is_dir()
            chr_dev = stat.S_ISCHR(entry.stat(follow_symlinks=False).st_mode)
            return special and chr_dev, f"entry type special: {special}, lstat character device: {chr_dev}"
    return False, "missing"


def sysfs():
    names = sorted(os.listdir("/sys/class/video4linux"))
    with open(f"/sys/class/video4linux/video{n}/name") as f:
        name = f.read().strip()
    return f"video{n}" in names and (want is None or name == want), f"{' '.join(names)}; name {name!r}"


def open_fstat():
    fd = os.open(dev, os.O_RDWR)
    try:
        st = os.fstat(fd)
        return stat.S_ISCHR(st.st_mode), stat.filemode(st.st_mode)
    finally:
        os.close(fd)


check("stat reports a V4L2 character device", stat_device)
check("access for read and write", lambda: (os.access(dev, os.R_OK | os.W_OK), ""))
check("/dev lists it and hides the blocked nodes", listing)
check("directory entry type", scandir_type)
check("sysfs", sysfs)
check("lstat-based realpath", lambda: (os.path.realpath(dev) == dev, os.path.realpath(dev)))
check("open and fstat", open_fstat)
sys.exit(0 if all(results) else 1)
