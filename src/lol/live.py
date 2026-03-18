"""
LiveTracker — LoL Spectator-V5 background polling with post-game tracking.

Polls active game status for all tracked LoL accounts. Uses adaptive polling:
30s when any account is in-game, 150s otherwise. Detects game-start and
game-end transitions, and for ranked games automatically syncs post-game
results (match data, LP change, win/loss).
"""
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dotenv import load_dotenv

from src.lol.api_client import RiotClient
from src.data.database import SessionLocal
from src.data import crud

# Queue ID constants
QUEUE_NAMES = {
    420: "Ranked Solo/Duo",
    440: "Ranked Flex",
    400: "Normal Draft",
    450: "ARAM",
}
RANKED_QUEUES = {
    420: "RANKED_SOLO_5x5",
    440: "RANKED_FLEX_SR",
}


class LiveTracker:
    POLL_INTERVAL_IDLE = 150   # seconds when no active games
    POLL_INTERVAL_ACTIVE = 30  # seconds when games are in progress

    def __init__(self):
        load_dotenv()
        primary = os.getenv("RIOT_API_KEY_PRIMARY")
        self.riot = RiotClient(primary_key=primary)
        self._running = False
        self._thread: threading.Thread | None = None
        self._active_games: dict[int, dict] = {}  # profile_id -> game metadata
        self._post_game_executor = ThreadPoolExecutor(max_workers=1)

    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._poll_loop, daemon=True, name="LiveTracker")
        self._thread.start()
        print("[LiveTracker] Started LoL live tracking.")

    def stop(self):
        self._running = False
        print("[LiveTracker] Stopped LoL live tracking.")

    @staticmethod
    def _map_platform(tag_line: str) -> str:
        tag = tag_line.upper()
        if tag in ["EUW", "EUW1"]:
            return "euw1"
        if tag == "EUNE":
            return "eun1"
        if tag in ["NA", "NA1"]:
            return "na1"
        if tag in ["KR", "KR1"]:
            return "kr"
        return "euw1"

    @staticmethod
    def _map_region(tag_line: str) -> str:
        """Map tag_line to regional routing value for Match-V5 calls."""
        tag = tag_line.upper()
        if tag in ["EUW", "EUW1", "EUNE"]:
            return "europe"
        if tag in ["NA", "NA1"]:
            return "americas"
        if tag in ["KR", "KR1"]:
            return "asia"
        return "europe"

    @property
    def _poll_interval(self) -> int:
        return self.POLL_INTERVAL_ACTIVE if self._active_games else self.POLL_INTERVAL_IDLE

    def _poll_loop(self):
        while self._running:
            try:
                self._poll_all()
            except Exception as e:
                print(f"[LiveTracker] Unexpected error in poll loop: {e}")
            # Sleep in 1-second ticks so stop() is responsive
            interval = self._poll_interval
            for _ in range(interval):
                if not self._running:
                    return
                time.sleep(1)

    def _poll_all(self):
        db = SessionLocal()
        try:
            accounts = crud.get_tracked_accounts(db, game_type="LOL")
            polled_profile_ids = set()

            for acc in accounts:
                if not self._running:
                    break
                if not acc.lol_profile:
                    continue
                profile = acc.lol_profile
                if profile.puuid.startswith("PENDING_"):
                    continue

                profile_id = profile.id
                polled_profile_ids.add(profile_id)
                platform = self._map_platform(profile.tag_line)

                try:
                    active_game = self.riot.get_active_game(platform, profile.puuid)
                    is_in_game = active_game is not None and "gameId" in active_game

                    if is_in_game and profile_id not in self._active_games:
                        # Game started
                        queue_id = active_game.get("gameQueueConfigId")
                        game_start = active_game.get("gameStartTime")
                        queue_name = QUEUE_NAMES.get(queue_id, "Custom Game")
                        print(f"[LiveTracker] {profile.game_name}#{profile.tag_line} is LIVE! ({queue_name})")

                        self._active_games[profile_id] = {
                            "queue_id": queue_id,
                            "game_start": game_start,
                            "puuid": profile.puuid,
                            "platform": platform,
                            "region": self._map_region(profile.tag_line),
                            "game_name": profile.game_name,
                            "tag_line": profile.tag_line,
                            "profile_id": profile_id,
                        }

                        # Write to DB: set in-game, clear previous result
                        crud.set_lol_in_game_status(
                            db, profile_id, True,
                            current_game_start=game_start,
                            current_game_queue_id=queue_id,
                            clear_result=True,
                        )
                        db.commit()

                    elif is_in_game and profile_id in self._active_games:
                        # Still playing — no-op
                        pass

                    elif not is_in_game and profile_id in self._active_games:
                        # Game ended
                        game_info = self._active_games.pop(profile_id)
                        queue_id = game_info.get("queue_id")
                        print(f"[LiveTracker] {game_info['game_name']}#{game_info['tag_line']} game ended.")

                        if queue_id in RANKED_QUEUES:
                            # Submit post-game processing for ranked games
                            self._post_game_executor.submit(self._handle_game_end, profile_id, game_info)
                        else:
                            # Non-ranked: just clear in-game status silently
                            crud.set_lol_in_game_status(db, profile_id, False)
                            db.commit()

                    # Not in-game and wasn't tracked — no-op

                except Exception as e:
                    db.rollback()
                    print(f"[LiveTracker] Error polling {profile.game_name}: {e}")

            # Clean up _active_games for profiles that are no longer tracked
            stale = set(self._active_games.keys()) - polled_profile_ids
            for pid in stale:
                self._active_games.pop(pid, None)

        finally:
            db.close()

    def _handle_game_end(self, profile_id: int, game_info: dict):
        """Post-game processing for ranked games. Runs on executor thread."""
        from src.services.data_service import _absolute_lp

        queue_id = game_info["queue_id"]
        queue_type = RANKED_QUEUES[queue_id]
        puuid = game_info["puuid"]
        region = game_info["region"]
        platform = game_info["platform"]
        name_tag = f"{game_info['game_name']}#{game_info['tag_line']}"

        db = SessionLocal()
        try:
            # 1. Snapshot current LP before update
            old_rank = crud.get_lol_current_rank(db, profile_id, queue_type)
            old_lp = _absolute_lp(old_rank.tier, old_rank.rank, old_rank.lp) if old_rank else None

            # 2. Wait for Riot API match data to become available
            print(f"[LiveTracker] Waiting 5s for match data ({name_tag})...")
            time.sleep(5)

            # 3. Re-fetch rank from League-V4 and upsert
            ranks_data = self.riot.get_league_entries(platform, puuid)
            if ranks_data:
                for r in ranks_data:
                    qt = r.get("queueType")
                    if qt in ["RANKED_SOLO_5x5", "RANKED_FLEX_SR"]:
                        crud.upsert_lol_ranks(
                            db=db,
                            profile_id=profile_id,
                            queue_type=qt,
                            tier=r.get("tier", "UNRANKED"),
                            rank=r.get("rank", ""),
                            lp=r.get("leaguePoints", 0),
                            wins=r.get("wins", 0),
                            losses=r.get("losses", 0),
                        )
                db.commit()

            # 4. Compute LP delta
            lp_change = None
            new_rank = crud.get_lol_current_rank(db, profile_id, queue_type)
            if old_lp is not None and new_rank:
                new_lp = _absolute_lp(new_rank.tier, new_rank.rank, new_rank.lp)
                lp_change = new_lp - old_lp
                print(f"[LiveTracker] LP change for {name_tag}: {lp_change:+d}")

            # 5. Fetch latest match IDs, retry up to 3 times
            result = None
            for attempt in range(3):
                match_ids = self.riot.get_match_ids(region, puuid, start=0, count=5)
                if not match_ids:
                    if attempt < 2:
                        print(f"[LiveTracker] No match IDs yet for {name_tag}, retrying in 30s...")
                        time.sleep(30)
                        continue
                    break

                # Check if any of these are new (not already in DB)
                known_ids = set(crud.get_lol_match_ids(db, profile_id))
                new_ids = [m for m in match_ids if m not in known_ids]

                if not new_ids:
                    if attempt < 2:
                        print(f"[LiveTracker] New match not yet available for {name_tag}, retrying in 30s...")
                        time.sleep(30)
                        continue
                    break

                # Download the newest match
                latest_id = new_ids[0]
                print(f"[LiveTracker] Downloading match {latest_id} for {name_tag}...")
                detail = self.riot.get_match_details(region, latest_id)
                timeline = self.riot.get_match_timeline(region, latest_id)

                if detail:
                    info = detail.get("info", {})
                    crud.add_lol_match(
                        db=db,
                        profile_id=profile_id,
                        match_id=latest_id,
                        puuid=puuid,
                        game_creation=info.get("gameCreation"),
                        game_duration=info.get("gameDuration"),
                        raw_details=detail,
                        raw_timeline=timeline,
                    )
                    db.commit()

                    # Extract win/loss
                    participants = info.get("participants", [])
                    p = next((x for x in participants if x.get("puuid") == puuid), None)
                    if p:
                        result = "Victory" if p.get("win") else "Defeat"

                break

            # 6. Write post-game state
            crud.set_lol_in_game_status(
                db, profile_id, False,
                last_game_result=result,
                last_game_queue_id=queue_id,
                last_game_lp_change=lp_change,
            )
            db.commit()
            print(f"[LiveTracker] Post-game complete for {name_tag}: {result}, LP: {lp_change}")

        except Exception as e:
            db.rollback()
            print(f"[LiveTracker] Post-game error for {name_tag}: {e}")
            # Still clear in-game status on error
            try:
                crud.set_lol_in_game_status(db, profile_id, False)
                db.commit()
            except Exception:
                db.rollback()
        finally:
            db.close()