# StarCraft II API Reference

This document serves as the comprehensive local reference for the Blizzard Battle.net StarCraft II APIs. It covers both the **Game Data APIs** (static game definitions, league structures) and the **Community APIs** (player profiles, ladders, match history).

## Core Concepts

### Authentication (OAuth 2.0)
All Blizzard APIs require an OAuth 2.0 access token. 
* **Endpoint:** `POST https://oauth.battle.net/token`
* **Grant Type:** `client_credentials`
* **Auth Method:** Basic Auth using `BLIZZARD_CLIENT_ID` and `BLIZZARD_CLIENT_SECRET`.
* **Usage:** Pass the token in the request header: `Authorization: Bearer {access_token}`. Tokens typically expire after 24 hours.

### Regional Routing & IDs
Requests must be routed to the specific regional server where the profile resides.

* **Region 1 (US / NA / LATAM):** `us.api.blizzard.com`
* **Region 2 (EU / Russia):** `eu.api.blizzard.com`
* **Region 3 (KR / TW):** `kr.api.blizzard.com`
* **Region 5 (CN):** `gateway.battlenet.com.cn`

**Realm IDs:** Profiles are further subdivided by Realm. Typically `1` or `2` for NA/EU.

---

## 1. Community APIs (Player Data)

### A. Profile API

#### 1. Get Static Profile Data
* **Endpoint:** `GET /sc2/static/profile/:regionId`
* **Purpose:** Returns all static SC2 profile data (achievements, categories, criteria, and rewards).
* **Parameters:** `regionId` (1=US, 2=EU, 3=KR/TW, 5=CN).

#### 2. Get Profile Metadata
* **Endpoint:** `GET /sc2/metadata/profile/:regionId/:realmId/:profileId`
* **Purpose:** Returns metadata for an individual's profile, including the player's true `displayName` (in-game name), portrait URL, and avatar URL. 

#### 3. Get Profile (Base)
* **Endpoint:** `GET /sc2/profile/:regionId/:realmId/:profileId`
* **Purpose:** Returns a summary of the player's lifetime statistics, campaign progress, total achievement points, and current season snapshot.

#### 4. Get Ladder Summary
* **Endpoint:** `GET /sc2/profile/:regionId/:realmId/:profileId/ladder/summary`
* **Purpose:** Returns a list of `showCaseEntries` representing the player's active ladders (1v1, 2v2, Archon, etc.). Data includes `ladderId`, `leagueName`, `wins`, `losses`, `rank`, and the `favoriteRace`.

#### 5. Get Ladder Details
* **Endpoint:** `GET /sc2/profile/:regionId/:realmId/:profileId/ladder/:ladderId`
* **Purpose:** Returns the entire ladder bracket for a specific `ladderId`, containing MMR data for teams/players.

---

### B. Ladder API

#### 1. Get Grandmaster Leaderboard
* **Endpoint:** `GET /sc2/ladder/grandmaster/:regionId`
* **Purpose:** Returns ladder data for the current season's grandmaster leaderboard.

#### 2. Get Season
* **Endpoint:** `GET /sc2/ladder/season/:regionId`
* **Purpose:** Returns data about the current season (seasonId, start and end dates).

---

### C. Account API

#### 1. Get Player by Account ID
* **Endpoint:** `GET /sc2/player/:accountId`
* **Purpose:** Returns metadata (regionId, realmId, profileId) for an individual's account.

---

### D. Legacy API

#### 1. Legacy Profile
* **Endpoint:** `GET /sc2/legacy/profile/:regionId/:realmId/:profileId`

#### 2. Legacy Ladders
* **Endpoint:** `GET /sc2/legacy/profile/:regionId/:realmId/:profileId/ladders`

#### 3. Match History
* **Endpoint:** `GET /sc2/legacy/profile/:regionId/:realmId/:profileId/matches`
* **Purpose:** Returns data about an individual SC2 profile's match history.

#### 4. Legacy Ladder
* **Endpoint:** `GET /sc2/legacy/ladder/:regionId/:ladderId`

#### 5. Legacy Achievements
* **Endpoint:** `GET /sc2/legacy/data/achievements/:regionId`

#### 6. Legacy Rewards
* **Endpoint:** `GET /sc2/legacy/data/rewards/:regionId`

---

---

## Rate Limit Findings

_Measured 2026-03-15 using `tests/test_blizzard_rate_limits.py`_

### Documented Limits
- **Per-second:** 100 requests/second
- **Per-hour:** 36,000 requests/hour

### Observed Behavior
- **No rate-limit headers returned** — Blizzard does not send `X-RateLimit-*`, `Retry-After`, or similar headers on normal responses. The `Retry-After` header only appears on actual `429` responses.
- **Very generous burst buffer** — A 300-request concurrent burst (multithreaded) completed without triggering any `429` responses, indicating a large burst allowance or average-based throttling rather than a strict per-second hard cutoff.
- **Sustained load** — 75 sequential requests averaged ~80–200 ms per call (region-dependent). No throttling observed at this rate.

### Implementation Notes
- `BlizzardClient` uses a proactive sliding-window counter (`deque`) tracking the last 1 second and last 1 hour of requests.
- Configured with conservative thresholds: 95 req/s and 35,000 req/hr (both slightly below documented limits).
- Since Blizzard's burst buffer appears very large, the effective constraint for this app is the **per-hour limit** (35,000 guard rail).
- With ~6–10 API calls per SC2 account sync, even 1,000 accounts can be synced comfortably within the hourly budget.

### Parallelism Recommendation
- **3 workers** is a safe default for parallel SC2 sync (used in `data_updater.py`).
- Could increase to 5–10 workers without risk of hitting rate limits for typical account counts.

---

## 2. Game Data APIs (Global State)

### A. Get League Data
* **Endpoint:** `GET /data/sc2/league/{seasonId}/{queueId}/{teamType}/{leagueId}`
* **Purpose:** Returns structural data for the specified season, queue, team, and league.
* **Variables:** 
  * `{seasonId}`: The ID of the season to retrieve.
  * `{queueId}`: 1=WoL 1v1, 2=WoL 2v2, 3=WoL 3v3, 4=WoL 4v4, 101=HotS 1v1, 102=HotS 2v2, 103=HotS 3v3, 104=HotS 4v4, 201=LotV 1v1, 202=LotV 2v2, 203=LotV 3v3, 204=LotV 4v4, 206=LotV Archon.
  * `{teamType}`: 0=arranged, 1=random.
  * `{leagueId}`: 0=Bronze, 1=Silver, 2=Gold, 3=Platinum, 4=Diamond, 5=Master, 6=Grandmaster.