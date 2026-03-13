# Game Account Manager

## Project Overview

This is a desktop UI application designed to manage and track game accounts and their current competitive ranks. It currently supports **League of Legends (LoL)** and **StarCraft II (SC2)**. 

The application provides a graphical interface to view account statistics and updates this data by interfacing with the official developer APIs for both games (Riot Games API and Blizzard Battle.net API).

### Key Technologies
*   **Language:** Python 3.11+
*   **Dependency Management:** Poetry (`pyproject.toml`, `poetry.lock`)
*   **GUI Framework:** `customtkinter` (Modern, customizable Tkinter wrapper)
*   **Data Layer:** `sqlite3` for fast indexing, Sharded JSON for heavy API payloads.
*   **API Requests:** `requests` with robust Rate-Limiting and Key-Pooling.
*   **Environment Management:** `python-dotenv`
*   **Exploration/Sandbox:** `streamlit` (Used for building POC dashboards for League data).

## Architecture & Data Flow

We recently overhauled the data architecture to support massive data-mining (fetching thousands of matches) without freezing the UI or getting IP banned by the API providers.

*   **`src/sync_engine.py` (The Core Engine):** Replaced the old monolithic JSON updaters. It uses a **Two-Phase Time-Based Pagination** system. Phase 1 (Frontier) delta-syncs new matches forward. Phase 2 (Deep Crawl) safely pages backward in time to backfill history without hitting Riot's index decryption bugs.
*   **`src/api_clients.py`:** Contains the API wrappers. The `RiotClient` implements **Key Pooling**, seamlessly rotating between a Primary and Fallback key to bypass the strict 100 requests/2min Personal Key limits.
*   **`src/db_manager.py`:** Manages `app_database.db` (SQLite). This lightweight local DB tracks relationships (Accounts, Ranks, MatchIndex). It prevents having to open thousands of files just to check if we downloaded a match already.
*   **Raw Data Storage:** Heavy API payloads (Match Details, Timelines) are saved as individual files in `E:\AccountManagerData\Raw\`.
*   **`main.py`:** Central state manager. It invokes `SyncEngine()` in a background thread and then pulls the formatted data back via `DBManager.get_full_account_data()` to render the UI.

## Critical API Warnings & Lessons Learned

### Riot Games: Global PUUID vs Platform PUUID
**Never use the PUUID returned by the `Account-V1` endpoint to fetch Ranks or Matches for legacy accounts.** 
The `Account-V1` endpoint returns a *Global PUUID*. For older accounts, passing this Global PUUID into `Match-V5` or `League-V4` will crash Riot's servers and return `400 Bad Request - Exception Decrypting`. 

**The Correct Flow (Two-Step Resolution):**
1. Send Riot ID to `Account-V1` -> Receive Global PUUID.
2. Send Global PUUID to `Summoner-V4` -> Receive **Platform PUUID**.
3. Save the Platform PUUID to the database. Use this for all future queries.

## Setup and Running

### Prerequisites
1.  **Python 3.11** or higher with **Poetry** installed.
2.  **Data Directory:** Ensure the directory `E:\AccountManagerData` is available, or modify `src/config.py` to point to a valid accessible data directory.

### Installation & Execution
```bash
poetry install
poetry shell
python main.py
```

### Environment Variables (`.env`)
```env
RIOT_API_KEY_PRIMARY=your_primary_key_here
RIOT_API_KEY_FALLBACK=your_fallback_key_here
BLIZZARD_CLIENT_ID=your_blizzard_client_id_here
BLIZZARD_CLIENT_SECRET=your_blizzard_client_secret_here
```

## Documentation Reference
Always consult the local, objective API reference documents before building new data pipelines:
*   **League of Legends API Specs:** `docs/riot_api_reference.md`
*   **StarCraft II API Specs:** `docs/sc2_api_reference.md`

## The Streamlit Sandbox
The project includes a `streamlit` dependency. This is intended to be used as a "Sandbox Playground". When designing complex data analytics (like Op.gg style timelines or decay bank calculations based on the massive downloaded JSON payloads), build it in Streamlit first as a Proof of Concept (POC) before trying to integrate it into the rigid `customtkinter` desktop UI.