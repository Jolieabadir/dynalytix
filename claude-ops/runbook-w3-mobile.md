# 📱 Runbook — iPhone-first labeling UI (Safari survival, touch frame nav, stepped forms, tap-to-place holds, PWA)

- **Wave:** W3 (moved from W2 by the Priority-change entry of 2026-09-17) · **Lane:** Mobile · **Feature:** `feat/mobile-first-labeling` · **Mailbox date:** 2026-09-17
- **Gate:** do not start until BOTH `runbook-w1-worker.md` (server-side pose) AND `runbook-w1-backend.md` (Dataset A) have merged to main. Build against the rating view (Dataset A) and the self-upload flow (Dataset B) as they exist after those two land.

> Priority-change rationale (verbatim): Focus is Paper A. Paper A's raters are three validated people on laptops, so the iPhone-first pass is not on the critical path. No change to the runbook's content.

## Purpose

iPhone is the main labeling client. Everything built in the UX round assumed a laptop (keyboard shortcuts, side panel, drag-to-draw, hover tooltips). This is a mobile-first pass, not a responsive stylesheet. **Gated on the server-side pose worker runbook** — the upload flow must be finished first.

## Requirements, in priority order

1. **Survive Safari.** iOS Safari evicts pages on app switch or lock. Every move, label, and tag saves to the backend the instant it's made; page reload rebuilds the whole session from the server. The Zustand store is a cache, never the source of truth. Upload is **resumable**: R2 multipart with presigned part URLs, each part retried independently, so a lock-screen mid-upload costs one chunk, not the file.
2. **Zero-wait start.** Local `File` plays immediately via object URL with `playsInline` (or iOS goes fullscreen). After upload completes, switch the video source to a presigned R2 URL so a reload still has the video (R2 supports range requests).
3. **Frame navigation without a keyboard.** Frame-step buttons (±1, ±10), a scrubber with a draggable thumb, swipe-left/right on the video for single frames. Landscape for video, portrait for forms.
4. **Forms as a stepped bottom sheet**, not a side panel. One lens per screen: Environment → Strategy → Outcome. Big tap targets, Next/Back. Definitions shown inline under each option, tap to expand (no hover on touch). This is Taylor's "people need their hand held" solved for phones.
5. **Holds by tap, not drag.** Tap the video to place a box centered there at a default size; pinch to resize; tap-and-hold to delete. Keep drag-to-draw on pointer devices.
6. **Upload size guidance.** Tell labelers once (dismissible): shoot 1080p **30fps** (Settings → Camera → Record Video) — halves upload and worker frame count; 30fps is the biomechanics standard. Do not transcode on the phone.
7. **PWA.** Manifest, icons, "Add to Home Screen" prompt. Fullscreen and slightly better session survival than a Safari tab.

## Constraints

- One backend, one worker, one UI: the laptop path must keep working. Pointer vs touch is detected, not a separate build.
- No new auth flow; the sign-in card stays (email confirmation is off).
- Backend changes only if resumable multipart needs new presign endpoints (`create-multipart`, `sign-part`, `complete-multipart`).

## Verify

- Full labeling session on a real iPhone (Safari, then Home Screen PWA): pick clip → label 3 moves with hold slots → lock phone mid-upload → unlock → upload resumes → tag 2 frames → switch apps and return → session intact → export.
- Same session on a laptop still works with keyboard shortcuts.

## Done when

A first-time labeler on an iPhone completes a session with no keyboard, no instructions beyond the in-app banners, and loses nothing if the phone locks.
