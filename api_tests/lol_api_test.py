import os
import sqlite3
import json
import time
from dotenv import load_dotenv
from pathlib import Path
import sys

# Add parent directory to path so we can import from src
sys.path.append(str(Path(__file__).resolve().parent.parent))

from src.api_clients import RiotClient
from src.config import SQLITE_DB_PATH

def summarize_output(data, max_depth=2, current_depth=0):
    """Recursively summarizes a dictionary/list to show its structure."""
    if current_depth >= max_depth:
        if isinstance(data, dict):
            return "{... " + f"{len(data)} keys" + " ...}"
        elif isinstance(data, list):
            return "[... " + f"{len(data)} items" + " ...]"
        else:
            return type(data).__name__

    if isinstance(data, dict):
        return {k: summarize_output(v, max_depth, current_depth + 1) for k, v in data.items()}
    elif isinstance(data, list):
        if not data:
            return []
        # Just show the structure of the first item
        return [summarize_output(data[0], max_depth, current_depth + 1)] + (["..."] if len(data) > 1 else [])
    else:
        return type(data).__name__

def save_raw_output(filename, data):
    """Saves the raw un-truncated JSON to the output folder."""
    out_dir = Path(__file__).resolve().parent / "output_lol"
    out_dir.mkdir(parents=True, exist_ok=True)
    with open(out_dir / filename, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print(f"    -> Full raw output saved to: output_lol/{filename}")

def run_lol_tests():
    print("="*60)
    print(" LEAGUE OF LEGENDS API TEST & SUMMARY REPORT ")
    print("="*60)
    
    load_dotenv()
    primary_key = os.getenv("RIOT_API_KEY_PRIMARY")
    fallback_key = os.getenv("RIOT_API_KEY_FALLBACK")
    
    if not primary_key:
        print("ERROR: RIOT_API_KEY_PRIMARY not found in .env")
        return
        
    client = RiotClient(primary_key, fallback_key)
    
    # 1. Fetch a sample account from the database
    print("\n[+] Fetching sample data from local database...")
    if not SQLITE_DB_PATH.exists():
        print(f"Database not found at {SQLITE_DB_PATH}. Cannot run dynamic tests.")
        return
        
    conn = sqlite3.connect(SQLITE_DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    cursor.execute("SELECT * FROM Accounts LIMIT 1")
    account = cursor.fetchone()
    
    if not account:
        print("No accounts found in database.")
        conn.close()
        return
        
    game_name = account['game_name']
    tag_line = account['tag_line']
        
    # We'll use hardcoded regions for the sample, or derive from db if possible.
    # The database generally stores standard info. Let's assume standard 'europe' / 'euw1'
    region = "europe"
    platform = "euw1"
    
    print(f"Sample Account: {game_name}#{tag_line}")
    
    endpoints = [
        {
            "name": "Account-V1: Get PUUID by Riot ID",
            "method": "get_puuid_by_riot_id",
            "args": (region, game_name, tag_line),
            "rate_limit": "App Limit (20/1s, 100/2m)",
            "description": "Resolves a player's readable name into a global puuid."
        },
    ]

    # Run the first endpoint to get the global PUUID
    print("\n" + "-"*60)
    print(f"1. {endpoints[0]['name']}")
    print(f"Description: {endpoints[0]['description']}")
    print(f"Rate Limit: {endpoints[0]['rate_limit']}")
    print(f"Input: region='{region}', game_name='{game_name}', tag_line='{tag_line}'")
    
    t0 = time.time()
    account_data = client.get_puuid_by_riot_id(region, game_name, tag_line)
    t1 = time.time()
    
    print(f"Latency: {(t1-t0)*1000:.2f}ms")
    if account_data:
        print("Output Structure:")
        print(json.dumps(summarize_output(account_data), indent=2))
        save_raw_output("1_account_v1.json", account_data)
        global_puuid = account_data.get('puuid')
    else:
        print("Failed to fetch data.")
        return

    # Second endpoint
    print("\n" + "-"*60)
    print("2. Summoner-V4: Get Summoner by PUUID")
    print("Description: Resolves global puuid into a platform puuid and profile info.")
    print("Rate Limit: App Limit")
    print(f"Input: platform='{platform}', puuid='{global_puuid}'")
    
    t0 = time.time()
    summoner_data = client.get_summoner_by_puuid(platform, global_puuid)
    t1 = time.time()
    
    print(f"Latency: {(t1-t0)*1000:.2f}ms")
    if summoner_data:
        print("Output Structure:")
        print(json.dumps(summarize_output(summoner_data), indent=2))
        save_raw_output("2_summoner_v4.json", summoner_data)
        platform_puuid = summoner_data.get('puuid')
    else:
        print("Failed to fetch summoner data.")
        return

    # Use platform_puuid for remaining queries as per Riot best practices
    
    # Third endpoint
    print("\n" + "-"*60)
    print("3. League-V4: Get League Entries")
    print("Description: Returns ranked data (Solo/Duo, Flex).")
    print("Rate Limit: App Limit")
    print(f"Input: platform='{platform}', puuid='{platform_puuid}'")
    
    t0 = time.time()
    league_data = client.get_league_entries(platform, platform_puuid)
    t1 = time.time()
    
    print(f"Latency: {(t1-t0)*1000:.2f}ms")
    if league_data is not None:
        print("Output Structure:")
        print(json.dumps(summarize_output(league_data), indent=2))
        save_raw_output("3_league_v4.json", league_data)
        
    # Fourth endpoint
    print("\n" + "-"*60)
    print("4. Match-V5: Get Match IDs")
    print("Description: Retrieves an array of match IDs played by the specified player.")
    print("Rate Limit: App Limit")
    print(f"Input: region='{region}', puuid='{platform_puuid}', start=0, count=5")
    
    t0 = time.time()
    match_ids = client.get_match_ids(region, platform_puuid, start=0, count=5)
    t1 = time.time()
    
    print(f"Latency: {(t1-t0)*1000:.2f}ms")
    if match_ids is not None:
        print("Output Structure:")
        print(json.dumps(summarize_output(match_ids), indent=2))
        save_raw_output("4_match_ids.json", match_ids)
    
    sample_match_id = match_ids[0] if match_ids else None
    
    # Fifth endpoint
    if sample_match_id:
        print("\n" + "-"*60)
        print("5. Match-V5: Get Match Details")
        print("Description: Returns the detailed JSON blob for a match.")
        print("Rate Limit: App Limit")
        print(f"Input: region='{region}', match_id='{sample_match_id}'")
        
        t0 = time.time()
        match_details = client.get_match_details(region, sample_match_id)
        t1 = time.time()
        
        print(f"Latency: {(t1-t0)*1000:.2f}ms")
        if match_details is not None:
            print("Output Structure (truncated to 3 levels):")
            print(json.dumps(summarize_output(match_details, max_depth=3), indent=2))
            save_raw_output("5_match_details.json", match_details)
            
        # Sixth endpoint
        print("\n" + "-"*60)
        print("6. Match-V5: Get Match Timeline")
        print("Description: Returns minute-by-minute frame data for a match.")
        print("Rate Limit: App Limit")
        print(f"Input: region='{region}', match_id='{sample_match_id}'")
        
        t0 = time.time()
        match_timeline = client.get_match_timeline(region, sample_match_id)
        t1 = time.time()
        
        print(f"Latency: {(t1-t0)*1000:.2f}ms")
        if match_timeline is not None:
            print("Output Structure (truncated to 3 levels):")
            print(json.dumps(summarize_output(match_timeline, max_depth=3), indent=2))
            save_raw_output("6_match_timeline.json", match_timeline)
            
    # Seventh endpoint
    print("\n" + "-"*60)
    print("7. Champion-Mastery-V4: Get Champion Masteries")
    print("Description: Returns mastery points and levels for every champion played.")
    print("Rate Limit: App Limit")
    print(f"Input: platform='{platform}', puuid='{platform_puuid}'")
    
    t0 = time.time()
    masteries = client.get_champion_masteries(platform, platform_puuid)
    t1 = time.time()
    
    print(f"Latency: {(t1-t0)*1000:.2f}ms")
    if masteries is not None:
        print("Output Structure (truncated to 2 levels):")
        print(json.dumps(summarize_output(masteries, max_depth=2), indent=2))
        save_raw_output("7_champion_masteries.json", masteries)

    print("\n" + "="*60)
    print(" LoL API TESTING COMPLETE ")
    print("="*60)

if __name__ == "__main__":
    run_lol_tests()
