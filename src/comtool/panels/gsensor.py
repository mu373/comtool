"""Render the G-sensor waveform panel (gsensor.mp4).

A 6-second window scrolls past a fixed centre playhead, so both the approaching
and the just-passed road show up around "now".  Drawn at telemetry.SS times the
final size and downscaled, which is what keeps the thin traces smooth.

Axes are labelled X/Y/Z exactly as the recorder reports them.  On a straight
run, gx is the only one that tracks GPS-derived longitudinal acceleration
(r=+0.30) while lateral acceleration is too small to separate gy from gz, so
neither is relabelled.
"""
from __future__ import annotations

import time

import numpy as np
from PIL import Image, ImageDraw

from .. import telemetry as tele

W, H = 640, 360
S = tele.SS
HALF = int(tele.FPS * 3)                 # half-window, in frames
GRANGE = 0.32                            # full-scale, g

L, R, T, B = 54, W - 16, 58, H - 34      # plot rectangle, final-size px
BG = (16, 18, 22)
PLOT_BG = (23, 26, 32)
GRID = (40, 44, 53)
ZERO = (84, 91, 105)
FG = (232, 236, 244)
DIM = (124, 132, 148)
HEAD = (255, 255, 255)
TRACES = (("X", "gx", (255, 104, 72)),
          ("Y", "gy", (72, 214, 138)),
          ("Z", "gz", (104, 168, 255)))


def gy_px(v):
    return (T + (GRANGE - v) / (2 * GRANGE) * (B - T)) * S


def render(out_dir=".", limit=0):
    d = tele.load(out_dir)
    n = d["n"]

    # pad with NaN so a window near either end just draws short
    pad = np.full(HALF, np.nan)
    sig = {key: np.concatenate([pad, d[key], pad]) for _, key, _ in TRACES}

    f_ttl = tele.font(16 * S, 600)
    f_lab = tele.font(13 * S, 400)
    f_key = tele.font(14 * S, 600)
    f_val = tele.font(17 * S, 500)
    xs = np.linspace(L * S, R * S, 2 * HALF + 1)

    # static background: plot area, grid, axis labels, title
    bg = Image.new("RGB", (W * S, H * S), BG)
    g = ImageDraw.Draw(bg)
    g.rounded_rectangle([L * S, T * S, R * S, B * S], 4 * S, fill=PLOT_BG)
    for v in (-0.3, -0.2, -0.1, 0.0, 0.1, 0.2, 0.3):
        y = gy_px(v)
        g.line([(L * S, y), (R * S, y)], fill=ZERO if v == 0 else GRID,
               width=int((1.6 if v == 0 else 1) * S))
        g.text(((L - 9) * S, y), f"{v:+.1f}".replace("+0.0", " 0.0"),
               font=f_lab, fill=DIM, anchor="rm")
    for s in (-3, -2, -1, 0, 1, 2, 3):
        x = (L + (s + 3) / 6 * (R - L)) * S
        if s:
            g.line([(x, T * S), (x, B * S)], fill=GRID, width=S)
        g.text((x, (B + 9) * S), f"{s:+d}s" if s else "now",
               font=f_lab, fill=DIM, anchor="ma")
    g.text((16 * S, 26 * S), "Gセンサー", font=f_ttl, fill=FG, anchor="lm")
    g.text((R * S, (T - 12) * S), "g", font=f_lab, fill=DIM, anchor="rs")

    proc = tele.ffmpeg_writer(f"{out_dir}/gsensor.mp4", W, H)
    end = min(n, tele.SKIP + limit) if limit else n
    t0 = time.time()
    for i in range(tele.SKIP, end):
        im = bg.copy()
        g = ImageDraw.Draw(im)
        # playhead sits under the traces so it never cuts through them
        g.line([(xs[HALF], T * S), (xs[HALF], B * S)], fill=HEAD, width=S)
        for k, (name, key, col) in enumerate(TRACES):
            w = sig[key][i:i + 2 * HALF + 1]
            pts = [(x, gy_px(np.clip(v, -GRANGE, GRANGE)))
                   for x, v in zip(xs, w) if not np.isnan(v)]
            if len(pts) > 1:
                g.line(pts, fill=col, width=int(1.8 * S), joint="curve")
            cy = gy_px(np.clip(d[key][i], -GRANGE, GRANGE))
            g.ellipse([xs[HALF] - 3 * S, cy - 3 * S, xs[HALF] + 3 * S, cy + 3 * S],
                      fill=col, outline=BG, width=int(1.2 * S))
            # live readout, one column per axis
            x = (196 + k * 108) * S
            g.rounded_rectangle([x - 6 * S, 15 * S, x + 8 * S, 37 * S],
                                3 * S, fill=col)
            g.text((x + 1 * S, 26 * S), name, font=f_key, fill=BG, anchor="mm")
            g.text((x + 18 * S, 26 * S), f"{d[key][i]:+.2f}",
                   font=f_val, fill=FG, anchor="lm")
        proc.stdin.write(im.resize((W, H), Image.LANCZOS).tobytes())
        if i % 400 == 0:
            print(f"  frame {i}/{end}")
    proc.stdin.close()
    proc.wait()
    print(f"wrote gsensor.mp4 ({end - tele.SKIP} frames in {time.time() - t0:.1f}s)")
