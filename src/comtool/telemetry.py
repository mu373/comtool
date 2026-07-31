"""Loading and drawing helpers shared by the panel renderers."""
from __future__ import annotations

import csv
import math
import os
import subprocess
from pathlib import Path

import numpy as np
from PIL import ImageFont
from scipy.interpolate import PchipInterpolator

FPS = 55 / 2
TILE = 256

# Panels are drawn at SS times their final size and LANCZOS-downscaled, which
# is what keeps small text and thin plot lines clean at 640 px wide.
SS = 3

# The composite drops the first source frame to correct the one-frame
# front/rear offset, so every panel must cover CSV rows SKIP..end to stay
# aligned.  See vstack.sh for how that offset was measured.
SKIP = 1

FONT_ENV = "COMTOOL_FONT"

# Any font with Japanese coverage will do; these are the usual system ones.
FONT_CANDIDATES = (
    "~/Library/Fonts/NotoSansJP-VariableFont_wght.ttf",
    "/Library/Fonts/NotoSansJP-VariableFont_wght.ttf",
    "/System/Library/Fonts/ヒラギノ角ゴシック W4.ttc",
    "/System/Library/Fonts/Hiragino Sans GB.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJKjp-Regular.otf",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc",
    "C:/Windows/Fonts/YuGothM.ttc",
    "C:/Windows/Fonts/meiryo.ttc",
)


def _find_font():
    override = os.environ.get(FONT_ENV)
    if override:
        if not Path(override).expanduser().is_file():
            raise SystemExit(f"{FONT_ENV} points at a missing file: {override}")
        return str(Path(override).expanduser())
    for p in FONT_CANDIDATES:
        q = Path(p).expanduser()
        if q.is_file():
            return str(q)
    raise SystemExit(
        "no Japanese-capable font found. Install Noto Sans JP "
        "(https://fonts.google.com/noto/specimen/Noto+Sans+JP) or point "
        f"{FONT_ENV} at a .ttf/.ttc that covers Japanese."
    )


_FONT_PATH = None


def font(size, weight=400):
    """A font instance at `size` px; `weight` applies to variable fonts only."""
    global _FONT_PATH
    if _FONT_PATH is None:
        _FONT_PATH = _find_font()
    f = ImageFont.truetype(_FONT_PATH, int(size))
    try:
        f.set_variation_by_axes([weight])
    except (OSError, AttributeError, ValueError):
        pass                      # static font: single weight, nothing to set
    return f


def load(out_dir="."):
    """Load telemetry.csv into a dict of numpy arrays, GPS smoothed per frame.

    The receiver reports position at 1 Hz and holds the value in between, so a
    raw plot steps once a second; interpolating through the change-points
    restores per-frame motion.

    Before the receiver gets a fix it emits "- --.------ ... ---.-km/h", which
    the extractor leaves blank.  Those frames come back as NaN and are flagged
    in d["fix"]; smoothing runs over the fixed frames only.
    """
    path = Path(out_dir) / "telemetry.csv"
    rows = list(csv.DictReader(open(path)))
    if not rows:
        raise SystemExit(f"{path} has no rows")

    def num(v):
        return float(v) if v not in ("", None) else np.nan

    d = {k: np.array([num(r[k]) for r in rows])
         for k in ("t", "lat", "lon", "kmh", "gx", "gy", "gz",
                   "temp_rise_c", "volt")}
    d["datetime"] = [r["datetime"] for r in rows]
    d["n"] = len(rows)
    d["fix"] = ~(np.isnan(d["lat"]) | np.isnan(d["lon"]))

    idx = np.arange(len(rows))
    fix = np.nonzero(d["fix"])[0]
    for k in ("lat", "lon", "kmh"):
        d[k + "_s"] = d[k].copy()
    if len(fix) > 3:
        # knots = frames where the fix actually updates
        step = np.nonzero((np.diff(d["lat"][fix]) != 0)
                          | (np.diff(d["lon"][fix]) != 0))[0] + 1
        chg = fix[np.concatenate(([0], step))]
        if len(chg) > 2:
            for k in ("lat", "lon", "kmh"):
                d[k + "_s"] = PchipInterpolator(chg, d[k][chg],
                                                extrapolate=True)(idx)
                d[k + "_s"][~d["fix"]] = np.nan
    return d


def merc(lat, lon, z):
    """Web-Mercator pixel coordinates at zoom z."""
    n = TILE * 2 ** z
    x = (np.asarray(lon) + 180.0) / 360.0 * n
    la = np.radians(np.asarray(lat))
    y = (1.0 - np.log(np.tan(la) + 1.0 / np.cos(la)) / math.pi) / 2.0 * n
    return x, y


def m_per_px(lat, z):
    return 156543.033928 * math.cos(math.radians(lat)) / 2 ** z


def ffmpeg_writer(path, w, h, fps=FPS, crf=18):
    """Open an ffmpeg process that accepts raw RGB24 frames on stdin."""
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    return subprocess.Popen(
        ["ffmpeg", "-v", "error", "-y",
         "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{w}x{h}",
         "-r", f"{fps}", "-i", "-",
         "-c:v", "libx264", "-preset", "veryfast", "-crf", str(crf),
         "-pix_fmt", "yuv420p", str(path)],
        stdin=subprocess.PIPE,
    )
