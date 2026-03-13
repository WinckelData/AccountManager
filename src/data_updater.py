import json
import time
import os
import requests
from src.config import LOL_DB_PATH, SC2_DB_PATH
from src.api_clients import RiotClient, BlizzardClient
from src.static_data import StaticDataManager

def get_current_patch():
    """Fetches the current live League of Legends patch from Data Dragon."""
    return StaticDataManager().get_latest_version() or "Unknown"

def calculate_decay_bank(puuid, match_history, queue_type):
    """
    Simulates the decay bank for Diamond+ accounts over the last 30 days.
    match_history: List of rich match JSON objects.
    queue_type: 420 for Solo/Duo, 440 for Flex.
    """
    if not match_history:
        return 0
        
    # Filter matches for the specific queue and sort by time (oldest first)
    valid_matches = []
    for m in match_history:
        info = m.get("info", {})
        if info.get("queueId") == queue_type:
            valid_matches.append(info.get("gameCreation", 0) / 1000) # Convert ms to seconds
            
    valid_matches.sort()
    
    if not valid_matches:
        return 0

    now = time.time()
    thirty_days_ago = now - (30 * 24 * 3600)
    
    # We only care about matches played in the last 30 days for current bank simulation
    recent_matches = [m for m in valid_matches if m > thirty_days_ago]
    
    return recent_matches

def update_lol_data():
    """
    DEPRECATED: This function used the old lol_database.json architecture.
    League of Legends data synchronization is now handled entirely by `src.sync_engine.SyncEngine`.
    """
    raise NotImplementedError("update_lol_data is deprecated. Use SyncEngine().sync_all() instead.")

def update_sc2_data(progress_callback=None):
    from dotenv import load_dotenv
    load_dotenv()
    try:
        with open(SC2_DB_PATH, "r", encoding="utf-8") as f:
            db = json.load(f)
    except FileNotFoundError:
        print("sc2_database.json not found!")
        return

    blizz = BlizzardClient()
    if not blizz.access_token:
        print("Failed to authenticate with Blizzard API. Check your .env file!")
        return

    print("Fetching live SC2 ranks, GM status, and logging history...\n" + "=" * 60)

    season_cache = {}

    accounts_list = db.get("sc2_accounts", [])
    total_accounts = len(accounts_list)

    for i, account in enumerate(accounts_list):
        original_account_name = account.get("account_name", "Unknown")
        # Ensure duplicate account names don't overwrite each other in UI state
        account_id = f"{original_account_name}_{account.get('account_folder_id', i)}"
        has_changes = False

        if progress_callback:
            progress_callback(account_id, "SYNCING", False, i, total_accounts)

        print(f"\nAccount: {original_account_name}")

        for profile in account.get("profiles", []):
            reg = profile["region"]
            rlm = profile["realm"]
            pid = profile["profile_id"]
            ign = profile.get("in_game_name", "Unknown")
            reg_name = {1: "NA", 2: "EU", 3: "KR"}.get(reg, "Unknown")

            if reg not in season_cache:
                season_cache[reg] = blizz.get_current_season(reg)
            current_season = season_cache[reg]
            season_tag = f"Season {current_season}"

            # Always fetch the base profile first to guarantee we get the true displayName
            metadata = blizz.get_profile_metadata(reg, rlm, pid)
            if "summary" in metadata and "displayName" in metadata["summary"]:
                display_name = metadata["summary"]["displayName"]
                profile["in_game_name"] = display_name
                ign = display_name
            
            print(f"  -> Profile: {ign} ({reg_name} | ID: {pid})")

            summary = blizz.get_ladder_summary(reg, rlm, pid)
            if "error" in summary:
                print(f"     [!] {summary['error']}")
                continue

            ranks = {} # Start empty, don't pre-fill with Unranked

            showcase = summary.get("showCaseEntries", [])
            for entry in showcase:
                team = entry.get("team", {})

                if team.get("localizedGameMode") != "1v1":
                    continue

                members = team.get("members", [])
                if not members: continue

                race = members[0].get("favoriteRace", "").lower()
                if race not in ["terran", "zerg", "protoss", "random"]: continue

                ladder_id = entry.get("ladderId")
                league = entry.get("leagueName", "UNKNOWN").capitalize()
                wins = entry.get("wins", 0)
                losses = entry.get("losses", 0)
                ladder_rank = entry.get("rank", 0)

                ladder_details = blizz.get_ladder_details(reg, rlm, pid, ladder_id)
                mmr = 0

                for ladder_team in ladder_details.get("ladderTeams", []):
                    team_members = ladder_team.get("teamMembers", [])
                    if any(str(m.get("id")) == str(pid) for m in team_members):
                        mmr = ladder_team.get("mmr", 0)
                        break

                ranks[race] = {
                    "league": league,
                    "mmr": mmr,
                    "wins": wins,
                    "losses": losses,
                    "rank": ladder_rank
                }

                time.sleep(0.1)

            profile["ranks"] = ranks

            if "history" not in profile:
                profile["history"] = {}

            if ranks:
                current_history = profile["history"].get(season_tag, {})
                if current_history != ranks:
                    has_changes = True
                    profile["history"][season_tag] = ranks
                    for r_name, data in ranks.items():
                        rank_str = f" (Rank {data['rank']})" if data['league'] == "Grandmaster" else ""
                        print(f"     - {r_name.capitalize()}: {data['league']}{rank_str} | MMR: {data['mmr']} | {data['wins']}W - {data['losses']}L")
                    print(f"     -> [History updated for {season_tag}]")
                else:
                    for r_name, data in ranks.items():
                        rank_str = f" (Rank {data['rank']})" if data['league'] == "Grandmaster" else ""
                        print(f"     - {r_name.capitalize()}: {data['league']}{rank_str} | MMR: {data['mmr']} | {data['wins']}W - {data['losses']}L")
                    print(f"     -> [No rank changes for {season_tag}]")
            else:
                print("     - No ranked 1v1 data for this season.")

        # Determine best display name for the whole account (Prefer EU)
        best_name = account.get("account_name", "Unknown")
        for p in account.get("profiles", []):
            if p.get("region") == 2: # EU
                best_name = p.get("in_game_name", best_name)
                break
        
        # If no EU, just take the first profile's name
        if best_name == "Unknown" and account.get("profiles"):
            best_name = account["profiles"][0].get("in_game_name", "Unknown")
            
        if best_name != original_account_name:
            has_changes = True
            
        account["account_name"] = best_name
        
        if has_changes:
            with open(SC2_DB_PATH, "w", encoding="utf-8") as f:
                json.dump(db, f, indent=4, ensure_ascii=False)

        if progress_callback:
            progress_callback(account_id, "DONE", has_changes, i + 1, total_accounts)

    with open(SC2_DB_PATH, "w", encoding="utf-8") as f:
        json.dump(db, f, indent=4, ensure_ascii=False)

    print("\n" + "=" * 60)
    print("SC2 Database successfully updated & history recorded!")
