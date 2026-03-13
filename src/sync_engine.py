import os
import json
import time
from pathlib import Path
from dotenv import load_dotenv

from src.api_clients import RiotClient
from src.db_manager import DBManager
from src.config import RAW_MATCHES_DIR, RAW_TIMELINES_DIR, LOL_DB_PATH

class SyncEngine:
    def __init__(self):
        load_dotenv()
        primary = os.getenv("RIOT_API_KEY_PRIMARY")
        fallback = os.getenv("RIOT_API_KEY_FALLBACK")
        self.riot = RiotClient(primary_key=primary, fallback_key=fallback)
        self.db = DBManager()
        
    def _map_region(self, tag_line: str) -> tuple[str, str]:
        """Naively maps a tag line to the correct routing parameters."""
        tag = tag_line.upper()
        if tag in ["EUW", "EUW1", "EUNE"]:
            return "europe", "euw1" if tag in ["EUW", "EUW1"] else "eun1"
        elif tag in ["NA", "NA1"]:
            return "americas", "na1"
        elif tag in ["KR", "KR1"]:
            return "asia", "kr"
        # Default fallback
        return "europe", "euw1"

    def bootstrap_from_old_db(self):
        """One-time execution to pull names from the old JSON into SQLite."""
        if not LOL_DB_PATH.exists():
            print("No old lol_database.json found to bootstrap.")
            return
            
        with open(LOL_DB_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
            
        accounts = data.get("lol_accounts", [])
        for acc in accounts:
            name = acc.get("account_name")
            tag = acc.get("riot_tagline")
            if name and tag:
                # CRITICAL: We MUST use a dummy PUUID initially. 
                # If we use the old PUUID from the JSON, it might be encrypted with an old/dead API key salt,
                # causing Riot to return 400 Exception Decrypting on Match/Summoner endpoints.
                dummy_puuid = f"PENDING_{name}_{tag}"
                login_name = acc.get("login_name") or acc.get("login") # Check common keys
                self.db.upsert_account(dummy_puuid, name, tag, login_name=login_name)
                print(f"Bootstrapped into DB: {name}#{tag} with login {login_name}")

    def sync_all(self, progress_callback=None):
        print("\n" + "="*50)
        print("Starting Data Synchronization...")
        print("="*50)
        
        accounts = self.db.get_tracked_accounts()
        if not accounts:
            print("No tracked accounts found. Run bootstrap or add an account.")
            return

        total_accounts = len(accounts)
        for i, acc in enumerate(accounts):
            game_name = acc["game_name"]
            tag_line = acc["tag_line"]
            puuid = acc["puuid"]
            
            has_changes = False
            account_id = game_name
            if progress_callback:
                progress_callback(account_id, "SYNCING", False, i, total_accounts)
            
            print(f"\n>> Syncing: {game_name}#{tag_line}")
            region, platform = self._map_region(tag_line)

            # 1. Resolve / Verify PUUID (Robust Two-Step Process)
            # CRITICAL FIX: Only resolve if the PUUID is a dummy "PENDING_" value.
            # Riot sometimes returns global PUUIDs from Account-V1 that fail on Match-V5.
            # We must resolve the global PUUID, then ask Summoner-V4 for the true platform PUUID.
            if puuid.startswith("PENDING_"):
                print("   - Resolving Riot ID to Global PUUID...")
                account_data = self.riot.get_puuid_by_riot_id(region, game_name, tag_line)
                if not account_data or "puuid" not in account_data:
                    print("     [ERROR] Failed to resolve Riot ID. Skipping.")
                    continue
                
                global_puuid = account_data["puuid"]
                
                print("   - Requesting true Platform PUUID from Summoner-V4...")
                summoner_data = self.riot.get_summoner_by_puuid(platform, global_puuid)
                if not summoner_data or "puuid" not in summoner_data:
                     print("     [ERROR] Failed to fetch Summoner Profile. Cannot resolve true PUUID. Skipping.")
                     continue
                     
                true_platform_puuid = summoner_data["puuid"]
                summoner_id = summoner_data.get("id")
                
                # Delete the old PENDING row manually since we are replacing its identity
                self.db.get_connection().execute("DELETE FROM Accounts WHERE puuid = ?", (puuid,)).connection.commit()
                
                # Insert the real one with full summoner details immediately
                self.db.upsert_account(
                    puuid=true_platform_puuid, 
                    game_name=game_name, 
                    tag_line=tag_line,
                    summoner_id=summoner_id,
                    summoner_level=summoner_data.get("summonerLevel"),
                    profile_icon_id=summoner_data.get("profileIconId"),
                    login_name=acc["login_name"]
                )
                puuid = true_platform_puuid

            # 2. Update Summoner Profile (Skip if we just did it during resolution)
            else:
                print("   - Fetching Profile...")
                summoner_data = self.riot.get_summoner_by_puuid(platform, puuid)
                summoner_id = None
                if summoner_data:
                    summoner_id = summoner_data.get("id")
                    self.db.upsert_account(
                        puuid=puuid, 
                        game_name=game_name, 
                        tag_line=tag_line,
                        summoner_id=summoner_id,
                        summoner_level=summoner_data.get("summonerLevel"),
                        profile_icon_id=summoner_data.get("profileIconId")
                    )

            # 3. Update Ranks (Now uses PUUID directly)
            print("   - Updating Ranks...")
            old_ranks = self.db.get_full_account_data()
            old_acc_data = next((a for a in old_ranks if a["puuid"] == puuid), {})
            
            ranks_data = self.riot.get_league_entries(platform, puuid)
            if ranks_data is not None:
                self.db.upsert_ranks(puuid, ranks_data)
                new_ranks = self.db.get_full_account_data()
                new_acc_data = next((a for a in new_ranks if a["puuid"] == puuid), {})
                if str(old_acc_data.get('api_solo_duo')) != str(new_acc_data.get('api_solo_duo')) or \
                   str(old_acc_data.get('api_flex')) != str(new_acc_data.get('api_flex')):
                    has_changes = True

            # 4. Delta Sync Matches (Two-Phase Approach)
            print("   - Fetching Match History...")
            known_ids = self.db.get_known_match_ids(puuid)
            oldest_local_time = self.db.get_oldest_local_match_time(puuid)
            
            # --- Phase 1: The Frontier (Delta Sync Forward) ---
            print("     [Phase 1] Syncing Frontier (New Matches)...")
            frontier_start = 0
            count = 100
            
            while True:
                print(f"     -> Requesting matches {frontier_start} to {frontier_start + count}...")
                match_ids = self.riot.get_match_ids(region, puuid, start=frontier_start, count=count)
                
                if not match_ids:
                    print("     -> Reached end of frontier.")
                    break
                    
                new_ids = [m for m in match_ids if m not in known_ids]
                
                if not new_ids and len(match_ids) > 0:
                    print("     -> Connected with known history. Frontier sync complete.")
                    break
                    
                print(f"     -> Found {len(new_ids)} new matches. Downloading...")
                self._download_batch(new_ids, puuid, region)
                has_changes = True
                
                # Update known_ids so Phase 2 doesn't re-download them
                known_ids.update(new_ids)
                
                if len(match_ids) < count:
                    print("     -> Reached end of match history.")
                    break
                    
                frontier_start += count
            
            # --- Phase 2: The Deep Crawl (Backfilling) ---
            # We only do this if we actually have *some* history to crawl back from
            if oldest_local_time is not None:
                print(f"     [Phase 2] Deep Crawl Backwards (From epoch {oldest_local_time})...")
                current_end_time = oldest_local_time - 1 # Start right before our oldest match
                
                while True:
                    print(f"     -> Requesting matches before {current_end_time}...")
                    match_ids = self.riot.get_match_ids(region, puuid, start=0, count=count, end_time=current_end_time)
                    
                    if not match_ids:
                        print("     -> Reached the 2-year API wall or account creation date. Deep crawl complete.")
                        break
                        
                    new_ids = [m for m in match_ids if m not in known_ids]
                    
                    if new_ids:
                        print(f"     -> Found {len(new_ids)} deep historical matches. Downloading...")
                        self._download_batch(new_ids, puuid, region)
                        known_ids.update(new_ids)
                        has_changes = True
                    else:
                        print(f"     -> Found {len(match_ids)} matches, but all are somehow known. Skipping download.")
                    
                    # Find the new oldest time to continue crawling backward
                    # We must open the detail files to get the gameCreation time to walk backwards reliably, 
                    # but if we didn't download any new ones, we can't easily find the *actual* new oldest time 
                    # without re-reading files. Instead, we query our DB for the absolute new minimum.
                    new_oldest_time = self.db.get_oldest_local_match_time(puuid)
                    
                    if new_oldest_time is None or new_oldest_time >= current_end_time:
                        # Safety break if time isn't advancing backward
                        print("     -> [Warning] Time anchor did not move backward. Stopping crawl to prevent loop.")
                        break
                        
                    current_end_time = new_oldest_time - 1
                    time.sleep(0.5) # Courtesy pause between deep crawls

            if progress_callback:
                progress_callback(account_id, "DONE", has_changes, i + 1, total_accounts)

        print("\n" + "="*50)
        print("Synchronization Complete!")
        print("="*50)

    def _download_batch(self, match_ids: list, puuid: str, region: str):
        for m_id in match_ids:
            # Check if the file already exists physically just in case DB is out of sync
            detail_path = RAW_MATCHES_DIR / f"{m_id}.json"
            timeline_path = RAW_TIMELINES_DIR / f"{m_id}.json"
            
            if detail_path.exists() and timeline_path.exists():
                self.db.insert_match_index(m_id, puuid, 0)
                continue
                
            print(f"       -> {m_id}...")
            detail = self.riot.get_match_details(region, m_id)
            time.sleep(0.05)
            
            timeline = self.riot.get_match_timeline(region, m_id)
            time.sleep(0.05)
            
            if detail and timeline:
                # Save to disk
                with open(detail_path, "w", encoding="utf-8") as f:
                    json.dump(detail, f)
                    
                with open(timeline_path, "w", encoding="utf-8") as f:
                    json.dump(timeline, f)
                    
                # Insert index
                creation_time = detail.get("info", {}).get("gameCreation", 0)
                self.db.insert_match_index(m_id, puuid, creation_time)
            else:
                print(f"       [ERROR] Failed to fetch full payload for {m_id}")

if __name__ == "__main__":
    engine = SyncEngine()
    engine.bootstrap_from_old_db()
    engine.sync_all()