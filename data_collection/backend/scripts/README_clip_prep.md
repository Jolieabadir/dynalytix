# Clip prep

`scripts/prepare_clip.py` turns a video file you already have on disk into a
dataset clip plus a metadata sidecar. It does **not** download anything, and
neither does the service. Getting the footage is a manual step.

## Workflow

1. **Get the footage.** Save the source video locally. Write down the public
   URL it came from and the timestamps of the climb you want.
2. **Trim.**
   ```bash
   cd data_collection/backend
   python scripts/prepare_clip.py ~/footage/semi.mp4 \
     --start 00:12:03.500 --end 00:12:41.000 \
     --source-type public_broadcast \
     --source-url "https://example.org/watch?v=..." \
     --license "Broadcast footage; research use, cited by URL + timestamps" \
     --event-name "Example Cup Semi-final" --event-date 2026-05-10 \
     [--athlete-id <athletes.id UUID>] [--notes "..."] [--name semi_w2_a1] \
     [--out-dir clips/]
   ```
   This writes `clips/<name>.mp4` and `clips/<name>.json`. The default name
   is `<input stem>_<start_ms>-<end_ms>`.
3. **Upload** the `.mp4` in the admin view, then click **"Import metadata
   JSON"** and pick the matching `.json`. The form fills in the source fields.

Several clips at once:

```bash
python scripts/prepare_clip.py --batch clips.csv --out-dir clips/
```

`clips.csv` has a header row with these columns:
`input,start,end,source_type,source_url,license,event_name,event_date,athlete_id,notes,name`.
`athlete_id`, `notes` and `name` can be blank. A relative `input` path is
resolved against the CSV's folder. Every row is checked before anything is
trimmed, so one bad row stops the whole batch with a list of what's wrong. The
results are printed and also saved to `<out-dir>/batch_summary.json`.

## Options and rules

| | |
|---|---|
| Timestamps | `HH:MM:SS.mmm`, `MM:SS.mmm`, or seconds (`723.5`) |
| `--source-type` | `public_broadcast`, `cc_license` or `research_dataset` |
| `--source-url` | required, `http(s)://` |
| `--license`, `--event-name` | required |
| `--event-date` | required, `YYYY-MM-DD` |
| `--athlete-id` | optional, must be a UUID |
| `--max-seconds` | longest clip allowed, default 180 |
| `--overwrite` | replace existing outputs (they are refused otherwise) |

Exit codes: `0` ok, `2` bad input (message on stderr), `1` ffmpeg/ffprobe
failure.

## What the trim does

- The output has **video only** (audio, subtitles and metadata are dropped)
  and keeps the source frame rate exactly. There is no frame-rate conversion.
- If the start time is on a keyframe, the video is stream-copied. The script
  then checks the copy's frame count and frame rate. If either is wrong (common
  with B-frames, where a copy overshoots the end), it throws the copy away and
  re-encodes instead.
- Otherwise it re-encodes with H.264 (`libx264`), CRF 18, `-preset slow`,
  yuv420p (when the dimensions are even).
- The cut includes the source frames whose timestamps fall in `[start, end)`,
  within one frame.

Sidecar keys: `source_type, source_url, clip_start_ms, clip_end_ms, license,
event_name, event_date, athlete_id, notes, fps, width, height, duration_ms,
frame_count, sha256, prepared_at, script_version`. `clip_start_ms` and
`clip_end_ms` are the requested times on the source's timeline. `fps` is a
rational string such as `30000/1001` or `60/1`. `sha256` is the hash of the
output `.mp4`.

Needs Python 3.11 and `ffmpeg`/`ffprobe` on PATH. No other packages.

## Clip inclusion criteria

Only prepare a clip if all of these are true:

- **Adult athletes only (18+).**
- **One continuous shot.** No cuts, replays or picture-in-picture inside the
  clip.
- **Static or near-static wide camera.** Panning or zooming breaks the hold
  boxes drawn on frame 1 and mixes camera motion into the movement features.
  The worker's camera check also flags this.
- **Full body visible** for the whole climb.

## Citation

The public release cites each clip by its **source URL plus the start and end
timestamps**. Those values come straight from the sidecar, so get them right
when you trim. The video files themselves are not what gets redistributed.
