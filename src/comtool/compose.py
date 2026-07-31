"""ffmpeg assembly of the finished clips.

Sync: the rear camera records about one frame ahead of the front.  Measured two
independent ways on a 92 s clip --

  * body-pitch motion, via 2-D phase correlation of consecutive frames from
    each camera, cross-correlated: +35.0 ms (sem 7.1 ms over 400-frame blocks,
    |r| = 0.74; the sign is negative because a nose-up pitch moves the two
    images in opposite directions)
  * the microphone track, which both files carry identically: +46.4 ms,
    quantised to the recorder's 1024-sample audio packets

Both land within a frame of each other, so pairing front[k+1] with rear[k]
corrects it; re-measuring the output gave a residual of -1.7 ms.  That is what
`trim=start_frame=1` on the front input does below, with the front audio
trimmed by the same 1/FPS to stay with its own picture.

Audio is front-only.  The rear file's track is the same single microphone
offset by ~46 ms, so mixing the two comb-filters the result.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

from .telemetry import FPS

FRAME = 1.0 / FPS

_ENCODE = [
    "-r", str(FPS),
    "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
    "-pix_fmt", "yuv420p", "-movflags", "+faststart",
    "-c:a", "aac", "-b:a", "192k",
]


def _run(args):
    subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "warning",
                    "-stats", *args], check=True)


def viewer(front_list, rear_list, panels, dest):
    """1920x1080 composite: front + map over rear + gsensor + info.

        1280x720 front | 640x720 map
         640x360 rear  | 640x360 gsensor | 640x360 info
    """
    _run([
        "-f", "concat", "-safe", "0", "-i", str(front_list),
        "-f", "concat", "-safe", "0", "-i", str(rear_list),
        "-i", str(panels["map"]),
        "-i", str(panels["gsensor"]),
        "-i", str(panels["info"]),
        "-filter_complex",
        f"[0:v]trim=start_frame=1,setpts=N/({FPS}*TB),scale=1280:720[f];"
        f"[1:v]setpts=N/({FPS}*TB),scale=640:360[r];"
        "[f][2:v][r][3:v][4:v]xstack=inputs=5:shortest=1:"
        "layout=0_0|1280_0|0_720|640_720|1280_720[v];"
        f"[0:a]atrim=start={FRAME},asetpts=N/SR/TB[a]",
        "-map", "[v]", "-map", "[a]", *_ENCODE, str(dest),
    ])
    return dest


def vstack(front_list, rear_list, dest):
    """1920x2160 front over rear, no overlays."""
    _run([
        "-f", "concat", "-safe", "0", "-i", str(front_list),
        "-f", "concat", "-safe", "0", "-i", str(rear_list),
        "-filter_complex",
        f"[0:v]trim=start_frame=1,setpts=N/({FPS}*TB)[f];"
        f"[1:v]setpts=N/({FPS}*TB)[r];"
        "[f][r]vstack=inputs=2:shortest=1[v];"
        f"[0:a]atrim=start={FRAME},asetpts=N/SR/TB[a]",
        "-map", "[v]", "-map", "[a]", *_ENCODE, str(dest),
    ])
    return dest
