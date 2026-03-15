# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

A desktop GUI application (Python + customtkinter) that tracks competitive ranks for **League of Legends** and **StarCraft II** accounts. It fetches data from the Riot Games API and Blizzard Battle.net API, stores it in a local SQLite database via SQLAlchemy ORM, and displays it in a multi-tab UI.

## Running the App

```bash
poetry install
poetry shell
python main.py
```

The `Launch App.bat` file runs this on Windows. No test suite exists currently.

## External Data Directory

All persistent data lives at `E:\AccountManagerData\` (configured in `src/config.py`):
- `app_orm.db` — SQLAlchemy SQLite database
- `settings.json` — UI settings (last update timestamp, etc.)

**If this path doesn't exist on a given machine, update `src/config.py`.**

## Environment Variables (`.env`)

```
RIOT_API_KEY_PRIMARY=
RIOT_API_KEY_FALLBACK=
BLIZZARD_CLIENT_ID=
BLIZZARD_CLIENT_SECRET=
```

## Architecture

### Layer Model

```
main.py (AccountManagerApp / ctk.CTk)
  └─ UI Layer: src/ui/ui_lol.py, src/ui/ui_sc2.py, src/ui/ui_utils.py
       └─ Service Layer: src/services/data_service.py
            └─ CRUD Layer: src/data/crud.py
                 └─ ORM Models: src/data/models.py (SQLAlchemy)
                      └─ Database: src/data/database.py (SQLite via ORM_DB_PATH)
```

### Data Flow

1. **Sync** — `main.py` spawns `SyncEngine` (`src/sync_engine.py`) in a background thread. It uses `RiotClient` (`src/api_clients.py`) to fetch fresh data and writes directly through `src/data/crud.py`.
2. **Read** — UI views call `src/services/data_service.py` (`get_lol_dashboard_data()`, `get_sc2_dashboard_data()`), which returns typed DTOs (`src/schemas.py`) — decoupling the UI from ORM models.
3. **SC2 updates** — handled by `src/data_updater.py` via `BlizzardClient`. SC2 raw JSON blobs (profile summary, ladder summary, match history) are stored directly in the `SC2RawData` ORM table as JSON columns.

### Key Components

| File | Responsibility |
|---|---|
| `main.py` | App entrypoint, `AccountManagerApp` class, threading, view switching |
| `src/sync_engine.py` | LoL data sync orchestration; resolves PUUIDs, fetches ranks/matches |
| `src/api_clients.py` | `RiotClient` (key pooling, rate-limit tracking), `BlizzardClient` |
| `src/data_updater.py` | SC2 sync logic; also contains `calculate_decay_bank()` for LoL |
| `src/data/models.py` | SQLAlchemy ORM models: `Account`, `LoLProfile`, `LoLRank`, `LoLMatch`, `LoLMatchParticipant`, `LoLMastery`, `SC2Profile`, `SC2Rank`, `SC2RawData` |
| `src/data/crud.py` | All DB reads/writes; uses SQLite native `INSERT ... ON CONFLICT` upserts |
| `src/data/database.py` | SQLAlchemy engine + `SessionLocal` factory |
| `src/services/data_service.py` | Reads ORM data and maps it to DTOs for the UI |
| `src/schemas.py` | Pure dataclass DTOs: `LoLProfileDTO`, `RankDTO`, `SC2AccountDTO`, `SC2ProfileDTO`, `SC2RankDTO` |
| `src/config.py` | Path constants (`BASE_DIR`, `DATA_DIR`, `ORM_DB_PATH`) |
| `src/static_data.py` | `StaticDataManager` — fetches LoL patch version from Data Dragon |

### ORM Session Pattern

`crud.py` functions accept a `Session` argument and call `db.flush()` (not `db.commit()`). Callers manage the transaction lifecycle. `data_service.py` creates and closes its own `SessionLocal()` sessions. **Do not mix the two patterns in a single call.**

## Critical API Notes

### Riot: PUUID Resolution

Testing (March 2025) confirmed that **Global PUUID == Platform PUUID** for all tested accounts. The historical distinction between Account-V1 and Summoner-V4 PUUIDs no longer applies. However, PUUIDs can become stale (e.g., after account transfers), causing `400 Bad Request` errors.

Resolution flow:
1. `Account-V1` (Riot ID → PUUID)
2. `Summoner-V4` (PUUID → summoner data) — also validates the PUUID
3. Store the PUUID in `LoLProfile.puuid`

**Self-healing**: If Summoner-V4 fails for a stored PUUID, `SyncEngine._sync_single()` automatically re-resolves from Riot ID via Account-V1 and updates the stored PUUID.

New accounts that haven't been resolved yet have `puuid` prefixed with `"PENDING_"` in the DB.

### Riot: Key Pooling

`RiotClient` tracks two API keys (`KeyState` objects) and rotates between them when one nears exhaustion. The limit is 100 requests per 120-second window (Personal API Key). State is updated from response headers (`X-App-Rate-Limit-Count`).

### Region Routing

LoL API calls require separate routing for platform (e.g., `na1`, `euw1`) and regional (e.g., `americas`, `europe`) base URLs. `SyncEngine._map_region()` derives both from the account's `tag_line`.

## API Reference Docs

Consult these before building new data pipelines — do not guess at endpoint shapes:
- `docs/riot_api_reference.md`
- `docs/sc2_api_reference.md`
- `docs/StarCraft II Local App Data Integration.md`

## Streamlit Sandbox

The project includes `streamlit` as a dependency. Use it to build POC dashboards for complex analytics (e.g., timeline charts, decay bank visualizations) before integrating into the customtkinter UI.

## Git Commit Rules

- **Never mention Claude, AI, or Co-Authored-By in commit messages.** Commits should read as if written by a human developer.