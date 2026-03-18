import io
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dotenv import load_dotenv

from src.sc2.api_client import BlizzardClient
from src.data.database import SessionLocal
from src.data import crud
from src.config import NUM_WORKERS_SC2

_print_lock = threading.Lock()


def _retry_commit(db, buf, max_retries=3):
    """Commit with retry on database locked errors."""
    delays = [2, 5, 10]
    for attempt in range(max_retries + 1):
        try:
            db.commit()
            return
        except Exception as e:
            if "database is locked" in str(e) and attempt < max_retries:
                db.rollback()
                print(f"  [RETRY] Database locked, retrying in {delays[attempt]}s...", file=buf)
                time.sleep(delays[attempt])
            else:
                raise


def get_current_patch():
    """Fetches the current live League of Legends patch from Data Dragon."""
    from src.static_data import StaticDataManager
    return StaticDataManager().get_latest_version() or "Unknown"


def _sync_single_sc2(account_dict, blizz, season_cache, gm_cache, progress_callback, total_accounts):
    """
    Sync a single SC2 account. Called from worker threads.
    Returns True if any changes were made.
    Output is buffered per-worker and printed atomically.
    """
    buf = io.StringIO()
    db = SessionLocal()
    try:
        acc_id = account_dict["account_id"]
        original_account_name = account_dict["account_name"]
        folder_id = account_dict["folder_id"]
        profiles = account_dict["profiles"]
        account_id_str = f"{original_account_name}_{folder_id or acc_id}"
        has_changes = False

        if progress_callback:
            progress_callback(account_id_str, "SYNCING", False, 0, total_accounts)

        print(f"\nAccount: {original_account_name}", file=buf)
        best_name = original_account_name

        for profile_dict in profiles:
            reg = profile_dict["region_id"]
            rlm = profile_dict["realm_id"]
            pid = profile_dict["profile_id"].split("-")[-1] if "-" in profile_dict["profile_id"] else profile_dict["profile_id"]
            ign = profile_dict["display_name"]
            profile_db_id = profile_dict["id"]
            reg_name = {1: "NA", 2: "EU", 3: "KR"}.get(reg, "Unknown")

            current_season = season_cache.get(reg)
            is_gm = str(pid) in gm_cache.get(reg, set())

            metadata = blizz.get_profile_metadata(reg, rlm, pid)
            if "summary" in metadata and "displayName" in metadata["summary"]:
                ign = metadata["summary"]["displayName"]
                crud.upsert_sc2_profile(db, acc_id, profile_dict["profile_id"], reg, rlm, ign)
                if reg == 2:
                    best_name = ign

            print(f"  -> Profile: {ign} ({reg_name} | ID: {pid}){' [GM]' if is_gm else ''}", file=buf)

            summary = blizz.get_ladder_summary(reg, rlm, pid)
            if "error" not in summary:
                showcase = summary.get("showCaseEntries", [])
                for entry in showcase:
                    team = entry.get("team", {})
                    if team.get("localizedGameMode") != "1v1":
                        continue

                    members = team.get("members", [])
                    if not members:
                        continue

                    race = members[0].get("favoriteRace", "").lower()
                    if race not in ["terran", "zerg", "protoss", "random"]:
                        continue

                    ladder_id = entry.get("ladderId")
                    league = entry.get("leagueName", "UNKNOWN").capitalize()

                    ladder_details = blizz.get_ladder_details(reg, rlm, pid, ladder_id)
                    mmr = 0
                    for ladder_team in ladder_details.get("ladderTeams", []):
                        team_members = ladder_team.get("teamMembers", [])
                        if any(str(m.get("id")) == str(pid) for m in team_members):
                            mmr = ladder_team.get("mmr", 0)
                            break

                    rank_changed = crud.upsert_sc2_ranks(
                        db=db,
                        profile_id=profile_db_id,
                        season=current_season,
                        race=race,
                        queue_type="1v1",
                        mmr=mmr,
                        league=league,
                        is_grandmaster=is_gm,
                    )
                    if rank_changed:
                        has_changes = True

                # showCaseEntries is capped at 3 — fetch any extra 1v1 ladders from allLadderMemberships
                processed_ladder_ids = {entry.get("ladderId") for entry in showcase
                                        if entry.get("team", {}).get("localizedGameMode") == "1v1"}
                for membership in summary.get("allLadderMemberships", []):
                    if not membership.get("localizedGameMode", "").startswith("1v1"):
                        continue
                    m_ladder_id = membership.get("ladderId")
                    if m_ladder_id in processed_ladder_ids:
                        continue

                    ladder_details = blizz.get_ladder_details(reg, rlm, pid, m_ladder_id)
                    for ladder_team in ladder_details.get("ladderTeams", []):
                        team_members = ladder_team.get("teamMembers", [])
                        if any(str(m.get("id")) == str(pid) for m in team_members):
                            mmr = ladder_team.get("mmr", 0)
                            race = team_members[0].get("favoriteRace", "").lower()
                            if race not in ("terran", "zerg", "protoss", "random"):
                                break
                            league = membership.get("localizedGameMode", "").split(" ", 1)[-1].capitalize()
                            rank_changed = crud.upsert_sc2_ranks(
                                db=db,
                                profile_id=profile_db_id,
                                season=current_season,
                                race=race,
                                queue_type="1v1",
                                mmr=mmr,
                                league=league,
                                is_grandmaster=is_gm,
                            )
                            if rank_changed:
                                has_changes = True
                            break

            # Fetch live match history (last 25 matches)
            print(f"  -> Fetching match history for {ign}...", file=buf)
            live_history = blizz.get_match_history(reg, rlm, pid)

            # Store raw data
            crud.upsert_sc2_raw_data(
                db=db,
                profile_id=profile_db_id,
                profile_summary=metadata.get("summary", {}),
                ladder_summary=summary,
                match_history=live_history if live_history else {},
            )

            # Extract structured SC2 matches
            if live_history:
                n = crud.upsert_sc2_matches(db, profile_db_id, live_history)
                if n:
                    print(f"  -> Upserted {n} new SC2 match records for {ign}", file=buf)

            # Commit after each profile to minimize transaction hold time
            _retry_commit(db, buf)

        # Update Account Name if EU profile name changed
        if best_name != original_account_name:
            crud.update_account(db, acc_id, account_name=best_name)
            _retry_commit(db, buf)
            has_changes = True
        return account_id_str, has_changes

    except Exception as e:
        db.rollback()
        print(f"  [ERROR] Sync failed for {account_dict['account_name']}: {e}", file=buf)
        return account_dict.get("account_name", "unknown"), False
    finally:
        db.close()
        with _print_lock:
            print(buf.getvalue(), end="")


def update_sc2_data(progress_callback=None):
    load_dotenv()

    blizz = BlizzardClient()
    if not blizz.access_token:
        print("Failed to authenticate with Blizzard API.")
        return

    print("Fetching live SC2 ranks, GM status, and logging history...\n" + "=" * 60)

    db = SessionLocal()
    try:
        accounts = crud.get_tracked_accounts(db, game_type="SC2")

        # Pre-populate season and GM caches (region-level, shared across workers)
        season_cache = {}
        gm_cache = {}
        regions_seen = set()
        for acc in accounts:
            for profile in acc.sc2_profiles:
                regions_seen.add(profile.region_id)

        import json

        def _fetch_region_data(reg):
            """Fetch season + GM ladder for one region in parallel."""
            reg_name = {1: "NA", 2: "EU", 3: "KR"}.get(reg, "Unknown")
            print(f"  -> Fetching season + GM ladder for region {reg_name}...")
            season_data = blizz.get_current_season(reg)
            season_id = season_data.get("seasonId") if season_data else None
            gm_data = blizz.get_grandmaster_ladder(reg)
            gm_ids = set()
            gm_mmrs = []
            for team in gm_data.get("ladderTeams", []):
                mmr_val = team.get("mmr", 0)
                if mmr_val > 0:
                    gm_mmrs.append(mmr_val)
                for member in team.get("teamMembers", []):
                    gm_ids.add(str(member.get("id", "")))
            return reg, season_id, gm_ids, gm_mmrs, season_data

        with ThreadPoolExecutor(max_workers=len(regions_seen)) as region_pool:
            for reg, season_id, gm_ids, gm_mmrs, season_data in region_pool.map(_fetch_region_data, regions_seen):
                season_cache[reg] = season_id
                gm_cache[reg] = gm_ids
                if gm_mmrs:
                    sorted_mmrs = sorted(gm_mmrs, reverse=True)
                    s_start = season_data.get("startDate") if season_data else None
                    s_end = season_data.get("endDate") if season_data else None
                    crud.upsert_sc2_gm_threshold(
                        db, reg, min(gm_mmrs), json.dumps(sorted_mmrs),
                        season_id=season_id, season_start=s_start, season_end=s_end,
                    )
        db.commit()

        # Build account dicts (eager-load to avoid DetachedInstanceError in workers)
        account_dicts = []
        for acc in accounts:
            account_dicts.append({
                "account_id": acc.id,
                "account_name": acc.account_name,
                "folder_id": acc.folder_id,
                "profiles": [
                    {
                        "id": p.id,
                        "profile_id": p.profile_id,
                        "region_id": p.region_id,
                        "realm_id": p.realm_id,
                        "display_name": p.display_name,
                    }
                    for p in acc.sc2_profiles
                ],
            })
    finally:
        db.close()

    if not account_dicts:
        print("No tracked SC2 accounts found.")
        return

    total_accounts = len(account_dicts)
    completed = [0]
    completed_lock = threading.Lock()

    def wrapped_progress(account_id_str, status, has_changes, _cur, _tot):
        if progress_callback:
            with completed_lock:
                cur = completed[0]
                if status == "DONE":
                    completed[0] += 1
                    cur = completed[0]
            progress_callback(account_id_str, status, has_changes, cur, total_accounts)

    # Parallel sync: up to NUM_WORKERS_SC2 workers (Blizzard limits are 100 req/s, each account ~10-15 calls)
    num_workers = min(NUM_WORKERS_SC2, total_accounts)
    print(f"[SC2 Sync] {total_accounts} accounts, {num_workers} worker(s)\n" + "=" * 60)

    with ThreadPoolExecutor(max_workers=num_workers) as executor:
        futures = {
            executor.submit(
                _sync_single_sc2,
                acc_dict, blizz, season_cache, gm_cache, wrapped_progress, total_accounts
            ): acc_dict
            for acc_dict in account_dicts
        }
        for future in as_completed(futures):
            account_id_str, has_changes = future.result()
            wrapped_progress(account_id_str, "DONE", has_changes, 0, total_accounts)

    print("\n" + "=" * 60)
    print("SC2 Database successfully updated via ORM!")