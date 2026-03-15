# AccountManager — Comprehensive Improvement Plan

_Last updated: 2026-03-15_

This document captures the full improvement roadmap, key design decisions, and execution status. Keep it updated as phases are completed.

---

## Key Design Decisions (User-Confirmed)

- **Match storage:** Keep raw JSON blobs (details + timeline) AND extract structured fields into columns. "Save more than too little."
- **Rate limit testing:** Stress-test Blizzard API locally. Riot rate limits documented via web research only (Personal key too constrained).
- **Modularization:** Deferred indefinitely (YAGNI). Only modularize when a third game is added.
- **Async vs threading:** Stay with threading. Bottleneck is API rate limits, not I/O.
- **Alembic:** All schema changes go through Alembic migrations from now on. Never delete the DB to apply schema changes.
- **Session pattern:** `data_service.py` creates/closes its own sessions. `sync_engine.py` and `data_updater.py` use `get_session()` context manager or manage sessions manually with explicit `db.commit()` / `db.rollback()`. Do not mix patterns.

---

## Execution Status

| Order | Step | What | Status |
|-------|------|------|--------|
| 1 | 0A | Fix broken add-account modal (LoL + SC2) | ✅ Done |
| 2 | 0B | Alembic migrations setup | ✅ Done |
| 3 | 0C | Add temporal columns (created_at/updated_at) | ✅ Done |
| 4 | 0D | Unique constraints + true upserts (LoLRank, SC2Rank, LoLMastery) | ✅ Done |
| 5 | 1A | Session management (get_session context manager, WAL mode) | ✅ Done |
| 6 | 1B | Rank history snapshot tables (LoLRankSnapshot, SC2RankSnapshot) | ✅ Done |
| 7 | 2A | Fix RiotClient retry (iterative, max 5, exponential backoff); remove sleeps | ✅ Done |
| 8 | 2B | Fix BlizzardClient (_request centralized, retry, token refresh) | ✅ Done |
| 9 | 2C | Blizzard rate limit stress test + docs update | ✅ Done |
| 10 | 2D | Parallel account sync (ThreadPoolExecutor) | ✅ Done |
| 11 | 3A | Extract structured match data from JSON blobs | ✅ Done |
| 12 | 3B | New Riot endpoints (Spectator-V5, match type filter) | 🔄 Partial |
| 13 | 3C | New Blizzard endpoints (match history, GM leaderboard) | ✅ Done |
| 14 | 3D | Computed/derived data + DTO extensions | 🔄 Partial |
| 15 | 4A | Display more data in LoL UI | ✅ Done |
| 16 | 4D | Account deletion from UI | ✅ Done |
| 17 | — | Post-sync polish (progress logging, KeyError fix) | ✅ Done |
| 18 | 4B | Streamlit Analytics Dashboard | ⬜ Pending |
| 19 | 4C | SC2 Replay Parsing (sc2reader) | ⬜ Pending |
| 20 | 4D | Remaining quick wins (export, grouping, auto-refresh, search) | ⬜ Pending |

---

## Phase 0: Critical Bugfix + Foundations ✅

### 0A. Fix Broken Add-Account Modal
**LoL path (`ui_utils.py`):**
- Was calling `app.db.upsert_account()` (pre-ORM remnant, didn't exist)
- Fixed: opens `SessionLocal()`, calls `crud.create_account()` + `crud.upsert_lol_profile()`, commits, closes

**SC2 path (`ui_utils.py`):**
- Was referencing `data_entries['alias']` (field removed from UI)
- Was using `SC2_DB_PATH` (undefined legacy variable)
- Was writing to `app.sc2_data` (legacy JSON approach)
- Fixed: uses composite ID `{reg}-{realm}-{prof_id}`, calls `crud.create_account()` + `crud.upsert_sc2_profile()`, commits

### 0B. Alembic Migrations Setup
- Added `alembic` dependency via `poetry add alembic`
- Initialized with `alembic init alembic`
- Configured `alembic/env.py`: imports `src.data.database.Base`, sets DB URL from `src.config.ORM_DB_PATH`, enables `render_as_batch=True` (required for SQLite ALTER TABLE)
- Generated baseline migration covering all Phase 0C/0D/1B schema changes

### 0C. Temporal Columns
Added `created_at` and `updated_at` (unix epoch integers) to:
- `LoLProfile`, `LoLRank`, `LoLMatch`, `LoLMastery`
- `SC2Profile`, `SC2Rank`, `SC2RawData`

### 0D. Unique Constraints + True Upserts
Added `UniqueConstraint` to:
- `LoLRank`: `(profile_id, queue_type)` → `uq_lol_rank_profile_queue`
- `SC2Rank`: `(profile_id, season, race, queue_type)` → `uq_sc2_rank_profile_season_race_queue`
- `LoLMastery`: `(profile_id, champion_id)` → `uq_lol_mastery_profile_champion`

Rewrote CRUD functions to use `INSERT ... ON CONFLICT DO UPDATE` (true upserts) instead of delete+insert.

---

## Phase 1: Data Layer Hardening ✅

### 1A. Session Management
- Added `get_session()` context manager to `database.py` (auto commit/rollback/close)
- Enabled WAL mode via SQLAlchemy `connect` event (`PRAGMA journal_mode=WAL`)

### 1B. Rank History Snapshot Tables
New tables: `LoLRankSnapshot`, `SC2RankSnapshot`

Snapshot is recorded **only when rank data changes** (or first time seen). This is done inside `upsert_lol_ranks()` and `upsert_sc2_ranks()` — compares incoming vs current before inserting snapshot.

Added query functions: `get_lol_rank_snapshots()`, `get_sc2_rank_snapshots()`

---

## Phase 2: API Layer & Efficiency

### 2A. RiotClient Fixes ✅
- Replaced recursive `_request()` with iterative loop (max 5 retries, exponential backoff)
- Reduced key buffer from 5 to 2 requests
- Added `timeout=10` to all requests
- Removed `time.sleep(0.5)` from deep crawl loop
- Removed `time.sleep(0.05)` x2 from `_download_batch()`
- Batch match commits: one `db.commit()` per batch, not per match
- `game_duration` now populated in `_download_batch()`

### 2B. BlizzardClient Fixes ✅
- Added centralized `_request()` with retry (max 3) + exponential backoff
- Auto token refresh on 401 responses
- Proper error logging with status codes
- `timeout=15` on all requests
- Added `get_match_history()` endpoint (Phase 3C partial)
- Added `get_grandmaster_ladder()` endpoint (Phase 3C partial)
- Removed silent `{}` return on all errors — now logs the status code

### 2C. Blizzard Rate Limit Stress Test ✅
- `tests/test_blizzard_rate_limits.py`: loads profile from DB (falls back to env vars), runs endpoint showcase + sustained 75-request sequential test + 300-request concurrent burst
- `docs/sc2_api_reference.md` updated with "Rate Limit Findings" section
- **Findings:** No rate headers returned; burst buffer very generous (no 429s at 300 concurrent); recommended 3 workers for parallel SC2 sync

### 2D. Parallel Account Sync ✅
- `ThreadPoolExecutor(max_workers=2)` in `sync_engine.py`
- Each worker gets dedicated `RiotClient` with its own API key
- Each worker opens its own `SessionLocal()` DB session
- Accounts distributed round-robin across workers
- Thread-safe progress tracking via `_progress_lock`

---

## Phase 3: Maximize Data Gain

### 3A. Extract Structured Match Data ✅
All columns added to `LoLMatchParticipant`: `champion_id`, `kills`, `deaths`, `assists`, `win`, `role`, `lane`, `gold_earned`, `total_damage_dealt`, `cs`, `vision_score`, `items` (JSON array).

Extraction happens in `crud.add_lol_match()` — parses each participant from raw JSON and inserts structured rows. CS computed as `totalMinionsKilled + neutralMinionsKilled`.

### 3B. New Riot Endpoints 🔄
- Spectator-V5: ✅ `get_active_game()` in `api_clients.py`, `is_in_game` + `current_game_start` columns on `LoLProfile`, called every sync, displayed as 🔴 LIVE badge in UI
- Match-V5 `type=ranked` filter: ⬜ `get_match_ids()` has `queue` param but no `type` param — currently downloads all match types

### 3C. New Blizzard Endpoints ✅
- `get_match_history()`: Added to client ✅, fetched during sync ✅ (stored as raw JSON in `SC2RawData`)
- `get_grandmaster_ladder()`: Added to client ✅, called during sync ✅ (sets GM badge on matching profiles)

### 3D. Computed/Derived Data 🔄
- ✅ `calculate_decay_bank()` — fixed, now simulates 30-day window and returns banked days (int)
- ✅ Rank delta (`lp_delta`) — `_compute_lp_delta()` in `data_service.py` compares newest vs oldest snapshot
- ✅ `games_this_week` — counts matches in last 7 days, shown in UI
- ✅ `last_played` — epoch ms of most recent match, shown as "Xd ago" in UI
- ✅ `is_in_game` — live badge from Spectator-V5
- ⬜ Win rate per champion (from structured participant data)
- ⬜ `games_today` count
- ⬜ LP gain/loss trend (multi-snapshot, not just delta)

---

## Phase 4: UI & Advanced Features 🔄

### 4A. Display More Data in Dashboard 🔄
**LoL (all done):** summoner level, win/loss + WR%, last played ("Xd ago"), LP delta (colored +/-), in-game 🔴 LIVE badge, games this week
- ⬜ Top masteries (data exists in DTO but not rendered in UI)
- ⬜ SC2: match history count, GM status badge, career totals

### 4B. Streamlit Analytics Dashboard
- LP over time, SC2 MMR over time, win rate by champion
- `streamlit_app.py` at project root, "Open Analytics" button in main app

### 4C. SC2 Replay Parsing
- Scan `~/Documents/StarCraft II/Accounts/{folder_id}/` for `.SC2Replay`
- `sc2reader` already a dependency but unused

### 4D. Quick Wins
- ✅ Account deletion from UI (delete button with 🗑 icon, confirmation modal, cascade delete in `crud.delete_account()`)
- ✅ Sync progress logging (`[X/Y]` per match download, per-phase summaries)
- ✅ Fixed `KeyError: 'name_lbl'` crash — `name_lbl` widget now stored in `row_widgets` dict
- ⬜ Data export (CSV/JSON)
- ⬜ Account grouping/tagging
- ⬜ Auto-refresh timer
- ⬜ Search/filter bar

---

## Architecture Notes

### ORM Session Pattern
- `crud.py` functions accept `Session`, call `db.flush()` (not `db.commit()`). Callers manage transaction lifecycle.
- `data_service.py` creates/closes its own sessions.
- `sync_engine.py` / `data_updater.py` manage sessions explicitly with `db.commit()` at logical checkpoints.
- **Do not mix patterns in a single call.**

### Alembic Workflow
```bash
# After any model change:
poetry run alembic revision --autogenerate -m "description_of_change"
poetry run alembic upgrade head

# To check current state:
poetry run alembic current
poetry run alembic history
```

### Rate Limit Notes
- Riot Personal API Key: 100 req / 120s app-wide, ~20 req/s method-level
- Blizzard: 100 req/s, 36,000 req/hr (documented). No rate headers. Very generous burst buffer — 300 concurrent requests caused zero 429s. See `docs/sc2_api_reference.md` for full findings.

### Blizzard API Improvements (2026-03-15)
- **Proactive rate tracking**: `BlizzardClient` now counts its own requests using two `deque` sliding windows (1s and 1hr). Sleeps proactively before hitting limits. No headers needed.
- **Parallel SC2 sync**: `data_updater.py` uses `ThreadPoolExecutor(max_workers=3)`. Season and GM caches pre-populated before workers dispatch. Each worker gets its own `SessionLocal()`.
- **SC2Match table**: New `sc2_matches` ORM model extracts individual matches from raw `match_history` JSON (map, type, decision, date, speed). Populated during sync via `crud.upsert_sc2_matches()`.

### Live Game Tracking (2026-03-15)
- **LoL**: `src/live_tracker.py` — `LiveTracker` class polls Spectator-V5 every 2.5 min for all tracked accounts. Updates `LoLProfile.is_in_game` / `current_game_start` in DB.
- **SC2**: `src/sc2_live.py` — `SC2Live` class detects `SC2_x64.exe` via `psutil`, polls `localhost:6119/game` every 5s. Updates `SC2Profile.is_in_game` / `current_opponent`. Falls back to 30s idle check when SC2 not running.
- **UI toggles**: "Live Tracking" checkbox added to LoL and SC2 header bars. State persisted in `settings.json` under `lol_live_tracking` / `sc2_live_tracking`.
- **New DB columns**: `sc2_profiles.is_in_game`, `current_game_map`, `current_opponent` (Alembic migration: `b9c4d3e2f6a5`).
