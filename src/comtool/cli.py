"""Command line entry point.

    comtool compose 120000 120030 120100    telemetry + panels + 1920x1080 composite
    comtool vstack  120000 120030 120100    front over rear, no overlays
    comtool panels  120000 120030 120100    just the three panel videos
    comtool extract 120000 120030 120100    just telemetry.csv

Segments are named by the HHMMSS stamp in their filename, listed in playback
order.  Output goes to <out>/<first>-<last>/.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from . import compose, extract, segments

PANELS = ("map", "gsensor", "info")


def _render(name, out_dir, limit):
    """Run one panel renderer; a module-level target so it can be subprocessed."""
    from importlib import import_module
    import_module(f"comtool.panels.{name}").render(out_dir, limit)
    return name


class Clip:
    """One run of segments and the directory its artefacts live in."""

    def __init__(self, args):
        self.stamps = args.segments
        self.src = Path(args.src) if args.src else segments.default_src()
        self.dir = Path(args.out) / segments.clip_name(self.stamps)
        self.dir.mkdir(parents=True, exist_ok=True)
        print(f"{segments.clip_name(self.stamps)}: {len(self.stamps)} segment(s) "
              f"from {self.src} -> {self.dir}")

    def lists(self):
        return (segments.concat_list(segments.resolve(self.src, self.stamps, "F"),
                                     self.dir / "front.txt"),
                segments.concat_list(segments.resolve(self.src, self.stamps, "R"),
                                     self.dir / "rear.txt"))

    def extract(self):
        return extract.to_csv(segments.resolve(self.src, self.stamps, "F"),
                              self.dir / "telemetry.csv")

    def panels(self, only=PANELS, limit=0):
        if not (self.dir / "telemetry.csv").exists():
            self.extract()
        with ProcessPoolExecutor(max_workers=len(only)) as pool:
            list(pool.map(_render, only, [str(self.dir)] * len(only),
                          [limit] * len(only)))
        return {n: self.dir / f"{n}.mp4" for n in PANELS}


def main(argv=None):
    p = argparse.ArgumentParser(
        prog="comtool", description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--src", help="footage root with Front/ and Rear/ "
                                 "(default: ./source, else the mounted card)")
    p.add_argument("--out", default="out", help="output root (default: out)")
    sub = p.add_subparsers(dest="cmd", required=True)

    for name, help_ in (("compose", "telemetry, panels and the 1920x1080 composite"),
                        ("vstack", "front over rear at full size, no overlays"),
                        ("panels", "the three panel videos only"),
                        ("extract", "telemetry.csv only")):
        s = sub.add_parser(name, help=help_)
        s.add_argument("segments", nargs="+", metavar="HHMMSS")
        if name == "panels":
            s.add_argument("--only", default=",".join(PANELS),
                           help=f"comma-separated subset of {','.join(PANELS)}")
            s.add_argument("--limit", type=int, default=0,
                           help="render only this many frames (quick preview)")

    args = p.parse_args(argv)
    clip = Clip(args)

    if args.cmd == "extract":
        clip.extract()
    elif args.cmd == "panels":
        only = [n.strip() for n in args.only.split(",") if n.strip()]
        bad = set(only) - set(PANELS)
        if bad:
            p.error(f"unknown panel(s): {', '.join(sorted(bad))}")
        clip.panels(only, args.limit)
    elif args.cmd == "vstack":
        front, rear = clip.lists()
        dest = compose.vstack(front, rear,
                              clip.dir / f"{clip.dir.name}_vstack.mp4")
        print(f"wrote {dest}")
    elif args.cmd == "compose":
        front, rear = clip.lists()
        panels = clip.panels()
        dest = compose.viewer(front, rear, panels,
                              clip.dir / f"{clip.dir.name}_viewer.mp4")
        print(f"wrote {dest}")


if __name__ == "__main__":
    main()
