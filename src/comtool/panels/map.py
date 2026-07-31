"""Render the follow-cam map panel (map.mp4).

Downloads the map tiles covering the route once into a local cache, stitches
them into a single basemap, then pans a fixed-zoom window over it so the
vehicle stays centred.

The panel is drawn at MS times its final size and downscaled.  MS=2 pairs with
one extra zoom level, so the basemap supplies real detail rather than an
upscale, and the overlay type comes out clean.
"""
from __future__ import annotations

import math
import os
import ssl
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from .. import telemetry as tele

W, H = 640, 720
MS = 2                                   # supersample factor for this panel
ZOOM = 17 + int(math.log2(MS))           # matching tile detail
CACHE = Path(os.environ.get("COMTOOL_TILE_CACHE", "tiles"))
UA = "comtool/0.1 (dashcam telemetry overlay)"

# GSI (Geospatial Information Authority of Japan) tiles.  The pale style stays
# legible under a bright track overlay, and the attribution below is a
# condition of use -- keep it on the frame.  Terms:
# https://maps.gsi.go.jp/development/ichiran.html
TILE_URL = os.environ.get(
    "COMTOOL_TILE_URL",
    "https://cyberjapandata.gsi.go.jp/xyz/pale/{z}/{x}/{y}.png")
ATTRIB = os.environ.get("COMTOOL_TILE_ATTRIB", "地理院タイル（国土地理院）")

BG = (26, 28, 32)
TRACK_HALO = (255, 255, 255)             # keeps the route readable over roads
TRACK_AHEAD = (46, 96, 210)              # route not driven yet
TRACK_DONE = (240, 70, 30)               # route already driven
CAR = (20, 190, 255)
FG = (236, 238, 242)
PANEL = (18, 20, 24, 178)


def ssl_context():
    """A context with a usable CA bundle.

    Some Python builds (notably the macOS python.org one) ship no root
    certificates, so a plain urlopen dies with CERTIFICATE_VERIFY_FAILED.
    """
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


CTX = ssl_context()


def fetch_tile(z, x, y):
    p = CACHE / f"{z}_{x}_{y}.png"
    if p.exists():
        return Image.open(p).convert("RGB")
    CACHE.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(TILE_URL.format(z=z, x=x, y=y),
                                 headers={"User-Agent": UA})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=20, context=CTX) as r:
                p.write_bytes(r.read())
            return Image.open(p).convert("RGB")
        except urllib.error.HTTPError as e:
            if e.code == 404:                       # tile genuinely absent
                break
            time.sleep(0.5 * (attempt + 1))
        except ssl.SSLError as e:                   # permanent; retrying wastes time
            raise SystemExit(f"TLS failure fetching tiles: {e}\n"
                             "Install certifi, or run the certificate installer "
                             "that ships with your Python.")
        except Exception:
            time.sleep(0.5 * (attempt + 1))
    print(f"  tile {z}/{x}/{y} unavailable", file=sys.stderr)
    return None


def build_basemap(px, py):
    """Stitch every tile needed to pan a (W x H) * MS window along the track."""
    mw, mh = W * MS, H * MS
    x0, x1 = px.min() - mw / 2 - 8, px.max() + mw / 2 + 8
    y0, y1 = py.min() - mh / 2 - 8, py.max() + mh / 2 + 8
    tx0, tx1 = int(x0 // tele.TILE), int(x1 // tele.TILE)
    ty0, ty1 = int(y0 // tele.TILE), int(y1 // tele.TILE)
    nx, ny = tx1 - tx0 + 1, ty1 - ty0 + 1
    print(f"basemap: {nx}x{ny} = {nx * ny} tiles at z{ZOOM}")
    base = Image.new("RGB", (nx * tele.TILE, ny * tele.TILE), BG)
    t0, got = time.time(), 0
    for j, ty in enumerate(range(ty0, ty1 + 1)):
        for i, tx in enumerate(range(tx0, tx1 + 1)):
            img = fetch_tile(ZOOM, tx, ty)
            if img is not None:
                base.paste(img, (i * tele.TILE, j * tele.TILE))
                got += 1
    print(f"  {got}/{nx * ny} tiles in {time.time() - t0:.1f}s")
    if got < nx * ny / 2:
        raise SystemExit("too many tiles missing - refusing to render a blank map")
    # pixel offset from world Mercator coords into this stitched image
    return base, tx0 * tele.TILE, ty0 * tele.TILE


def car_marker(draw, cx, cy, course_deg):
    """Draw the vehicle at (cx, cy) pointing along course_deg (CW from north).

    Screen axes are x-east / y-south, so forward maps to (sin, -cos) and the
    marker's right side to (cos, sin).  Nothing is drawn under the marker, so
    the travelled track stays visible right up to it.
    """
    a = math.radians(course_deg)
    ca, sa = math.cos(a), math.sin(a)

    def rot(u, v):
        return (cx + (u * ca + v * sa) * MS, cy + (u * sa - v * ca) * MS)

    draw.polygon([rot(0, 22), rot(-14, -15), rot(0, -6), rot(14, -15)],
                 fill=CAR + (255,), outline=(255, 255, 255, 255),
                 width=int(2.5 * MS))


def searching_frame(mw, mh, clock, f_big, f_lab):
    """Panel shown while the receiver has no fix -- no map, no guessed position."""
    im = Image.new("RGB", (mw, mh), (22, 24, 29))
    g = ImageDraw.Draw(im)
    cx, cy = mw // 2, mh // 2
    for k, r in enumerate((46, 66, 86)):
        v = 60 - k * 14
        g.ellipse([cx - r * MS, cy - r * MS, cx + r * MS, cy + r * MS],
                  outline=(v, v + 4, v + 10), width=int(2 * MS))
    g.text((cx, cy), "GPS", font=f_lab, fill=(150, 158, 172), anchor="mm")
    g.text((cx, cy + 130 * MS), "測位中…", font=f_big, fill=(216, 220, 228),
           anchor="mm")
    g.text((cx, cy + 170 * MS), clock, font=f_lab, fill=(120, 128, 142),
           anchor="mm")
    return im


def render(out_dir=".", limit=0):
    d = tele.load(out_dir)
    n = d["n"]
    px, py = tele.merc(d["lat_s"], d["lon_s"], ZOOM)
    have = np.isfinite(px) & np.isfinite(py)
    mw, mh = W * MS, H * MS

    f_val = tele.font(15 * MS, 500)
    f_lab = tele.font(12 * MS, 400)
    f_big = tele.font(22 * MS, 500)

    end = min(n, tele.SKIP + limit) if limit else n
    proc = tele.ffmpeg_writer(f"{out_dir}/map.mp4", W, H)
    t0 = time.time()

    if not have[tele.SKIP:end].any():
        print("no GPS fix anywhere in this clip - rendering the searching panel")
        for i in range(tele.SKIP, end):
            im = searching_frame(mw, mh, d["datetime"][i].split(" ")[1],
                                 f_big, f_lab)
            proc.stdin.write(im.resize((W, H), Image.LANCZOS).tobytes())
        proc.stdin.close()
        proc.wait()
        print(f"wrote map.mp4 ({end - tele.SKIP} frames in {time.time() - t0:.1f}s)")
        return

    base, ox, oy = build_basemap(px[have], py[have])
    bx, by = px - ox, py - oy               # track in stitched-image pixels

    # course from the smoothed track tangent -- steadier than a 1 Hz bearing.
    # The window is clamped inside the fixed span so it never samples a NaN.
    win = int(tele.FPS * 2)
    fx = np.nonzero(have)[0]
    course = np.full(n, np.nan)
    lo = np.clip(fx - win, fx[0], fx[-1])
    hi = np.clip(fx + win, fx[0], fx[-1])
    course[fx] = np.degrees(np.arctan2(bx[hi] - bx[lo],
                                       -(by[hi] - by[lo]))) % 360

    # mute the basemap so the overlay reads clearly on top of it
    base = Image.blend(base, Image.new("RGB", base.size, (255, 255, 255)), 0.35)

    # burn the full route into the basemap once; only the travelled part and the
    # marker are drawn per frame.  A white halo separates it from the road fill.
    dr = ImageDraw.Draw(base)
    route = list(zip(bx[have], by[have]))
    dr.line(route, fill=TRACK_HALO, width=int(11 * MS), joint="curve")
    dr.line(route, fill=TRACK_AHEAD, width=int(6 * MS), joint="curve")

    bar_m = 100
    bar_px = int(bar_m / tele.m_per_px(float(np.nanmean(d["lat"])), ZOOM))
    step = 4                                 # decimate the travelled polyline

    for i in range(tele.SKIP, end):
        if not have[i]:
            im = searching_frame(mw, mh, d["datetime"][i].split(" ")[1],
                                 f_big, f_lab)
            proc.stdin.write(im.resize((W, H), Image.LANCZOS).tobytes())
            continue
        left, top = int(bx[i] - mw / 2), int(by[i] - mh / 2)
        fr = base.crop((left, top, left + mw, top + mh)).convert("RGBA")
        ov = Image.new("RGBA", (mw, mh), (0, 0, 0, 0))
        g = ImageDraw.Draw(ov)

        sl = np.nonzero(have[:i + 1])[0][::step]
        pts = [(x - left, y - top) for x, y in zip(bx[sl], by[sl])]
        pts.append((bx[i] - left, by[i] - top))
        m = 60 * MS
        vis = [p for p in pts if -m < p[0] < mw + m and -m < p[1] < mh + m]
        if len(vis) > 1:
            g.line(vis, fill=TRACK_DONE + (255,), width=int(6 * MS), joint="curve")

        car_marker(g, bx[i] - left, by[i] - top, course[i])

        # coordinate readout
        g.rounded_rectangle([8 * MS, 8 * MS, 312 * MS, 36 * MS], 5 * MS, fill=PANEL)
        g.text((18 * MS, 22 * MS), f"{d['lat'][i]:.6f}° N   {d['lon'][i]:.6f}° E",
               font=f_val, fill=FG + (255,), anchor="lm")
        # scale bar
        g.rounded_rectangle([8 * MS, mh - 46 * MS, 26 * MS + bar_px, mh - 10 * MS],
                            5 * MS, fill=PANEL)
        y = mh - 21 * MS
        g.line([(18 * MS, y), (18 * MS + bar_px, y)], fill=FG + (255,),
               width=int(2.5 * MS))
        for xx in (18 * MS, 18 * MS + bar_px):
            g.line([(xx, y - 6 * MS), (xx, y + 6 * MS)], fill=FG + (255,),
                   width=int(2.5 * MS))
        g.text((18 * MS, mh - 33 * MS), f"{bar_m} m   z{ZOOM}", font=f_lab,
               fill=FG + (255,), anchor="lm")
        g.text((mw - 8 * MS, mh - 8 * MS), ATTRIB, font=f_lab,
               fill=(80, 80, 80, 230), anchor="rd")

        out = Image.alpha_composite(fr, ov).convert("RGB")
        proc.stdin.write(out.resize((W, H), Image.LANCZOS).tobytes())
        if i % 400 == 0:
            el = time.time() - t0
            done = i - tele.SKIP + 1
            print(f"  frame {i}/{end}  {done / max(el, 1e-9):.0f} fps  "
                  f"eta {el / done * (end - tele.SKIP - done):.0f}s")
    proc.stdin.close()
    proc.wait()
    print(f"wrote map.mp4 ({end - tele.SKIP} frames in {time.time() - t0:.1f}s)")
