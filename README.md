# comtool

Extract the GPS and G-sensor telemetry from **Comtec (コムテック) ZDR055** dashcam footages, and render a viewer-style composite from the front and rear cameras.

```
┌──────────────────────┬─────────┐
│                      │   MAP   │
│        FRONT         │ 640×720 │
│       1280×720       │         │
├──────────┬───────────┼─────────┤
│   REAR   │ G-SENSOR  │  INFO   │
│ 640×360  │  640×360  │ 640×360 │
└──────────┴───────────┴─────────┘
            1920 × 1080
```

## Requirements

- [uv](https://docs.astral.sh/uv/)
- `ffmpeg` and `ffprobe` on `PATH`
- a font with Japanese coverage: Noto Sans JP, Hiragino, Yu Gothic and Noto Sans CJK are all found automatically; set `COMTOOL_FONT` to override

## Usage

Copy the segments you want off the card (they are named
`YYYYMMDD_HHMMSS_{F,R}_*.AVI`), keeping the `Front/` and `Rear/` split:

```sh
mkdir -p source/Front source/Rear
cp /Volumes/SDHC/NORMAL/Front/20260101_1200*_F_*.AVI source/Front/
cp /Volumes/SDHC/NORMAL/Rear/20260101_1200*_R_*.AVI  source/Rear/
```

Then name the segments by their `HHMMSS` stamp, in playback order:

```sh
uv run comtool compose 120000 120030 120100
```

| command | output |
| --- | --- |
| `comtool compose SEG…` | telemetry, the three panels, and the 1920×1080 composite |
| `comtool vstack SEG…` | front over rear at full 1920×2160, no overlays |
| `comtool panels SEG…` | the three panel videos only (`--only map,info`, `--limit 300`) |
| `comtool extract SEG…` | `telemetry.csv` only |

Everything lands in `out/<first>-<last>/`. `--src` reads from somewhere else
(it defaults to `./source`, falling back to the mounted card) and `--out`
moves the output root:

```sh
uv run comtool --src /Volumes/SDHC/NORMAL compose 120130 120200 120230
```

## Telemetry format

Stream #2 of every AVI is one plain-ASCII record per video frame, declared as
an unknown subtitle codec. No binary format to reverse:

```
ZDR055:2026-01-01 12:00:00 X: 0.03 Y: 0.02 Z: 0.01 023.0T 14.4V G  35.6812362 N  139.7671248 E 26km/hE:255 M:255 EM:255 SA:0 V:100 S:20833k 5,0
```

Before the receiver acquires a fix the GPS slot degrades to placeholders, and those columns are left blank:

```
... 000.0T 12.4V - --.------ - ---.------ - ---.-km/h E:255 ...
```

The front and rear files of a segment carry byte-identical streams — the GPS
receiver and the accelerometer both live in the front unit.

`telemetry.csv` columns:
`frame`, `t`, `datetime`, `lat`, `lon`, `kmh`, `temp_rise_c`, `gx`, `gy`, `gz`, `volt`, `course`


### Notes

**`023.0T` is not a heading.** It has no correlation with the direction of
travel. It reads `000.0` the instant the unit powers up and then climbs on an
asymptotic curve — 7 after 15 s, 12 after 45 s, 21 after 4 min, 24 after 9 min,
31 after 17 min — so it is a warm-up above the power-on baseline rather than
ambient air temperature. It is recorded as `temp_rise_c` and not displayed.
Because there is no heading field, `course` is derived from the track itself.

**The burned-in timestamp lags the telemetry by about a second.** Aligning the
OSD pixels against the metadata clock puts the offset at +0.95 s. Cross-
correlating apparent image motion against GPS speed, however, matches to within
0.2 s, so the position and speed do belong to the frame they are attached to
and are used unshifted; it is the on-screen text that trails.

### G-sensor axes

Labelled `X`/`Y`/`Z` as the recorder reports them. On a straight run `gx` is
the only axis that tracks GPS-derived longitudinal acceleration (r = +0.30),
while lateral acceleration is too small to separate `gy` from `gz`.

## Front/rear sync

The rear camera records about one frame ahead of the front. Measured two ways
on a 92-second clip: body-pitch motion (2-D phase correlation per camera, then
cross-correlated) gives +35.0 ms, and the shared microphone track gives
+46.4 ms. Both `compose` and `vstack` pair `front[k+1]` with `rear[k]`, which
measured out to a residual of −1.7 ms.

Audio is taken from the front file only. The rear file's track is the same
single microphone offset by ~46 ms, so mixing the two comb-filters it.

## Map tiles

Map data comes from the Geospatial Information Authority of Japan
([地理院タイル](https://maps.gsi.go.jp/development/ichiran.html)); the
attribution shown on the panel is a condition of use. Tiles are cached under
`tiles/` and fetched once. Point `COMTOOL_TILE_URL` and `COMTOOL_TILE_ATTRIB`
at another XYZ source for footage outside Japan, and `COMTOOL_TILE_CACHE`
elsewhere.

## Licence

MIT
