# Runbook W2 — Worker: camera-motion score + cut detection

> Ingested from the Dynalytix Mailbox on 2026-10-06 ("Runbook — Worker: camera-motion score + cut detection, gate mark-ready").
> Branch: `feat/camera-check`, cut after `feat/single-dataset` (it gates the mark-ready endpoint that branch rewrites).

## Purpose
Broadcast cameras pan, zoom and cut. That breaks hold boxes drawn on frame 1 and mixes camera motion into pixel-space velocity / center-of-mass features. The paper uses only clips with a static or near-static camera and no cuts. The worker measures this; the admin can't mark a clip ready if it fails.

## Worker (`data_collection/worker`)
Runs inside `extract_pose` after pose extraction, reusing decoded frames and landmarks. CPU work. Pose CSV contract and golden test untouched.
1. Cut detection: per-frame HSV histogram difference; `has_cut` + `cut_frames`.
2. Camera motion: mask the climber with the landmarks' bounding box (dilated 20%); track background features (`goodFeaturesToTrack` + `calcOpticalFlowPyrLK`, or ORB + RANSAC affine); per-frame median translation (normalized by frame diagonal) and scale change.
3. `camera_motion_score` = p95 of per-frame normalized displacement; `camera_zoom_range` = max/min cumulative scale; `camera_motion_frames_pct`.
4. Write to `videos`. Failures here must not fail the pose job (fields null, logged).

## Backend
1. Migration: `has_cut`, `cut_frames` jsonb, `camera_motion_score`, `camera_zoom_range`, `camera_motion_frames_pct`, `camera_override` bool default false, `camera_override_note`.
2. Env thresholds `CAMERA_MOTION_MAX` (0.002), `CAMERA_ZOOM_MAX` (1.05) — placeholders until calibrated.
3. Mark-ready (non-community) 422 if pose isn't done, `has_cut`, or over threshold — unless `camera_override` with a note via `PUT /api/admin/videos/{id}/camera-override`.
4. Exports include camera fields + override.

## Frontend (admin only)
Cut / motion / zoom per video with pass/fail, block reason, override control (note required).

## Calibration (before merge)
Run on ≥10 real clips (static wide + panning/zooming); table in REPORT.md; propose thresholds. If clips aren't available, ship defaults and mark calibration as Jolie's manual step.

## Tests
Synthetic: static → low; pan → high; zoom → zoom flag; concatenated → `has_cut`; failure leaves pose `done`. Golden CSV test passes.
