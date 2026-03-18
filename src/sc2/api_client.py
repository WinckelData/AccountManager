import requests
import time
import os
import threading
from collections import deque


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
        """Return full season dict with seasonId, startDate, endDate (epoch seconds)."""
        url = f"https://{self._get_region_name(region_id)}.api.blizzard.com/sc2/ladder/season/{region_id}"
        data = self._request(url)
        if not data:
            return None
        return {
            "seasonId": data.get("seasonId"),
            "startDate": data.get("startDate"),
            "endDate": data.get("endDate"),
        }

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

    def _probe(self, url):
        """Single raw GET with 10s timeout, no retries, no rate-limit wait.
        Returns (status, ok, message, latency_ms).
        """
        if not self.access_token:
            return (None, False, "No access token", 0)
        headers = {"Authorization": f"Bearer {self.access_token}"}
        try:
            start = time.time()
            resp = requests.get(url, headers=headers, timeout=10)
            latency = int((time.time() - start) * 1000)
            ok = resp.status_code == 200
            msg = "OK" if ok else resp.reason or str(resp.status_code)
            return (resp.status_code, ok, msg, latency)
        except requests.exceptions.RequestException as e:
            return (None, False, str(e), 0)

    def health_check(self, test_profiles=None):
        """Run diagnostic probes against Blizzard SC2 API endpoints.

        test_profiles: dict mapping region_id -> (realm_id, profile_id)
            e.g. {1: (1, 12345), 2: (1, 67890)}
        """
        from src.health import EndpointResult, HealthCheckReport

        if test_profiles is None:
            test_profiles = {}

        results = []
        region_names = {1: "NA", 2: "EU", 3: "KR"}

        # 1. OAuth token probe
        try:
            start = time.time()
            resp = requests.post(
                "https://oauth.battle.net/token",
                data={"grant_type": "client_credentials"},
                auth=(self.client_id, self.client_secret),
                timeout=5,
            )
            latency = int((time.time() - start) * 1000)
            ok = resp.status_code == 200
            results.append(EndpointResult(
                endpoint="oauth/token",
                region="--",
                status=resp.status_code,
                ok=ok,
                message="OK" if ok else resp.reason or str(resp.status_code),
                latency_ms=latency,
            ))
            if ok:
                self.access_token = resp.json().get("access_token")
        except requests.exceptions.RequestException as e:
            results.append(EndpointResult(
                endpoint="oauth/token", region="--",
                status=None, ok=False, message=str(e),
            ))

        if not self.access_token:
            results.append(EndpointResult(
                endpoint="(remaining)", region="--",
                status=None, ok=False, message="Skipped — no token",
            ))
            return HealthCheckReport(service="Blizzard", results=results)

        # 2. Per-region probes
        for region_id in (1, 2, 3):
            rname = region_names[region_id]
            host = self._get_region_name(region_id)

            # current_season
            url = f"https://{host}.api.blizzard.com/sc2/ladder/season/{region_id}"
            status, ok, msg, lat = self._probe(url)
            results.append(EndpointResult("current_season", rname, status, ok, msg, lat))

            # grandmaster_ladder
            url = f"https://{host}.api.blizzard.com/sc2/ladder/grandmaster/{region_id}"
            status, ok, msg, lat = self._probe(url)
            results.append(EndpointResult("grandmaster_ladder", rname, status, ok, msg, lat))

            # Profile-dependent endpoints
            if region_id in test_profiles:
                realm_id, profile_id = test_profiles[region_id]

                url = f"https://{host}.api.blizzard.com/sc2/profile/{region_id}/{realm_id}/{profile_id}"
                status, ok, msg, lat = self._probe(url)
                results.append(EndpointResult("sc2_profile", rname, status, ok, msg, lat))

                url = f"https://{host}.api.blizzard.com/sc2/metadata/profile/{region_id}/{realm_id}/{profile_id}"
                status, ok, msg, lat = self._probe(url)
                results.append(EndpointResult("profile_metadata", rname, status, ok, msg, lat))

                url = f"https://{host}.api.blizzard.com/sc2/profile/{region_id}/{realm_id}/{profile_id}/ladder/summary"
                status, ok, msg, lat = self._probe(url)
                results.append(EndpointResult("ladder_summary", rname, status, ok, msg, lat))

                url = f"https://{host}.api.blizzard.com/sc2/legacy/profile/{region_id}/{realm_id}/{profile_id}/matches"
                status, ok, msg, lat = self._probe(url)
                results.append(EndpointResult("match_history", rname, status, ok, msg, lat))

                results.append(EndpointResult(
                    "ladder_details", rname, None, False,
                    "Skipped — needs ladder_id from summary",
                ))

        return HealthCheckReport(service="Blizzard", results=results)

    def _get_region_name(self, region_id):
        regions = {1: "us", 2: "eu", 3: "kr"}
        return regions.get(region_id, "us")