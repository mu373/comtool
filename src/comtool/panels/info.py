"""Render the telemetry readout panel (info.mp4).

A round needle gauge for speed plus the recorded fix, drawn at telemetry.SS
times the final size and downscaled so the type stays crisp.  Speed comes from
the smoothed GPS series so neither needle nor digits jump once a second.
"""
from __future__ import annotations

import math
import time

from PIL import Image, ImageDraw

from .. import telemetry as tele

W, H = 640, 360
S = tele.SS

BG = (16, 18, 22)
FG = (236, 240, 248)
DIM = (124, 132, 148)
RULE = (44, 48, 58)
ACC = (255, 96, 64)
DIAL_BG = (24, 27, 33)
DIAL_ARC = (58, 63, 74)

VMAX = 80                       # gauge full scale, km/h
CX, CY, RAD = 150, 190, 118     # dial centre and radius, in final-size px
A0, A1 = 150.0, 390.0           # sweep start/end, degrees clockwise from east

ROWS_X, RIGHT = 306 * S, (W - 20) * S
ROW_Y = (196 * S, 282 * S)      # baselines of the latitude / longitude rows


def polar(cx, cy, r, deg):
    a = math.radians(deg)
    return cx + r * math.cos(a), cy + r * math.sin(a)


def draw_dial_face(g):
    """Everything on the dial that never changes."""
    cx, cy, r = CX * S, CY * S, RAD * S
    g.ellipse([cx - r, cy - r, cx + r, cy + r], fill=DIAL_BG)
    g.arc([cx - r, cy - r, cx + r, cy + r], A0, A1, fill=DIAL_ARC, width=int(2 * S))
    f_tick = tele.font(15 * S, 500)
    for v in range(0, VMAX + 1, 5):
        ang = A0 + (A1 - A0) * v / VMAX
        major = v % 10 == 0
        r1 = r - (14 if major else 8) * S
        g.line([polar(cx, cy, r1, ang), polar(cx, cy, r - 2 * S, ang)],
               fill=FG if major else DIM, width=int((2.5 if major else 1.5) * S))
        if major:
            tx, ty = polar(cx, cy, r - 30 * S, ang)
            g.text((tx, ty), str(v), font=f_tick, fill=DIM, anchor="mm")


def draw_needle(g, kmh, f_speed):
    """The parts that move: progress arc, needle, hub and digits.

    kmh is NaN before the receiver gets a fix; the needle rests at zero and the
    digits read "--" rather than implying a measured standstill.
    """
    cx, cy, r = CX * S, CY * S, RAD * S
    known = not math.isnan(kmh)
    kmh = kmh if known else 0.0
    sweep = (A1 - A0) * min(kmh / VMAX, 1.0)
    if sweep > 0.5:
        g.arc([cx - r + 3 * S, cy - r + 3 * S, cx + r - 3 * S, cy + r - 3 * S],
              A0, A0 + sweep, fill=ACC, width=int(5 * S))

    ang = A0 + (A1 - A0) * min(kmh / VMAX, 1.0)
    g.polygon([polar(cx, cy, r - 22 * S, ang),
               polar(cx, cy, 7 * S, ang + 90),
               polar(cx, cy, 16 * S, ang + 180),
               polar(cx, cy, 7 * S, ang - 90)], fill=ACC)
    g.ellipse([cx - 9 * S, cy - 9 * S, cx + 9 * S, cy + 9 * S],
              fill=BG, outline=ACC, width=int(2.5 * S))
    g.text((cx, cy + 46 * S), f"{kmh:.0f}" if known else "--",
           font=f_speed, fill=FG if known else DIM, anchor="mm")


def render(out_dir=".", limit=0):
    d = tele.load(out_dir)
    n = d["n"]

    f_lab = tele.font(14 * S, 400)
    f_val = tele.font(23 * S, 500)
    f_big = tele.font(34 * S, 600)
    f_speed = tele.font(46 * S, 600)

    bg = Image.new("RGB", (W * S, H * S), BG)
    g = ImageDraw.Draw(bg)
    draw_dial_face(g)
    g.text((CX * S, (CY + 76) * S), "km/h", font=f_lab, fill=DIM, anchor="mm")
    g.text((ROWS_X, 70 * S), "時刻", font=f_lab, fill=DIM, anchor="ls")
    g.line([(ROWS_X, 136 * S), (RIGHT, 136 * S)], fill=RULE, width=S)
    for lab, y in zip(("緯度", "経度"), ROW_Y):
        g.text((ROWS_X, y), lab, font=f_lab, fill=DIM, anchor="ls")
    g.line([(ROWS_X, 222 * S), (RIGHT, 222 * S)], fill=RULE, width=S)

    proc = tele.ffmpeg_writer(f"{out_dir}/info.mp4", W, H)
    end = min(n, tele.SKIP + limit) if limit else n
    t0 = time.time()
    for i in range(tele.SKIP, end):
        im = bg.copy()
        g = ImageDraw.Draw(im)
        draw_needle(g, d["kmh_s"][i], f_speed)

        date, clock = d["datetime"][i].split(" ")
        g.text((ROWS_X, 112 * S), clock, font=f_big, fill=FG, anchor="ls")
        g.text((RIGHT, 112 * S), date, font=f_lab, fill=DIM, anchor="rs")
        fix = d["fix"][i]
        for val, y in zip((f"{d['lat'][i]:.6f}° N", f"{d['lon'][i]:.6f}° E")
                          if fix else ("測位中…", "測位中…"), ROW_Y):
            g.text((RIGHT, y), val, font=f_val, fill=FG if fix else DIM,
                   anchor="rs")

        proc.stdin.write(im.resize((W, H), Image.LANCZOS).tobytes())
        if i % 400 == 0:
            print(f"  frame {i}/{end}")
    proc.stdin.close()
    proc.wait()
    print(f"wrote info.mp4 ({end - tele.SKIP} frames in {time.time() - t0:.1f}s)")
