# Runbook W2 — Backend: Clip-prep script

> Ingested from the Dynalytix Mailbox on 2026-10-06 ("Runbook — Clip-prep script (trim local footage + source-metadata sidecar)").
> Branch: `feat/clip-prep`. Script-only; can run in parallel with `feat/single-dataset`.

## Purpose
The paper's clips come from public footage that Jolie obtains and trims locally. This script turns a local video file into a clip plus a metadata sidecar the admin prep form imports. **No downloading is built into this script or the service.**

## Defaults
- Location: `data_collection/backend/scripts/prepare_clip.py`. Python 3.11, stdlib + `ffmpeg`/`ffprobe` on PATH. No new runtime deps for the service.

## Behavior
```
python scripts/prepare_clip.py INPUT.mp4 --start 00:12:03.500 --end 00:12:41.000 \
  --source-type public_broadcast --source-url URL --license "…" \
  --event-name "…" --event-date 2026-05-10 [--athlete-id UUID] [--notes "…"] [--out-dir clips/]
```
1. Validate: input exists, `end > start`, duration ≤ `--max-seconds` (default 180), event date parses, source type in ('public_broadcast','cc_license','research_dataset').
2. Trim with ffmpeg. Stream copy when the start is on a keyframe; otherwise re-encode H.264 CRF 18, `-preset slow`, keep the source frame rate, `-an`.
3. ffprobe the output: fps (rational), width, height, duration, frame count.
4. Write `<name>.mp4` and `<name>.json` with keys `source_type, source_url, clip_start_ms, clip_end_ms, license, event_name, event_date, athlete_id, notes, fps, width, height, duration_ms, frame_count, sha256, prepared_at, script_version`.
5. `--batch CSV`: one row per clip, same columns; writes all outputs and a summary.

## Tests
`tests/test_prepare_clip.py` with synthetic ffmpeg `testsrc` videos at 30 and 60 fps: trim accuracy within one frame, fps preserved, sidecar schema, validation errors, batch mode. Skip if ffmpeg is missing.

## Docs
`scripts/README_clip_prep.md`: workflow, clip inclusion criteria (adult athletes, single continuous shot, static or near-static wide camera, full body visible), and that source URLs + timestamps are what the public release cites.
