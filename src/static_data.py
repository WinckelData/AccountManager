import requests
import json
import os
from src.config import DATA_DIR

STATIC_DIR = DATA_DIR / "static"

class StaticDataManager:
    def __init__(self):
        os.makedirs(STATIC_DIR, exist_ok=True)

    def get_latest_version(self):
        """Cheaply check the latest live patch version."""
        url = "https://ddragon.leagueoflegends.com/api/versions.json"
        try:
            resp = requests.get(url, timeout=5)
            if resp.status_code == 200:
                return resp.json()[0]
        except Exception as e:
            print(f"Error checking versions: {e}")
        return None

    def sync_all(self, version):
        """Downloads and caches all major static data for a specific version."""
        version_dir = STATIC_DIR / version
        os.makedirs(version_dir, exist_ok=True)

        endpoints = {
            "champions": f"https://ddragon.leagueoflegends.com/cdn/{version}/data/en_US/champion.json",
            "items": f"https://ddragon.leagueoflegends.com/cdn/{version}/data/en_US/item.json",
            "maps": f"https://ddragon.leagueoflegends.com/cdn/{version}/data/en_US/map.json"
        }

        for name, url in endpoints.items():
            file_path = version_dir / f"{name}.json"
            if not file_path.exists():
                print(f"    -> Syncing static {name} (Version {version})...")
                try:
                    resp = requests.get(url, timeout=10)
                    if resp.status_code == 200:
                        with open(file_path, "w", encoding="utf-8") as f:
                            json.dump(resp.json(), f)
                except Exception as e:
                    print(f"    [!] Failed to sync {name}: {e}")

        self.sync_queues(version_dir)

    def sync_queues(self, target_dir):
        """Syncs the queue ID mapping (maintained by community/Riot docs)."""
        file_path = target_dir / "queues.json"
        if not file_path.exists():
            print("    -> Syncing queue definitions...")
            url = "https://static.developer.riotgames.com/docs/lol/queues.json"
            try:
                resp = requests.get(url, timeout=10)
                if resp.status_code == 200:
                    with open(file_path, "w", encoding="utf-8") as f:
                        json.dump(resp.json(), f)
            except Exception as e:
                print(f"    [!] Failed to sync queues: {e}")

    def get_local_path(self, version, name):
        return STATIC_DIR / version / f"{name}.json"

def load_static_map(version, data_type):
    """Utility to load a specific map (e.g. 'champions') from local cache."""
    mgr = StaticDataManager()
    path = mgr.get_local_path(version, data_type)
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}
