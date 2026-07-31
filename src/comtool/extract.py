"""Extract GPS / G-sensor telemetry from Comtec ZDR055 dashcam AVI files.

The recorder embeds one plain-ASCII record per video frame in stream #2, which
it declares as an unknown subtitle codec.  With a GPS fix the record reads
(coordinates here are Tokyo Station, standing in for a real one):

  ZDR055:2026-01-01 12:00:00 X: 0.03 Y: 0.02 Z: 0.01 023.0T 14.4V \
  G  35.6812362 N  139.7671248 E 26km/hE:255 M:255 EM:255 SA:0 V:100 S:20833k 5,0

and before the receiver acquires one the GPS slot degrades to placeholders:

  ... 000.0T 12.4V - --.------ - ---.------ - ---.-km/h E:255 ...

Front and rear files of the same segment carry byte-identical streams: the
GPS receiver and accelerometer both live in the front unit.
"""
from __future__ import annotations

import csv
import math
import re
import subprocess
import tempfile
from pathlib import Path

FPS = 55 / 2

REC = re.compile(
    r"(?P<dt>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) "
    r"X:\s*(?P<x>-?[\d.]+) Y:\s*(?P<y>-?[\d.]+) Z:\s*(?P<z>-?[\d.]+) "
    r"(?P<temp>[\d.]+)T (?P<volt>[\d.]+)V "
    r"(?P<gps>.*?)km/h"
)

# Present once the receiver has a fix; until then lat/lon/kmh stay blank.
FIX = re.compile(
    r"G\s+(?P<lat>[\d.]+) (?P<ns>[NS])\s+(?P<lon>[\d.]+) (?P<ew>[EW]) "
    r"(?P<kmh>\d+)$"
)


def read_stream(avi):
    """Return the raw metadata stream of an AVI as a str."""
    with tempfile.NamedTemporaryFile(suffix=".bin") as tmp:
        subprocess.run(
            ["ffmpeg", "-v", "error", "-i", str(avi),
             "-map", "0:2", "-c", "copy", "-f", "data", tmp.name, "-y"],
            check=True,
        )
        return Path(tmp.name).read_bytes().decode("ascii", "replace")


def parse(avi):
    """Parse one AVI into a list of telemetry dicts, one per record."""
    rows = []
    for chunk in read_stream(avi).split("ZDR055:"):
        m = REC.match(chunk.strip())
        if not m:
            continue
        g = m.groupdict()
        fix = FIX.match(g["gps"].strip())
        f = fix.groupdict() if fix else {}
        rows.append({
            "datetime": g["dt"],
            "lat": float(f["lat"]) * (1 if f["ns"] == "N" else -1) if fix else "",
            "lon": float(f["lon"]) * (1 if f["ew"] == "E" else -1) if fix else "",
            "kmh": int(f["kmh"]) if fix else "",
            # "023.0T" is not a GPS bearing -- it does not correlate with the
            # track at all.  It reads 000.0 the instant the unit powers up and
            # then climbs on an asymptotic curve (7 after 15 s, 12 after 45 s,
            # 21 after 4 min, 24 after 9 min, 31 after 17 min), so it is a
            # warm-up above the power-on baseline, not ambient air temperature.
            # Course therefore has to come from the track itself, see
            # add_course().
            "temp_rise_c": float(g["temp"]),
            "gx": float(g["x"]),
            "gy": float(g["y"]),
            "gz": float(g["z"]),
            "volt": float(g["volt"]),
        })
    return rows


def video_frames(avi):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v",
         "-show_entries", "stream=nb_frames", "-of", "csv=p=0", str(avi)],
        capture_output=True, text=True, check=True,
    )
    return int(out.stdout.strip().rstrip(","))


def add_course(frames, win=int(FPS * 3)):
    """Fill in a 'course' field: GPS bearing over a +/-win frame window.

    GPS updates at 1 Hz, so a short baseline gives a course that flips around
    on quantisation noise; three seconds is long enough to be stable and short
    enough to follow a turn.  Frames without a fix are left blank.
    """
    for f in frames:
        f["course"] = ""
    fix = [i for i, f in enumerate(frames) if f["lat"] != ""]
    if len(fix) < 2 * win + 2:
        return
    first, last = fix[0], fix[-1]
    for i in fix:
        # slide rather than shrink at the ends, so the first/last fixed frames
        # keep a full-width baseline instead of collapsing to a zero bearing
        lo = max(first, min(i - win, last - 2 * win))
        a, b = frames[lo], frames[min(last, lo + 2 * win)]
        if a["lat"] == "" or b["lat"] == "":
            continue
        dn = b["lat"] - a["lat"]
        de = (b["lon"] - a["lon"]) * math.cos(math.radians(frames[i]["lat"]))
        frames[i]["course"] = round(math.degrees(math.atan2(de, dn)) % 360, 1) \
            if (dn or de) else 0.0


def to_csv(avis, dest):
    """Write one telemetry row per video frame of the concatenated segments."""
    frames = []
    for avi in avis:
        rows, nf = parse(avi), video_frames(avi)
        if not rows:
            raise SystemExit(f"no telemetry records in {avi}")
        # records and frames differ by ~1 per segment; resample by index
        for i in range(nf):
            frames.append(rows[min(i * len(rows) // nf, len(rows) - 1)])
        print(f"  {Path(avi).name}: {len(rows)} records -> {nf} frames")

    add_course(frames)

    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    with open(dest, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["frame", "t"] + list(frames[0]))
        w.writeheader()
        for i, r in enumerate(frames):
            w.writerow({"frame": i, "t": round(i / FPS, 4), **r})

    nofix = sum(1 for r in frames if r["lat"] == "")
    note = f" ({nofix} without a GPS fix)" if nofix else ""
    print(f"  wrote {len(frames)} rows -> {dest}{note}")
    return dest
