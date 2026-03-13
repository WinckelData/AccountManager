import os
import json
import time
from dotenv import load_dotenv
from pathlib import Path
import sys

# Add parent directory to path so we can import from src
sys.path.append(str(Path(__file__).resolve().parent.parent))

from src.api_clients import BlizzardClient
from src.config import SC2_DB_PATH

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
    out_dir = Path(__file__).resolve().parent / "output_sc2"
    out_dir.mkdir(parents=True, exist_ok=True)
    with open(out_dir / filename, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print(f"    -> Full raw output saved to: output_sc2/{filename}")

def run_sc2_tests():
    print("="*60)
    print(" STARCRAFT II API TEST & SUMMARY REPORT ")
    print("="*60)
    
    load_dotenv()
    client_id = os.getenv("BLIZZARD_CLIENT_ID")
    client_secret = os.getenv("BLIZZARD_CLIENT_SECRET")
    
    if not client_id or not client_secret:
        print("ERROR: BLIZZARD_CLIENT_ID or BLIZZARD_CLIENT_SECRET not found in .env")
        return
        
    client = BlizzardClient(client_id, client_secret)
    if not client.access_token:
        print("Failed to authenticate with Blizzard API.")
        return
        
    # 1. Fetch a sample account from the json database
    print("\n[+] Fetching sample data from local database...")
    if not SC2_DB_PATH.exists():
        print(f"Database not found at {SC2_DB_PATH}. Cannot run dynamic tests.")
        return
        
    with open(SC2_DB_PATH, "r", encoding="utf-8") as f:
        db = json.load(f)
        
    accounts = db.get("sc2_accounts", [])
    if not accounts:
        print("No SC2 accounts found in database.")
        return
        
    sample_account = None
    for acc in accounts:
        if acc.get("profiles"):
            sample_account = acc
            break
            
    if not sample_account:
        print("No valid SC2 profiles found.")
        return
        
    profile = sample_account["profiles"][0]
    region_id = profile["region"]
    realm_id = profile["realm"]
    profile_id = profile["profile_id"]
    
    print(f"Sample Profile: Region={region_id}, Realm={realm_id}, Profile={profile_id}")
    
    # First endpoint
    print("\n" + "-"*60)
    print("1. Get Current Season")
    print("Description: Returns data about the current season for a region.")
    print("Rate Limit: Oauth limits (typically 36,000/hour global)")
    print(f"Input: region_id={region_id}")
    
    t0 = time.time()
    season = client.get_current_season(region_id)
    t1 = time.time()
    
    print(f"Latency: {(t1-t0)*1000:.2f}ms")
    if season is not None:
        print("Output Structure:")
        print(f"Season ID: {season}")
        save_raw_output("1_current_season.json", {"seasonId": season})
        
    # Second endpoint
    print("\n" + "-"*60)
    print("2. Get Profile Metadata")
    print("Description: Returns metadata for an individual's profile (displayName, avatar URL).")
    print("Rate Limit: Oauth limits")
    print(f"Input: region_id={region_id}, realm_id={realm_id}, profile_id={profile_id}")
    
    t0 = time.time()
    metadata = client.get_profile_metadata(region_id, realm_id, profile_id)
    t1 = time.time()
    
    print(f"Latency: {(t1-t0)*1000:.2f}ms")
    if metadata:
        print("Output Structure:")
        print(json.dumps(summarize_output(metadata), indent=2))
        save_raw_output("2_profile_metadata.json", metadata)
        
    # Third endpoint
    print("\n" + "-"*60)
    print("3. Get Profile (Base)")
    print("Description: Returns a summary of the player's lifetime statistics.")
    print("Rate Limit: Oauth limits")
    print(f"Input: region_id={region_id}, realm_id={realm_id}, profile_id={profile_id}")
    
    t0 = time.time()
    profile_data = client.get_sc2_profile(region_id, realm_id, profile_id)
    t1 = time.time()
    
    print(f"Latency: {(t1-t0)*1000:.2f}ms")
    if profile_data:
        print("Output Structure (truncated):")
        print(json.dumps(summarize_output(profile_data, max_depth=3), indent=2))
        save_raw_output("3_profile_base.json", profile_data)
        
    # Fourth endpoint
    print("\n" + "-"*60)
    print("4. Get Ladder Summary")
    print("Description: Returns a list of active ladders (1v1, 2v2).")
    print("Rate Limit: Oauth limits")
    print(f"Input: region_id={region_id}, realm_id={realm_id}, profile_id={profile_id}")
    
    t0 = time.time()
    ladder_summary = client.get_ladder_summary(region_id, realm_id, profile_id)
    t1 = time.time()
    
    print(f"Latency: {(t1-t0)*1000:.2f}ms")
    if ladder_summary:
        print("Output Structure:")
        print(json.dumps(summarize_output(ladder_summary, max_depth=3), indent=2))
        save_raw_output("4_ladder_summary.json", ladder_summary)
        
        showcase = ladder_summary.get("showCaseEntries", [])
        if showcase:
            ladder_id = showcase[0].get("ladderId")
            
            # Fifth endpoint
            print("\n" + "-"*60)
            print("5. Get Ladder Details")
            print("Description: Returns the entire ladder bracket for a specific ladderId.")
            print("Rate Limit: Oauth limits")
            print(f"Input: region_id={region_id}, realm_id={realm_id}, profile_id={profile_id}, ladder_id={ladder_id}")
            
            t0 = time.time()
            ladder_details = client.get_ladder_details(region_id, realm_id, profile_id, ladder_id)
            t1 = time.time()
            
            print(f"Latency: {(t1-t0)*1000:.2f}ms")
            if ladder_details:
                print("Output Structure (truncated):")
                print(json.dumps(summarize_output(ladder_details, max_depth=3), indent=2))
                save_raw_output("5_ladder_details.json", ladder_details)

    print("\n" + "="*60)
    print(" SC2 API TESTING COMPLETE ")
    print("="*60)

if __name__ == "__main__":
    run_sc2_tests()
