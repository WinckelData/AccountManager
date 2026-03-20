import requests
import time


class RateLimitExhaustedException(Exception):
    """Raised when both primary and fallback keys have exhausted their limits."""
    pass


class NetworkError(Exception):
    """Raised when _request exhausts all retries due to network/server errors."""
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
                    body = response.text[:80].replace('\n', ' ').strip()
                    print(f"[RiotClient] {response.status_code} for {url}: {body}")
                    if attempt < max_retries - 1:
                        wait = 2 ** attempt
                        time.sleep(wait)

            except requests.exceptions.RequestException as e:
                err_msg = str(e).split('\n')[0][:120]
                print(f"[RiotClient] Network error (attempt {attempt + 1}): {err_msg}")
                if attempt < max_retries - 1:
                    time.sleep(2 ** attempt)

        raise NetworkError(f"All {max_retries} attempts failed for {url}")

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

    def _probe(self, url, ok_statuses=(200,)):
        """Single raw GET using primary key, 5s timeout, no retries.
        Returns (status, ok, message, latency_ms).
        """
        headers = {"X-Riot-Token": self.keys[0].key}
        try:
            start = time.time()
            resp = requests.get(url, headers=headers, timeout=5)
            latency = int((time.time() - start) * 1000)
            ok = resp.status_code in ok_statuses
            msg = "OK" if ok else resp.reason or str(resp.status_code)
            return (resp.status_code, ok, msg, latency)
        except requests.exceptions.RequestException as e:
            return (None, False, str(e), 0)

    def health_check(self, test_data):
        """Run diagnostic probes against Riot LoL API endpoints.

        test_data: dict with keys:
            puuid, game_name, tag_line, regional, platform,
            match_id (optional)
        """
        from src.health import EndpointResult, HealthCheckReport

        results = []
        puuid = test_data["puuid"]
        game_name = test_data["game_name"]
        tag_line = test_data["tag_line"]
        regional = test_data["regional"]
        platform = test_data["platform"]
        match_id = test_data.get("match_id")

        base_r = self.base_url_regional.format(region=regional)
        base_p = self.base_url_platform.format(platform=platform)

        # 1. account/v1
        url = f"{base_r}/riot/account/v1/accounts/by-riot-id/{game_name}/{tag_line}"
        status, ok, msg, lat = self._probe(url)
        results.append(EndpointResult("account/v1", regional, status, ok, msg, lat))

        # 2. summoner/v4
        url = f"{base_p}/lol/summoner/v4/summoners/by-puuid/{puuid}"
        status, ok, msg, lat = self._probe(url)
        results.append(EndpointResult("summoner/v4", platform, status, ok, msg, lat))

        # 3. league/v4
        url = f"{base_p}/lol/league/v4/entries/by-puuid/{puuid}"
        status, ok, msg, lat = self._probe(url)
        results.append(EndpointResult("league/v4", platform, status, ok, msg, lat))

        # 4. match/v5/ids
        url = f"{base_r}/lol/match/v5/matches/by-puuid/{puuid}/ids?start=0&count=1"
        status, ok, msg, lat = self._probe(url)
        results.append(EndpointResult("match/v5/ids", regional, status, ok, msg, lat))

        # 5. spectator/v5 (404 = OK, means not in game)
        url = f"{base_p}/lol/spectator/v5/active-games/by-summoner/{puuid}"
        status, ok, msg, lat = self._probe(url, ok_statuses=(200, 404))
        results.append(EndpointResult("spectator/v5", platform, status, ok, msg, lat))

        # 6. mastery/v4
        url = f"{base_p}/lol/champion-mastery/v4/champion-masteries/by-puuid/{puuid}"
        status, ok, msg, lat = self._probe(url)
        results.append(EndpointResult("mastery/v4", platform, status, ok, msg, lat))

        # 7. match/v5/detail
        if match_id:
            url = f"{base_r}/lol/match/v5/matches/{match_id}"
            status, ok, msg, lat = self._probe(url)
            results.append(EndpointResult("match/v5/detail", regional, status, ok, msg, lat))
        else:
            results.append(EndpointResult(
                "match/v5/detail", regional, None, False, "Skipped — no match_id",
            ))

        # 8. match/v5/timeline
        if match_id:
            url = f"{base_r}/lol/match/v5/matches/{match_id}/timeline"
            status, ok, msg, lat = self._probe(url)
            results.append(EndpointResult("match/v5/timeline", regional, status, ok, msg, lat))
        else:
            results.append(EndpointResult(
                "match/v5/timeline", regional, None, False, "Skipped — no match_id",
            ))

        return HealthCheckReport(service="Riot", results=results)