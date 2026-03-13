# In-Depth Code Review: Game Account Manager

This code review assesses the current architecture, code quality, and efficiency of the Account Manager application. The goal is to evaluate the foundation and identify areas for improvement to ensure long-term maintainability, scalability, and performance.

---

## 1. High-Priority Concerns & Critical Bugs

### 1.1. Incomplete Database Migration & "Add Account" Bug (CRITICAL)
- **The Issue:** The project recently migrated League of Legends (LoL) data from `lol_database.json` to an SQLite database (`app_database.db`) using `SyncEngine` and `DBManager`. However, the UI utility `open_add_modal` in `src/ui/ui_utils.py` still writes new LoL accounts directly to `lol_database.json`.
- **Impact:** If a user adds a new LoL account via the UI, it gets saved to the old JSON file but the main UI loads data from SQLite (`self.db.get_full_account_data()`). The newly added account will **not** appear in the application or be tracked by the `SyncEngine` unless a manual bootstrap is re-run.
- **Action:** Update `open_add_modal` to use `DBManager().upsert_account()` using a `PENDING_...` PUUID as expected by the `SyncEngine` resolution logic, completely removing the dependency on `lol_database.json`.

### 1.2. UI Layer Coupling with Business Logic
- **The Issue:** The `open_add_modal` function handles UI layout, form validation, direct API calls (e.g., `RiotClient().get_live_ranks()`), and direct database writes (`json.dump`).
- **Impact:** Violates the Single Responsibility Principle (SRP) and MVC patterns. It makes the UI hard to test and tightly couples it to external I/O.
- **Action:** Extract the API verification and database saving logic into a dedicated service or controller class. The modal should only gather user input and invoke a callback.

### 1.3. Dead Code (`data_updater.py`)
- **The Issue:** The file `src/data_updater.py` contains `update_lol_data()`, which performs data fetching and decay logic using the old JSON architecture. Since `main.py` explicitly uses `SyncEngine().sync_all()` for LoL, this old function appears to be dead code.
- **Action:** Remove or formally deprecate `update_lol_data()` in `data_updater.py`. Verify if the decay logic needs to be ported over to `SyncEngine` or `DBManager`, as the new DB schema currently does not seem to track the advanced decay bank simulation.

---

## 2. Architecture & Design

### 2.1. Hybrid Storage System
- **Observation:** LoL is using SQLite, while SC2 is still using `sc2_database.json` and updated via `data_updater.py`. 
- **Improvement:** To have a solid basis for the future, SC2 data should be migrated to the SQLite database. A unified data layer simplifies backups, queries, and UI state management.

### 2.2. State Management in UI
- **Observation:** Sorting state is managed by dynamically injecting attributes into the CTk container (`getattr(container, "sort_col")`). 
- **Improvement:** Refactor the UI views (`ui_lol.py`, `ui_sc2.py`) into proper Object-Oriented classes (e.g., `class LoLView(ctk.CTkFrame):`). This encapsulates the state (`self.sort_col`, `self.sort_asc`) naturally without runtime attribute hacking.

### 2.3. SQLite Connection Management
- **Observation:** `DBManager.get_connection()` creates a new connection for every single query (`with self.get_connection() as conn:`). While thread-safe, it introduces massive overhead during deep crawls where thousands of queries are run.
- **Improvement:** Implement connection pooling or share a single connection within the `SyncEngine` execution context, ensuring bulk inserts are batched inside a single transaction.

---

## 3. Code Quality & Efficiency

### 3.1. Blocking API Calls & Threading
- **Observation:** Network calls in `RiotClient` and `BlizzardClient` are strictly synchronous (`requests.get`). In `sync_engine.py`, fetching thousands of match details is done linearly in a loop, with hardcoded sleeps (`time.sleep(0.05)`).
- **Efficiency Impact:** Syncing a single active account with a lot of history could take several minutes.
- **Improvement:** Transition the API clients to use `asyncio` and `aiohttp`. Python's async features would allow concurrent fetching of match details (e.g., fetching 20-50 matches concurrently), drastically reducing the total sync time while still respecting rate limits.

### 3.2. Lack of Type Hinting & Data Validation
- **Observation:** The project heavily relies on raw dictionaries (`dict`) moving between the DB, API, and UI. There are very few type hints.
- **Improvement:** Adopt `Pydantic` or Python `dataclasses`. Defining models for `Account`, `Match`, and `Rank` will validate API responses, document the data structures automatically, and prevent `KeyError` crashes in the UI.

### 3.3. Logging vs. Print Statements
- **Observation:** Diagnostics and errors are handled via `print()`. 
- **Improvement:** Implement Python's standard `logging` module. Write logs to a rotating file (e.g., `app.log`) so background thread errors aren't lost when the application is compiled to an executable or closed.

---

## 4. Ideas for Future Expansion

1. **Background Service Worker:** Instead of locking up a UI timer, abstract the `SyncEngine` into a standalone daemon or background service that runs periodically (e.g., every hour) even when the main GUI is closed.
2. **Local Caching for API Limits:** The current `RiotClient` handles rate limits cleanly using primary/fallback keys. Integrating a Redis or SQLite-based cache for identical API requests (especially static data) would further shield against `429 Too Many Requests`.
3. **Advanced Analytics View:** Since you already save granular `Timeline` data to the `Raw` directory, consider building a separate "Analytics Dashboard" (perhaps reusing the Streamlit PoC) inside the UI that plots LP changes or Gold/Min over time. 
4. **Unified Error Handling UI:** Implement a global notification toast or snackbar in `customtkinter` for API failures, rather than relying on standard labels that might get overwritten.