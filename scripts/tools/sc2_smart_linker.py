import os
import json
import re
from pathlib import Path

# Fix relative path finding to locate data folder correctly when run as a script
BASE_DIR = Path(__file__).resolve().parent.parent.parent
SC2_DB_PATH = BASE_DIR / "data" / "sc2_database.json"

def get_local_account_folders():
    """Scans the SC2 Documents directory for root account folders."""
    base_dir = os.path.expanduser('~/Documents/StarCraft II/Accounts')
    folders = {}
    if os.path.exists(base_dir):
        for item in os.listdir(base_dir):
            full_path = os.path.join(base_dir, item)
            if os.path.isdir(full_path) and item.isdigit():
                profiles = []
                for root, dirs, files in os.walk(full_path):
                    match = re.search(r'(\d)-S2-(\d)-(\d+)', root)
                    if match:
                        reg_id, rlm_id, prof_id = int(match.group(1)), int(match.group(2)), int(match.group(3))
                        if not any(p['region'] == reg_id and p['profile_id'] == prof_id for p in profiles):
                            profiles.append({
                                "region": reg_id,
                                "realm": rlm_id,
                                "profile_id": prof_id
                            })
                if profiles:
                    folders[item] = profiles
    return folders

def interactive_smart_link():
    try:
        with open(SC2_DB_PATH, "r", encoding="utf-8") as f:
            db = json.load(f)
    except FileNotFoundError:
        print("sc2_database.json not found! Ensure you have run the app at least once.")
        return

    print("\n" + "=" * 65)
    print(" SC2 SMART FOLDER-TO-EMAIL LINKING TOOL ")
    print("=" * 65)

    local_folders = get_local_account_folders()
    if not local_folders:
        print("No SC2 Account folders found in your Documents directory.")
        return

    existing_accounts = db.get("sc2_accounts", [])
    
    # Restructure accounts safely to avoid duplicates
    new_accounts = []
    used_emails = set()
    unmapped_accounts = existing_accounts.copy()
    
    for folder_id, profiles in local_folders.items():
        print(f"\n[Folder ID: {folder_id}] - Found {len(profiles)} profiles.")
        
        # Try to guess email from existing db if any profile ID matches
        guessed_email = None
        guessed_alias = None
        existing_profiles_map = {} # Map to keep existing data
        
        for acc in existing_accounts:
            for existing_prof in acc.get("profiles", []):
                existing_profiles_map[str(existing_prof["profile_id"])] = existing_prof
                
                if not guessed_email and any(str(p["profile_id"]) == str(existing_prof["profile_id"]) for p in profiles):
                    guessed_email = acc.get("email")
                    guessed_alias = acc.get("account_name")
                    # Mark this legacy account as mapped so we don't warn about it later
                    unmapped_accounts = [ua for ua in unmapped_accounts if ua.get("email") != guessed_email]
        
        if guessed_email:
            print(f"-> Auto-matched to Email: {guessed_email} (Alias: {guessed_alias})")
            confirm = input("Press Enter to confirm or type a new email: ").strip()
            if confirm:
                email = confirm
                alias = guessed_alias if confirm == guessed_email else "Unknown"
            else:
                email = guessed_email
                alias = guessed_alias
        else:
            email = input(f"-> No match found. Enter the Email for this account: ").strip()
            if not email:
                print("Skipping folder.")
                continue
            alias = input("Enter an Alias (Optional UI Name) or press Enter for 'Unknown': ").strip() or "Unknown"

        # Duplicate check
        if email in used_emails:
            print(f"   [!] WARNING: The email '{email}' is already linked to another folder! An email must be unique.")
            print(f"   [!] Skipping this folder to prevent database corruption.")
            continue
            
        used_emails.add(email)

        # Attach standard properties to the profiles, preserving old data if it exists
        enriched_profiles = []
        for p in profiles:
            prof_str_id = str(p["profile_id"])
            if prof_str_id in existing_profiles_map:
                # Merge existing data
                old_p = existing_profiles_map[prof_str_id]
                p["in_game_name"] = old_p.get("in_game_name", alias)
                # Keep existing ranks if they exist and aren't full of empty defaults
                old_ranks = old_p.get("ranks", {})
                if old_ranks and any(v.get("league") != "Unranked" for k, v in old_ranks.items()):
                    # Strip out unranked defaults if they were saved in the old system
                    cleaned_ranks = {k: v for k, v in old_ranks.items() if v.get("league") != "Unranked"}
                    p["ranks"] = cleaned_ranks
                else:
                    p["ranks"] = {}
                
                if "history" in old_p:
                    p["history"] = old_p["history"]
            else:
                p["in_game_name"] = alias
                p["ranks"] = {}
            enriched_profiles.append(p)
            
        new_accounts.append({
            "game": "SC2",
            "account_name": alias,
            "email": email,
            "account_folder_id": folder_id,
            "profiles": enriched_profiles
        })

    # Save exactly what was mapped from folders, throwing out unmapped legacy data.
    with open(SC2_DB_PATH, "w", encoding="utf-8") as f:
        json.dump({"sc2_accounts": new_accounts}, f, indent=4, ensure_ascii=False)

    print("\n" + "=" * 65)
    print("SC2 Database successfully rebuilt based on folder mapping!")
    
    if unmapped_accounts:
        print("\n" + "!" * 65)
        print(" WARNING: UNMAPPED LEGACY ACCOUNTS FOUND ")
        print("!" * 65)
        print("The following accounts existed in your old database but could not be mapped")
        print("to a local folder in Documents/StarCraft II/Accounts. They have NOT been saved.")
        for ua in unmapped_accounts:
            print(f"- Email: {ua.get('email')} | Alias: {ua.get('account_name')}")
            for p in ua.get("profiles", []):
                print(f"   -> ID: {p.get('profile_id')} (Reg: {p.get('region')})")

if __name__ == "__main__":
    interactive_smart_link()