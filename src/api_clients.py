import requests
import time
import os
import threading
from collections import deque

class RateLimitExhaustedException(Exception):
    """Raised when both primary and fallback keys have exhausted their limits."""
    pass

class KeyState:
    def __init__(self, key):
        self.key = key
        # Default to standard Personal API limits
        self.app_limit = 100
        self.app_window = 120 # 2 minutes
        self.app_count = 0
        self.last_reset_time = time.time()
        
    def get_available_capacity(self):
        """Returns how many requests are theoretically left in the window."""
        # Simple local tracking, will be overwritten by headers
        now = time.time()
        if now - self.last_reset_time >= self.app_window:
            self.app_count = 0
            self.last_reset_time = now
            
        return self.app_limit - self.app_count

    def update_from_headers(self, headers):
        """Updates internal state based on Riot's headers."""
        app_count_header = headers.get("X-App-Rate-Limit-Count")
        if app_count_header:
            try:
                # Format is usually "X:Y,Z:W" -> "Requests:WindowLength"
                # We care about the 120 second window (the highest count)
                parts = app_count_header.split(',')
                for p in parts:
                    count, window = map(int, p.split(':'))
                    if window == 120:
                        self.app_count = count
                        break
            except ValueError:
                pass


class RiotClient:
    def __init__(self, primary_key, fallback_key=None):
        self.keys = [KeyState(primary_key)]
        if fallback_key:
            self.keys.append(KeyState(fallback_key))
            
        self.current_key_idx = 0
        self.base_url_platform = "https://{platform}.api.riotgames.com"
        self.base_url_regional = "https://{region}.api.riotgames.com"

    def _get_active_key_state(self):
        """Returns the KeyState object with available capacity, or None if all are exhausted."""
        start_idx = self.current_key_idx
        for _ in range(len(self.keys)):
            state = self.keys[self.current_key_idx]
            if state.get_available_capacity() > 2: # Leave a small buffer
                return state
                
            # If empty, rotate to next key
            print(f"[RiotClient] Key {self.current_key_idx} exhausted. Rotating...")
            self.current_key_idx = (self.current_key_idx + 1) % len(self.keys)
            
        return None

    def _request(self, url, max_retries=5):
        """Core request handler with key rotation and iterative exponential backoff."""
        for attempt in range(max_retries):
            key_state = self._get_active_key_state()

            if not key_state:
                wait = min(15 * (2 ** attempt), 120)
                print(f"[RiotClient] All keys exhausted. Waiting {wait}s (attempt {attempt + 1}/{max_retries})...")
                time.sleep(wait)
                continue

            headers = {"X-Riot-Token": key_state.key}

            try:
                response = requests.get(url, headers=headers, timeout=10)
                key_state.update_from_headers(response.headers)

                if response.status_code == 200:
                    return response.json()
                elif response.status_code == 400:
                    print(f"[RiotClient] 400 Bad Request: {url}: {response.text[:200]}")
                    return None
                elif response.status_code == 429:
                    retry_after = int(response.headers.get("Retry-After", 10))
                    print(f"[RiotClient] 429 on attempt {attempt + 1}. Sleeping {retry_after}s.")
                    key_state.app_count = key_state.app_limit
                    time.sleep(retry_after)
                elif response.status_code == 404:
                    return None
                else:
                    print(f"[RiotClient] {response.status_code} for {url}: {response.text[:200]}")
                    if attempt < max_retries - 1:
                        wait = 2 ** attempt
                        time.sleep(wait)

            except requests.exceptions.RequestException as e:
                print(f"[RiotClient] Network error (attempt {attempt + 1}): {e}")
                if attempt < max_retries - 1:
                    time.sleep(2 ** attempt)

        print(f"[RiotClient] All {max_retries} attempts failed for {url}")
        return None

    # --- Endpoints ---

    def get_puuid_by_riot_id(self, region, game_name, tag_line):
        url = f"{self.base_url_regional.format(region=region)}/riot/account/v1/accounts/by-riot-id/{game_name}/{tag_line}"
        return self._request(url)

    def get_summoner_by_puuid(self, platform, puuid):
        url = f"{self.base_url_platform.format(platform=platform)}/lol/summoner/v4/summoners/by-puuid/{puuid}"
        return self._request(url)

    def get_league_entries(self, platform, puuid):
        url = f"{self.base_url_platform.format(platform=platform)}/lol/league/v4/entries/by-puuid/{puuid}"
        return self._request(url)

    def get_match_ids(self, region, puuid, start=0, count=100, start_time=None, end_time=None, queue=None):
        url = f"{self.base_url_regional.format(region=region)}/lol/match/v5/matches/by-puuid/{puuid}/ids?start={start}&count={count}"
        if start_time is not None:
            url += f"&startTime={int(start_time)}"
        if end_time is not None:
            url += f"&endTime={int(end_time)}"
        if queue is not None:
            url += f"&queue={int(queue)}"
        return self._request(url)

    def get_active_game(self, platform, puuid):
        """Spectator-V5: returns active game data or None if not in game."""
        url = f"{self.base_url_platform.format(platform=platform)}/lol/spectator/v5/active-games/by-summoner/{puuid}"
        return self._request(url)

    def get_match_details(self, region, match_id):
        url = f"{self.base_url_regional.format(region=region)}/lol/match/v5/matches/{match_id}"
        return self._request(url)

    def get_match_timeline(self, region, match_id):
        url = f"{self.base_url_regional.format(region=region)}/lol/match/v5/matches/{match_id}/timeline"
        return self._request(url)

    def get_champion_masteries(self, platform, puuid):
        url = f"{self.base_url_platform.format(platform=platform)}/lol/champion-mastery/v4/champion-masteries/by-puuid/{puuid}"
        return self._request(url)

class BlizzardClient:
    # Blizzard documented limits: 100 req/s, 36,000 req/hr — use conservative buffers
    _LIMIT_PER_SECOND = 95
    _LIMIT_PER_HOUR = 35_000

    def __init__(self, client_id=None, client_secret=None):
        self.client_id = client_id or os.getenv("BLIZZARD_CLIENT_ID")
        self.client_secret = client_secret or os.getenv("BLIZZARD_CLIENT_SECRET")
        self.access_token = self._get_access_token()
        self._req_timestamps_1s: deque = deque()
        self._req_timestamps_1hr: deque = deque()
        self._rate_lock = threading.Lock()

    def _wait_for_rate_limit(self):
        """Block until within Blizzard's documented rate limits."""
        with self._rate_lock:
            now = time.time()
            # Prune stale timestamps
            while self._req_timestamps_1s and now - self._req_timestamps_1s[0] > 1.0:
                self._req_timestamps_1s.popleft()
            while self._req_timestamps_1hr and now - self._req_timestamps_1hr[0] > 3600.0:
                self._req_timestamps_1hr.popleft()

            # Enforce per-second limit
            if len(self._req_timestamps_1s) >= self._LIMIT_PER_SECOND:
                sleep_for = 1.0 - (now - self._req_timestamps_1s[0])
                if sleep_for > 0:
                    time.sleep(sleep_for)
                    now = time.time()
                    while self._req_timestamps_1s and now - self._req_timestamps_1s[0] > 1.0:
                        self._req_timestamps_1s.popleft()

            # Enforce per-hour limit
            if len(self._req_timestamps_1hr) >= self._LIMIT_PER_HOUR:
                sleep_for = 3600.0 - (now - self._req_timestamps_1hr[0])
                if sleep_for > 0:
                    print(f"[BlizzardClient] Hourly limit reached. Sleeping {sleep_for:.0f}s...")
                    time.sleep(sleep_for)
                    now = time.time()
                    while self._req_timestamps_1hr and now - self._req_timestamps_1hr[0] > 3600.0:
                        self._req_timestamps_1hr.popleft()

            # Record this request
            self._req_timestamps_1s.append(now)
            self._req_timestamps_1hr.append(now)

    def _get_access_token(self):
        if not self.client_id or not self.client_secret:
            print("[BlizzardClient] Missing client_id or client_secret.")
            return None
        url = "https://oauth.battle.net/token"
        data = {"grant_type": "client_credentials"}
        auth = (self.client_id, self.client_secret)
        try:
            response = requests.post(url, data=data, auth=auth, timeout=10)
            if response.status_code == 200:
                return response.json().get("access_token")
            print(f"[BlizzardClient] Token fetch failed: {response.status_code} {response.text[:200]}")
        except requests.exceptions.RequestException as e:
            print(f"[BlizzardClient] Token fetch network error: {e}")
        return None

    def _request(self, url, fallback=None, max_retries=3):
        """
        Centralized request handler with retry, exponential backoff, and auto token refresh.
        Returns fallback value (default None) on permanent failure.
        """
        if fallback is None:
            fallback = {}

        for attempt in range(max_retries):
            self._wait_for_rate_limit()
            if not self.access_token:
                print("[BlizzardClient] No access token. Attempting refresh...")
                self.access_token = self._get_access_token()
                if not self.access_token:
                    print("[BlizzardClient] Token refresh failed. Aborting.")
                    return fallback

            headers = {"Authorization": f"Bearer {self.access_token}"}
            try:
                response = requests.get(url, headers=headers, timeout=15)

                if response.status_code == 200:
                    return response.json()
                elif response.status_code == 401:
                    print(f"[BlizzardClient] 401 Unauthorized. Refreshing token (attempt {attempt + 1})...")
                    self.access_token = self._get_access_token()
                elif response.status_code == 404:
                    return fallback
                elif response.status_code == 429:
                    retry_after = int(response.headers.get("Retry-After", 5))
                    print(f"[BlizzardClient] 429 rate limited. Sleeping {retry_after}s.")
                    time.sleep(retry_after)
                else:
                    print(f"[BlizzardClient] {response.status_code} for {url}: {response.text[:200]}")
                    if attempt < max_retries - 1:
                        time.sleep(2 ** attempt)

            except requests.exceptions.RequestException as e:
                print(f"[BlizzardClient] Network error (attempt {attempt + 1}): {e}")
                if attempt < max_retries - 1:
                    time.sleep(2 ** attempt)

        print(f"[BlizzardClient] All {max_retries} attempts failed for {url}")
        return fallback

    def _request_nullable(self, url, max_retries=3):
        """Same as _request but returns None (not {}) on failure — for endpoints where {} is ambiguous."""
        result = self._request(url, fallback=None, max_retries=max_retries)
        return result

    def get_sc2_profile(self, region_id, realm_id, profile_id):
        url = f"https://{self._get_region_name(region_id)}.api.blizzard.com/sc2/profile/{region_id}/{realm_id}/{profile_id}"
        return self._request_nullable(url)

    def get_current_season(self, region_id):
        url = f"https://{self._get_region_name(region_id)}.api.blizzard.com/sc2/ladder/season/{region_id}"
        data = self._request(url)
        return data.get("seasonId") if data else None

    def get_profile_metadata(self, region_id, realm_id, profile_id):
        url = f"https://{self._get_region_name(region_id)}.api.blizzard.com/sc2/metadata/profile/{region_id}/{realm_id}/{profile_id}"
        return self._request(url)

    def get_ladder_summary(self, region_id, realm_id, profile_id):
        url = f"https://{self._get_region_name(region_id)}.api.blizzard.com/sc2/profile/{region_id}/{realm_id}/{profile_id}/ladder/summary"
        return self._request(url)

    def get_ladder_details(self, region_id, realm_id, profile_id, ladder_id):
        url = f"https://{self._get_region_name(region_id)}.api.blizzard.com/sc2/profile/{region_id}/{realm_id}/{profile_id}/ladder/{ladder_id}"
        return self._request(url)

    def get_match_history(self, region_id, realm_id, profile_id):
        """Legacy match history: last 25 matches with date, type, decision, map."""
        url = f"https://{self._get_region_name(region_id)}.api.blizzard.com/sc2/legacy/profile/{region_id}/{realm_id}/{profile_id}/matches"
        return self._request(url)

    def get_grandmaster_ladder(self, region_id):
        """Grandmaster leaderboard for a region."""
        url = f"https://{self._get_region_name(region_id)}.api.blizzard.com/sc2/ladder/grandmaster/{region_id}"
        return self._request(url)

    def _get_region_name(self, region_id):
        regions = {1: "us", 2: "eu", 3: "kr"}
        return regions.get(region_id, "us")
