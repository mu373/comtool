"""Locating recorded segments and naming the clip they form."""
from __future__ import annotations

from pathlib import Path

# Where the card mounts on macOS.  Used only if no local copy is present.
CARD = Path("/Volumes/SDHC/NORMAL")
LOCAL = Path("source")

CAMERAS = {"F": "Front", "R": "Rear"}


def default_src():
    return LOCAL if (LOCAL / "Front").is_dir() else CARD


def find(src, stamp, cam):
    """The AVI for one HHMMSS stamp and one camera ('F' or 'R')."""
    d = Path(src) / CAMERAS[cam]
    hits = sorted(d.glob(f"*_{stamp}_{cam}_*.AVI"))
    if not hits:
        raise SystemExit(f"no {CAMERAS[cam]} segment {stamp} under {src}")
    return hits[0].resolve()


def resolve(src, stamps, cam):
    return [find(src, s, cam) for s in stamps]


def clip_name(stamps):
    return stamps[0] if len(stamps) == 1 else f"{stamps[0]}-{stamps[-1]}"


def concat_list(paths, dest):
    """Write an ffmpeg concat demuxer list and return its path."""
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text("".join(f"file '{p}'\n" for p in paths))
    return dest
