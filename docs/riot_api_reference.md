# Riot API Local Reference

This document serves as the local source of truth for the Riot Games API endpoints utilized by the Account Manager application. It specifically details the endpoints and their rate limits based on empirical testing of **Personal API Keys**.

## Core Concepts

### Rate Limiting (The "Two-Tier" System)
Riot enforces limits on two separate layers.
1.  **App Rate Limits (`X-App-Rate-Limit`)**: The global limit for *all* requests made with your key.
    *   **Personal Key App Limits:** `20 requests / 1 second` AND `100 requests / 2 minutes`.
2.  **Method Rate Limits (`X-Method-Rate-Limit`)**: The specific limit for a particular endpoint (e.g., Match Details). 

If a request returns `429 Too Many Requests`, the `Retry-After` header dictates the wait time in seconds.

### Routing
*   **Platform Routing (Local):** Used for localized data (Ranks, Spectator, Mastery).
    *   *Examples:* `na1.api.riotgames.com`, `euw1.api.riotgames.com`, `kr.api.riotgames.com`
*   **Regional Routing (Global):** Used for universally unique data (Accounts, Matches).
    *   *Examples:* `americas.api.riotgames.com`, `europe.api.riotgames.com`, `asia.api.riotgames.com`

---

## 1. Authentication & Resolution (Account-V1 & Summoner-V4)

### A. Get PUUID by Riot ID
*   **Endpoint:** `GET /riot/account/v1/accounts/by-riot-id/{gameName}/{tagLine}`
*   **Routing:** Regional
*   **Purpose:** Resolves a player's readable name into a global `puuid`.

### B. Get Summoner ID by PUUID
*   **Endpoint:** `GET /lol/summoner/v4/summoners/by-puuid/{encryptedPUUID}`
*   **Routing:** Platform
*   **Purpose:** Resolves the global `puuid` into a `summonerId`, and provides the true, safely-encrypted **Platform PUUID**, Profile Icon, and Summoner Level.

---

## 2. Ranks & Leaderboards (League-V4)

### A. Get Current Ranks
*   **Endpoint:** `GET /lol/league/v4/entries/by-puuid/{encryptedPUUID}`
*   **Routing:** Platform
*   **Purpose:** Returns an array of rank objects (Solo/Duo and Flex). Includes Tier, Rank, LP, Wins, and Losses.

---

## 3. Match History & Analytics (Match-V5)

### A. Get Match IDs
*   **Endpoint:** `GET /lol/match/v5/matches/by-puuid/{puuid}/ids`
*   **Routing:** Regional
*   **Query Params:** `start` (index, default 0), `count` (max 100), `startTime` (epoch seconds), `endTime` (epoch seconds), `queue` (queue ID filter, e.g. `420` for Solo/Duo Ranked, `440` for Flex).
*   **Purpose:** Retrieves an array of match IDs played by the specified player.

### B. Get Match Details
*   **Endpoint:** `GET /lol/match/v5/matches/{matchId}`
*   **Routing:** Regional
*   **Purpose:** Returns the detailed JSON blob for a match (Participants, KDA, Damage, Items, Runes, Bans).

### C. Get Match Timeline
*   **Endpoint:** `GET /lol/match/v5/matches/{matchId}/timeline`
*   **Routing:** Regional
*   **Purpose:** Returns minute-by-minute frame data (Gold charts, item purchase timestamps, kill coordinates) for a match.

---

## 4. Advanced Scouting (Mastery & Spectator)

### A. Champion Masteries
*   **Endpoint:** `GET /lol/champion-mastery/v4/champion-masteries/by-puuid/{encryptedPUUID}`
*   **Routing:** Platform
*   **Purpose:** Returns mastery points and levels for every champion the player has ever played.

### B. Active Game (Spectator)
*   **Endpoint:** `GET /lol/spectator/v5/active-games/by-summoner/{encryptedPUUID}`
*   **Routing:** Platform
*   **Responses:** Returns `200 OK` with 10 participant profiles if in-game. Returns `404 Not Found` if the player is not currently in an active game.