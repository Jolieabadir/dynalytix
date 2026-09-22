# Round C — Labeling UX, Definitions, and Holds

Branch `feat/ux-round-holds`, cut from `feat/pose-extractor-v2` (which itself sits on
the Supabase/R2 backend work). Sections below are appended as each step lands; the
Pose Extractor v2 report follows unchanged from §"Pose Extractor v2" onward.

---

## C0. The current UX flow, as found

Read from `App.jsx`, `store/useStore.js`, `api/client.js`, `api/auth.js`,
`components/{VideoUpload,VideoPlayer,MoveForm,MovesList,TaggingMode}.jsx`.

### The path a labeler walks today

1. **App boot.** `App.jsx` calls `getConfig()` once on mount. Until it resolves the
   whole app renders `<h2>Loading Dynalytix...</h2>`.
2. **No sign-in exists.** `api/auth.js` is a token *reader* only — `getSupabase()`,
   `getAccessToken()`, `requireAccessToken()`. There is no UI anywhere that calls
   `signInWithPassword`, so in practice there is never a session.
3. **Upload.** `currentVideo === null` → `VideoUpload`. Picking a file runs MediaPipe
   pose extraction in the browser (play-through capture loop), then
   `registerVideo()` (JSON) → `uploadOriginalVideo()` (presign → `PUT` to R2 →
   confirm). The CSV string and parsed rows land in the store.
4. **Define mode.** `VideoPlayer` and `MovesList` sit side by side. The player shows
   the video with a `SkeletonOverlay` drawn from the CSV, transport buttons, a
   timeline slider, and `[` / `]` to mark start and end frames. With both marked, a
   **Create Move** button appears and sets `showMoveForm`.
5. **Labeling.** `MoveForm` renders as a **full-screen modal overlay**
   (`.move-form-overlay` / `.move-form-modal`) covering the player. Three lens
   sections — Environment, Strategy, Outcome — then Save, which POSTs move →
   environment → outcome, with a rollback `deleteMove` if a later call fails.
6. **Tagging mode.** Choosing a move from `MovesList` switches `mode` to `tagging`.
   `TaggingMode` replays only that move's frame range, looping at the end, and adds
   sensation tags at the current frame.
7. **Finish.** `DoneButton` → `exportVideo()` → `ThankYouModal`.

### What is wrong with it — the motivation for this round

| # | Problem | Addressed by |
|---|---|---|
| 1 | **No way to sign in.** `/api/config` now requires a bearer token, so a fresh user 401s and sits on "Loading Dynalytix..." forever with no error and no route forward. | C1 |
| 2 | **No definitions.** Every option renders through `formatLabel()` — `horizontal_edge` → "Horizontal Edge" — and nothing says what any of them *mean*. Only four `move_tags` have a `title` tooltip, hardcoded in JSX rather than served by config. | C2 |
| 3 | **No onboarding.** Nothing tells a first-time labeler that `[` and `]` set the move boundaries, or that tagging mode wants the scrub bar. The shortcuts are discoverable only by reading the source. | C3 |
| 4 | **The form hides the video.** `MoveForm` is a modal overlay, so the labeler cannot see the movement, the skeleton, or scrub while deciding what to call it — exactly when they most need to look. | C4 |
| 5 | **No sense of progress.** Nothing shows how many moves are defined, labeled, or tagged, and "Done" is a single button with no indication of what remains. | C5 |
| 6 | **Two-hold model, stale schema.** The form still asks for `hold_type_reaching` / `hold_type_non_reaching` and posts `timing`, `dyno_style`, `tags`, `foot_cut` — all **removed** in schema v3. `previousEnvironment` in the store carries the same dead shape. The backend now wants four named slots. | C6 |
| 7 | **Holds are invisible.** The backend has had `holds` since v3 and the frontend has never touched them: no overlay, no picking, no detection. Nothing connects a label to a place on the wall. | C7 |
| 8 | **Reach wording is baked into the enum.** `reached_not_controlled` renders straight through `formatLabel()`, so changing the wording means changing the stored value. | C8 |
| 9 | **`TaggingMode` reads removed config keys.** It requires `traction_sources` in `REQUIRED_CONFIG_KEYS` and posts `traction_source` / `traction_direction`, all dropped in v3 — it will fail its own config validation against the live backend. | C6 |
| 10 | **Stale export/download client.** `exportVideo()` still sends `?delete_video=`, and `downloadExport()` expects a streamed blob where the backend now answers `307` to a presigned URL. `VideoPlayer`'s CSV fallback `fetch` sends no auth header at all. | C1, C5 |

### Store shape, as found

`useStore.js` holds: video (`currentVideo`, `videos`, `videoBlobUrl`, `csvData`,
`csvString`), moves (`moves`, `currentMove`), `frameTags`, player
(`currentFrame`, `isPlaying`), selection (`moveStart`, `moveEnd`), UI (`mode`,
`showMoveForm`, `showTagPopup`, `tagPopupType`), `config`, and
`previousEnvironment` — still the old two-hold shape.

---

---

## C1. Per-file changes

### New files

| File | What it is |
|---|---|
| `src/components/AuthGate.jsx` | Email + password sign-up / sign-in screen, shown whenever there is no session. One toggle between modes, client-side validation before any API call, and Supabase's terse errors translated into plain language. |
| `src/components/InfoTip.jsx` | The "i" beside an option. Hover and focus reveal the definition; a click pins it for touch devices. Renders nothing when config has no definition, rather than an empty bubble. |
| `src/components/OnboardingBanner.jsx` | The define / tagging one-liners. Dismissal goes to the store, session-only. |
| `src/components/ProgressStrip.jsx` | Persistent "{n} defined · {m} labeled · {k} tagged" header with Save & Next Move and Finish & Export. |
| `src/components/HoldOverlay.jsx` | Hold boxes over the video: drag to add, click to delete, and a pick mode for assigning a box to a form slot. |
| `src/services/holdDetector.js` | YOLOv8n / onnxruntime-web detection. **Off by default, no weights bundled** — see §C4. |
| `src/services/holdAssignment.js` | The four-slot suggestion **policy** for MoveForm. A thin adapter over `holdMatching` — no geometry of its own (§C9). |
| `src/utils/taxonomy.js` | `optionLabel` / `optionDescription` — reads `display_label` and definitions out of config. |
| `src/utils/progress.js` | `progressCounts`, the defined/labeled/tagged arithmetic. |
| `src/test/setup.js`, `vitest.config.js` | DOM test environment. |
| 5 × `*.test.js(x)` | 66 tests — see §C5. |

### Changed files

| File | Change |
|---|---|
| `src/App.jsx` | **Rewritten.** Reads the persisted session at boot and follows it; renders `AuthGate` when there is none. Config now loads *after* a session exists — it requires a bearer token in v3, and loading it first was why a signed-out user hung on "Loading Dynalytix…". Header gains the account email and Sign out. Define mode gains the progress strip, the banner, and a side-panel layout. Finish & Export resolves the presigned link. |
| `src/api/auth.js` | Added `signUp`, `signIn`, `signOut`, `getSession`, `onAuthChange`, `refreshSession`, and `readableAuthError`. The token reader it already had is unchanged. |
| `src/api/client.js` | Response interceptor refreshes once on 401 and replays the request. Holds CRUD added (`getHolds`, `createHoldsBulk`, `createHold`, `updateHold`, `deleteHold`). `exportVideo` no longer sends `?delete_video`. `getExportDownloadUrl` reads the 307 `Location` instead of expecting a body. `getVideoCsvText` fetches the CSV with auth. |
| `src/api/ExportService.js` | Reduced to a re-export of the client's implementations, so the two existing import sites keep working. |
| `src/components/MoveForm.jsx` | **Rewritten.** A right-side `<aside>` panel instead of a full-screen modal. Four hold slots, each with its own hold type, hold qualities, and "pick on video". Auto-suggest on open. Every option carries its definition. `timing`, `dyno_style`, `tags` and `foot_cut` removed; `confidence` added. Config comes from the store rather than a second fetch. |
| `src/components/VideoPlayer.jsx` | **Rewritten.** Hold overlay wired in, toggled with `H`. CSV fallback now sends the token and follows the 307 (it previously sent no auth and expected a body). **Keyboard guard narrowed** to genuine text entry, so `[` and `]` keep working while the panel is open and a radio has focus. `csvData` derived rather than mirrored into state. |
| `src/components/TaggingMode.jsx` | `traction_sources` / `traction_source` / `traction_direction` removed — all dropped in v3, and the component would have failed its own config validation against the live backend. Config from the store. Banner and tag-type definitions added. |
| `src/components/ThankYouModal.jsx` | Shows the presigned download link, says it expires, and distinguishes a failed export from a failed link. |
| `src/components/VideoUpload.jsx` | After register + upload, runs detection on the first frame (when enabled), posts the boxes in bulk, and loads holds into the store. Entirely best-effort. |
| `src/store/useStore.js` | `previousEnvironment` moved to the four-slot v3 shape (`hold_id` deliberately never carries over). Added holds, overlay toggle, pick slot, `dismissedBanners`, `session`, and `resetForSignOut`. |
| `src/App.css` | ~290 lines for the auth screen, progress strip, banners, tooltips, panel layout, hold overlay, and a narrow-screen stack. |
| `vite.config.js` | Marks `onnxruntime-web` external when detection is off — see §C4. |
| `package.json` | Added `onnxruntime-web`; vitest + testing-library + jsdom. `npm test` now runs both suites. |

### From the merge with feat/pose-extractor-v2

Kept unchanged from B: `src/services/holdMatching.js`, `src/services/holdSuggestions.js`,
`src/components/HoldSuggestions.jsx`, `src/services/poseMath.js` (33 landmarks, rounding,
`normalizeLandmark`), `scripts/fixtures/golden_pose.csv`, `scripts/golden_frames.mjs`,
`scripts/make_golden.mjs`, `src/components/SkeletonOverlay.jsx`, and the
`20260913180000_add_video_dimensions.sql` migration. Hand-merged:
`TaggingMode.jsx`, `VideoUpload.jsx`, `client.js`, `useStore.js`, `App.css`,
`package.json` — see §C9.

### Backend (only the three areas the brief allowed, plus the merge)

| File | Change |
|---|---|
| `src/labeling/models.py` | `DEFINITIONS` — plain-language descriptions for all 11 taxonomies, plus `display_label` on `reach_details`. |
| `src/web/api.py` | `/api/config` serves `definitions`. New `POST /api/videos/{id}/holds` (bulk, capped at 200) and `PUT /api/holds/{id}`. New `HoldItem` / `HoldBulkCreate` / `HoldUpdate` schemas. |
| `src/labeling/database.py` | `create_holds_bulk` (one transaction) and `update_hold` (box and source only — `video_id`/`user_id` are fixed at creation). From B: `width`/`height` on videos, and `apply_schema_sql` applying **all** migrations rather than just the base schema. |
| `scripts/auth_shim.sql`, `scripts/setup_test_db.sh` | **New.** The `auth.uid()`/`auth.role()` shim and scratch-database builder the test suite needs on a plain Postgres (§C5). |

---

## C2. Definitions — the two that were being read backwards

Both are called out explicitly in the UI, not just in the config:

- **Confidence** is *the labeler's confidence in the labels they just gave* — the camera angle, the speed, the taxonomy. Not how confident the climber looked on the wall.
- **Size** is *the size of the movement*. Not the size of the hold.

`reach_details` carries `display_label` so Taylor's preferred wording can land without touching a stored enum value or migrating existing rows. **Taylor's wording is still pending**; the current labels are placeholders chosen to be unambiguous:

| Stored value | Current display | 
|---|---|
| `reached_controlled` | Reached it — in control |
| `reached_not_controlled` | Reached it — not in control |
| `didnt_reach` | Did not reach it |

---

## C3. Defaults taken

1. **Config is loaded once, in `App`, after sign-in**, and read from the store by everything else. `MoveForm` and `TaggingMode` each used to fetch it independently.
2. **401 refreshes once and replays.** A second 401 propagates and the auth listener shows the sign-in screen. Guarded against a loop by a flag on the request.
3. **Banner dismissal is session-only**, per the brief — no localStorage. A test asserts nothing is written there.
4. **`hold_id` never carries over between moves.** Hold *type* and *quality* prefill from the previous move; the id would point at the wrong box.
5. **Hold deletes are optimistic**, and roll back if the server refuses.
6. **Suggestions are marked `suggested` until touched.** Any edit to a slot clears the flag. A wrong guess is visible rather than silently adopted.
7. **A distance cap (0.15 of the frame) means no suggestion rather than a wrong one.**
8. **The `foot` slot is optional**; `start_left`, `start_right` and `end` require a hold type unless the move is tagged No Hands.
9. **Empty slots are sent as `{}`**, which is how v3 expresses no-hands, one-hand and no-feet moves.
10. **Finish & Export does not block on the download link.** A failed link is reported as such; the labels are saved either way.

---

## C4. The hold detector: source, licence, and why it ships off

**Surveyed 2026-09-13. No permissively-licensed climbing-hold model exists.**

| Model | Licence | Signal | Files |
|---|---|---|---|
| `jwlarocque/yolov8n-freeclimbs-detect-2` | **AGPL-3.0** | 0 downloads, 3 likes | fp16 + fp32 `.onnx`, `.pt` |
| `samolego/yolo-holds` | **AGPL-3.0** | 0 downloads, 0 likes | `.pt` only |
| `ricardosreichert/holds_yolo_v8` | **none declared** (= all rights reserved) | 0 downloads, 0 likes | `.pt` only |

The first is the best technical fit: a single "hold" class, trained on home and spray walls, and it ships ONNX. Its card notes that an earlier MIT label was an error and AGPL-3.0 is binding.

The constraint is **structural, not bad luck**: Ultralytics YOLOv8 is itself AGPL-3.0, so every fine-tune of it inherits the copyleft. "A YOLOv8n-format ONNX with a permissive licence" is close to a contradiction in terms today.

Bundling AGPL-3.0 weights into a web frontend would put AGPL obligations on the served application. That is a licensing decision for the project owner, not a default to take quietly — so this takes the fallback the brief specified:

- **The manual flow is complete and is the shipped path.** Drag to add, click to delete, pick-on-video per slot, auto-suggest from the pose data. Nothing about labeling depends on the detector.
- **Detection is behind `VITE_ENABLE_HOLD_DETECTION`, default off, with no weights in the repo.**
- The full onnxruntime-web decode path is written and lazily imported. The flag is written so Rollup folds it, and `vite.config.js` marks the package external when off — the default build is 643 KB with no wasm; flipping the flag on bundles the ~28 MB runtime properly. Both paths verified.

**To enable**, once a model is chosen and its licence accepted:

```bash
# 1. put the .onnx at public/models/holds.onnx (or set VITE_HOLD_MODEL_URL)
# 2. re-check VITE_HOLD_MODEL_INPUT — freeclimbs wants 2560, the default here is 640
# 3.
VITE_ENABLE_HOLD_DETECTION=true npm run build
```

⚠️ The decode path is written against the standard YOLOv8 head (`[1, 4+nc, N]`, xywh in input-space pixels) but **has not been validated against real detector output** — there was no usable model to validate it with. Treat the first run as a bring-up, not a regression test.

---

## C5. Tests

**197 tests, 0 failures** across both branches' suites, unioned.

### Frontend — `npm test`, 125 tests

| Suite | Runner | Tests | Covers |
|---|---|---|---|
| `scripts/test_pose_math.mjs` | `node --test` | 61 | fps detection, frame math, CSV shaping, the 33-landmark widening and its golden file, rounding, and the `holdMatching` geometry (normalization, point-to-rectangle distance, containment, `maxDistance`, the divergence test) |
| `src/services/holdAssignment.test.js` | vitest | 25 | The four-slot policy: preference lists, reaching side, thresholds, both CSV widths, resolution independence |
| `src/components/MoveForm.test.jsx` | vitest | 15 | Four hold slots, definitions, panel layout |
| `src/components/AuthGate.test.jsx` | vitest | 8 | Sign in / sign up / validation / errors |
| `src/components/OnboardingBanner.test.jsx` | vitest | 7 | Copy, dismissal, session-only persistence |
| `src/utils/progress.test.js` | vitest | 9 | Progress strip counts |

125 = C's 91 + B's 36 new pose-math tests − **2 genuine duplicates**. The two
removed were `holdAssignment`'s own `boxCenter` / `distanceToBox` geometry
tests: that geometry now lives in `holdMatching` and is covered by B's suite,
so re-testing it here would have been testing a re-export. Everything policy-
shaped in that file was kept and extended.

### Backend — `pytest`, 72 tests

Run against a **throwaway local Postgres**, never the live Supabase project —
the v3 migration DROPs and recreates the labeling tables. 61 pre-existing plus
**11 new** covering the endpoints this branch added and §C6 previously flagged
as unverified: bulk create ordering, empty batch, all-or-nothing on a bad box,
the 200 cap, out-of-frame rejection, owner scoping, and PUT (partial update,
no-op, bad source, cross-user 404, missing 404).

Plain Postgres has no `auth` schema, so the RLS policies cannot even be
created. `scripts/auth_shim.sql` supplies `auth.uid()` and `auth.role()` reading
the same session GUCs Supabase uses, and `scripts/setup_test_db.sh` builds the
database and prints its DSN:

```bash
cd data_collection/backend
TEST_DATABASE_URL="$(./scripts/setup_test_db.sh)" python3 -m pytest tests/ -q
```

The script refuses any database name that looks hosted, and the shim is marked
test-fixture-only — applying it to the real project would shadow Supabase's own
auth schema.

### Bugs the tests found and fixed

1. `InfoTip` toggled on click while hover had already opened it — clicking the "i" made the definition vanish under the cursor. Hover and pin are now separate state.
2. The build emitted onnxruntime-web's ~28 MB wasm as an orphan asset even with detection disabled.
3. Node 22's partial built-in `localStorage` shadows jsdom's and has no `clear()`, which matters because a test asserts we never write there. The setup installs a complete one.
4. **From the merge:** git silently combined both branches' holds additions in `client.js` and `useStore.js` into duplicate definitions, and dropped a closing brace in `App.css`. Lint and the build caught all three — see §C9.

`npm run build` passes. New and rewritten files lint clean; `MovesList.jsx` and `SkeletonOverlay.jsx` carry pre-existing lint errors that were not in scope.

---

## C6. What is NOT done

- ~~Backend tests were not run.~~ **Done.** 72 tests pass against a throwaway local Postgres, including 11 new ones covering the bulk-create and update hold endpoints. See §C5 for how to reproduce.
- **Nothing was run in a browser.** No dev server, no manual click-through. §C10 is the checklist for that.
- **`MovesList.jsx` was not updated.** It renders moves from the list and was not part of the brief, but it reads `move.tags` in one place, which v3 removed. Worth a look during QA.
- **Hold *creation* is still only manual.** Detection ships off (§C4), so `HoldSuggestions` and MoveForm auto-suggest both have nothing to work with until a labeller draws boxes by hand. That is a complete flow, not a gap — but it does mean the "Holds in use" panel reads "No holds recorded" on a fresh video until someone marks one.
- **The detector is unvalidated** — see §C4.

---

## C7. Railway

`VITE_SUPABASE_URL` and `VITE_SUPABASE_ANON_KEY` are set on
`steadfast-vitality` / **`Data_collection_climbing`** / `production` — the
frontend service, which serves `collect.dynalytix.net`.

- Both piped through `railway variables --set-from-stdin` with `--skip-deploys`. No value was printed at any point; verified by name and length only (40 and 208 characters, matching `backend/.env`).
- Values come from the new dedicated Supabase project (`nbqtgknayvsjkevaoeef`), not the old shared `login_system` one.
- `VITE_API_URL` was already set and needed no change.
- **Nothing was deployed**, and `adorable-integrity` was not touched — it still has zero `VITE_` variables and the same deployment id as before this session.

---

## C8. Local `.env`

`data_collection/frontend/.env` was copied from the original checkout and is **not committed** (`.gitignore` covers it). Its two Supabase values were placeholders — 19 and 24 characters, left over from an earlier project — so they were replaced with the real ones from `backend/.env`. Anyone else setting this branch up locally needs to do the same, or sign-in will fail against the wrong project.

---

## C9. ✅ Resolved: merged with feat/pose-extractor-v2

`feat/pose-extractor-v2` (`4046982`) is **merged into this branch**. The overlap
this section previously flagged as a merge blocker is gone: there is now one
geometry module, one set of hold UI surfaces, and one test suite.

### What arrived from B

| Commit | What it does |
|---|---|
| `d6b8bbc` | Pose CSV widened to all **33** MediaPipe landmarks (75 → 147 columns), adding `*_index` fingertip and `*_foot_index` toe points. First 75 columns byte-identical. |
| `cd75a9a` | CSV coordinates rounded (4dp landmarks, 3dp visibility); overlay draws only the 15 body joints. |
| `4eb637d` | `holdMatching.js` geometry primitives, `normalizeLandmark`/`normalizeLandmarks` in poseMath, the `width`/`height` migration, and `apply_schema_sql` applying **all** migrations. |
| `4046982` | `holdSuggestions.js` + `HoldSuggestions.jsx` — the "Holds in use" panel on the tag form. |

### The geometry decision

**`holdMatching.js` is the single source of geometry.** It is untouched by this
merge — byte-for-byte as B wrote it.

`holdAssignment.js` was **reduced to a thin policy adapter** rather than
deleted, because MoveForm's slot auto-suggest genuinely needs a different call
shape from the tagging panel's: it matches *two different frames* (hands at the
start, the reaching hand at the end) against *named slots*, where
`nearestHoldsFor` matches one frame against a flat landmark list. That
difference is policy, not geometry, so the policy is all that is left in it.

Deleted from `holdAssignment.js`, now used from their canonical homes:

| Was duplicated | Now comes from |
|---|---|
| `boxCenter`, `distanceToBox` | `holdMatching.distanceToBox` (via `nearestHold`) |
| `nearestHold` (centre-distance) | `holdMatching.nearestHold` (point-to-rectangle) |
| `normalizedLandmark` | `poseMath.normalizeLandmark` |
| `landmarkFromRow` | `holdSuggestions.landmarkFromRow` |

The centre-distance version was also simply **worse**, which the merge settled
for free: with it, a large hold the hand is resting *inside* could lose to a
small hold further away. B's point-to-rectangle distance (0 when inside) is
correct, and that behaviour is now what the slot suggester gets.

The one arithmetic left in `holdAssignment.js` is a `Math.hypot` in
`reachingSide`, measuring how far each hand travelled between two frames. No
box is involved, so no primitive covers it; both points still go through
`poseMath.normalizeLandmark` first, so it stays scale-correct on a non-square
frame — pinned by a test at 1000×2000.

### Both UI surfaces kept

- **MoveForm four-slot assignment (C)** — start-left, start-right, end, foot,
  each with "pick on video", hold type, hold qualities, and auto-suggest.
- **"Holds in use" panel on the tag form (B)** — `HoldSuggestions` wired into
  `TaggingMode`, click-to-apply, four distinguishable empty states.

They do not collide: one answers "which hold is this *move* about" during
define mode, the other "which holds is the climber on *right now*" during
tagging. Their thresholds differ accordingly and deliberately —
`SUGGEST_THRESHOLD` 0.15 for the move slots (a near-miss is still the right
hold, and the labeller confirms it anyway) against `CONTACT_THRESHOLD` 0.04 for
live contact (which wants to be strict).

**C's `traction_sources` fix and B's TaggingMode changes are both in.** The
component no longer requires the removed `traction_sources` config key or posts
`traction_source`/`traction_direction`, *and* it fetches holds and renders the
suggestion panel. Config is read from the store, not re-fetched.

### Duplicates git merged silently

Three needed hand-resolution — git combined both copies without reporting a
conflict, which would have shipped broken:

- `client.js` — two `getHolds`/`createHold`/`deleteHold` definitions. Kept C's
  superset (it adds `createHoldsBulk` and `updateHold`, and its `createHold`
  is the one the overlay calls); B's were unused by its own admission.
- `useStore.js` — two `holds`/`setHolds`/`addHold`/`removeHold` keys. Kept C's
  superset, carrying B's normalization note across.
- `App.css` — the `@media` block lost its closing brace, because git treated it
  as context shared with B's appended block. Restored.

### Kept from B without change

- The 33-landmark CSV **with rounding**, its golden file
  (`scripts/fixtures/golden_pose.csv`) and `make-golden` script.
- The `width`/`height` migration and the `apply_schema_sql` all-migrations
  change — both needed, and both now exercised by the backend suite.
- `VideoUpload` falling back to measured `width`/`height` when the backend
  echoes null, merged with C's detection-and-holds block.

**This also clears the caveat this section used to carry**: auto-suggest no
longer silently suggests nothing, because `currentVideo` now carries
`width`/`height`. Where they are genuinely absent — a video registered before
the migration — it still suggests nothing rather than guessing a resolution,
which is the correct behaviour and is pinned by a test.

## C10. Cutover runbook — backend §9 and this branch, merged

This supersedes §9 of `backend/REPORT.md`. The governing fact is unchanged:

> `adorable-integrity` (backend) **and** `Data_collection_climbing` (frontend) both auto-deploy from **`main`**, with **Wait for CI off**. A push to `main` deploys both within seconds. There is no staging gate.

**Therefore: do not merge any of these branches alone.**

`feat/pose-extractor-v2` is now merged *into* this branch (§C9), so what remains
is two branches, not three: **merge `feat/supabase-r2-schema-v3` and
`feat/ux-round-holds` to `main` in one go.** This branch already contains every
pose-extractor commit through `4046982`.

### Step 0 — apply migrations FIRST, before anything deploys

**This step exists because skipping it broke the first cutover attempt.** The
code was merged and deployed while `20260913180000_add_video_dimensions.sql`
had never been pushed to Supabase, so every `POST /api/videos/register`
returned 500 with `column "width" of relation "videos" does not exist`. Nothing
else had failed. Apply the schema *before* the code that needs it.

`apply_schema_sql()` is a **test-only** path — it never runs against
production. Production migrations go through the Supabase CLI.

```bash
cd data_collection/backend

# The DSN in .env is the TRANSACTION pooler (port 6543), which does not support
# prepared statements. The CLI fails on it with:
#     prepared statement "lrupsc_1_0" already exists (SQLSTATE 42P05)
# The API itself is fine — database.py sets prepare_threshold = None — but the
# CLI has no such escape. Use the SESSION pooler: same host and credentials,
# port 5432.
SESSION_DSN=$(python3 -c "
import os, urllib.parse as u
p = u.urlparse(os.environ['DATABASE_URL'])
print(u.urlunparse(p._replace(netloc=f'{p.username}:{u.quote(p.password, safe=\"\")}@{p.hostname}:5432')))
")

supabase db push --db-url "$SESSION_DSN" --dry-run   # review what will apply
supabase db push --db-url "$SESSION_DSN"
supabase migration list --db-url "$SESSION_DSN"
```

- [ ] `supabase migration list` shows **every** local migration with a matching
      Remote entry.
- [ ] A second `supabase db push --dry-run` reports **"Remote database is up to
      date."**
- [ ] **STOP if anything is still pending.** Do not merge, do not deploy.

Note the migration directory only exists on the feature branch until the merge
lands, so run this from a worktree that has `supabase/migrations/` — not from a
freshly-checked-out `main`.

### Before the merge

- [x] ~~Reconcile `holdMatching.js` and `holdAssignment.js`~~ — **done** (§C9). `holdMatching` is the single source of geometry; `holdAssignment` is a thin policy adapter over it.
- [x] ~~Merge the video-dimensions migration~~ — **done**. `currentVideo` carries `width`/`height`, with a fallback to the measured values when the backend echoes null.
- [x] ~~Run the backend suite against a scratch Postgres~~ — **done**. 72 pass, including new coverage for the bulk and update hold endpoints. Reproduce with `scripts/setup_test_db.sh` (§C5).
- [ ] Re-run both suites after the merge to `main` resolves any further conflicts.
- [ ] Confirm the frontend is complete against the §7 contract: bearer token on every `/api` call, JSON register, three-step presigned upload, four-slot environment, `foot_cut`/`timing`/`dyno_style`/`traction_*` gone, 307s followed. *(Done on this branch — re-verify after the merge resolves conflicts.)*
- [ ] `VITE_SUPABASE_URL` / `VITE_SUPABASE_ANON_KEY` point at the **new** project `nbqtgknayvsjkevaoeef`. *(Done — §C7.)*
- [ ] Decide how labelers get accounts. **Email confirmation is ON** in this project (confirmed live during cutover): public sign-up creates the user but leaves it unconfirmed, `AuthGate` says "Check your email for a confirmation link, then sign in", and nobody gets in until they click it. So either the labelers' addresses must actually receive mail, or create and confirm their accounts through the Supabase admin API / dashboard. **Supabase also rejects non-resolvable TLDs on public sign-up** — `@dynalytix.test` is refused with "Email address is invalid"; the admin API bypasses that, which is why the smoke test can use it and a person cannot.
- [ ] Decide about the old data. Nothing is migrated — schema v3 starts empty by design. Old SQLite labels on the Railway disk are already lost on every redeploy; exports live in the `dynalytix-data` GitHub repo.
- [ ] Decide on the detector (§C4): accept AGPL-3.0, find a permissive model, or leave it off. **Leaving it off is a complete product** — every hold can be placed by hand.

### The merge

- [ ] Merge all three branches to `main` in a single merge. Both services rebuild automatically; watch both in the Railway dashboard.

### Immediately after

- [ ] Unset the retired backend variables (left in place so the old build's GitHub sync kept working):
      ```bash
      cd data_collection/backend
      railway variables delete GITHUB_TOKEN --service adorable-integrity --environment production --skip-deploys
      railway variables delete DATA_REPO   --service adorable-integrity --environment production
      ```
- [ ] Backend health:
      ```bash
      curl https://adorable-integrity-production.up.railway.app/api/health
      # expect {"status":"ok","database":"ok","r2":"ok","schema_version":3}
      ```
      `r2` must read `ok`, not `not configured`. `/api/config` returning 401 without a token is correct.
- [ ] Smoke test against the deployment:
      ```bash
      set -a && . ./.env && set +a
      python scripts/smoke_test.py --url https://adorable-integrity-production.up.railway.app
      # expect 35 passed, 0 failed
      ```
- [ ] Truncate afterwards so smoke-test rows do not pollute the first real session:
      ```bash
      psql -d "$DATABASE_URL" -c "TRUNCATE frame_tags, outcomes, environments, moves, holds, videos RESTART IDENTITY CASCADE;"
      ```
- [ ] Walk §C11 end to end on `collect.dynalytix.net`.

### Worth doing soon after

- [ ] **Narrow CORS.** Both `api.py` (`allow_origins=["*"]`) and the R2 bucket rule are wide open. Tighten to `["https://collect.dynalytix.net", "http://localhost:5173"]`.
- [ ] **Consider turning off auto-deploy from `main`,** or point production at a release branch. With Wait for CI off, any push to `main` ships straight to a live service.
- [ ] Delete the two `smoke-test-*@dynalytix.test` users if you would rather not keep them.
- [ ] Retire the old storage: `data/labels.db`, `data/*.csv`, `data/exports/`, `videos/`, and the `dynalytix-data` repo.
- [ ] Rotate the R2 token if you would rather it had never passed through an agent session.
- [ ] Update `MovesList.jsx`, which still reads the removed `move.tags` (§C6).

### If it goes wrong

Railway keeps previous deployments: open the service → Deployments → pick the `7be1840` build → Redeploy. That restores the old backend. Supabase and R2 are separate and unaffected by a rollback.

---

## C11. Manual QA — your first session as a labeler

Walk this in one sitting, on a real climbing clip. Each step says what you should see, so a wrong result is obvious.

**Setup**

```bash
cd data_collection/backend && uvicorn src.web.api:app --reload   # one shell
cd data_collection/frontend && npm run dev                       # another
```

`.env` must hold the real Supabase values (§C8), or sign-in fails against the wrong project.

### 1. Sign up
- [ ] Open the app signed out. You get the **sign-in screen**, not a spinner and not a blank page.
- [ ] Choose **Sign up**, enter an email and a password under 6 characters → it refuses locally, without a network call.
- [ ] Sign up properly. Either you land in the app, or you are told to confirm your email — no silent nothing.
- [ ] **Reload the page.** You stay signed in.
- [ ] Your email and **Sign out** are in the header. Sign out, confirm you are back at the gate, sign in again.

### 2. Upload
- [ ] Pick a climbing video. Progress runs; the tab-switch warning appears.
- [ ] When it finishes you land on the player with the **skeleton drawn over the climber**. If the skeleton is offset or shrunken, stop — that is the coordinate bug, not a UI issue.
- [ ] The header strip reads **0 moves defined · 0 labeled · 0 tagged**.
- [ ] The define banner reads *"Set the start frame with [, the end frame with ], then Create Move."* Dismiss it; it stays gone. Reload; it comes back (session-only, by design).

### 3. Holds
- [ ] Press **H** or click Show Holds. Detection is off by default, so expect **zero boxes** — that is correct, not a failure.
- [ ] **Drag on the video** over a hold. A box appears and persists.
- [ ] Add three or four more, on the holds your climber actually uses.
- [ ] **Click a box.** It disappears. Reload the page — it stays gone.

### 4. Define a move
- [ ] Scrub to where a move starts, press **`[`**. Scrub to where it ends, press **`]`**. Markers appear on the timeline.
- [ ] Click **Create Move**. The form opens **beside the video, not over it**.
- [ ] **With the panel open, press `[` and `]` again, and the arrow keys.** They must still work — this is the whole point of the panel. If focus is in the Description box they correctly do not.

### 5. Label it
- [ ] All four hold slots are there: Start Left, Start Right, End, and Foot marked optional.
- [ ] Hover an **"i"** next to a hold type. The definition appears. Try one on Confidence — it should say it is *your* confidence in the labels, not the climber's. Try Size — the size of the *movement*.
- [ ] On Start Left, click **Pick on video**. The button activates and the video shows a hint. **Click a box** — it is assigned, and the button returns to normal. Press **Esc** during pick mode to confirm it cancels.
- [ ] Give each of the three required slots a hold type; tick a couple of qualities.
- [ ] Under Reach Detail the options read as sentences ("Reached it — in control"), not `Reached Not Controlled`.
- [ ] Try **Save Move** with a required slot empty → it names the missing slot rather than failing silently.
- [ ] Fill it in and save. The panel closes and the strip reads **1 move defined · 1 labeled · 0 tagged**.

*(If the slots arrive pre-filled and marked **suggested**, auto-suggest is working — it needs holds drawn in step 3 and the video's `width`/`height`, both of which this branch now has. A video registered before the dimensions migration will suggest nothing, deliberately: see §C9.)*

### 6. Define a second move
- [ ] Mark `[` and `]` again and open the form. **Wall angle and the hold types/qualities prefill** from the previous move; the hold assignments do **not**.
- [ ] Save it. The strip reads **2 moves defined**.

### 7. Tag
- [ ] Pick a move from the list to enter tagging mode.
- [ ] The banner reads *"Use the scroll bar to find the frame, then tag it."*
- [ ] Scrub to a frame and add a sensation tag. Hover its **"i"** — the definition appears.
- [ ] The tag shows on the timeline. The strip's **tagged** count goes up.
- [ ] Confirm there is **no Traction Source or Traction Direction field** anywhere — removed in v3.
- [ ] The **"Holds in use"** panel is there. On a frame where the climber is on the holds you boxed in step 3, it lists them; **click a row** and the body parts land in the tag form (a hand becomes the wrist, a foot becomes the ankle — `BODY_PARTS` has no fingertip or toe). Clicking a second row **adds** to the selection rather than replacing it.
- [ ] Scrub to a frame where the climber is mid-move, off the holds. The panel says so in words — "no contact", not an empty box. Four distinct messages exist (no holds / no dimensions / no pose / no contact); any of them is correct behaviour, a blank panel is not.

### 8. Export and download
- [ ] Click **Finish & Export**.
- [ ] The modal offers **"Download the labeled CSV"** as a link, and says the link expires.
- [ ] Click it. The CSV downloads.
- [ ] **Open it.** Confirm your moves are there with the four hold slots, and that the pose columns are intact.

### 9. The awkward cases
- [ ] Tag a move **No Hands** → the three hand slots disappear, Foot stays. Save it; it should be accepted with empty hand slots.
- [ ] Sign out mid-session, sign back in → you are returned to a clean upload screen, not a half-populated one.
- [ ] Leave the app open long enough for the access token to expire (an hour), then save a move. It should **refresh and succeed**, not throw you back to the sign-in screen.

# Pose Extractor v2 — Frontend Report

Branch: `feat/pose-extractor-v2`, cut from `feat/supabase-r2-schema-v3` (commit `aea9920`).
Scope: `data_collection/frontend` only. No backend file is modified — `backend/REPORT.md`
and `backend/src/web/api.py` were read only, to pin the API contract.

---

## 1. Current flow, fps assumptions, and the CSV contract

### 1.1 How extraction works today

`VideoUpload.jsx` → `PoseExtractor.js`, entirely client-side. The video never leaves
the browser; only the pose CSV is sent to the server.

1. `handleFileSelect` validates the extension (`.mov`, `.mp4`, `.avi`), makes a blob URL,
   and stores it as `videoBlobUrl` for later playback.
2. It creates a detached `<video>`, waits for `loadedmetadata`, then **hardcodes
   `const fps = 30`** (`VideoUpload.jsx:62`) and derives
   `totalFrames = Math.floor(duration * 30)`.
3. `PoseExtractor.initialize()` builds a `PoseLandmarker` — **a fresh one per upload**,
   re-downloading WASM + model each time. Model is `pose_landmarker_full` (not lite),
   `delegate: 'GPU'` with no CPU fallback, `runningMode: 'VIDEO'`.
4. `extractFromVideo()` is the bottleneck. For every frame it does:

   ```js
   videoElement.currentTime = timestampMs / 1000;
   await new Promise(resolve => { videoElement.onseeked = resolve; });
   ```

   A **discrete seek per frame**. Each seek forces the decoder to find and decode to an
   exact position; on a long-GOP phone H.264/HEVC file that can mean re-decoding from the
   preceding keyframe every time. At 30fps assumed over a 2-minute clip that is 3,600
   seeks. This is why upload takes many minutes, and it is the single thing this branch
   replaces.
5. `framesToCSV()` shapes the rows, the result goes into the Zustand store, and the CSV is
   POSTed to `/api/videos/register` as **multipart form data** with no auth header.

### 1.2 Correctness problems in the current math

- **fps is a guess.** A 60fps iPhone clip is walked at 30fps, so *every other frame is
  silently dropped* and `frame_number` in the CSV counts 30ths of a second while the
  player counts 60ths. Frame indices in saved moves and frame tags are then wrong by 2×
  against the real video.
- **`Math.floor(duration * fps)`** truncates, losing the final partial frame.
- **`onseeked` as a bare property** is overwritten each iteration and never removed; a
  seek that resolves late can settle the wrong promise.
- **No cancel path.** Navigating away mid-extraction leaves the loop running.
- **No decode-failure detection.** An HEVC file Chrome can't decode produces a silent run
  of null-landmark rows rather than an error.

### 1.3 Every place fps is assumed (the full list)

| File | Line | Assumption | Fate on this branch |
|---|---|---|---|
| `components/VideoUpload.jsx` | 62 | `const fps = 30` — the source of the bug | **Removed**; measured from frame callbacks |
| `components/VideoUpload.jsx` | 64 | `Math.floor(duration * fps)` | **Replaced** with `Math.round` |
| `services/PoseExtractor.js` | 166–193 | `fps` passed in; seek-per-frame | **Rewritten** |
| `components/VideoPlayer.jsx` | 34 | `currentVideo?.fps \|\| 30` | Fallback **removed** |
| `components/VideoPlayer.jsx` | 82 | `Math.floor(currentTime * fps)` → currentFrame | Reads store fps |
| `components/VideoPlayer.jsx` | 133 | `frame / fps` → seek time | Reads store fps |
| `components/VideoPlayer.jsx` | 193 | `(currentFrame / fps).toFixed(2)` display | Reads store fps |
| `components/TaggingMode.jsx` | 103 | `currentVideo?.fps \|\| 30` | Fallback **removed** |
| `components/TaggingMode.jsx` | 143, 155, 166, 188, 243 | frame↔time both directions | Reads store fps |
| `components/MoveForm.jsx` | 231, 238–239 | `(moveStart / fps) * 1000` → `timestamp_*_ms` sent to API | Reads store fps |
| `components/MoveForm.jsx` | 344, 346 | `currentVideo?.fps \|\| 30` duration display | Fallback **removed** |
| `components/SkeletonOverlay.jsx` | 59 | `csvData[currentFrame]` — **positional**, assumes row N is frame N | Kept; the no-gap guarantee is what makes it safe |
| `services/PoseExtractor.js` | 19 | `30: 'right_heel'` | **Not fps** — a MediaPipe landmark index. Stays. |

`MovesList.jsx`, `ExportService.js`, and `api/client.js` do no frame↔time conversion.

`SkeletonOverlay` deserves emphasis: it indexes the parsed CSV array *by position*. That
is only correct while the CSV has exactly one row per frame with no gaps, which is
precisely the invariant step 5 verifies.

### 1.4 The CSV column contract — recorded exactly

> **Updated by the landmark widening — see §9.** The contract is now **147 columns /
> 33 landmarks**. This section describes the *current* format; the original 15-landmark,
> 75-column layout is preserved verbatim as the first 75 columns, so everything below
> about column 75 is additive. §9 covers what changed and why.

When this branch started, the code emitted **15 landmarks and 12 angles** — not the
"33 landmarks, 10 joint angles" the original brief named. That gap is what §9 closes.
The angle count stays at **12**: the brief's "10" omitted `angle_upper_back` and
`angle_lower_back`, which the code has always emitted.

**147 columns**, in this order:

1. `frame_number` — integer, from 0
2. `timestamp_ms` — float, milliseconds
3. `speed_center_of_mass` — px/s of the hip midpoint; `0` on the first frame and whenever
   landmarks are missing
4. **12 angles**, degrees, empty string when any contributing landmark is absent:
   `angle_left_elbow`, `angle_right_elbow`, `angle_left_shoulder`, `angle_right_shoulder`,
   `angle_left_hip`, `angle_right_hip`, `angle_left_knee`, `angle_right_knee`,
   `angle_left_ankle`, `angle_right_ankle`, `angle_upper_back`, `angle_lower_back`
5. **33 landmarks × 4 fields** = 132 columns, `landmark_<name>_{x,y,z,visibility}`.
   Names are MediaPipe's canonical ones. The order is **the original 15 first**, then the
   18 added ones — *not* MediaPipe index order (§9 explains why).

   **Original 15** (columns 16–75, unchanged): `nose`, `left_shoulder`, `right_shoulder`,
   `left_elbow`, `right_elbow`, `left_wrist`, `right_wrist`, `left_hip`, `right_hip`,
   `left_knee`, `right_knee`, `left_ankle`, `right_ankle`, `left_heel`, `right_heel`

   **Added 18** (columns 76–147), in MediaPipe index order: `left_eye_inner`, `left_eye`,
   `left_eye_outer`, `right_eye_inner`, `right_eye`, `right_eye_outer`, `left_ear`,
   `right_ear`, `mouth_left`, `mouth_right`, `left_pinky`, `right_pinky`, `left_index`,
   `right_index`, `left_thumb`, `right_thumb`, `left_foot_index`, `right_foot_index`

Header line, verbatim:

```
frame_number,timestamp_ms,speed_center_of_mass,angle_left_elbow,angle_right_elbow,angle_left_shoulder,angle_right_shoulder,angle_left_hip,angle_right_hip,angle_left_knee,angle_right_knee,angle_left_ankle,angle_right_ankle,angle_upper_back,angle_lower_back,landmark_nose_x,landmark_nose_y,landmark_nose_z,landmark_nose_visibility,landmark_left_shoulder_x,landmark_left_shoulder_y,landmark_left_shoulder_z,landmark_left_shoulder_visibility,landmark_right_shoulder_x,landmark_right_shoulder_y,landmark_right_shoulder_z,landmark_right_shoulder_visibility,landmark_left_elbow_x,landmark_left_elbow_y,landmark_left_elbow_z,landmark_left_elbow_visibility,landmark_right_elbow_x,landmark_right_elbow_y,landmark_right_elbow_z,landmark_right_elbow_visibility,landmark_left_wrist_x,landmark_left_wrist_y,landmark_left_wrist_z,landmark_left_wrist_visibility,landmark_right_wrist_x,landmark_right_wrist_y,landmark_right_wrist_z,landmark_right_wrist_visibility,landmark_left_hip_x,landmark_left_hip_y,landmark_left_hip_z,landmark_left_hip_visibility,landmark_right_hip_x,landmark_right_hip_y,landmark_right_hip_z,landmark_right_hip_visibility,landmark_left_knee_x,landmark_left_knee_y,landmark_left_knee_z,landmark_left_knee_visibility,landmark_right_knee_x,landmark_right_knee_y,landmark_right_knee_z,landmark_right_knee_visibility,landmark_left_ankle_x,landmark_left_ankle_y,landmark_left_ankle_z,landmark_left_ankle_visibility,landmark_right_ankle_x,landmark_right_ankle_y,landmark_right_ankle_z,landmark_right_ankle_visibility,landmark_left_heel_x,landmark_left_heel_y,landmark_left_heel_z,landmark_left_heel_visibility,landmark_right_heel_x,landmark_right_heel_y,landmark_right_heel_z,landmark_right_heel_visibility,landmark_left_eye_inner_x,landmark_left_eye_inner_y,landmark_left_eye_inner_z,landmark_left_eye_inner_visibility,landmark_left_eye_x,landmark_left_eye_y,landmark_left_eye_z,landmark_left_eye_visibility,landmark_left_eye_outer_x,landmark_left_eye_outer_y,landmark_left_eye_outer_z,landmark_left_eye_outer_visibility,landmark_right_eye_inner_x,landmark_right_eye_inner_y,landmark_right_eye_inner_z,landmark_right_eye_inner_visibility,landmark_right_eye_x,landmark_right_eye_y,landmark_right_eye_z,landmark_right_eye_visibility,landmark_right_eye_outer_x,landmark_right_eye_outer_y,landmark_right_eye_outer_z,landmark_right_eye_outer_visibility,landmark_left_ear_x,landmark_left_ear_y,landmark_left_ear_z,landmark_left_ear_visibility,landmark_right_ear_x,landmark_right_ear_y,landmark_right_ear_z,landmark_right_ear_visibility,landmark_mouth_left_x,landmark_mouth_left_y,landmark_mouth_left_z,landmark_mouth_left_visibility,landmark_mouth_right_x,landmark_mouth_right_y,landmark_mouth_right_z,landmark_mouth_right_visibility,landmark_left_pinky_x,landmark_left_pinky_y,landmark_left_pinky_z,landmark_left_pinky_visibility,landmark_right_pinky_x,landmark_right_pinky_y,landmark_right_pinky_z,landmark_right_pinky_visibility,landmark_left_index_x,landmark_left_index_y,landmark_left_index_z,landmark_left_index_visibility,landmark_right_index_x,landmark_right_index_y,landmark_right_index_z,landmark_right_index_visibility,landmark_left_thumb_x,landmark_left_thumb_y,landmark_left_thumb_z,landmark_left_thumb_visibility,landmark_right_thumb_x,landmark_right_thumb_y,landmark_right_thumb_z,landmark_right_thumb_visibility,landmark_left_foot_index_x,landmark_left_foot_index_y,landmark_left_foot_index_z,landmark_left_foot_index_visibility,landmark_right_foot_index_x,landmark_right_foot_index_y,landmark_right_foot_index_z,landmark_right_foot_index_visibility
```

Value rules that must survive the rewrite:

- Rows are joined with `\n`; no trailing newline; no quoting (no field can contain a comma).
- Landmark `x`/`y` are **pixel coordinates in the original video's resolution**
  (`lm.x * videoWidth`), *not* normalized. **This is the subtle part of the downscale
  work**: MediaPipe returns normalized coordinates, so the 512px inference canvas must
  *not* be used as the multiplier — the original `videoWidth`/`videoHeight` must be, or
  every coordinate silently shrinks and the overlay misaligns.
- `z` is raw MediaPipe depth, passed through unscaled. `visibility` is `lm.visibility || 0`.
- A frame with no detected pose emits `frame_number,timestamp_ms,0` then `''` for all 144
  remaining columns.
- Numbers are stringified by `Array.join`, i.e. JS default formatting.

### 1.5 Backend contract this must be written against

From `backend/src/web/api.py` (read-only). The backend on this base branch **has already
moved off the old shape**, so the current frontend is broken against it regardless of
performance:

- **Auth is now required** on every `/api` route except `/api/health`:
  `Authorization: Bearer <supabase access token>`, else `401`.
- **`POST /api/videos/register` takes JSON, not multipart**:
  `{ filename, fps: float, total_frames: int, duration_ms: float, csv_data: string }`
  → `201 { id, filename, fps, total_frames, duration_ms, r2_video_key, r2_pose_csv_key,
  r2_export_key, uploaded_at }`. `path`/`csv_path` are gone. `413` over 60 MB.
- **`POST /api/videos/upload` was removed.** The original video now goes up directly:
  `POST /api/videos/{id}/upload-url` `{content_type}` → `{url, key, expires_in}`, then a
  credential-free `PUT` to that URL with a **matching `Content-Type`** (or the signature
  fails), then `POST /api/videos/{id}/confirm-upload` `{key}`.

**The frontend currently has no Supabase client at all** — `@supabase/supabase-js` is not
in `package.json` and nothing reads `VITE_SUPABASE_URL`/`VITE_SUPABASE_ANON_KEY`, though
both are present in `.env`. Resolving that is recorded under the defaults in §3.

---

## 2. What changed, file by file

| File | Change |
|---|---|
| `src/services/poseMath.js` | **New.** All pure math: `detectFps`, `frameIndexFor`, `totalFramesFor`, `computeResult`, `buildRows`, `framesToCSV`, `csvHeaders`, plus the angle geometry and `LANDMARK_MAP`/`ANGLE_DEFINITIONS`. No MediaPipe or DOM import, so it is testable in Node. |
| `src/services/PoseExtractor.js` | **Rewritten.** Play-through capture loop, module-level landmarker singleton, fps detection, typed errors, cancel, visibility handling. Re-exports the pure helpers so existing importers keep working. |
| `src/utils/frames.js` | **New.** `fpsOf` / `timeToFrame` / `frameToTime` / `frameToMs` / `totalFrames`. One rounding rule for the whole app. |
| `src/components/VideoUpload.jsx` | **Rewritten.** Time-based progress, cancel, tab notice, typed error rendering, desktop hint, register with retry, presigned video upload. |
| `src/api/client.js` | Auth interceptor; `registerVideo` (JSON + backoff), `getUploadUrl`, `putVideoToR2`, `confirmUpload`, `uploadOriginalVideo`. Removed `uploadVideo` (endpoint no longer exists). |
| `src/api/auth.js` | **New.** Supabase client + `getAccessToken` / `requireAccessToken` / `authHeader`. |
| `src/components/VideoPlayer.jsx` | `|| 30` removed; conversions via `utils/frames`. Frame-from-time now **rounds** instead of flooring, matching the extractor. |
| `src/components/TaggingMode.jsx` | `|| 30` removed; 5 conversion sites via `utils/frames`. |
| `src/components/MoveForm.jsx` | `|| 30` removed; `timestamp_start_ms`/`timestamp_end_ms` via `frameToMs`. |
| `src/App.css` | Added `.cancel-button`. |
| `scripts/make_test_video.sh` | **New.** ffmpeg clip generator (installs ffmpeg if missing). |
| `scripts/test_pose_math.mjs` | **New.** 25 tests. |
| `scripts/fixtures/frame_times_{30,60}fps.json` | **New.** Real presentation times from the generated clips. |
| `package.json` | Added `@supabase/supabase-js`; `npm test`, `npm run make-test-videos`. |
| `.gitignore` | `.env` (was **not** ignored before) and `test-videos/`. |

`MovesList.jsx`, `SkeletonOverlay.jsx`, `ExportService.js`, `useStore.js`, `App.jsx` are unchanged.

### Why it should be fast now

The old loop set `currentTime` and waited for `seeked` once per frame. On long-GOP
phone footage each seek can re-decode from the preceding keyframe, so cost grows with
GOP length rather than frame count — thousands of seeks for a 2-minute clip.

The new loop decodes each frame exactly once, in presentation order, which is the
same work the video element does during ordinary playback. The floor is therefore the
clip's own duration, and the ceiling is set by whether inference keeps up. Pausing on
every frame callback means that when inference is slower than realtime the clip simply
takes longer — it never silently skips a frame, which a plain "detect on every
callback while playing" loop would do.

## 3. Defaults taken

Per instruction, decisions were made without asking and are recorded here.

1. **Every frame processed**, no fps sampling, as specified.
2. **512px long-edge** inference canvas. Landmarks are denormalized against the
   **original** resolution, so the CSV's pixel coordinates are unchanged by this.
3. **MediaPipe Tasks PoseLandmarker, lite model, GPU→CPU fallback, `runningMode: 'VIDEO'`**,
   as specified. The project was already on `@mediapipe/tasks-vision` (0.10.32), so
   **no legacy `@mediapipe/pose` migration was needed** — but the model changed from
   `pose_landmarker_full` to `pose_landmarker_lite` per the brief. Expect slightly
   lower landmark accuracy in exchange for the speed.
4. **CDN pinned to 0.10.32** rather than `@latest`, matching `package-lock.json`. The
   WASM glue and JS wrapper must agree, and `@latest` defeats CDN caching.
5. **`requestVideoFrameCallback` required**; no seek fallback. A browser without it
   gets a message naming Chrome, Edge and Safari in place of the upload panel.
6. **CSV contract initially kept as shipped** (75 columns, 15 landmarks, 12 angles)
   rather than the 33-landmark shape named in the brief, since the brief and the code
   disagreed. **Superseded:** the widening in §9 takes it to 147 columns / 33 landmarks,
   additively. Angles stay at 12.
7. **`REPORT.md` lives in `data_collection/frontend/`**, since the backend has its own.
8. **Holes are filled, not skipped.** A missing frame index produces a pose-less row
   rather than a gap, because `SkeletonOverlay` indexes the CSV positionally.
9. **`Math.round`, not `Math.floor`**, for both `frame_index` and `total_frames`.
   The old floor dropped the last partial frame and disagreed with the player.
10. **Fallback fps of 30** survives in `PoseExtractor.js` for clips with fewer than 3
    presented frames, where detection is impossible. Justified in §5.
11. **`@supabase/supabase-js` added** to mint the bearer token the backend now requires.
    This is the token *reader* only — **no sign-in UI**. See §7 for the handoff.
12. **Original-video upload is best-effort.** It runs after `register`, so a failure
    there logs a warning rather than discarding a successful extraction.
13. **Register retries only transport errors and 5xx.** A 401 or 413 will not become
    true on a retry, so those fail immediately.
14. **`.env` copied** from the original checkout and **added to `.gitignore`**. It was
    not ignored before, which was a live risk of committing keys. It is not committed.

## 4. Verification

`npm test` — **25 tests, all passing.**

```
✔ detectFps recovers each supported rate from ideal timings
✔ detectFps snaps NTSC rates to their nominal neighbour
✔ detectFps survives a stalled interval
✔ detectFps tolerates jitter within a rate
✔ detectFps returns null when there is too little to measure
✔ detectFps identifies the real recorded clips
✔ frameIndexFor rounds to the nearest frame
✔ totalFramesFor rounds rather than truncating
✔ every recorded presentation time maps to its own frame index
✔ rows are contiguous from 0 with no gaps, for both clips
✔ row count matches duration x fps for both clips
✔ timestamp equals frame_index / fps to within 1ms
✔ timestamps increase strictly
✔ duplicate presentation times collapse to one row
✔ a missing frame is filled rather than left as a gap
✔ out-of-order samples are sorted before indexing
✔ buildRows on no samples yields no rows
✔ the header is byte-identical to the shipped contract
✔ every row carries exactly 75 fields
✔ a pose-less frame is encoded as zero speed and empty columns
✔ the CSV has no trailing newline and one header line
✔ no field can contain a comma, so unquoted CSV stays parseable
✔ landmarks denormalize against the source resolution, not the canvas
✔ centre-of-mass speed is zero on the first frame and measured after
✔ a 60fps clip read as 30fps loses half the frames — the original bug
```

The three checks the brief asked for, confirmed for **both** clips:

- **Row count ≈ duration × fps** — 300 rows for the 30fps clip, 600 for the 60fps clip,
  against ffprobe's exact counts of 300 and 600.
- **`frame_index` monotonic with no gaps** — asserted index-by-index from 0.
- **`timestamp = frame_index / fps` within 1ms** — exact, since `timestamp_ms` is
  derived from the index rather than measured independently.

**Byte-identical output confirmed separately.** The new `framesToCSV` was diffed
against the old implementation (recovered from `aea9920`) over 200 synthetic frames
including pose-less frames and null angles: **243,156 bytes from both, identical.**

`npm run build` succeeds. ESLint reports **zero problems in every new or changed file**;
the 10 errors and 2 warnings that remain in `MovesList`, `SkeletonOverlay`, `VideoPlayer`
and `useStore` are all pre-existing — verified by linting `VideoPlayer.jsx` at `aea9920`,
which produces the same 3 errors and 1 warning, only shifted a line by the added import.

### Why not Playwright

MediaPipe needs a GPU-backed browser; in a headless container it either falls back to a
CPU path that measures nothing useful or fails outright. A Node test over recorded
frame timings covers exactly the logic that was wrong before, and the parts it cannot
reach are listed as manual checks in §6.

## 5. Justification for every remaining `30` in `src`

```
src/utils/frames.js:6            — the string "|| 30" inside a comment explaining the bug
src/components/TaggingMode.jsx:28 — unstable: '#eab308'  (a colour, not a rate)
src/services/PoseExtractor.js:53  — FALLBACK_FPS = 30
src/services/poseMath.js:30       — 30: 'right_heel'   (a MediaPipe landmark index)
src/services/poseMath.js:44       — KNOWN_FPS = [24, 25, 30, ...]  (a candidate, not a default)
src/services/PoseExtractor.js     — detectFps(...) ?? FALLBACK_FPS   (x2)
```

Only `FALLBACK_FPS` is a real fps default, and it is materially different from the old
`const fps = 30`. The old one was an **assumption applied to every video**. This one is
reached only when a clip presents fewer than three frames, so no interval exists to
measure. Every real clip measures its own rate. **No hardcoded 30 is on the path of a
normal upload.**

## 6. Step 6 — dev server and browser run

The dev server runs clean (`VITE v7.3.1 ready in 727 ms`, `http://localhost:5173/`) and
`npm run build` succeeds.

**No end-to-end browser timing was captured, and the automated attempt is worth
describing so it isn't repeated.** The app shell stops at `Loading Dynalytix…` without a
backend, so the extractor was driven directly in the page instead — the module imported
from the dev server, the 60fps clip fetched as a `File`. That part worked:
`requestVideoFrameCallback` present, clip served, module loaded.

The run never finished. The automation tab reports `document.hidden === true` and could
not be foregrounded (a screenshot, and `osascript … activate`, both left it hidden), and
Chrome throttles a background tab hard enough that a 10-second clip had not completed
after roughly two minutes. Forcing `document.hidden` to `false` and dispatching
`visibilitychange` resumed the loop but not the throttling; a bounded 300-call inference
benchmark, which needs no frame presentation at all, also failed to finish in 85s. At
that point the renderer stopped answering CDP for 45s. **These numbers measure Chrome's
background-tab throttling, not the extractor, so none of them are reported as timings.**

Two things this did establish, both real:

- The **`visibilitychange` pause works in a real browser** — the loop stopped precisely
  when the tab was backgrounded, which is what stalled the benchmark.
- The module **loads and runs under Vite** with no import or resolution errors.

**Before/after timing is therefore unmeasured.** The reasoning for the expected
improvement is in §2; the number itself has to come from the manual test below.

## 7. The manual test to run on your laptop

Do this in a **foreground** Chrome window with a real 60fps iPhone clip.

```bash
cd data_collection/frontend
npm install
npm run dev                       # http://localhost:5173
# and, in another shell, the backend, or register will 401
```

You must be **signed in** — the backend rejects every `/api` call without a Supabase
bearer token, and this branch adds no login screen (§8). With no session you should see
*"You are not signed in…"*, which is itself a valid check of the error path.

1. **Timing.** Open DevTools → Console, upload a 2-minute 60fps clip, and read the line
   `[PoseExtractor] N frames in Xs (clip Ys at 60fps, Zx realtime)`.
   **Expect `Z` around 1.0 or below.** Anything above ~2 means inference is the
   bottleneck — check the same console for
   `GPU delegate unavailable, falling back to CPU`, which would explain it.
2. **fps.** The progress line should read **`60 fps`**, not 30. This is the core fix.
3. **Frame count.** `N` should be within a frame or two of `duration × 60`
   (~7,200 for 2 minutes). Roughly half that means fps detection regressed.
4. **Progress + cancel.** The bar should track video time smoothly. Hit **Cancel**
   mid-run: it should return to the picker immediately with no error, and the same file
   should be selectable again.
5. **Tab notice.** While extracting, confirm *"Keep this tab open"*. Switch to another
   tab for a few seconds and come back — it should say it paused, then resume and finish
   with the **correct total frame count**. (This is the behaviour that blocked automation
   in §6, so it is worth confirming by hand.)
6. **HEVC path.** Set iPhone Camera → Formats → **High Efficiency**, record a short
   clip, and upload it. Expect *"This video format can't be decoded in this browser…"*
   within about 5 seconds — not a hang and not a CSV full of empty rows. Then switch to
   **Most Compatible** and confirm the same shot works.
7. **Overlay alignment.** After extraction, scrub the player and check the skeleton sits
   on the climber. Misalignment would mean the 512px downscale leaked into the stored
   coordinates — the one regression the row-level tests cannot see.
8. **Frame accuracy.** Mark a move at a distinctive instant, then confirm the frame
   number in the player matches the moment on screen. On a 60fps clip the old build was
   off by 2×; this is the user-visible version of that check.
9. **Synthetic clips.** `npm run make-test-videos`, then upload `test_30fps.mp4` and
   `test_60fps.mp4`. Expect exactly 30/60 fps detected and ~300/~600 frames.

## 8. What the backend and the next frontend pass must know

**Nothing in this branch requires a backend change.** It was written against
`api.py` as it stands on `feat/supabase-r2-schema-v3`. Three things to be aware of:

1. **Sign-in is still missing, and it blocks uploads.** This branch adds
   `src/api/auth.js` — the token reader — and the bearer header on every request, but
   no login UI. **`register` will 401 for any user who has not signed in by some other
   means.** That screen is the single highest-priority follow-up; `.env` already has
   `VITE_SUPABASE_URL` and `VITE_SUPABASE_ANON_KEY`.
2. **The rest of the frontend is still on the old API contract.** §7 of the backend
   report lists breaking changes this branch did **not** touch, because they are outside
   pose extraction: `moves` lost `timing`/`dyno_style`/`contextual_data`/`tags` and
   gained `confidence`; `environments` was restructured into four named slots;
   `export` and `csv` now return `307` redirects to presigned URLs rather than bodies;
   `/api/holds` is new. `MoveForm`, `TaggingMode` and `ExportService` will need that pass.
   **`ExportService.js` still sends `?delete_video=true`, which the new endpoint ignores.**
3. **Store and API shapes.**
   - `currentVideo` is now the new register response: `path` and `csv_path` are **gone**,
     replaced by `r2_video_key` / `r2_pose_csv_key` / `r2_export_key`. Anything reading
     `currentVideo.path` will get `undefined`.
   - **`currentVideo.fps` is now a measured float and is authoritative.** No component
     may reintroduce a default; use `fpsOf` from `src/utils/frames.js`, which returns
     `null` rather than guessing.
   - `total_frames` is now `round(duration × fps)`, so it may be one higher than the old
     floored value for the same clip.
   - The store itself is unchanged — no new fields, no renames.

### Known limitations

- Extraction is **single-threaded on the main thread**. A Web Worker with
  `OffscreenCanvas` would keep the UI responsive on slow machines; not done here, as it
  would have meant restructuring the capture loop around a second MediaPipe context.
- **Switching tabs pauses extraction.** Deliberate — background throttling makes the
  capture loop unreliable — but it does mean a long clip needs the tab left open.
- The **lite** model is less accurate than the `full` model this replaces. If landmark
  quality regresses noticeably on real climbing footage, `MODEL_URL` in
  `PoseExtractor.js` is a one-line change back to `pose_landmarker_full`, at a cost in
  speed.
- **No end-to-end timing has been measured** (§6). The headline performance claim is
  reasoned, not observed.

---

## 9. Landmark widening — 15 → 33 landmarks (follow-up)

The CSV now carries **all 33 MediaPipe Pose landmarks**, `x`/`y`/`z`/`visibility` each,
alongside the unchanged 12 angles. **147 columns**, up from 75.

MediaPipe always returned all 33; the old `LANDMARK_MAP` simply discarded 18 of them
before they reached the CSV. So this costs nothing at inference time — the landmarks were
already computed and thrown away. The only real cost is file size (below).

### Column order: additive, not canonical

The 18 new landmarks are **appended after** the original 15 rather than interleaved into
MediaPipe index order. Index order would have been tidier, but it would push
`left_shoulder` from column 19 to column 23 and shift every column after it.

Appending keeps the change **purely additive in layout**: the first 75 columns are the
same columns, in the same order, under the same names. A positional reader of the old
format keeps working unchanged, and a name-based reader is unaffected either way. Within
the appended block the 18 are in MediaPipe index order, so there is still a rule, just
applied to the new columns only.

> **Note on "byte-identical".** §10 rounds coordinates for output, which changes the
> *values* in every landmark column including the original 15. The columns are unchanged;
> the digits in them are shorter. A byte-comparison against a CSV produced before §10
> will differ, and that is intended.

New names are MediaPipe's canonical ones. The original 15 already used canonical names,
so **no existing column name changed**:

| Added | MediaPipe indices |
|---|---|
| Face — `left_eye_inner`, `left_eye`, `left_eye_outer`, `right_eye_inner`, `right_eye`, `right_eye_outer`, `left_ear`, `right_ear`, `mouth_left`, `mouth_right` | 1–10 |
| Hands — `left_pinky`, `right_pinky`, `left_index`, `right_index`, `left_thumb`, `right_thumb` | 17–22 |
| Feet — `left_foot_index`, `right_foot_index` | 31, 32 |

For climbing, the hand and foot landmarks are the interesting ones: `left_index` /
`left_thumb` / `left_pinky` give hand orientation on a hold, and `left_foot_index` gives
toe position, none of which the heel-only foot model could express.

### Golden file replaces the ad-hoc diff

The previous byte-identical check compared against the old implementation recovered from
git, which stops being possible once the contract deliberately changes. It is now a
committed golden file:

- `scripts/fixtures/golden_pose.csv` — 40 rows, 147 columns, 96,744 bytes.
- `scripts/golden_frames.mjs` — the seeded, deterministic frames behind it, shared by the
  generator and the test so the two cannot drift. It deliberately includes pose-less
  frames, frames with individual landmarks missing, null angles, and the first frame's
  zero centre-of-mass speed.
- `npm run make-golden` regenerates it. **Regenerate only when the contract is meant to
  change, and read the diff.**

**33 tests pass** (was 25). The 8 new ones cover the golden bytes, the 147-column header,
all 33 canonical names at their correct indices, the original 15 names surviving, and —
the important one — *the first 75 columns of the golden file reproducing the
pre-widening format exactly*.

The golden test was checked for bite: reordering the landmarks into canonical index order
fails 5 tests, and renaming a single landmark fails 5 tests. The row-count, `frame_index`
contiguity and `timestamp = frame_index / fps` tests all still pass unchanged.

### Backend check (read-only — no backend file modified)

Both are column-agnostic; **no backend change is needed**:

- **`POST /api/videos/register`** treats `csv_data` as opaque text. It length-checks the
  UTF-8 bytes and puts the string straight to R2 (`api.py:591`, `api.py:612`). It never
  parses columns.
- **`exporter.py`** reads with `csv.DictReader` and builds its writer from
  `list(reader.fieldnames) + self.label_columns()` (`exporter.py:50–52`, `150–155`) — it
  passes whatever columns arrive straight through and appends the label columns. The only
  column name it depends on is **`frame_number`** (`exporter.py:161`), which remains
  column 1.
- No `landmark_*` or `angle_*` name appears anywhere in the backend Python. The other
  `frame_number` hits are the `frame_tags` table, unrelated to the pose CSV.

### Size: doubled by the widening, then more than undone by rounding

The widening alone took the row from **1,154 → 2,330 bytes, a 2.02× increase**, which put
a 5-minute 60fps clip at ~48 MB against the backend's 60 MB `MAX_REGISTER_BYTES`.

**§10 resolved this.** Rounding coordinates for output brings the row to **1,091 bytes** —
*below the original 75-column format's 1,154*, with 18 more landmarks in it. Current
figures are in §10.

### One visible side effect — resolved in §10

`SkeletonOverlay` drew a joint dot for **every** `landmark_*` column it found, so the
widening would have put 33 dots on the overlay instead of 15, cluttering the face.
**§10 filters the display back to the original 15.**

---

## 10. Output rounding and overlay filtering (follow-up)

### 10.1 Coordinate rounding

Landmark values are rounded **in the CSV writer only**:

| Field | Decimals |
|---|---|
| `landmark_*_x`, `landmark_*_y`, `landmark_*_z` | **4** |
| `landmark_*_visibility` | **3** |

Rounding is applied at write time, never to the in-memory result, so angles and
centre-of-mass speed are still derived from full-precision landmarks — only the stored
text is shortened. `Math.round(v * 10**d) / 10**d` rather than `toFixed`, so values
stringify without padding (`0` stays `"0"`, not `"0.0000"`), with `-0` collapsed to `0`
and no exponent notation. Three tests enforce all of that.

**Correcting the premise this was requested under:** `x` and `y` are **pixel coordinates
at source resolution**, not normalized — `computeResult` multiplies MediaPipe's
normalized output by the original `videoWidth`/`videoHeight` (§1.4). Only `z` and
`visibility` are roughly normalized. The 4-decimal choice is still safe, but for a
different reason than "sub-pixel up to 10k": at pixel scale 4 decimals is **1/10,000 of a
pixel**, which is far more headroom than needed at any resolution. 2 decimals would still
be comfortably sub-pixel and would save more; 4 is kept as specified.

`speed_center_of_mass`, the 12 angles and `timestamp_ms` are **not** rounded — they were
not in scope, and at 1 column each their contribution is negligible next to 132 landmark
columns. Rounding the angles too would be an easy further saving.

### 10.2 Measured effect

Golden file: **96,744 → 47,208 bytes, a 51% reduction.**

| Format | Bytes/row |
|---|---|
| 75 columns, unrounded (original) | 1,154 |
| 147 columns, unrounded (after §9) | 2,330 |
| **147 columns, rounded (now)** | **1,091** |

**The rounding more than pays for the widening.** The CSV now carries 18 more landmarks
per frame in *fewer* bytes per row than the original 15-landmark format used.

| Clip | Pose CSV |
|---|---|
| 2 min @ 30fps | ~3.7 MB |
| 2 min @ 60fps | ~7.5 MB |
| 5 min @ 60fps | ~22.5 MB |
| 10 min @ 60fps | ~45.0 MB |

**Maximum clip under the 60 MB `MAX_REGISTER_BYTES` cap: 57,656 frames**, i.e.

- **16.0 minutes at 60fps** (was ~6 minutes after §9, ~12 minutes before the widening)
- **32.0 minutes at 30fps**

The 2-minute target case sits at ~7.5 MB, roughly 12% of the cap. The `413` ceiling is no
longer a practical concern for climbing footage.

### 10.3 Tests

**36 tests pass** (was 33). The golden file was regenerated with the rounded values, and
the three new tests cover:

- no landmark coordinate exceeds 4 decimals, no visibility exceeds 3, and nothing uses
  exponent notation — checked across every value in the golden file
- rounding does **not** reach back into `computeResult`, so in-memory precision is intact
- values rounding toward zero from either side produce `0`, never `-0` or `1e-7`

**The first-75-columns test still passes.** Note what it now means: it asserts that the
first 75 columns of the current output match the pre-widening *column layout* — same
columns, same order, same names. It is not a claim that the bytes match a CSV produced
before rounding, which they deliberately do not.

Row count, `frame_index` contiguity and `timestamp = frame_index / fps` are untouched and
still green.

### 10.4 Overlay: 33 landmarks stored, 15 drawn

`SkeletonOverlay` now draws joint dots only for the original 15 body landmarks, via
`LEGACY_LANDMARK_ORDER` imported from `poseMath`. **Skeleton lines are unchanged** —
`SKELETON_CONNECTIONS` was already a fixed list and never depended on the landmark count.

The data/display split is deliberate and commented in place: all 33 landmarks are
extracted, stored and exported; the overlay just doesn't dot eyes, ears, mouth, fingers
and toes, which cluttered the face without saying anything about the climbing. Anything
wanting the face or hand points reads them from the CSV, where they still are.

Incidentally this removed one pre-existing lint error (an unused loop variable in the old
`Object.entries` iteration), taking `SkeletonOverlay.jsx` from 5 problems to 4. The
remaining 4 are pre-existing hoisting and dependency-array warnings, untouched.

---

## 11. Coordinate spaces: landmarks vs hold boxes (follow-up)

### 11.1 The mismatch

Pose landmarks are stored as **pixels** at source resolution — `computeResult`
multiplies MediaPipe's normalized output by `videoWidth`/`videoHeight` (§1.4). Hold
bounding boxes are stored **normalized 0–1** (`public.holds`: `bbox_* CHECK (>= 0 AND
<= 1)`). Comparing them directly is meaningless.

It is worse than a scale factor. Every box looks ~200+ units away from every landmark,
so the ranking collapses to "whichever box extends furthest right and down", because
that shrinks the pixel gap fractionally. A hold the hand is **literally inside** loses to
one on the opposite corner of the wall. There is a test pinning exactly that.

### 11.2 ⚠️ The nearest-box comparison does not exist yet

**There is no hold-matching code anywhere in this repo**, and there was none before this
change. Checked:

- **Frontend** — no bbox or nearest-box logic. The `hold_type_reaching` /
  `hold_type_non_reaching` / `hold_quality` fields in `MoveForm` and the store are Lens-1
  *taxonomy dropdowns*, unrelated to bounding boxes.
- **Backend** — `/api/holds` is CRUD only: create, list-by-video, delete. No distance,
  nearest, or matching logic in any Python file.

So there was nothing to fix. What this adds is the **primitives, with the units handled
correctly**, so whoever builds the feature does not rediscover the bug:

| Added | Purpose |
|---|---|
| `poseMath.normalizeLandmark(lm, w, h)` | Pixel → normalized. Divides `x`/`y` only. |
| `poseMath.normalizeLandmarks(map, w, h)` | Whole landmark map; skips internal `_com`. |
| `holdMatching.distanceToBox(point, box)` | Point-to-rectangle, 0 inside. |
| `holdMatching.isInsideBox(point, box)` | Containment. |
| `holdMatching.nearestHold(lm, holds, w, h, opts)` | Normalizes, then ranks. `maxDistance` in normalized units. |
| `holdMatching.nearestHoldsFor(...)` | Several landmarks at once. |
| `holdMatching.CONTACT_LANDMARKS` | The four fingertip/toe points that touch holds. |

`src/services/holdMatching.js` was marked NOT WIRED UP. **§12 wires it up** — the file
itself is unchanged.

Two deliberate choices:

- **`z` is never divided.** MediaPipe's `z` is a depth estimate on roughly the same scale
  as normalized `x`, and is stored unmultiplied, so dividing it by a pixel dimension
  would corrupt it. A test pins this.
- **Unknown frame size returns `null`, it does not guess.** Rows registered before §11.3
  have no dimensions. Assuming 1920×1080 would produce a confident, wrong answer; `null`
  forces the caller to skip the comparison.

`CONTACT_LANDMARKS` is `left_index`, `right_index`, `left_foot_index`, `right_foot_index`
— fingertips and toes rather than wrists and heels, since those sit far closer to the
hold actually being used. **These only exist because of the §9 widening**; the
15-landmark format had no fingertip or toe, so accurate contact matching was not possible
before it.

### 11.3 Backend: extras are silently dropped, so a migration was required

**Checked first, as asked: the backend does *not* store unknown JSON fields.** No
pydantic model sets `model_config` or `extra=`, so pydantic v2's default `extra='ignore'`
applies. Verified empirically against the installed pydantic 2.12.5:

```python
class M(BaseModel): a: int
M(**{'a': 1, 'width': 1920}).model_dump()   # -> {'a': 1}
```

`width` and `height` would have been **accepted and silently discarded** — no error, no
warning, nothing stored. So the migration was necessary.

**`supabase/migrations/20260913180000_add_video_dimensions.sql`** adds nullable
`width`/`height` `integer` columns to `public.videos`, with `CHECK (… IS NULL OR … > 0)`.
Additive and nullable, because rows written before it must stay valid.

Two traps this had to avoid, neither obvious from the migration alone:

1. **`check_schema()` requires an *exact* match** against `SCHEMA_VERSION` (`!=`, not
   `<`). Bumping `schema_version` to 4 would make the API **refuse to start** against any
   database that had not yet had this file applied, and would break
   `test_schema_version_is_three`. The migration therefore **does not bump
   `schema_version`** — it is purely additive and nullable, so a v3 reader is unaffected.
   That decision is commented in the migration file.
2. **`apply_schema_sql()` globbed `*_schema_v3.sql` only**, applying just the base file.
   The test suite builds its schema through it, so a test database would have been left
   without the new columns and every video-creating test would have failed on an
   unknown column. It now applies **every** `supabase/migrations/*.sql` in filename
   order. This was a latent limitation: any future additive migration would have hit it.

Plumbed through: `models.Video` (`Optional[int]`), `database.create_video` and
`_row_to_video` (via `row.get`, so a database still on v3 reads back as unknown rather
than raising), `api.VideoRegister` (optional, `gt=0`), `api.VideoResponse`,
`video_to_response`, and the register insert.

**This is the one additional backend change**, and it is confined to those files plus the
new migration. Nothing else in the backend was touched.

### 11.4 Frontend plumbing

`extractFromFile` already returned `width`/`height`; they are now sent in the register
payload and kept on the store's video object. `setCurrentVideo` falls back to the
measured values when the response echoes `null`, so a frontend running against a backend
that has not yet applied the migration still has the dimensions in memory for the
session.

### 11.5 Verification

**Frontend: 48 tests pass** (was 36). The 12 new ones cover normalization (including `z`
untouched and the round-trip back to MediaPipe's input), refusal on unknown frame size,
point-to-rectangle distance, containment agreeing with zero distance, `maxDistance` in
normalized units, per-landmark matching, the contact landmarks existing in the 33-set —
and the divergence test that pins the bug itself.

**Backend: 61 tests pass**, run against a throwaway local Postgres, *not* the live
Supabase project — the v3 migration `DROP`s and recreates the labeling tables, so running
the suite against production data would destroy it. Plain Postgres needs a small `auth`
schema shim (`auth.uid()`, `auth.role()`) for the RLS policies; with that in place the
suite is green, including `test_schema_version_is_three`, which still passes precisely
because the version was not bumped.

Round-trip checked directly against the migrated table: `width`/`height` store and read
back as `1920`/`1080`; a video registered without them reads back `None`/`None`; and
`width=0` is rejected by the `CHECK` constraint.

### 11.6 Coordination note

The backend files touched here (`models.py`, `database.py`, `api.py`) are the same ones
the Supabase/R2 session is working in on `feat/supabase-r2-schema-v3`. **These edits are
small and additive, but they will need a careful merge** if that branch has moved. The
`apply_schema_sql` change in particular alters shared behaviour — it now applies all
migrations rather than only the base schema.

---

## 12. Hold auto-suggest UI (follow-up)

The primitives from §11 are now wired into the tagging flow. **`holdMatching.js` is
byte-for-byte unchanged** — no unit handling was touched. Everything new sits on top of
it and delegates every coordinate decision downward.

### 12.1 What it does

While tagging a frame, a **Holds in use** panel shows which holds the climber is on:

```
HOLDS IN USE                                 frame 412
  ✋ Left hand      hold #11              on
  🦶 Right foot     hold #33      2.1% away
  [ Use all 2 ]
  Suggested: left_wrist, right_ankle · left side
```

Clicking a row applies it to the frame-tag form. This is the part that makes it a
*suggestion* rather than a readout: the contacts map onto fields that actually exist.
`BODY_PARTS` has no fingertip or toe entry, so each contact degrades to the nearest real
option — `left_index → left_wrist`, `right_foot_index → right_ankle` — which is what a
tag on that limb would carry anyway.

It is **read-only assistance**. It never writes a tag by itself, every suggestion is one
click to apply and free to ignore, and applying is additive, so accepting two in a row
keeps both body parts. `side` is only filled when the contacts agree on one — a tag
carries a single side, so two hands must leave that to the labeller.

### 12.2 Layering

| Layer | File | Owns |
|---|---|---|
| Primitives (§11, **unchanged**) | `services/holdMatching.js` | pixel→normalized, point-to-box distance, nearest, unknown-size refusal |
| Labelling logic (new) | `services/holdSuggestions.js` | limb→body-part mapping, contact threshold, visibility filter, reason codes |
| UI (new) | `components/HoldSuggestions.jsx` | rendering, click-to-apply |
| Wiring | `components/TaggingMode.jsx` | fetches holds, applies suggestions to the tag form |

`holdSuggestions.js` does **no geometry**. It calls `nearestHoldsFor` and reads the
result. If a suggestion is wrong in space, the bug is in the inputs — a missing
`width`/`height`, a bad `bbox` — not in that file.

Two thresholds, both judgement calls rather than derived facts:

- **`CONTACT_THRESHOLD = 0.04`** — 4% of the frame. Roughly a hold's own width, which
  absorbs landmark jitter without matching a limb halfway across the wall. Passed to
  `nearestHold` as `maxDistance`, in normalized units.
- **`minVisibility = 0.5`** — an occluded hand sitting exactly on a hold produces no
  suggestion. A confident suggestion from a limb MediaPipe cannot see is worse than none.

### 12.3 It explains itself when it has nothing to say

Four distinguishable reasons, rendered as prose rather than an empty list, so "nothing
detected" is never mistaken for "broken":

| Reason | Shown as |
|---|---|
| `no-holds` | No holds recorded for this video yet |
| `no-dimensions` | Registered before frame dimensions were stored — re-upload to enable |
| `no-pose` | No pose detected on this frame |
| `no-contact` | No hand or foot near a hold on this frame |

`no-dimensions` is the §11 refusal surfacing in the UI: rather than assuming 1920×1080
for a video registered before the migration, it says so.

### 12.4 ⚠️ Prerequisite: nothing creates holds yet

**In practice this panel will show "No holds recorded for this video yet" for every
video today.** `/api/holds` accepts `POST`, but nothing in the frontend calls it — there
is no hold-drawing UI and no detection. The suggest path is complete and tested; the
supply of holds is not.

Building hold creation was **not** in scope here and I did not add it. The smallest thing
that would make this live is a box-drawing overlay on the video that `POST`s normalized
`bbox_*` — the API client functions it would need (`createHold`, `deleteHold`) are
already added and unused. Say the word.

### 12.5 Also added

- **Holds API client**: `getHolds(videoId)` → `GET /api/videos/{id}/holds`,
  plus `createHold` / `deleteHold`. Endpoint paths verified against `api.py`.
- **Store slice**: `holds`, `setHolds`, `addHold`, `removeHold`, matching the existing
  `moves` / `frameTags` pattern.
- **Fetch is best-effort.** A holds failure logs a warning and disables suggestions;
  tagging works fine without them.
- Routed one remaining raw `currentFrame / fps` display conversion in `TaggingMode`
  through `frameToTime`. Same family as §3, correct before, just inconsistent.

### 12.6 A real bug this surfaced

The first run failed three tests on my own code. `Number('')` is `0`, and
`Number.isFinite(0)` is `true` — so parsing a pose-less frame's empty landmark columns
produced **a phantom limb at (0, 0)**, which then matched any hold near the frame's
top-left corner *with full confidence and `inside: true`*.

Fixed with an explicit `numberOrNull` that treats an empty cell as absent before any
arithmetic, and pinned by a regression test. Worth noting that the trap was described in
a comment in the test I wrote before the implementation hit it anyway — empty-string
coercion is easy to write past.

### 12.7 Verification

**61 tests pass** (was 48). The 13 new ones cover row parsing and empty-column rejection,
limb→body-part mapping against the real `BODY_PARTS` taxonomy, `sideFor` refusing on
mixed sides, the threshold boundary (inside vs near vs beyond), the visibility filter,
ordering surest-first, all four reason codes, the unknown-size refusal, and the
phantom-limb regression.

One test is worth calling out: **the same contact is resolved identically at 1920×1080,
3840×2160 and 720×1280.** That is only true because the landmarks are normalized before
comparison, and it is the property the whole §11/§12 pair exists to protect.

Lint clean on every new and changed file; build succeeds.

---

## 13. Dataset A frontend (runbook-w1-backend, frontend half)

Branch `feat/dataset-a-assignments`, on top of the backend half (commits `1fe2947`…
`2a00c38`). Built against `data_collection/backend/API_DATASET_A.md`. Dataset B — the
self-upload flow under **My videos** — is the app as it was; a non-admin with no
assignments lands there with no Admin tab (asserted in `App.test.jsx`).

### 13.1 Per-file changes

**Backend (one additive endpoint, documented in API_DATASET_A.md)**

| File | Change |
|---|---|
| `backend/src/web/api.py` | `GET /api/videos/{id}/video-url` → `{url, expires_in}`: presigned GET for the original video, owner/rater/admin scoped through `_require_video_access`, 404 when no original was uploaded. Without it the rating view had nothing to play — a rater never had the file in their browser, and `VideoPlayer` only played from the session's blob URL. |
| `backend/tests/test_dataset_a.py` | `test_playback_url_for_owner_rater_admin_and_404_otherwise` (108 → 109). |
| `backend/API_DATASET_A.md` | The endpoint, under *New endpoints*. |

**Frontend — new**

| File | What |
|---|---|
| `api/client.js` | `getMyProfile` (404 → `null`), `createMyProfile`, `updateMyProfile`, `getMyAssignments`, `startAssignment`, `completeAssignment` (a 422 with `missing` comes back as `{incomplete: true, detail, missing}` — a normal outcome, not an exception), `deleteEnvironment/Outcome`, `adminListVideos`, `adminUpdateVideoMetadata`, `adminMarkReady/CloseVideo/ReopenVideo`, `adminListAssignments`, `adminCreateAssignment`, `adminDeleteAssignment`, `adminListRaters`, `adminUpdateRater`, `downloadAdminExport(kind, {dataset, video_id}, saveBlob)` — authenticated `fetch` → blob → temporary `<a download>`, filename from `Content-Disposition` (the same pattern as `getExportDownloadUrl`; the export routes are not presigned). `getVideoPlaybackUrl` (404 → `null`). |
| `api/client.test.js` | The export helper (token on the request, filename parsing, non-OK → throw and no save), `completeAssignment` 422/200/other, `getMyProfile` 404. |
| `store/useStore.js` | `profile`, `view` (`videos` \| `queue` \| `admin` \| `rating`), `assignments`, `currentAssignment`, `readOnlyStructure`, `videoPlaybackUrl`, and `resetVideoState()` — one `VIDEO_SCOPED_RESET` object shared with `resetForSignOut`, so opening another assignment (or signing out) wipes moves, holds, frame tags, csv, the environment prefill and the read-only flag. **This is the client-side half of "never render another rater's labels"**: the API only ever returns the caller's rows, and the store never carries rows from one video into the next. |
| `utils/csv.js` | `parsePoseCsv` — the parse `VideoUpload`/`VideoPlayer` do inline, shared by the two entry points that load someone else's extraction. |
| `components/LensFields.jsx` | `EnvironmentLens`, `OutcomeLens`, `RadioGroup` extracted from `MoveForm` (same DOM — the 15 MoveForm tests pass unchanged), plus `StrategySummary` (read-only Lens 2). `EnvironmentLens` takes an optional `holds` list and then renders a per-slot dropdown restricted to those holds, next to the existing *Pick on video*. |
| `components/ProfileGate.jsx` (+test) | Display name, years climbing, highest grade, coaching cert (optional), research background → `POST /api/me/profile`. Rendered in place of the app until it succeeds. No tier control: tier is admin-set. |
| `components/AppNav.jsx` | My videos / My queue / Admin (`profile.is_admin` only). Leaving the rating view calls `resetVideoState`. Open-assignment count badge on My queue. |
| `components/MyQueue.jsx` (+test) | `GET /api/me/assignments` → table (filename, moves, cohort, status, assigned date), *Rate* / *Review*. Re-fetched on every mount. |
| `components/RatingView.jsx` (+test) | Loads video, holds, canonical moves, playback URL, pose CSV (for suggestions), and this rater's environment/outcome presence per move; sets `readOnlyStructure`; calls `POST …/start` on open when status is `assigned`. Side column: `MovesList readOnly` (with ✓/○ per lens) or `RaterMoveForm`. *Tag Frames* → the existing `TaggingMode`. **Complete** → `POST /api/assignments/{id}/complete`; 422 renders `missing` inline as "Move N: missing Environment and Outcome" with each entry clickable to open that move; 200 sets status `done`, updates the queue entry, hides Complete, locks the form and tags. |
| `components/RaterMoveForm.jsx` | The rater's three-lens panel: `StrategySummary` (approach, size, tags, form quality, effort, prepper confidence, notes — read-only), `EnvironmentLens` and `OutcomeLens` editable. Loads with `GET /moves/{id}/environment|outcome` (the caller's own), saves with `POST` first time / `PUT` after; a `409` on POST (reload mid-save) falls back to GET+PUT. Hold slots: *Pick on video* (through `holdPickSlot` + `HoldOverlay` pick mode) or the dropdown, both limited to the video's holds. First-open auto-suggest from the pose data, marked *suggested*, as in `MoveForm`. 403 → "This rating is locked". |
| `components/AdminView.jsx` (+test) | `GET /api/admin/videos` table: filename, owner (resolved to a display name through the rater roster), dataset, prep_status pill, assignment count (+done). Row actions: *Open* (loads the video into the Define/prep flow), *Mark ready* (draft), *Close* (ready), *Reopen* (ready/closed), *Assign rater* (expands: rater picker from `GET /api/admin/raters` minus already-assigned, cohort select `validated`/`overlap`, assignment list with remove). 409 → "already assigned". Exports panel: dataset select (A/B/all) + *Export long CSV* / *Export full CSV*. Raters panel: tier select + validation note → `PUT /api/admin/raters/{user_id}`. |
| `components/VideoMetadataPanel.jsx` (+test) | Above the labeling area in the owner flow: filename · dataset · prep_status pill; *Video details* toggles the metadata form (route_grade, wall_type, climber_experience, climber_height_cm, climber_ape_index_cm, camera_angle, gym, notes) → `PUT /api/admin/videos/{id}/metadata` for admins, read-only values otherwise; *Mark ready to rate* / *Reopen for editing* for admins. Sets `readOnlyStructure` when the video is `ready`/`closed` **and** the viewer is not an admin, with a banner saying holds and moves are locked. |
| `App.test.jsx` | Non-admin/no-assignment lands on My videos with no Admin tab; profile 404 → gate → app; ≥1 assignment → My queue; admin tab → admin view. |
| `components/HoldOverlay.test.jsx` | readOnly: click does not delete, drag does not draw, pick still works; default mode still deletes. |

**Frontend — changed**

| File | Change |
|---|---|
| `App.jsx` | Boot: session → config → profile (`404` → `ProfileGate`, error → sign-out screen) → assignments → landing (`queue` if any, else `videos`). Header gains `AppNav` and shows the display name (+ *validated* badge). View switch: `rating` → `RatingView`, `queue` → `MyQueue`, `admin` (admin only) → `AdminView`, else the unchanged Define/Tagging pair. `DefineMode` renders `VideoMetadataPanel` and, when `readOnlyStructure`, hides the define banner, never opens `MoveForm`, and renders `MovesList readOnly`. Admin *Open* fetches holds, playback URL and pose CSV so the reopened video is labelable. Session lost via `onAuthChange` resets the gate state so the next sign-in re-runs it. |
| `components/MoveForm.jsx` | Uses `EnvironmentLens`/`OutcomeLens`/`RadioGroup`; Strategy section and all state/validation untouched. |
| `components/HoldOverlay.jsx` | `readOnly` prop: no drag-to-create, no click-to-delete, pick unchanged; titles/aria say "Hold N" instead of "Delete hold N". |
| `components/VideoPlayer.jsx` | Reads `readOnlyStructure`, `videoPlaybackUrl`, `currentMove`. Read-only: `[`/`]` ignored, Mark Start/End/Create Move replaced by a "Select a move" strip, hold hint reworded, overlay read-only, the selected canonical move's range shown on the timeline. `src` falls back to the playback URL. |
| `components/MovesList.jsx` | `readOnly`, `onSelect`, `labelStatus` props; heading "Canonical Moves", numbered cards with *Rate* / *Edit rating*, ✓/○ per lens, no ✕. Default props render exactly the old list. Dropped two unused imports (pre-existing lint error). |
| `components/TaggingMode.jsx` | In rating: *← Back to moves* instead of *Save & Next Move* + *Done*; tag buttons and delete disabled with a note once the assignment is `done` or the video `closed`. `src` falls back to the playback URL. |
| `App.css` | Nav, pills, tables, rating strip, missing list, strategy summary, hold select, metadata panel, admin panels. Appended; nothing existing changed. |

### 13.2 Defaults taken (not asked)

- **Opening an assignment calls `/start`** (idempotent), so the queue shows *In progress* as soon as a rater has looked at a video, not only after the first label write.
- **Landing rule** is "≥ 1 assignment of any status → My queue". A rater whose assignments are all `done` still lands on the queue; My videos is one click away.
- **Metadata form is admin-only** because the endpoint is (`PUT /api/admin/videos/{id}/metadata`). A non-admin owner sees the values read-only with a note that an admin fills them. See discrepancy (a) below.
- **Admins are never structure-locked**: an admin who owns a `ready` video keeps hold/move editing (the API allows it; `access_role` comes back `owner` on the fast path, so the flag keys on `profile.is_admin`, not `access_role`).
- Rater form reuses MoveForm's rule that `foot` is optional and the three hand slots need a hold **type** (a hold id is optional); `no_hands` on the canonical move hides the hand slots.
- Owner display in the admin table resolves `owner_user_id` through the rater roster; a user with no profile shows the first 8 characters of the uuid.
- Exports default to `dataset=A` (the API default for long) with a select for B/all; `video_id` narrowing is supported by the client helper but has no UI.
- `label` status per move in the rating view costs 2 GETs per move on open; fine at prep sizes (≤ ~15 moves), noted in case videos get long.

### 13.3 Contract discrepancies found

(a) **Prep metadata is admin-only.** The runbook's frontend item 5 puts the metadata form in "the existing upload → holds → define flow", but the only write endpoint is `PUT /api/admin/videos/{id}/metadata` (403 for non-admins). Since the runbook's design also says the prep pass is an admin task, the UI follows the API: admins edit, owners read. If Dataset B uploaders should fill their own metadata later, the backend needs an owner-scoped `PUT /api/videos/{id}/metadata`.

(b) **No playback URL existed.** Not in the contract at all; added as `GET /api/videos/{id}/video-url` (see 13.1). `VideoResponse.r2_video_key` is exposed but is useless client-side without a signature.

(c) `access_role` is `owner`, not `admin`, for an admin on their own draft video (documented in `_require_video_access`); harmless, but the UI must not use it to decide admin powers — it uses `profile.is_admin`.

(d) `GET /api/videos` remains owner-only, so there is still no "My videos" *list* — My videos is the upload screen as before, and an existing video is reopened from the Admin table (*Open*). A non-admin cannot reopen their own earlier upload; that was already true.

### 13.4 Verification

- `cd data_collection/frontend && npx vitest run` — **103 passed** (was 67; 36 new across `App`, `ProfileGate`, `MyQueue`, `RatingView`, `AdminView`, `VideoMetadataPanel`, `HoldOverlay`, `api/client`).
- `npm run build` — succeeds (CSS 45.6 kB, JS 462.6 kB gzip 147 kB, unchanged JS size).
- `npx eslint src/` — every new and changed file clean. The 4 errors + 1 warning in `SkeletonOverlay.jsx` predate this work and were left alone.
- `cd data_collection/backend && TEST_DATABASE_URL=… python -m pytest tests/ -q` — **109 passed** (was 108).

### 13.5 What could not be verified, and why

- **No browser run against the deployed API.** No dev server or deployed backend was reachable from this session; everything above is jsdom with the API client mocked, plus the real backend under pytest. In particular: real `<video>` playback from the presigned R2 URL (`r2-cors.json` already allows `GET`/`HEAD` from `*`, so this should work; if the player is blank, that is the first thing to check), the blob download in a real browser, and layout of the new tables on a phone.
- **The non-admin locked banner is only reachable in one way today.** It keys on `currentVideo.prep_status`, and a non-admin can only have a video in the store by uploading it in this session (there is no My videos *list*, see 13.3 d). If an admin marks that video ready while the uploader still has it open, the store copy is stale: the banner does not appear, but every mutation the API refuses surfaces its 403 detail inline ("Video N is ready: holds and moves are locked") through the existing `holdError` / form error paths. The banner path itself is covered by `VideoMetadataPanel.test.jsx`.
- **No real 3-rater session.** Cross-rater invisibility is enforced and tested server-side (`test_raters_never_see_each_others_labels`); the client-side guarantee is `resetVideoState` on every open/exit and the fact that nothing reads label rows except by the caller's own GETs. Not exercised with three real accounts.
- **Long export → `scripts/irr_alpha.py`** round trip through the browser download was not run; the shape is tested in `test_long_export_shape`.
- `VideoPlayer` and `TaggingMode` are stubbed in the `RatingView`/`App` tests (jsdom has no canvas/video); their read-only behaviour is covered through the store flag and `HoldOverlay.test.jsx`, not a rendered player.

### 13.6 Manual QA for Jolie

Prerequisites: migration pushed (`supabase migration list` clean), backend deployed from this branch, `is_admin = true` set on your `rater_profiles` row in SQL after you have created your profile once through the app.

1. **Profile gate.** Sign in with a fresh account → the profile form appears instead of the app; save → app. Sign out/in → no gate the second time. `GET /api/me/profile` in the network tab is 404 then 200.
2. **Prep (admin).** My videos → upload a short clip → holds detected/drawn → define 2–3 moves → *Video details* → fill route grade, wall type, height → *Save details* → *Mark ready to rate*. The pill turns `ready`; you (admin) can still add/delete holds. Reload; Admin → *Open* on that video: the video plays (if it doesn't, see the CORS note in 13.5), holds and moves are there.
3. **Assign.** Admin → the video row → *Assign rater* → pick two test accounts (each must have saved a profile first, or the API 404s) with cohort `validated`; a third with `overlap`. Assigning the same rater twice → "already assigned".
4. **Rate (rater A).** Sign in as A → lands on My queue → *Rate*. Check: no *Mark Start/End*, no *Create Move*, no ✕ on moves or holds, dragging on the video draws nothing, `[`/`]` do nothing. Open move 1: Strategy is a read-only summary; pick holds via *Pick on video* and via the dropdown (only the prepped holds appear); *Save Rating*; the card shows ✓ Environment ✓ Outcome. *Tag Frames* → add a tag → *← Back to moves*. Press *Complete* with move 2 unrated → the red box lists "Move 2: missing Environment and Outcome"; click it → the form opens. Rate it → *Complete* → status *Done*, form/tag controls disabled, queue shows *Done*.
5. **Independence (rater B).** Sign in as B on the same video: every move shows ○ ○, no tags — nothing of A's. Rate differently. Sign back in as A: A's labels are still A's.
6. **Owner lock (non-admin).** As a non-admin, upload a video and keep the tab open; as admin in another browser, *Mark ready* on it. Back in the uploader's tab, drag a new hold: the request is refused and the message "Video N is ready: holds and moves are locked" shows under the player (the store copy is stale, see 13.5). The banner + hidden controls version of this needs a locked video loaded fresh, which only an admin can do today.
7. **Export.** Admin → *Export long CSV* (dataset A) → a file `dynalytix_long.csv` downloads; `python scripts/irr_alpha.py dynalytix_long.csv` runs on it. *Export full CSV* with dataset `all` → `dynalytix_full.csv`.
8. **Raters panel.** Set A to `validated` with a note → *Save*; A's header badge reads *validated* after their next sign-in.
9. **Close.** Admin → *Close* the video → rater B (not done) sees "This video is closed to rating" and cannot save. *Reopen* → `draft` again; the owner can edit structure.

### 13.7 Profile: bio replaces coaching_cert (branch `feat/rater-bio`)

`ProfileGate.jsx` swaps the *Coaching certification* input for an optional
multi-line *Bio (optional)* textarea (`maxLength` 1000, placeholder "A sentence
or two about your climbing / coaching background"), sent as `bio` (trimmed,
`null` when blank). `AdminView.jsx` raters panel shows the bio as an
ellipsised sub-line under the background cell (full text on hover) instead of
the cert. Tests updated (`ProfileGate.test.jsx`, new AdminView bio case);
vitest 129/129, build green. Needs backend §10.8 and its migration
`20260922150000_rater_bio.sql` pushed.

## 14. Server-side pose extraction (runbook-w1-worker)

Branch `feat/server-pose-worker`, together with backend REPORT §11 and
`data_collection/worker/`. **One feature unit — merge all three together, and
only after the Modal app is deployed and `MODAL_ENDPOINT_URL` /
`MODAL_WEBHOOK_SECRET` are set on Railway and the `pose_status` migration is
pushed.** Backend §11.6 has the ordered steps.

### 14.1 What changed for the labeler

Pick a file and the player is there within a second, playing the local file
(`playsInline`, so iPhone Safari does not go full-screen). The upload runs
behind the UI with a percentage in a header chip; when it lands, the backend
hands the clip to the worker and the chip walks through "Pose extraction
queued" → "Extracting pose on the server…" → "Pose ready". At that moment
the skeleton overlay switches on, hold suggestions start working, and
"Finish & Export" (and Tagging mode's "Done") become enabled. Until then
they are disabled with a tooltip saying why. If the worker fails, the chip
turns red with the server's reason and a Retry button. Nothing about the
browser matters any more: no MediaPipe download, no HEVC decode question, no
"keep this tab open", no throttling when the tab is backgrounded.

### 14.2 Per-file changes

| File | Change |
|---|---|
| `src/services/PoseExtractor.js` | **Deleted** (browser MediaPipe, fps detection loop, monotonic detect clock, DecodeUnsupported/FrameCallbackUnsupported paths, visibilitychange pausing). |
| `scripts/test_pose_extractor.mjs` | **Deleted** (tests of the detect clock). |
| `package.json` / `package-lock.json` | `@mediapipe/tasks-vision` removed (`npm uninstall`); `test:extractor` script removed; `test` now runs `test:math` + `test:ui`. Bundle 293 kB (was larger with the WASM loader). `onnxruntime-web` stays: it belongs to the (off by default) hold detector. |
| `src/services/poseMath.js` | `detectFps` and `KNOWN_FPS` removed (nothing measures fps in the browser now). Everything else stays: this file is the **CSV contract** the worker's `angles.py` reproduces byte for byte, and `normalizeLandmark(s)` is still used for hold matching. Header comment says so. |
| `scripts/test_pose_math.mjs` | The six `detectFps` tests removed; the frame-index tests against the recorded `frame_times_*.json` fixtures and the golden-file test stay (55 pass). |
| `src/utils/csv.js` | **New.** The one `parseCsv` (was duplicated in VideoUpload and VideoPlayer). |
| `src/utils/videoMeta.js` | **New.** `readVideoMetadata(objectUrl)` (duration, videoWidth/Height from a detached `<video>`), `PROVISIONAL_FPS = 30`, `provisionalRegisterPayload(file, meta)`. |
| `src/api/client.js` | `registerVideo` payload has no `csv_data`. **New** `putVideoToR2WithProgress` (XHR; fetch has no upload progress), `uploadOriginalVideo(videoId, file, {onProgress, signal})` returns the confirm body (which carries `pose_status`), `getPoseStatus`, `retryPose`, `getPoseCsvUrl`, `fetchPoseCsvText`. `getVideoCSV`/`getVideoCsvText` (the 307 dance against `/csv`) removed. |
| `src/store/useStore.js` | `csvString` removed. **New** `patchCurrentVideo(fields)`, `upload {state, fraction, error}` + `setUpload`, `poseStatus` (last `/status` payload) + `setPoseStatus`; both reset on sign-out. |
| `src/hooks/usePoseStatus.js` | **New.** The poll (5 s, stops on done/failed, survives transient errors). On done: patches `fps/total_frames/duration_ms/width/height` onto `currentVideo`, rescales saved moves + the `[ ]` selection + the play head if fps changed (moves via `PUT /api/moves/{id}` with frames recomputed from their timestamps), then fetches the CSV from its presigned URL into `csvData`. `retry()` calls `/retry-pose` and restarts the loop. Exports `rescaleFrame`, `movesToRescale`, `POLL_INTERVAL_MS`. |
| `src/components/PoseStatusChip.jsx` | **New.** Header chip described above; owns the hook. |
| `src/components/VideoUpload.jsx` | Rewritten: read metadata → register → hand over the player → `runBackgroundJobs` (upload with progress → confirm → seed `poseStatus` from the confirm body → hold detection if enabled). Upload/register errors are shown; the "processed locally / best on a computer" copy is gone. |
| `src/components/VideoPlayer.jsx` | No CSV fetch of its own; reads `csvData` + `poseStatus` from the store. `SkeletonOverlay` renders only when `poseStatus.pose_status === 'done'` and rows exist; the skeleton toggle is disabled with "(waiting for pose)" until then. `<video playsInline>`. |
| `src/components/ProgressStrip.jsx` | `canExport` / `exportBlockedReason` props → disabled + `title`. |
| `src/App.jsx` | Renders `PoseStatusChip` in the header; computes `poseDone` and the blocked reason for `ProgressStrip`. |
| `src/components/HoldSuggestions.jsx` | New reasons `waiting-for-pose` and `pose-failed`, shown until the CSV is in. |
| `src/components/TaggingMode.jsx` / `DoneButton.jsx` | Done disabled with a tooltip until pose is done; `DoneButton` gets a separate `busy` prop; the stale `exportVideo(id, true)` second argument dropped. |
| `src/App.css` | `.pose-chip*` styles. |
| Tests | **New** `utils/csv.test.js`, `utils/videoMeta.test.js`, `hooks/usePoseStatus.test.jsx` (cadence with fake timers, stop on done/failed, retry restarts, fps rescale of moves/selection/play head, no rescale when fps unchanged, transient failure), `components/PoseStatusChip.test.jsx`, `components/ProgressStrip.test.jsx`, `components/VideoUpload.test.jsx` (player before upload completes, exact register payload without `csv_data`, progress into the store, confirm's failed enqueue surfaces, upload failure keeps the player, register failure stays on the picker, non-video rejected). |

### 14.3 Defaults taken

- **Provisional fps = 30 at register.** The browser cannot read a frame
  rate; the worker measures it. If it comes back different (a 60 fps clip),
  `usePoseStatus` rescales already-saved moves through their `timestamp_ms`
  (authoritative), and the current selection/play head through time. Frame
  tags are not rescaled: they are made in Tagging mode, normally well after
  the worker finished, and there is no update route for them. The chip makes
  the waiting state obvious; the recommended capture setting stays 30 fps.
- **Polling, not push**: 5 s interval per the runbook, one request while
  pending/processing, none after done/failed.
- **The chip shows the upload first**, then the worker: a labeler cannot see
  "queued" while the file is still leaving the phone.
- **Export gating is client-side and server-side**: the button is disabled
  with a tooltip, and the backend would 409 anyway.
- **Skeleton renders only when done** (the runbook's wording), not on a
  partial CSV — there is no partial CSV.
- **No cancel button for the upload.** The old cancel stopped a minutes-long
  browser extraction; the upload is a background job that finishes on its
  own. `putVideoToR2WithProgress` accepts an `AbortSignal` if one is wanted.
- Kept `onnxruntime-web` and the hold detector untouched (off by default).

### 14.3a Coexistence with Dataset A (§13) — rebased onto `e5cf348`

- **The header chip is view-independent.** `PoseStatusChip` sits next to
  the Dataset A nav/profile badge and mounts `usePoseStatus` for whichever
  view has a `currentVideo`: My videos (Define/Tagging), the **rating view**
  and a video an admin opened for prep. The CSV therefore has one loader.
  `RatingView` and `App.handleOpenVideoForPrep` no longer fetch the CSV
  themselves (`getVideoCsvText` and the 307 dance are gone); they load holds,
  moves and the playback URL and let the hook bring the pose rows in when
  `/status` says done. A rater on a video whose worker has not finished sees
  the chip, no skeleton, and "waiting for pose" in the suggestions — the
  backend lets raters read `/status` and `/pose-csv-url`, and 403s them on
  retry (the chip's Retry button will surface that error; retrying is the
  prepper's or admin's job).
- `utils/csv.js` exports Dataset A's `parsePoseCsv` and keeps `parseCsv` as
  an alias (same implementation).
- `VideoPlayer` keeps Dataset A's `videoBlobUrl || videoPlaybackUrl` source
  and gains `playsInline`; the skeleton gate is unchanged.
- `TaggingMode` keeps the rating-mode header (no Done button for raters) and
  gates the Dataset B Done button on pose done.
- `useStore`: `VIDEO_SCOPED_RESET` (Dataset A's per-video reset) now also
  clears `upload` and `poseStatus`; `csvString` is gone.
- `RatingView.test.jsx` / `App.test.jsx` mock factories swap
  `getVideoCsvText` for the pose-status client functions.

### 14.4 Verification

```
$ npx vitest run             Test Files 16 passed · Tests 128 passed   (main at e5cf348: 104)
$ node --test scripts/test_pose_math.mjs      # pass 55  # fail 0
$ npm run build              ✓ built in 1.83s   dist/assets/index-*.js 293.51 kB
$ npx eslint src scripts     3 errors + 1 warning, all pre-existing on main (SkeletonOverlay hoisting); none in changed files
```

### 14.5 What could NOT be verified, and why

- **A real browser run against the deployed stack** (pick → label at once →
  chip → skeleton appears → export): needs the Modal app deployed and the
  Railway variables set (backend §11.5/§11.6). Every piece is unit-tested
  with the API mocked; the integration is the manual step.
- **iPhone Safari specifics**: `playsInline` on the local object URL, XHR
  upload progress events for a 300 MB HEVC clip over cellular, and Safari's
  behaviour when the tab is backgrounded mid-upload (the upload may pause;
  the chip will show it stalled, and the labeler can keep labeling — the
  video is not needed for labels, only for the worker). This is the W3
  mobile runbook's territory; nothing here should make it harder.
- The `accept` attribute now also lists `video/*` so the iOS picker offers
  the camera roll; not tested on a device.

### 14.6 Manual test for Jolie (after the backend/worker steps in §11.6)

1. Open the deployed site, sign in, pick a short iPhone clip. The player
   should appear before you can count to one, playing the local file.
2. Header chip: "Uploading video… NN%" climbing, then "Pose extraction
   queued", then "Extracting pose on the server…" (this is the worker's
   `processing`), then green "Pose ready". Press S to toggle the skeleton
   once it is ready; it should be disabled with "(waiting for pose)" before.
3. Mark a move with [ and ] *before* the chip is green and save it. When the
   chip turns green the move's frame numbers should still land on the same
   moment of video (they are rescaled if the clip was not 30 fps).
4. "Finish & Export" is disabled (hover for the reason) until green, then
   exports and offers the download.
5. Failure path: temporarily blank `MODAL_ENDPOINT_URL` on Railway, upload a
   clip — the chip should go red with "worker not configured…" and a Retry
   button; restore the variable, press Retry, watch it go green.
