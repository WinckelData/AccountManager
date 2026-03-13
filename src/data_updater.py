import time
from dotenv import load_dotenv

from src.api_clients import BlizzardClient
from src.data.database import SessionLocal
from src.data import crud

def get_current_patch():
    """Fetches the current live League of Legends patch from Data Dragon."""
    from src.static_data import StaticDataManager
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


def update_sc2_data(progress_callback=None):
    load_dotenv()
    
    blizz = BlizzardClient()
    if not blizz.access_token:
        print("Failed to authenticate with Blizzard API.")
        return

    print("Fetching live SC2 ranks, GM status, and logging history...\n" + "=" * 60)

    season_cache = {}
    db = SessionLocal()
    
    try:
        accounts = crud.get_tracked_accounts(db, game_type="SC2")
        total_accounts = len(accounts)

        for i, acc in enumerate(accounts):
            original_account_name = acc.account_name
            account_id = f"{original_account_name}_{acc.folder_id or i}"
            has_changes = False

            if progress_callback:
                progress_callback(account_id, "SYNCING", False, i, total_accounts)

            print(f"\nAccount: {original_account_name}")
            best_name = original_account_name

            for profile in acc.sc2_profiles:
                reg = profile.region_id
                rlm = profile.realm_id
                # The DB stores global ID like '2-1-10215683'. The Blizz API wants just '10215683'.
                pid = profile.profile_id.split("-")[-1] if "-" in profile.profile_id else profile.profile_id
                ign = profile.display_name
                reg_name = {1: "NA", 2: "EU", 3: "KR"}.get(reg, "Unknown")

                if reg not in season_cache:
                    season_cache[reg] = blizz.get_current_season(reg)
                current_season = season_cache[reg]

                metadata = blizz.get_profile_metadata(reg, rlm, pid)
                if "summary" in metadata and "displayName" in metadata["summary"]:
                    ign = metadata["summary"]["displayName"]
                    crud.upsert_sc2_profile(db, acc.id, profile.profile_id, reg, rlm, ign)
                    if reg == 2: best_name = ign # Prefer EU name

                print(f"  -> Profile: {ign} ({reg_name} | ID: {pid})")

                summary = blizz.get_ladder_summary(reg, rlm, pid)
                if "error" in summary: continue

                showcase = summary.get("showCaseEntries", [])
                for entry in showcase:
                    team = entry.get("team", {})
                    if team.get("localizedGameMode") != "1v1": continue

                    members = team.get("members", [])
                    if not members: continue

                    race = members[0].get("favoriteRace", "").lower()
                    if race not in ["terran", "zerg", "protoss", "random"]: continue

                    ladder_id = entry.get("ladderId")
                    league = entry.get("leagueName", "UNKNOWN").capitalize()
                    
                    ladder_details = blizz.get_ladder_details(reg, rlm, pid, ladder_id)
                    mmr = 0
                    for ladder_team in ladder_details.get("ladderTeams", []):
                        team_members = ladder_team.get("teamMembers", [])
                        if any(str(m.get("id")) == str(pid) for m in team_members):
                            mmr = ladder_team.get("mmr", 0)
                            break

                    # Upsert Ranks
                    crud.upsert_sc2_ranks(
                        db=db,
                        profile_id=profile.id,
                        season=current_season,
                        race=race,
                        queue_type="1v1",
                        mmr=mmr,
                        league=league
                    )
                    time.sleep(0.1)
                    has_changes = True

                # Upsert Raw Data
                history = profile.raw_data.match_history if profile.raw_data else {}
                crud.upsert_sc2_raw_data(
                    db=db,
                    profile_id=profile.id,
                    profile_summary=metadata.get("summary", {}),
                    ladder_summary=summary,
                    match_history=history # We retain the existing history for now
                )
                
            # Update Account Name if EU profile name changed
            if best_name != original_account_name:
                crud.update_account(db, acc.id, account_name=best_name)
                has_changes = True
                
            db.commit()

            if progress_callback:
                progress_callback(account_id, "DONE", has_changes, i + 1, total_accounts)

    except Exception as e:
        db.rollback()
        print(f"SC2 Sync Error: {e}")
    finally:
        db.close()

    print("\n" + "=" * 60)
    print("SC2 Database successfully updated via ORM!")
