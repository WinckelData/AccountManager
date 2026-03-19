"""
SC2Live — StarCraft II localhost:6119 background polling.

Polls the local SC2 client API every 5 seconds to detect in-game status,
opponent, and race. Falls back to 15-second polling when SC2 is not running
(ConnectionError from HTTP call).

Detection logic (from localhost:6119/game):
- In-game: isReplay == false AND players non-empty AND any result == "Undecided"
- Post-game/replay/menu: everything else

Opponent detection: matches player names against tracked SC2 display_names
from the database. The non-matching player is the opponent.
"""
import json
import threading
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor

import requests

from src.data.database import SessionLocal
from src.data import crud

SC2_GAME_URL = "http://localhost:6119/game"


class SC2Live:
    POLL_INTERVAL_ACTIVE = 5   # seconds when SC2 is reachable
    POLL_INTERVAL_IDLE = 15    # seconds when SC2 is not reachable
    POST_GAME_FETCH_DELAY = 3  # seconds to wait for Blizzard API to update after game

    def __init__(self, blizzard_client=None):
        self._running = False
        self._thread: threading.Thread | None = None
        self._was_in_game = False
        self._game_start_epoch: int | None = None  # epoch ms when game was first detected
        self._last_players: list | None = None      # players array from last in-game tick
        self._blizzard_client = blizzard_client
        self._post_game_gen = 0  # incremented each game end; stale threads check this

    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._poll_loop, daemon=True, name="SC2Live")
        self._thread.start()
        print("[SC2Live] Started SC2 live tracking.")

    def stop(self):
        self._running = False
        print("[SC2Live] Stopped SC2 live tracking.")

    def _poll_loop(self):
        while self._running:
            try:
                response = requests.get(SC2_GAME_URL, timeout=2)
                if response.status_code != 200:
                    if self._was_in_game:
                        self._clear_all_in_game()
                    interval = self.POLL_INTERVAL_IDLE
                else:
                    self._process_game_data(response)
                    interval = self.POLL_INTERVAL_ACTIVE
            except (requests.exceptions.ConnectionError, requests.exceptions.Timeout):
                # SC2 not running or request timed out
                if self._was_in_game:
                    self._clear_all_in_game()
                interval = self.POLL_INTERVAL_IDLE
            except (json.JSONDecodeError, ValueError):
                # SC2 starting up — HTTP server returns non-JSON
                interval = self.POLL_INTERVAL_IDLE
            except Exception as e:
                print(f"[SC2Live] Error: {e}")
                interval = self.POLL_INTERVAL_IDLE

            for _ in range(interval):
                if not self._running:
                    return
                time.sleep(1)

    def _process_game_data(self, response):
        """Parse the /game response and update DB accordingly."""
        try:
            game_data = json.loads(response.content.decode("utf-8", errors="replace"))
        except (json.JSONDecodeError, ValueError):
            # SC2 startup: HTTP 200 but non-JSON body
            if self._was_in_game:
                self._handle_game_end(game_data={})
            return

        players: list = game_data.get("players", [])
        is_replay: bool = game_data.get("isReplay", False)

        # In-game = not a replay, has players, and at least one result is undecided
        is_in_game = (
            not is_replay
            and len(players) > 0
            and any(p.get("result") == "Undecided" for p in players)
        )

        just_started = is_in_game and not self._was_in_game
        just_ended = not is_in_game and self._was_in_game

        if just_started:
            # Use displayTime to back-calculate actual game start
            display_time = game_data.get("displayTime", 0)
            if display_time > 0:
                self._game_start_epoch = int((time.time() - display_time) * 1000)
            else:
                self._game_start_epoch = int(time.time() * 1000)
            self._last_players = players
            print("[SC2Live] Game started!")
        elif is_in_game:
            # Recalculate start time every poll for accuracy
            display_time = game_data.get("displayTime", 0)
            if display_time > 0:
                self._game_start_epoch = int((time.time() - display_time) * 1000)
            self._last_players = players
        elif just_ended:
            # Game just ended — capture results before clearing
            self._handle_game_end(game_data)
            return

        self._was_in_game = is_in_game

        if not is_in_game:
            # Not in game and wasn't before — nothing to do
            return

        # --- In-game: update DB with live status ---
        db = SessionLocal()
        try:
            profiles = crud.get_all_sc2_display_names(db)
            player_names = [p.get("name", "") for p in players]

            # Count unique accounts per matching display_name
            # Multiple profiles on the same account (different regions) are NOT ambiguous
            name_to_accounts = defaultdict(set)
            for p in profiles:
                if p.display_name in player_names:
                    name_to_accounts[p.display_name].add(p.account_id)

            for profile in profiles:
                if profile.display_name in player_names and len(name_to_accounts[profile.display_name]) == 1:
                    # All profiles with this name belong to the same account — safe to show LIVE
                    opponents = [
                        p.get("name") for p in players
                        if p.get("name") != profile.display_name
                        and p.get("type") == "user"
                    ]
                    if not opponents:
                        opponents = [
                            p.get("name") for p in players
                            if p.get("name") != profile.display_name
                        ]
                    opponent_name = opponents[0] if opponents else None

                    crud.set_sc2_in_game_status(
                        db, profile.id, True,
                        current_opponent=opponent_name,
                        current_game_start=self._game_start_epoch,
                        clear_result=just_started,
                    )
                    if just_started:
                        print(f"[SC2Live] {profile.display_name} (profile_db_id={profile.id}, region={profile.region_id}) in game vs {opponent_name}")
                else:
                    if profile.display_name in player_names:
                        print(f"[SC2Live] {profile.display_name} (profile_db_id={profile.id}) ambiguous — {len(name_to_accounts.get(profile.display_name, set()))} different accounts share this name")
                    crud.set_sc2_in_game_status(db, profile.id, False)

            db.commit()
        except Exception as e:
            db.rollback()
            print(f"[SC2Live] DB error: {e}")
        finally:
            db.close()

    def _handle_game_end(self, game_data: dict):
        """Process game end: extract results from the final players array and persist them."""
        # Use the players from the end-game response if available, otherwise fall back to last known
        players = game_data.get("players", [])
        if not players:
            players = self._last_players or []

        self._was_in_game = False
        self._game_start_epoch = None
        self._last_players = None
        self._post_game_gen += 1  # cancel any stale post-game thread
        current_gen = self._post_game_gen
        print("[SC2Live] Game ended.")

        # Tuple: (profile_id, profile_db_id, region_id, realm_id, game_result, opponent_name, is_ambiguous)
        matched_profiles = []
        db = SessionLocal()
        try:
            profiles = crud.get_all_sc2_display_names(db)
            player_names = [p.get("name", "") for p in players]

            name_to_accounts = defaultdict(set)
            for p in profiles:
                if p.display_name in player_names:
                    name_to_accounts[p.display_name].add(p.account_id)

            for profile in profiles:
                if profile.display_name in player_names:
                    # Find this player's result
                    player_entry = next(
                        (p for p in players if p.get("name") == profile.display_name), None
                    )
                    result = player_entry.get("result") if player_entry else None
                    if result in ("Victory", "Defeat", "Tie"):
                        game_result = result
                    else:
                        game_result = None

                    opponents = [
                        p.get("name") for p in players
                        if p.get("name") != profile.display_name
                        and p.get("type") == "user"
                    ]
                    if not opponents:
                        opponents = [
                            p.get("name") for p in players
                            if p.get("name") != profile.display_name
                        ]
                    opponent_name = opponents[0] if opponents else None

                    is_ambiguous = len(name_to_accounts[profile.display_name]) > 1

                    if not is_ambiguous:
                        # Unique match — set result immediately
                        crud.set_sc2_in_game_status(
                            db, profile.id, False,
                            last_game_result=game_result,
                            last_game_opponent=opponent_name,
                        )
                    else:
                        # Ambiguous — just clear in-game, defer result to post-game
                        crud.set_sc2_in_game_status(db, profile.id, False)

                    if game_result:
                        matched_profiles.append((
                            profile.profile_id, profile.id,
                            profile.region_id, profile.realm_id,
                            game_result, opponent_name, is_ambiguous,
                        ))
                else:
                    crud.set_sc2_in_game_status(db, profile.id, False)

            db.commit()
        except Exception as e:
            db.rollback()
            print(f"[SC2Live] DB error: {e}")
        finally:
            db.close()

        # Snapshot latest match dates for disambiguation before spawning post-game thread
        latest_match_dates = {}  # profile_db_id -> latest match date (epoch) or None
        if matched_profiles and self._blizzard_client:
            db = SessionLocal()
            try:
                for _, profile_db_id, _, _, _, _, _ in matched_profiles:
                    latest_match_dates[profile_db_id] = crud.get_latest_sc2_match_date(db, profile_db_id)
            finally:
                db.close()

            threading.Thread(
                target=self._post_game_fetch,
                args=(matched_profiles, current_gen, latest_match_dates),
                daemon=True,
                name="SC2Live-PostGame",
            ).start()

    def _post_game_fetch(self, matched_profiles, gen, latest_match_dates):
        """Wait for API update, then re-fetch ranks and compute MMR delta.

        Uses match history to disambiguate profiles sharing a display_name,
        and a region-level circuit breaker to avoid spamming broken ladder endpoints.
        """
        blizz = self._blizzard_client
        print(f"[SC2Live] Waiting {self.POST_GAME_FETCH_DELAY}s for API update...")
        for _ in range(self.POST_GAME_FETCH_DELAY):
            if not self._running:
                return
            time.sleep(1)

        # Abort if a newer game has started since we were spawned
        if gen != self._post_game_gen:
            print("[SC2Live] Post-game fetch cancelled (new game detected)")
            return

        import json as _json
        from sqlalchemy import select
        from src.data.models import SC2Rank as SC2RankModel

        # Snapshot old MMR and GM ranks per profile before any re-fetches
        old_data = {}  # profile_db_id -> {race: mmr}
        old_gm_ranks = {}  # profile_db_id -> gm_rank (int or None)


        db = SessionLocal()
        try:
            for _, profile_db_id, region_id, _, _, _, _ in matched_profiles:
                rows = db.execute(
                    select(SC2RankModel).where(
                        SC2RankModel.profile_id == profile_db_id,
                        SC2RankModel.queue_type == "1v1",
                    )
                ).scalars().all()
                old_data[profile_db_id] = {r.race: r.mmr for r in rows}

                # Compute old GM rank from current ladder data
                gm_row = next((r for r in rows if r.is_grandmaster), None)
                if gm_row:
                    ladder_data = crud.get_sc2_gm_ladder(db, region_id)
                    ladder_mmrs = ladder_data[1] if ladder_data else []
                    if ladder_mmrs:
                        old_gm_ranks[profile_db_id] = sum(1 for m in ladder_mmrs if m > gm_row.mmr) + 1
        finally:
            db.close()

        # Only refresh GM ladders for regions that have existing ranked data
        ranked_regions = set()
        for _, profile_db_id, region_id, _, _, _, _ in matched_profiles:
            if old_data.get(profile_db_id):
                ranked_regions.add(region_id)

        if ranked_regions:
            def _refresh_gm(rid):
                try:
                    gm_data = blizz.get_grandmaster_ladder(rid)
                    gm_mmrs = []
                    for team in gm_data.get("ladderTeams", []):
                        mmr = team.get("mmr", 0)
                        if mmr > 0:
                            gm_mmrs.append(mmr)
                    if gm_mmrs:
                        sorted_mmrs = sorted(gm_mmrs, reverse=True)
                        gm_db = SessionLocal()
                        try:
                            crud.upsert_sc2_gm_threshold(
                                gm_db, rid, min(gm_mmrs), _json.dumps(sorted_mmrs),
                            )
                            gm_db.commit()
                        finally:
                            gm_db.close()
                        reg_name = {1: "NA", 2: "EU", 3: "KR"}.get(rid, "?")
                        print(f"[SC2Live] Refreshed GM ladder for {reg_name} ({len(gm_mmrs)} players)")
                except Exception as e:
                    print(f"[SC2Live] Failed to refresh GM ladder for region {rid}: {e}")

            with ThreadPoolExecutor(max_workers=len(ranked_regions)) as pool:
                list(pool.map(_refresh_gm, ranked_regions))
        else:
            pass  # No ranked data — skip GM ladder refresh

        # Re-snapshot old MMR now that GM ladders are refreshed
        db = SessionLocal()
        try:
            for _, profile_db_id, region_id, _, _, _, _ in matched_profiles:
                rows = db.execute(
                    select(SC2RankModel).where(
                        SC2RankModel.profile_id == profile_db_id,
                        SC2RankModel.queue_type == "1v1",
                    )
                ).scalars().all()
                old_data[profile_db_id] = {r.race: r.mmr for r in rows}

                gm_row = next((r for r in rows if r.is_grandmaster), None)
                if gm_row:
                    ladder_data = crud.get_sc2_gm_ladder(db, region_id)
                    ladder_mmrs = ladder_data[1] if ladder_data else []
                    if ladder_mmrs:
                        old_gm_ranks[profile_db_id] = sum(1 for m in ladder_mmrs if m > gm_row.mmr) + 1
        finally:
            db.close()

        # Region-level circuit breaker for ladder endpoints
        ladder_unavailable_regions = set()

        # Disambiguate ambiguous profiles using match history
        ambiguous_ids = {
            profile_db_id
            for _, profile_db_id, _, _, _, _, is_ambiguous in matched_profiles
            if is_ambiguous
        }
        confirmed_played = set()  # profile_db_ids confirmed via match history
        if ambiguous_ids:
            for composite_pid, profile_db_id, region_id, realm_id, _, _, is_ambiguous in matched_profiles:
                if not is_ambiguous:
                    continue
                raw_pid = composite_pid.split("-")[-1] if "-" in composite_pid else composite_pid
                try:
                    history = blizz.get_match_history(region_id, realm_id, raw_pid)
                    matches = history.get("matches", []) if history else []
                    if matches:
                        newest_date = max(m.get("date", 0) for m in matches)
                        old_date = latest_match_dates.get(profile_db_id)
                        if old_date is None or newest_date > old_date:
                            confirmed_played.add(profile_db_id)
                            print(f"[SC2Live] Match history confirms {composite_pid} played (new match detected)")
                        # Also persist the new matches to DB
                        db = SessionLocal()
                        try:
                            crud.upsert_sc2_matches(db, profile_db_id, history)
                            db.commit()
                        finally:
                            db.close()
                except Exception as e:
                    print(f"[SC2Live] Match history fetch failed for {composite_pid}: {e}")

        # Single pass: fetch ladder data and compute MMR delta
        for composite_pid, profile_db_id, region_id, realm_id, game_result, opponent_name, is_ambiguous in matched_profiles:
            # For ambiguous profiles, skip those not confirmed by match history
            if is_ambiguous and profile_db_id not in confirmed_played:
                continue

            raw_pid = composite_pid.split("-")[-1] if "-" in composite_pid else composite_pid
            try:
                old_ranks = old_data.get(profile_db_id, {})

                # Try ladder endpoints for MMR delta (skip if region already failed)
                best_delta = None
                best_race = None
                best_is_gm = False
                best_new_mmr = 0

                if region_id not in ladder_unavailable_regions:
                    season_data = blizz.get_current_season(region_id)
                    current_season = season_data.get("seasonId") if season_data else None

                    if current_season:
                        summary = blizz.get_ladder_summary(region_id, realm_id, raw_pid)
                        if not summary or "error" in summary:
                            # Ladder endpoint actually failed — mark region unavailable
                            reg_name = {1: "NA", 2: "EU", 3: "KR"}.get(region_id, "?")
                            if region_id not in ladder_unavailable_regions:
                                print(f"[SC2Live] Ladder endpoint unavailable for {reg_name}, skipping ladder fetches for this region")
                                ladder_unavailable_regions.add(region_id)
                        elif not summary.get("showCaseEntries") and not summary.get("allLadderMemberships"):
                            # Truly unranked — no data to fetch, but endpoint is fine
                            pass
                        else:
                            db = SessionLocal()
                            try:
                                for entry in summary.get("showCaseEntries", []):
                                    team = entry.get("team", {})
                                    if team.get("localizedGameMode") != "1v1":
                                        continue
                                    members = team.get("members", [])
                                    if not members:
                                        continue
                                    race = members[0].get("favoriteRace", "").lower()
                                    if race not in ("terran", "zerg", "protoss", "random"):
                                        continue

                                    ladder_id = entry.get("ladderId")
                                    league = entry.get("leagueName", "UNKNOWN").capitalize()
                                    ladder_details = blizz.get_ladder_details(region_id, realm_id, raw_pid, ladder_id)

                                    mmr = 0
                                    for ladder_team in ladder_details.get("ladderTeams", []):
                                        team_members = ladder_team.get("teamMembers", [])
                                        if any(str(m.get("id")) == str(raw_pid) for m in team_members):
                                            mmr = ladder_team.get("mmr", 0)
                                            break

                                    # Check if GM from current DB state
                                    existing = db.execute(
                                        select(SC2RankModel).where(
                                            SC2RankModel.profile_id == profile_db_id,
                                            SC2RankModel.season == current_season,
                                            SC2RankModel.race == race,
                                            SC2RankModel.queue_type == "1v1",
                                        )
                                    ).scalar_one_or_none()
                                    is_gm = existing.is_grandmaster if existing else False

                                    crud.upsert_sc2_ranks(
                                        db, profile_db_id, current_season, race, "1v1",
                                        mmr, league, is_gm,
                                    )

                                    # Compute delta
                                    old_mmr = old_ranks.get(race)
                                    if old_mmr is not None and mmr != 0:
                                        delta = mmr - old_mmr
                                        if best_delta is None or abs(delta) > abs(best_delta):
                                            best_delta = delta
                                            best_race = race
                                            best_is_gm = is_gm
                                            best_new_mmr = mmr
                                    elif old_mmr is None and mmr > 0:
                                        # Newly ranked (placement) — treat full MMR as delta
                                        if best_delta is None:
                                            best_delta = mmr
                                            best_race = race
                                            best_is_gm = is_gm
                                            best_new_mmr = mmr

                                # showCaseEntries is capped at 3 — fetch extra 1v1 ladders from allLadderMemberships
                                processed_ladder_ids = {entry.get("ladderId") for entry in summary.get("showCaseEntries", [])
                                                        if entry.get("team", {}).get("localizedGameMode") == "1v1"}
                                for membership in summary.get("allLadderMemberships", []):
                                    if not membership.get("localizedGameMode", "").startswith("1v1"):
                                        continue
                                    m_ladder_id = membership.get("ladderId")
                                    if m_ladder_id in processed_ladder_ids:
                                        continue

                                    ladder_details = blizz.get_ladder_details(region_id, realm_id, raw_pid, m_ladder_id)
                                    for ladder_team in ladder_details.get("ladderTeams", []):
                                        team_members = ladder_team.get("teamMembers", [])
                                        if any(str(m.get("id")) == str(raw_pid) for m in team_members):
                                            mmr = ladder_team.get("mmr", 0)
                                            race = team_members[0].get("favoriteRace", "").lower()
                                            if race not in ("terran", "zerg", "protoss", "random"):
                                                break
                                            league = membership.get("localizedGameMode", "").split(" ", 1)[-1].capitalize()

                                            existing = db.execute(
                                                select(SC2RankModel).where(
                                                    SC2RankModel.profile_id == profile_db_id,
                                                    SC2RankModel.season == current_season,
                                                    SC2RankModel.race == race,
                                                    SC2RankModel.queue_type == "1v1",
                                                )
                                            ).scalar_one_or_none()
                                            is_gm = existing.is_grandmaster if existing else False

                                            crud.upsert_sc2_ranks(
                                                db, profile_db_id, current_season, race, "1v1",
                                                mmr, league, is_gm,
                                            )

                                            old_mmr = old_ranks.get(race)
                                            if old_mmr is not None and mmr != 0:
                                                delta = mmr - old_mmr
                                                if best_delta is None or abs(delta) > abs(best_delta):
                                                    best_delta = delta
                                                    best_race = race
                                                    best_is_gm = is_gm
                                                    best_new_mmr = mmr
                                            elif old_mmr is None and mmr > 0:
                                                # Newly ranked (placement)
                                                if best_delta is None:
                                                    best_delta = mmr
                                                    best_race = race
                                                    best_is_gm = is_gm
                                                    best_new_mmr = mmr
                                            break

                                db.commit()
                            except Exception as e:
                                db.rollback()
                                print(f"[SC2Live] Post-game DB error: {e}")
                            finally:
                                db.close()

                # Record game result (with or without MMR delta)
                db = SessionLocal()
                try:
                    if best_delta is not None and best_delta != 0:
                        # Compute GM rank change if applicable
                        gm_rank_change = None
                        if best_is_gm and profile_db_id in old_gm_ranks:
                            ladder_data = crud.get_sc2_gm_ladder(db, region_id)
                            new_ladder_mmrs = ladder_data[1] if ladder_data else []
                            if new_ladder_mmrs:
                                new_gm_rank = sum(1 for m in new_ladder_mmrs if m > best_new_mmr) + 1
                                old_gm_rank = old_gm_ranks[profile_db_id]
                                gm_rank_change = old_gm_rank - new_gm_rank

                        crud.set_sc2_in_game_status(
                            db, profile_db_id, False,
                            last_game_result=game_result,
                            last_game_opponent=opponent_name,
                            last_game_mmr_change=best_delta,
                            last_game_mmr_race=best_race,
                            last_game_gm_rank_change=gm_rank_change,
                        )
                        sign = "+" if best_delta >= 0 else ""
                        print(f"[SC2Live] Post-game MMR change: {sign}{best_delta}")
                    elif best_delta is not None and best_delta == 0 and not is_ambiguous:
                        # Unique match with +0 delta — still record it
                        crud.set_sc2_in_game_status(
                            db, profile_db_id, False,
                            last_game_mmr_change=best_delta,
                            last_game_mmr_race=best_race,
                        )
                        print("[SC2Live] Post-game MMR change: +0")
                    elif region_id in ladder_unavailable_regions:
                        # Ladder failed — still record game result without MMR delta
                        crud.set_sc2_in_game_status(
                            db, profile_db_id, False,
                            last_game_result=game_result,
                            last_game_opponent=opponent_name,
                        )
                        print(f"[SC2Live] Recorded game result ({game_result}) without MMR delta (ladder unavailable)")
                    else:
                        # No MMR data (unranked / no ladder entries) — still record game result
                        crud.set_sc2_in_game_status(
                            db, profile_db_id, False,
                            last_game_result=game_result,
                            last_game_opponent=opponent_name,
                        )
                        print(f"[SC2Live] Recorded game result ({game_result}) without MMR data")
                    db.commit()
                except Exception as e:
                    db.rollback()
                    print(f"[SC2Live] Post-game DB error: {e}")
                finally:
                    db.close()
            except Exception as e:
                print(f"[SC2Live] Post-game fetch error for {composite_pid}: {e}")

    def _clear_all_in_game(self):
        """SC2 disconnected — clear all live and result state."""
        self._was_in_game = False
        self._game_start_epoch = None
        self._last_players = None
        db = SessionLocal()
        try:
            profiles = crud.get_all_sc2_display_names(db)
            for profile in profiles:
                crud.set_sc2_in_game_status(db, profile.id, False, clear_result=True)
            db.commit()
        except Exception as e:
            db.rollback()
            print(f"[SC2Live] DB error: {e}")
        finally:
            db.close()