# 📬 Mailbox protocol

The Dynalytix Mailbox (Notion database, collection `ef1f46c1-2b9e-4499-a24a-4e8faa0042e5`, under the Dynalytix hub) is the transport channel from chat-Claude to Claude Code sessions working on `Jolieabadir/dynalytix`. It is a mailbox, not a docs home: the repo is source of truth the moment an entry is ingested.

## Rules

1. **Chat-Claude only creates entries with Status=New.** Entries are never edited after creation. An amendment to a queued runbook is a new entry (Type: Amendment) naming the original by exact title in References — never an edit to the original.
2. **Ingest happens once per wave.** The first session to start a wave queries every Status=New entry for that wave, in Lane order, and writes each Runbook body to `claude-ops/runbook-w<wave>-<lane>.md` on `main` in one docs-only commit. Amendments and Priority-changes are applied to the referenced runbook file in the same commit. A Note is followed if it is docs-scoped; otherwise stop and ask.
3. **Docs-only commits may go straight to main.** `claude-ops/**` and `*.md` do not trigger meaningful rebuilds. Everything else does — see rule 6.
4. **After ingest, stamp each entry:** Status=Ingested, Ingest Commit = the docs commit hash. If an Amendment replaces an un-ingested entry, mark the old one Superseded.
5. **`claude-ops/runbook-*.md` on main is the only execution queue.** Never execute work directly from a Mailbox entry. If it isn't in a runbook file on main, it doesn't exist.
6. **Main auto-deploys with no CI gate.** Both `adorable-integrity` (backend) and `Data_collection_climbing` (frontend) rebuild on every push to main. Feature work lives on the branch named in the entry's Feature field and merges to main only as one complete, tested unit. Backend and frontend halves of one change never merge separately. A runbook that changes an API contract merges together with the frontend change that consumes it.
7. **One worktree per lane.** `git worktree add ../dynalytix-<lane> -b <feature> <base>`. Parallel sessions never share a checkout.
8. **Schema changes go through `supabase db push` via the session pooler (5432)** before the code that depends on them deploys. `supabase migration list` must show no pending migrations before any merge to main. This is step 0 of every cutover.
9. **Every runbook ends in a `REPORT.md` update** on its branch: per-file changes, defaults taken, what could not be verified and why, manual steps for Jolie. The session's last action is push + print the branch name and head hash.
10. **On execution, stamp the entry:** Status=Executed, Ingest Commit = the merge commit hash on main. Status=Blocked with a one-line reason if the runbook cannot complete; blockers are reported in REPORT.md and to Jolie, never written back into the Mailbox body.
11. **One direction per channel.** Mailbox: chat → sessions only. Questions and blockers go out through REPORT.md and the chat, never into the Mailbox.
12. **A lane reads only its own runbook.** It may read others for context but executes only the steps in the runbook whose Lane matches. Two lanes executing the same step is the most expensive failure available here.

## Lanes

- **Backend** — `data_collection/backend` (FastAPI, Supabase Postgres, R2)
- **Worker** — `data_collection/worker` (Modal pose extraction)
- **Frontend** — `data_collection/frontend` (React/Vite, pointer devices)
- **Mobile** — `data_collection/frontend` touch/PWA work
- **INT — integration** — cross-lane merges and cutovers

## Never

- Touch `fms-demo` or the FMS services (`dynalytix`, `Movement_analysis`).
- Run the backend test suite against the live `DATABASE_URL` — it drops tables. Use `scripts/setup_test_db.sh`.
- Print a secret. Set Railway variables with `--set-from-stdin --skip-deploys`.
- Merge a branch to main to "see if it works."

## Queue state

| File | Wave | Lane | Feature branch | Source entry | Status |
|---|---|---|---|---|---|
| `runbook-w1-backend.md` | W1 | Backend | `feat/dataset-a-assignments` | Runbook — Dataset A: prep/rating split, rater assignments, validated-rater profiles, admin + long-format IRR export | ingested 2026-09-22 |
| `runbook-w1-worker.md` | W1 | Worker | `feat/server-pose-worker` | Runbook — Server-side async pose extraction on Modal (replace browser extractor) | ingested 2026-09-22 |
| `runbook-w3-mobile.md` | W3 (was W2) | Mobile | `feat/mobile-first-labeling` | Runbook — iPhone-first labeling UI (Safari survival, touch frame nav, stepped forms, tap-to-place holds, PWA) | ingested 2026-09-22; gated on both W1 runbooks |

Priority-change applied at ingest (2026-09-17 entry, Lane INT): the iPhone-first UI moved W2 → W3 and now gates on both W1 runbooks. W1 is two parallel lanes; the Dataset A (Backend) runbook has priority if only one session runs.
