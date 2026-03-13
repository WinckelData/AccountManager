import requests
import time
import os

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
            if state.get_available_capacity() > 5: # Leave a small buffer
                return state
                
            # If empty, rotate to next key
            print(f"[RiotClient] Key {self.current_key_idx} exhausted. Rotating...")
            self.current_key_idx = (self.current_key_idx + 1) % len(self.keys)
            
        return None

    def _request(self, url):
        """Core request handler with rotation and backoff."""
        key_state = self._get_active_key_state()
        
        if not key_state:
            # Both keys are completely exhausted. We must sleep.
            print("[RiotClient] All keys exhausted limits! Sleeping for 15 seconds to allow windows to reset...")
            time.sleep(15)
            # Try again recursively
            return self._request(url)

        headers = {"X-Riot-Token": key_state.key}
        
        try:
            response = requests.get(url, headers=headers)
            key_state.update_from_headers(response.headers)
            
            if response.status_code == 200:
                return response.json()
            elif response.status_code == 429:
                retry_after = int(response.headers.get("Retry-After", 10))
                print(f"[RiotClient] Hit 429 Too Many Requests! Sleeping for {retry_after}s.")
                # Force count to max so we rotate keys next time
                key_state.app_count = key_state.app_limit 
                time.sleep(retry_after)
                return self._request(url)
            elif response.status_code == 404:
                # Valid response for things like Spectator or missing players
                return None
            else:
                print(f"[RiotClient] Request failed: {url} -> {response.status_code}: {response.text}")
                return None
                
        except requests.exceptions.RequestException as e:
            print(f"[RiotClient] Network error: {e}")
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

    def get_match_ids(self, region, puuid, start=0, count=100, start_time=None, end_time=None):
        url = f"{self.base_url_regional.format(region=region)}/lol/match/v5/matches/by-puuid/{puuid}/ids?start={start}&count={count}"
        if start_time is not None:
            url += f"&startTime={int(start_time)}"
        if end_time is not None:
            url += f"&endTime={int(end_time)}"
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
    def __init__(self, client_id=None, client_secret=None):
        self.client_id = client_id or os.getenv("BLIZZARD_CLIENT_ID")
        self.client_secret = client_secret or os.getenv("BLIZZARD_CLIENT_SECRET")
        self.access_token = self._get_access_token()

    def _get_access_token(self):
        if not self.client_id or not self.client_secret:
            return None
        url = "https://oauth.battle.net/token"
        data = {"grant_type": "client_credentials"}
        auth = (self.client_id, self.client_secret)
        response = requests.post(url, data=data, auth=auth)
        return response.json().get("access_token") if response.status_code == 200 else None

    # (Existing SC2 methods can remain untouched for now)
    def get_sc2_profile(self, region_id, realm_id, profile_id):
        url = f"https://{self._get_region_name(region_id)}.api.blizzard.com/sc2/profile/{region_id}/{realm_id}/{profile_id}"
        headers = {"Authorization": f"Bearer {self.access_token}"}
        response = requests.get(url, headers=headers)
        return response.json() if response.status_code == 200 else None

    def get_current_season(self, region_id):
        url = f"https://{self._get_region_name(region_id)}.api.blizzard.com/sc2/ladder/season/{region_id}"
        headers = {"Authorization": f"Bearer {self.access_token}"}
        response = requests.get(url, headers=headers)
        if response.status_code == 200:
            return response.json().get("seasonId")
        return None

    def get_profile_metadata(self, region_id, realm_id, profile_id):
        url = f"https://{self._get_region_name(region_id)}.api.blizzard.com/sc2/metadata/profile/{region_id}/{realm_id}/{profile_id}"
        headers = {"Authorization": f"Bearer {self.access_token}"}
        response = requests.get(url, headers=headers)
        return response.json() if response.status_code == 200 else {}

    def get_ladder_summary(self, region_id, realm_id, profile_id):
        url = f"https://{self._get_region_name(region_id)}.api.blizzard.com/sc2/profile/{region_id}/{realm_id}/{profile_id}/ladder/summary"
        headers = {"Authorization": f"Bearer {self.access_token}"}
        response = requests.get(url, headers=headers)
        return response.json() if response.status_code == 200 else {}

    def get_ladder_details(self, region_id, realm_id, profile_id, ladder_id):
        url = f"https://{self._get_region_name(region_id)}.api.blizzard.com/sc2/profile/{region_id}/{realm_id}/{profile_id}/ladder/{ladder_id}"
        headers = {"Authorization": f"Bearer {self.access_token}"}
        response = requests.get(url, headers=headers)
        return response.json() if response.status_code == 200 else {}

    def _get_region_name(self, region_id):
        regions = {1: "us", 2: "eu", 3: "kr"}
        return regions.get(region_id, "us")
