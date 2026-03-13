import os
import time
from dotenv import load_dotenv

from src.api_clients import RiotClient
from src.data.database import SessionLocal
from src.data import crud
from src.data.models import LoLMatch

class SyncEngine:
    def __init__(self):
        load_dotenv()
        primary = os.getenv("RIOT_API_KEY_PRIMARY")
        fallback = os.getenv("RIOT_API_KEY_FALLBACK")
        self.riot = RiotClient(primary_key=primary, fallback_key=fallback)
        
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
        print("\n" + "="*50)
        print("Starting Data Synchronization...")
        print("="*50)
        
        db = SessionLocal()
        try:
            accounts = crud.get_tracked_accounts(db, game_type="LOL")
            if not accounts:
                print("No tracked accounts found.")
                return

            total_accounts = len(accounts)
            for i, acc in enumerate(accounts):
                # Ensure we have a profile to sync
                if not acc.lol_profile:
                    continue
                    
                game_name = acc.lol_profile.game_name
                tag_line = acc.lol_profile.tag_line
                puuid = acc.lol_profile.puuid
                profile_id = acc.lol_profile.id
                
                has_changes = False
                account_id = game_name
                if progress_callback:
                    progress_callback(account_id, "SYNCING", False, i, total_accounts)
                
                print(f"\n>> Syncing: {game_name}#{tag_line}")
                region, platform = self._map_region(tag_line)

                # 1. Resolve / Verify PUUID
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
                         continue
                         
                    puuid = summoner_data["puuid"]
                    summoner_id = summoner_data.get("id")
                    
                    crud.upsert_lol_profile(
                        db=db,
                        account_id=acc.id,
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
                    summoner_data = self.riot.get_summoner_by_puuid(platform, puuid)
                    if summoner_data:
                        crud.upsert_lol_profile(
                            db=db,
                            account_id=acc.id,
                            puuid=puuid,
                            game_name=game_name,
                            tag_line=tag_line,
                            summoner_id=summoner_data.get("id"),
                            summoner_level=summoner_data.get("summonerLevel"),
                            profile_icon_id=summoner_data.get("profileIconId")
                        )
                        db.commit()

                # 3. Update Ranks
                print("   - Updating Ranks...")
                ranks_data = self.riot.get_league_entries(platform, puuid)
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
                                losses=r.get("losses", 0)
                            )
                    db.commit()
                    has_changes = True

                # 4. Update Champion Masteries
                print("   - Updating Champion Masteries...")
                masteries_data = self.riot.get_champion_masteries(platform, puuid)
                if masteries_data:
                    parsed_masteries = []
                    # Riot API often limits or we limit to top N. Let's store what we get.
                    for m in masteries_data:
                        parsed_masteries.append({
                            "champion_id": m.get("championId"),
                            "mastery_level": m.get("championLevel", 0),
                            "champion_points": m.get("championPoints", 0),
                            "last_play_time": m.get("lastPlayTime", 0)
                        })
                    crud.upsert_lol_masteries(db, profile_id, parsed_masteries)
                    db.commit()

                # 5. Delta Sync Matches
                print("   - Fetching Match History...")
                known_ids = set(crud.get_lol_match_ids(db, profile_id))
                
                # Fetch oldest local match time directly via SQLAlchemy
                oldest_match = db.query(LoLMatch).join(LoLMatch.participations).filter(
                    LoLMatch.participations.any(profile_id=profile_id)
                ).order_by(LoLMatch.game_creation.asc()).first()
                oldest_local_time = oldest_match.game_creation if oldest_match else None

                # --- Phase 1: The Frontier ---
                print("     [Phase 1] Syncing Frontier (New Matches)...")
                frontier_start = 0
                count = 100
                while True:
                    match_ids = self.riot.get_match_ids(region, puuid, start=frontier_start, count=count)
                    if not match_ids: break
                    
                    new_ids = [m for m in match_ids if m not in known_ids]
                    if not new_ids and len(match_ids) > 0: break
                        
                    self._download_batch(db, profile_id, new_ids, region)
                    has_changes = True
                    known_ids.update(new_ids)
                    
                    if len(match_ids) < count: break
                    frontier_start += count
                
                # --- Phase 2: The Deep Crawl ---
                if oldest_local_time is not None:
                    print(f"     [Phase 2] Deep Crawl Backwards (From {oldest_local_time})...")
                    current_end_time = oldest_local_time - 1
                    while True:
                        match_ids = self.riot.get_match_ids(region, puuid, start=0, count=count, end_time=current_end_time)
                        if not match_ids: break
                            
                        new_ids = [m for m in match_ids if m not in known_ids]
                        if new_ids:
                            self._download_batch(db, profile_id, new_ids, region)
                            known_ids.update(new_ids)
                            has_changes = True
                        
                        # Find new absolute minimum time
                        oldest_match = db.query(LoLMatch).join(LoLMatch.participations).filter(
                            LoLMatch.participations.any(profile_id=profile_id)
                        ).order_by(LoLMatch.game_creation.asc()).first()
                        new_oldest_time = oldest_match.game_creation if oldest_match else None
                        
                        if new_oldest_time is None or new_oldest_time >= current_end_time:
                            break
                        current_end_time = new_oldest_time - 1
                        time.sleep(0.5)

                if progress_callback:
                    progress_callback(account_id, "DONE", has_changes, i + 1, total_accounts)

            print("\n" + "="*50)
            print("Synchronization Complete!")
            print("="*50)

        except Exception as e:
            db.rollback()
            print(f"Error during LoL sync: {e}")
            raise e
        finally:
            db.close()

    def _download_batch(self, db, profile_id: int, match_ids: list, region: str):
        for m_id in match_ids:
            print(f"       -> {m_id}...")
            detail = self.riot.get_match_details(region, m_id)
            time.sleep(0.05)
            timeline = self.riot.get_match_timeline(region, m_id)
            time.sleep(0.05)
            
            if detail and timeline:
                creation_time = detail.get("info", {}).get("gameCreation", 0)
                # Save JSON directly to DB column
                crud.add_lol_match(
                    db=db,
                    profile_id=profile_id,
                    match_id=m_id,
                    game_creation=creation_time,
                    raw_details=detail,
                    raw_timeline=timeline
                )
                db.commit()
            else:
                print(f"       [ERROR] Failed to fetch full payload for {m_id}")

if __name__ == "__main__":
    engine = SyncEngine()
    engine.sync_all()