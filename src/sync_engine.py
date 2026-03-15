import os
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dotenv import load_dotenv

from src.api_clients import RiotClient
from src.data.database import SessionLocal
from src.data import crud
from src.data.models import LoLMatch


class SyncEngine:
    def __init__(self, use_fallback_key=False):
        load_dotenv()
        primary = os.getenv("RIOT_API_KEY_PRIMARY")
        fallback = os.getenv("RIOT_API_KEY_FALLBACK") if use_fallback_key else None
        self.riot = RiotClient(primary_key=primary, fallback_key=fallback)
        self._progress_lock = threading.Lock()
        self._completed_count = 0

    def _map_region(self, tag_line: str) -> tuple[str, str]:
        tag = tag_line.upper()
        if tag in ["EUW", "EUW1", "EUNE"]:
            return "europe", "euw1" if tag in ["EUW", "EUW1"] else "eun1"
        elif tag in ["NA", "NA1"]:
            return "americas", "na1"
        elif tag in ["KR", "KR1"]:
            return "asia", "kr"
        return "europe", "euw1"

    def sync_all(self, progress_callback=None):
        print("\n" + "=" * 50)
        print("Starting LoL Data Synchronization...")
        print("=" * 50)

        db = SessionLocal()
        try:
            accounts = list(crud.get_tracked_accounts(db, game_type="LOL"))
            # Eagerly extract account data while session is open to avoid
            # DetachedInstanceError when workers access lazy-loaded relationships.
            account_dicts = []
            for acc in accounts:
                if not acc.lol_profile:
                    continue
                account_dicts.append({
                    "account_id": acc.id,
                    "account_name": acc.account_name,
                    "profile_id": acc.lol_profile.id,
                    "game_name": acc.lol_profile.game_name,
                    "tag_line": acc.lol_profile.tag_line,
                    "puuid": acc.lol_profile.puuid,
                })
        finally:
            db.close()

        if not account_dicts:
            print("No tracked accounts found.")
            return

        total = len(account_dicts)
        self._completed_count = 0

        num_workers = min(2, len(self.riot.keys), total)
        print(f"[SyncEngine] {total} accounts, {num_workers} worker(s)")

        if num_workers <= 1:
            client = RiotClient(primary_key=self.riot.keys[0].key)
            self._sync_batch(account_dicts, client, progress_callback, total)
        else:
            batches = [[], []]
            for i, acc in enumerate(account_dicts):
                batches[i % 2].append(acc)

            clients = [
                RiotClient(primary_key=self.riot.keys[0].key),
                RiotClient(primary_key=self.riot.keys[1].key),
            ]

            with ThreadPoolExecutor(max_workers=2) as executor:
                futures = [
                    executor.submit(self._sync_batch, batches[i], clients[i], progress_callback, total)
                    for i in range(2)
                    if batches[i]
                ]
                for f in as_completed(futures):
                    f.result()

        print("\n" + "=" * 50)
        print("Synchronization Complete!")
        print("=" * 50)

    def _sync_batch(self, accounts, client, progress_callback, total):
        db = SessionLocal()
        try:
            for acc in accounts:
                self._sync_single(db, client, acc, progress_callback, total)
        except Exception as e:
            db.rollback()
            print(f"[SyncEngine] Batch error: {e}")
            raise
        finally:
            db.close()

    def _sync_single(self, db, client, acc, progress_callback, total):
        game_name = acc["game_name"]
        tag_line = acc["tag_line"]
        puuid = acc["puuid"]
        profile_id = acc["profile_id"]
        has_changes = False

        with self._progress_lock:
            current_idx = self._completed_count

        if progress_callback:
            progress_callback(game_name, "SYNCING", False, current_idx, total)

        print(f"\n>> Syncing: {game_name}#{tag_line}")
        region, platform = self._map_region(tag_line)

        # 1. Resolve / Verify PUUID
        if puuid.startswith("PENDING_"):
            print("   - Resolving Riot ID to Global PUUID...")
            account_data = client.get_puuid_by_riot_id(region, game_name, tag_line)
            if not account_data or "puuid" not in account_data:
                print("     [ERROR] Failed to resolve Riot ID. Skipping.")
                return

            global_puuid = account_data["puuid"]
            print("   - Requesting true Platform PUUID from Summoner-V4...")
            summoner_data = client.get_summoner_by_puuid(platform, global_puuid)
            if not summoner_data or "puuid" not in summoner_data:
                return

            puuid = summoner_data["puuid"]
            summoner_id = summoner_data.get("id")

            # Update the PENDING stub's PUUID in-place so the upsert's
            # ON CONFLICT(puuid) will match, preserving any related rows.
            from src.data.models import LoLProfile
            db.query(LoLProfile).filter(LoLProfile.id == profile_id).update(
                {"puuid": puuid}
            )
            db.flush()

            crud.upsert_lol_profile(
                db=db,
                account_id=acc["account_id"],
                puuid=puuid,
                game_name=game_name,
                tag_line=tag_line,
                summoner_id=summoner_id,
                summoner_level=summoner_data.get("summonerLevel"),
                profile_icon_id=summoner_data.get("profileIconId"),
            )
            db.commit()

        # 2. Update Summoner Profile
        else:
            print("   - Fetching Profile...")
            summoner_data = client.get_summoner_by_puuid(platform, puuid)
            if not summoner_data:
                # Stored PUUID is stale — re-resolve from Riot ID
                print(f"   - Stored PUUID failed. Re-resolving from Riot ID...")
                account_data = client.get_puuid_by_riot_id(region, game_name, tag_line)
                if not account_data or "puuid" not in account_data:
                    print("     [ERROR] Re-resolution failed. Skipping account.")
                    return
                new_puuid = account_data["puuid"]
                if new_puuid == puuid:
                    print("     [ERROR] Re-resolved same PUUID. API key issue? Skipping.")
                    return
                summoner_data = client.get_summoner_by_puuid(platform, new_puuid)
                if not summoner_data:
                    print("     [ERROR] New PUUID also failed Summoner-V4. Skipping.")
                    return
                puuid = new_puuid
                print(f"   - PUUID updated successfully.")

                # Update the PUUID in-place to preserve ranks, masteries,
                # and match participations (avoid cascade-delete).
                from src.data.models import LoLProfile
                db.query(LoLProfile).filter(LoLProfile.id == profile_id).update(
                    {"puuid": puuid}
                )
                db.flush()

            crud.upsert_lol_profile(
                db=db,
                account_id=acc["account_id"],
                puuid=puuid,
                game_name=game_name,
                tag_line=tag_line,
                summoner_id=summoner_data.get("id"),
                summoner_level=summoner_data.get("summonerLevel"),
                profile_icon_id=summoner_data.get("profileIconId"),
            )
            db.commit()

        # 3. Update Ranks
        print("   - Updating Ranks...")
        ranks_data = client.get_league_entries(platform, puuid)
        if ranks_data is not None:
            for r in ranks_data:
                queue_type = r.get("queueType")
                if queue_type in ["RANKED_SOLO_5x5", "RANKED_FLEX_SR"]:
                    crud.upsert_lol_ranks(
                        db=db,
                        profile_id=profile_id,
                        queue_type=queue_type,
                        tier=r.get("tier", "UNRANKED"),
                        rank=r.get("rank", ""),
                        lp=r.get("leaguePoints", 0),
                        wins=r.get("wins", 0),
                        losses=r.get("losses", 0),
                    )
            db.commit()
            has_changes = True

        # 4. Check in-game status (Spectator-V5)
        print("   - Checking in-game status...")
        active_game = client.get_active_game(platform, puuid)
        is_in_game = active_game is not None and "gameId" in active_game
        game_start = active_game.get("gameStartTime") if active_game else None
        game_queue_id = active_game.get("gameQueueConfigId") if active_game else None
        crud.set_lol_in_game_status(db, profile_id, is_in_game, game_start, current_game_queue_id=game_queue_id)
        db.commit()
        if is_in_game:
            print(f"   - [LIVE] {game_name} is currently in a game!")

        # 5. Update Champion Masteries
        print("   - Updating Champion Masteries...")
        masteries_data = client.get_champion_masteries(platform, puuid)
        if masteries_data:
            parsed_masteries = [
                {
                    "champion_id": m.get("championId"),
                    "mastery_level": m.get("championLevel", 0),
                    "champion_points": m.get("championPoints", 0),
                    "last_play_time": m.get("lastPlayTime", 0),
                }
                for m in masteries_data
            ]
            crud.upsert_lol_masteries(db, profile_id, parsed_masteries)
            db.commit()

        # 6. Delta Sync Matches
        print("   - Fetching Match History...")
        known_ids = set(crud.get_lol_match_ids(db, profile_id))

        oldest_match = (
            db.query(LoLMatch)
            .join(LoLMatch.participations)
            .filter(LoLMatch.participations.any(profile_id=profile_id))
            .order_by(LoLMatch.game_creation.asc())
            .first()
        )
        oldest_local_time = oldest_match.game_creation if oldest_match else None

        # Phase 1: Frontier (new matches)
        print("     [Phase 1] Syncing Frontier (New Matches)...")
        frontier_start = 0
        count = 100
        total_frontier_ids = 0
        while True:
            match_ids = client.get_match_ids(region, puuid, start=frontier_start, count=count)
            if not match_ids:
                break
            new_ids = [m for m in match_ids if m not in known_ids]
            if not new_ids and len(match_ids) > 0:
                break
            total_frontier_ids += len(new_ids)
            print(f"     Found {len(new_ids)} new match IDs (batch at offset {frontier_start})")
            self._download_batch(db, profile_id, puuid, new_ids, region, client)
            has_changes = True
            known_ids.update(new_ids)
            if len(match_ids) < count:
                break
            frontier_start += count
        print(f"     [Phase 1] Complete — {total_frontier_ids} new matches downloaded")

        # Phase 2: Deep Crawl (backwards)
        if oldest_local_time is not None:
            print(f"     [Phase 2] Deep Crawl Backwards (From {oldest_local_time})...")
            current_end_time = oldest_local_time - 1
            total_crawl_ids = 0
            while True:
                match_ids = client.get_match_ids(region, puuid, start=0, count=count, end_time=current_end_time)
                if not match_ids:
                    break
                new_ids = [m for m in match_ids if m not in known_ids]
                if new_ids:
                    total_crawl_ids += len(new_ids)
                    print(f"     Found {len(new_ids)} new match IDs (crawl before {current_end_time})")
                    self._download_batch(db, profile_id, puuid, new_ids, region, client)
                    known_ids.update(new_ids)
                    has_changes = True

                oldest_match = (
                    db.query(LoLMatch)
                    .join(LoLMatch.participations)
                    .filter(LoLMatch.participations.any(profile_id=profile_id))
                    .order_by(LoLMatch.game_creation.asc())
                    .first()
                )
                new_oldest_time = oldest_match.game_creation if oldest_match else None

                if new_oldest_time is None or new_oldest_time >= current_end_time:
                    break
                current_end_time = new_oldest_time - 1
            print(f"     [Phase 2] Complete — {total_crawl_ids} new matches downloaded")

        with self._progress_lock:
            self._completed_count += 1
            idx = self._completed_count

        if progress_callback:
            progress_callback(game_name, "DONE", has_changes, idx, total)

    def _download_batch(self, db, profile_id: int, puuid: str, match_ids: list, region: str, client: RiotClient):
        total = len(match_ids)
        for idx, m_id in enumerate(match_ids, 1):
            print(f"       [{idx}/{total}] -> {m_id}...")
            detail = client.get_match_details(region, m_id)
            timeline = client.get_match_timeline(region, m_id)

            if detail and timeline:
                info = detail.get("info", {})
                crud.add_lol_match(
                    db=db,
                    profile_id=profile_id,
                    match_id=m_id,
                    puuid=puuid,
                    game_creation=info.get("gameCreation"),
                    game_duration=info.get("gameDuration"),
                    raw_details=detail,
                    raw_timeline=timeline,
                )
                db.commit()
            else:
                print(f"       [ERROR] Failed to fetch full payload for {m_id}")


if __name__ == "__main__":
    engine = SyncEngine()
    engine.sync_all()
