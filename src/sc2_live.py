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

import requests
from sqlalchemy import select

from src.data.database import SessionLocal
from src.data.models import SC2Profile
from src.data import crud

SC2_GAME_URL = "http://localhost:6119/game"


class SC2Live:
    POLL_INTERVAL_ACTIVE = 5   # seconds when SC2 is reachable
    POLL_INTERVAL_IDLE = 15    # seconds when SC2 is not reachable

    def __init__(self):
        self._running = False
        self._thread: threading.Thread | None = None
        self._was_in_game = False
        self._game_start_epoch: int | None = None  # epoch ms when game was first detected
        self._last_players: list | None = None      # players array from last in-game tick

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
            profiles = db.execute(select(SC2Profile)).scalars().all()
            player_names = [p.get("name", "") for p in players]

            for profile in profiles:
                if profile.display_name in player_names:
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
                        clear_result=just_started,  # clear previous result when new game starts
                    )
                    if just_started:
                        print(f"[SC2Live] {profile.display_name} in game vs {opponent_name}")
                else:
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
        print("[SC2Live] Game ended.")

        db = SessionLocal()
        try:
            profiles = db.execute(select(SC2Profile)).scalars().all()
            player_names = [p.get("name", "") for p in players]

            for profile in profiles:
                if profile.display_name in player_names:
                    # Find this player's result
                    player_entry = next(
                        (p for p in players if p.get("name") == profile.display_name), None
                    )
                    result = player_entry.get("result") if player_entry else None
                    # Map result: "Victory", "Defeat", "Tie", "Undecided" → keep first three
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

                    crud.set_sc2_in_game_status(
                        db, profile.id, False,
                        last_game_result=game_result,
                        last_game_opponent=opponent_name,
                    )
                else:
                    crud.set_sc2_in_game_status(db, profile.id, False)

            db.commit()
        except Exception as e:
            db.rollback()
            print(f"[SC2Live] DB error: {e}")
        finally:
            db.close()

    def _clear_all_in_game(self):
        """SC2 disconnected — clear all live and result state."""
        self._was_in_game = False
        self._game_start_epoch = None
        self._last_players = None
        db = SessionLocal()
        try:
            profiles = db.execute(select(SC2Profile)).scalars().all()
            for profile in profiles:
                crud.set_sc2_in_game_status(db, profile.id, False, clear_result=True)
            db.commit()
        except Exception as e:
            db.rollback()
            print(f"[SC2Live] DB error: {e}")
        finally:
            db.close()
