import os
import requests
import time
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

PRIMARY_KEY = os.getenv("RIOT_API_KEY_PRIMARY")
FALLBACK_KEY = os.getenv("RIOT_API_KEY_FALLBACK")

# We will use Agurin#EUW as a highly active generic test subject if one isn't provided
test_game_name = "Agurin"
test_tag_line = "EUW"
platform = "euw1"  # EUW
region = "europe"  # Europe region routing

print(f"Test Subject: {test_game_name}#{test_tag_line} ({region} / {platform})")
print("=" * 60)

def print_headers(headers):
    app_limit = headers.get("X-App-Rate-Limit", "N/A")
    app_count = headers.get("X-App-Rate-Limit-Count", "N/A")
    method_limit = headers.get("X-Method-Rate-Limit", "N/A")
    method_count = headers.get("X-Method-Rate-Limit-Count", "N/A")
    
    print(f"    [App Limits]    Count: {app_count} | Limit: {app_limit}")
    print(f"    [Method Limits] Count: {method_count} | Limit: {method_limit}")

def test_endpoint(name, url, headers, key_name):
    print(f"\n[{key_name}] Testing {name}...")
    try:
        response = requests.get(url, headers=headers)
        print(f"    -> Status: {response.status_code}")
        
        if response.status_code == 200:
            print_headers(response.headers)
            return response.json()
        elif response.status_code == 403:
            print("    -> Error 403: Forbidden (Check if key is valid or endpoint is enabled)")
            return None
        else:
            print(f"    -> Error: {response.text}")
            return None
    except Exception as e:
        print(f"    -> Exception: {e}")
        return None

def run_suite(key, key_name):
    if not key:
        print(f"\n[!] Key for {key_name} is missing or empty. Skipping.")
        return

    req_headers = {"X-Riot-Token": key}
    
    # 1. Account-V1 (Get PUUID)
    url_account = f"https://{region}.api.riotgames.com/riot/account/v1/accounts/by-riot-id/{test_game_name}/{test_tag_line}"
    account_data = test_endpoint("Account-V1 (Get PUUID)", url_account, req_headers, key_name)
    
    puuid = None
    if account_data and "puuid" in account_data:
        puuid = account_data["puuid"]
        print(f"    -> Extracted PUUID: {puuid[:15]}...")
    else:
        print("    -> Failed to get PUUID, skipping dependent tests.")
        return

    time.sleep(0.5)

    # 2. Summoner-V4
    url_summoner = f"https://{platform}.api.riotgames.com/lol/summoner/v4/summoners/by-puuid/{puuid}"
    summoner_data = test_endpoint("Summoner-V4", url_summoner, req_headers, key_name)
    
    summoner_id = None
    if summoner_data and "id" in summoner_data:
        summoner_id = summoner_data["id"]

    time.sleep(0.5)

    # 3. League-V4
    if summoner_id:
        url_league = f"https://{platform}.api.riotgames.com/lol/league/v4/entries/by-summoner/{summoner_id}"
        test_endpoint("League-V4", url_league, req_headers, key_name)

    time.sleep(0.5)

    # 4. Match-V5 (Get IDs)
    url_match_ids = f"https://{region}.api.riotgames.com/lol/match/v5/matches/by-puuid/{puuid}/ids?start=0&count=5"
    match_ids = test_endpoint("Match-V5 (Get IDs)", url_match_ids, req_headers, key_name)

    match_id = None
    if match_ids and len(match_ids) > 0:
        match_id = match_ids[0]
        print(f"    -> Extracted Match ID: {match_id}")
    
    time.sleep(0.5)

    # 5. Match-V5 (Get Details)
    if match_id:
        url_match_detail = f"https://{region}.api.riotgames.com/lol/match/v5/matches/{match_id}"
        test_endpoint("Match-V5 (Match Detail)", url_match_detail, req_headers, key_name)
        
        time.sleep(0.5)
        
        # 6. Match-V5 (Get Timeline)
        url_timeline = f"https://{region}.api.riotgames.com/lol/match/v5/matches/{match_id}/timeline"
        test_endpoint("Match-V5 (Timeline)", url_timeline, req_headers, key_name)

    time.sleep(0.5)

    # 7. Champion-Mastery-V4
    url_mastery = f"https://{platform}.api.riotgames.com/lol/champion-mastery/v4/champion-masteries/by-puuid/{puuid}/top?count=3"
    test_endpoint("Champion-Mastery-V4", url_mastery, req_headers, key_name)

    time.sleep(0.5)

    # 8. Spectator-V5
    url_spectator = f"https://{platform}.api.riotgames.com/lol/spectator/v5/active-games/by-summoner/{puuid}"
    test_endpoint("Spectator-V5 (Active Game)", url_spectator, req_headers, key_name)

    print("-" * 60)

if __name__ == "__main__":
    print("Starting API Test Suite...\n")
    run_suite(PRIMARY_KEY, "PRIMARY_KEY (Dev)")
    
    print("\nWaiting 2 seconds before testing fallback key...")
    time.sleep(2)
    
    run_suite(FALLBACK_KEY, "FALLBACK_KEY (Restricted)")
    
    print("\nAPI Testing Complete!")
