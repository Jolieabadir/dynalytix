# API — Dataset A additions (runbook W1 Backend)

Every new or changed endpoint on `data_collection/backend` for the
prep/rating split. Everything below `/api` (except `/api/health`) takes
`Authorization: Bearer <Supabase access token>`. Errors are FastAPI-shaped:
`{"detail": "<message>"}` unless a shape is given below.

`TAXONOMY_VERSION = "3.1.0"`; the API reports `version: "3.1.0"`.

## Roles and scoping

Each video-bound request resolves the caller to one role:

| role | who | reads | writes |
|---|---|---|---|
| `owner` | `videos.user_id` = caller (`owner_user_id` in responses; the uploader on Dataset B, the prepper on Dataset A) | video, holds, moves, csv, own labels | holds and moves **only while `prep_status = 'draft'`**; own environment / outcome / frame_tags always (unless the video is `closed` **and** they are a rater, see below) |
| `rater` | caller has a `video_assignments` row on the video | video, holds, canonical moves, csv, **own** labels only | own environment / outcome / frame_tags while the assignment is `assigned` or `in_progress` and the video is not `closed`. Never holds or moves. |
| `admin` | `rater_profiles.is_admin = true` | everything | everything, including holds/moves on a locked video |

Anyone else gets **404** on the video and everything under it (ids stay
private). **403** means "you can see this but may not change it": rater
writing holds/moves, owner writing holds/moves on a `ready`/`closed` video,
rater label writes on a `closed` video or a `done` assignment, non-admin on
`/api/admin/*`.

Labels (environments, outcomes, frame_tags) are **always** filtered by
`user_id = caller`. Rater A gets 404 on rater B's environment/outcome ids and
an empty list for B's frame tags, on the same move. Only the admin exports
read across raters.

`prep_status`: `draft` → (`POST /api/admin/videos/{id}/ready`) → `ready` →
(`.../close`) → `closed`; `.../reopen` returns to `draft`. `ready` and
`closed` lock holds and moves for non-admins. `closed` also blocks rater
label writes.

## Changed existing endpoints

### `GET /api/config`
Adds `"version": "3.1.0"` (the taxonomy version, stamped on every label row).

### `GET /api/videos/{id}` · `GET /api/videos/{id}/csv` · `GET /api/videos/{id}/holds` · `GET /api/videos/{id}/moves` · `GET /api/moves/{id}`
Now readable by owner, assigned rater or admin (404 otherwise). `holds` and
`moves` return the video's full canonical set regardless of who created
them; `frame_tag_count` on a move is the **caller's** own tag count.

`GET /api/videos` (list) is unchanged: **owner's own videos only**. A
rater's queue is `GET /api/me/assignments`.

`VideoResponse` gains (in addition to the v3 fields):
```json
{
  "owner_user_id": "uuid",          // == videos.user_id
  "dataset": "A" | "B",             // default "B"
  "prep_status": "draft" | "ready" | "closed",
  "route_grade": null, "wall_type": null, "climber_experience": null,
  "climber_height_cm": null, "climber_ape_index_cm": null,
  "camera_angle": null, "gym": null, "notes": null,
  "access_role": "owner" | "rater" | "admin"   // the caller's role on this video
}
```

### `POST /api/holds` · `POST /api/videos/{id}/holds` (bulk) · `PUT /api/holds/{id}` · `DELETE /api/holds/{id}` · `POST /api/moves` · `PUT /api/moves/{id}` · `DELETE /api/moves/{id}`
Owner while `draft`, or admin. **403** for a rater, and for the owner once
`ready`/`closed`. 404 if the caller cannot see the video/hold/move at all.
`DELETE /api/moves/{id}` cascades every rater's labels on that move.

### `POST /api/environments` · `PUT /api/environments/{id}` · `POST /api/outcomes` · `PUT /api/outcomes/{id}` · `POST /api/frame-tags` · `DELETE /api/frame-tags/{id}`
Scoped to the caller's own rows. One environment and one outcome per
(move, caller): a second `POST` for the same move by the same user is
**409**; a different rater's `POST` on the same move is 201. A rater's
first label write on a video moves their assignment `assigned →
in_progress`. **403** when the video is `closed` (raters) or the assignment
is `done`. Hold slot `hold_id`s must belong to the move's video (400
otherwise; 404 if the hold is on a video the caller cannot see).

Responses gain `"taxonomy_version": "3.1.0"` and `"is_gold": false`.
`taxonomy_version` is re-stamped on every PUT. Rows from before the
migration read `"pre-3.1"`.

### `GET /api/moves/{id}/environment` · `GET /api/moves/{id}/outcome` · `GET /api/moves/{id}/frame-tags`
The caller's own row(s) only. 404 / `[]` if they have none, even when
another rater has one.

## New endpoints

### `DELETE /api/environments/{id}` · `DELETE /api/outcomes/{id}`
Delete the caller's own row. 204; 404 if not theirs; 403 under the same
write rules as PUT.

### Rater profile

#### `GET /api/me/profile`
200 `ProfileResponse`, or **404** `{"detail": "No profile for this user yet"}`
→ the app shows the profile gate.

```json
ProfileResponse {
  "user_id": "uuid", "display_name": "str", "tier": "open" | "validated",
  "years_climbing": int | null, "coaching_cert": "str" | null,
  "highest_grade": "str" | null, "research_background": bool,
  "validation_note": "str" | null, "is_admin": bool,
  "created_at": "ISO-8601"
}
```
`is_admin` tells the app whether to show admin views.

#### `POST /api/me/profile` → 201 `ProfileResponse`
```json
{ "display_name": "str (1..120, required)", "years_climbing": int|null (0..100),
  "coaching_cert": "str"|null, "highest_grade": "str"|null,
  "research_background": bool (default false) }
```
**409** if a profile exists. `tier` starts `open`, `is_admin` false.

#### `PUT /api/me/profile` → 200 `ProfileResponse`
Same fields as POST, all optional; `""` clears `coaching_cert` /
`highest_grade`. `tier`, `validation_note`, `is_admin` are ignored if sent.
**404** if no profile yet.

### Rater queue

#### `GET /api/me/assignments` → 200 `MyAssignmentItem[]` (oldest first)
```json
[{ "assignment": AssignmentResponse, "video": VideoResponse /* access_role "rater" */,
   "move_count": int }]
```
```json
AssignmentResponse {
  "id": int, "video_id": int, "rater_user_id": "uuid",
  "cohort": "validated" | "overlap",
  "status": "assigned" | "in_progress" | "done",
  "assigned_at": "ISO-8601", "completed_at": "ISO-8601" | null
}
```

#### `POST /api/assignments/{id}/start` → 200 `AssignmentResponse`
`assigned → in_progress`; idempotent. 404 if not the caller's; **403** if
`done`. Optional: the first label write does this too.

#### `POST /api/assignments/{id}/complete` → 200 `AssignmentResponse` (`status: "done"`)
Validates that **every canonical move** on the video has both an
environment and an outcome by this rater (Strategy = the canonical move,
always present). Idempotent once done (200). On failure:

**422**
```json
{ "detail": "2 of 3 moves are incomplete",
  "missing": [ { "move_id": 12, "move_index": 1, "missing": ["outcome"] },
               { "move_id": 13, "move_index": 2, "missing": ["environment", "outcome"] } ] }
```
`move_index` is the position in `GET /api/videos/{id}/moves` (ordered by
`frame_start`, then id). A video with no moves is also 422 with `missing: []`.
404 if the assignment is not the caller's.

### Admin — all **403** `{"detail": "Admin only"}` for non-admins

#### `GET /api/admin/videos` → 200 `AdminVideoListItem[]` (newest first)
```json
[{ "video": VideoResponse /* access_role "admin" */, "assignment_count": int, "done_count": int }]
```

#### `PUT /api/admin/videos/{id}/metadata` → 200 `VideoResponse`
```json
{ "dataset": "A"|"B", "route_grade": "str", "wall_type": "str", "climber_experience": "str",
  "climber_height_cm": int (>0), "climber_ape_index_cm": int, "camera_angle": "str",
  "gym": "str", "notes": "str" }   // all optional; omitted = unchanged; "" clears a text field
```
400 bad `dataset`; 404 no such video.

#### `POST /api/admin/videos/{id}/ready` → 200 `VideoResponse`
Sets `dataset = "A"` and `prep_status = "ready"`. Locks holds/moves.

#### `POST /api/admin/videos/{id}/close` → 200 `VideoResponse`
`prep_status = "closed"`. Rater label writes stop.

#### `POST /api/admin/videos/{id}/reopen` → 200 `VideoResponse`
`prep_status = "draft"` (dataset unchanged). Owner can edit holds/moves again.

#### `GET /api/admin/assignments?video_id=` → 200 `AssignmentResponse[]`
All assignments, or one video's. Ordered by video then id.

#### `POST /api/admin/assignments` → 201 `AssignmentResponse`
```json
{ "video_id": int, "rater_user_id": "uuid", "cohort": "validated" | "overlap" }
```
400 bad cohort · 404 video or rater profile missing (rater must have
`POST /api/me/profile`d first) · **409** rater already assigned to that video.
Raters per video: 3 by convention; the API does not enforce a cap.

#### `DELETE /api/admin/assignments/{id}` → 204
Label rows the rater already wrote are kept. 404 if missing.

#### `GET /api/admin/raters` → 200 `ProfileResponse[]` (oldest first)

#### `PUT /api/admin/raters/{user_id}` → 200 `ProfileResponse`
```json
{ "tier": "validated"|"open", "validation_note": "str", "is_admin": bool, "display_name": "str" }  // all optional
```
400 bad tier · 404 no profile.

#### `GET /api/admin/export/long?dataset=A|B|all&video_id=` → 200 `text/csv`
`Content-Disposition: attachment; filename="dynalytix_long[_video{id}].csv"`.
Default `dataset=A`; `video_id` overrides dataset. Columns, exactly:

```
video_id,dataset,move_id,move_index,rater_user_id,rater_tier,cohort,lens,field,value,taxonomy_version,is_gold
```
One row per (video, move, rater, lens, field), sorted by video_id,
move_index, rater_user_id, lens, field, value. Lenses and fields:

| lens | field(s) | value |
|---|---|---|
| `strategy` | approach, move_tags, size, form_quality, effort_level, confidence | from the canonical move; emitted once **per rater** (identical values) so per-field tables are rectangular. On Dataset B the "rater" is the move creator. |
| `environment` | wall_angle; per slot `start_left`/`start_right`/`end`/`foot`: `{slot}_hold_id`, `{slot}_hold_type`, `{slot}_hold_quality` | quality list pipe-delimited (`incut\|small`) |
| `outcome` | result, reach_detail, confidence | |
| `frame_tags` | `field` = tag_type, one row per tag | `frame:level:side:locations` e.g. `12:6:left:left_shoulder\|left_elbow` |

Raters on a move = everyone assigned to the video ∪ anyone with a label row
on the move; fallback the move creator. `cohort` is `""` for an unassigned
rater (owner). `rater_tier` is `""` for a user without a profile. `is_gold`
is `true`/`false`. `scripts/irr_alpha.py <csv>` computes alpha from this.

#### `GET /api/admin/export/full?dataset=A|B|all&video_id=` → 200 `text/csv`
Default all datasets. Same shape as the per-video export
(`POST /api/videos/{id}/export`): **one row per pose frame** with the label
columns appended, for every video and every rater on it, with identity
columns in front:

```
video_id,dataset,prep_status,owner_user_id,filename,rater_user_id,rater_tier,cohort,
<pose columns, union across videos>,
move_id,approach,size,move_tags,form_quality,effort_level,move_confidence,wall_angle,
{slot}_hold_id,{slot}_hold_type,{slot}_hold_quality,{slot}_hold_bbox (x4 slots),
result,reach_detail,outcome_confidence,tag_types,tag_levels,tag_locations,tag_sides,tag_notes
```
Frames repeat once per rater. Large; use `dataset`/`video_id` to narrow.

## Not changed

Dataset B self-upload: `POST /api/videos/register`, `.../upload-url`,
`.../confirm-upload`, `POST /api/videos/{id}/export`,
`.../export/download`, `GET /api/exports/mine` — owner-only, as before.
New videos default to `dataset "B"`, `prep_status "draft"`.

## Frontend checklist (from the runbook)

1. On sign-in: `GET /api/me/profile`; 404 → profile gate → `POST`.
2. Nav: `GET /api/me/assignments` for "My queue"; `GET /api/videos` for
   "My videos"; admin views when `profile.is_admin`.
3. Rating view: `GET /api/videos/{id}` (`access_role === "rater"` →
   hide Define mode, holds/moves read-only), `.../holds`, `.../moves`,
   `.../csv`; per move `GET/POST/PUT` environment, outcome, frame-tags;
   hold slots pick from `.../holds`. "Complete" → `POST
   /api/assignments/{id}/complete`; on 422 render `missing`.
4. Admin: `GET /api/admin/videos`, `GET /api/admin/raters`,
   `POST/DELETE /api/admin/assignments`, `PUT .../metadata`, `POST
   .../ready|close|reopen`, export links to `/api/admin/export/long` and
   `/full` (send the bearer token; they are not presigned).
