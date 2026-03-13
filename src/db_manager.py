import sqlite3
import json
import time
from pathlib import Path
from typing import List, Dict, Optional, Set
from src.config import SQLITE_DB_PATH

class DBManager:
    def __init__(self):
        self.db_path = SQLITE_DB_PATH
        self._initialize_db()

    def get_connection(self):
        # Using ROW to return dict-like objects
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _initialize_db(self):
        """Creates the necessary tables if they do not exist."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            # Accounts Table: Stores core player identity
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS Accounts (
                    puuid TEXT PRIMARY KEY,
                    game_name TEXT,
                    tag_line TEXT,
                    summoner_id TEXT,
                    summoner_level INTEGER,
                    profile_icon_id INTEGER,
                    is_tracked BOOLEAN DEFAULT 1,
                    last_updated_epoch INTEGER,
                    login_name TEXT
                )
            ''')
            
            # Migration to add login_name to existing databases
            try:
                cursor.execute("ALTER TABLE Accounts ADD COLUMN login_name TEXT")
            except sqlite3.OperationalError:
                pass # Column already exists
            
            # Ranks Table: Stores the current rank snapshot
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS Ranks (
                    puuid TEXT PRIMARY KEY,
                    solo_tier TEXT,
                    solo_rank TEXT,
                    solo_lp INTEGER,
                    solo_wins INTEGER,
                    solo_losses INTEGER,
                    flex_tier TEXT,
                    flex_rank TEXT,
                    flex_lp INTEGER,
                    flex_wins INTEGER,
                    flex_losses INTEGER,
                    FOREIGN KEY (puuid) REFERENCES Accounts (puuid)
                )
            ''')
            
            # MatchIndex Table: Lightweight lookup to map matches to players
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS MatchIndex (
                    match_id TEXT,
                    puuid TEXT,
                    game_creation_time INTEGER,
                    PRIMARY KEY (match_id, puuid),
                    FOREIGN KEY (puuid) REFERENCES Accounts (puuid)
                )
            ''')
            
            # Champion Masteries: Tracks individual champion expertise
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS Masteries (
                    puuid TEXT,
                    champion_id INTEGER,
                    mastery_level INTEGER,
                    champion_points INTEGER,
                    last_play_time INTEGER,
                    PRIMARY KEY (puuid, champion_id),
                    FOREIGN KEY (puuid) REFERENCES Accounts (puuid)
                )
            ''')
            
            conn.commit()

    # --- Sync Engine Helpers ---

    def get_tracked_accounts(self) -> List[sqlite3.Row]:
        """Returns all accounts currently marked for active tracking."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM Accounts WHERE is_tracked = 1")
            return cursor.fetchall()

    def upsert_account(self, puuid: str, game_name: str, tag_line: str, 
                       summoner_id: str = None, summoner_level: int = None, 
                       profile_icon_id: int = None, is_tracked: bool = True,
                       login_name: str = None):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            now = int(time.time())
            cursor.execute('''
                INSERT INTO Accounts (puuid, game_name, tag_line, summoner_id, summoner_level, profile_icon_id, is_tracked, last_updated_epoch, login_name)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(puuid) DO UPDATE SET
                    game_name = excluded.game_name,
                    tag_line = excluded.tag_line,
                    summoner_id = COALESCE(excluded.summoner_id, Accounts.summoner_id),
                    summoner_level = COALESCE(excluded.summoner_level, Accounts.summoner_level),
                    profile_icon_id = COALESCE(excluded.profile_icon_id, Accounts.profile_icon_id),
                    last_updated_epoch = excluded.last_updated_epoch,
                    login_name = COALESCE(excluded.login_name, Accounts.login_name)
            ''', (puuid, game_name, tag_line, summoner_id, summoner_level, profile_icon_id, int(is_tracked), now, login_name))
            conn.commit()

    def upsert_ranks(self, puuid: str, ranks_data: List[Dict]):
        """Takes the raw list from League-V4 endpoint and flattens it for SQLite."""
        solo = {"tier": "UNRANKED", "rank": "", "lp": 0, "wins": 0, "losses": 0}
        flex = {"tier": "UNRANKED", "rank": "", "lp": 0, "wins": 0, "losses": 0}
        
        for q in ranks_data:
            if q.get("queueType") == "RANKED_SOLO_5x5":
                solo = {"tier": q.get("tier"), "rank": q.get("rank"), "lp": q.get("leaguePoints"), "wins": q.get("wins"), "losses": q.get("losses")}
            elif q.get("queueType") == "RANKED_FLEX_SR":
                flex = {"tier": q.get("tier"), "rank": q.get("rank"), "lp": q.get("leaguePoints"), "wins": q.get("wins"), "losses": q.get("losses")}

        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO Ranks (puuid, solo_tier, solo_rank, solo_lp, solo_wins, solo_losses, flex_tier, flex_rank, flex_lp, flex_wins, flex_losses)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(puuid) DO UPDATE SET
                    solo_tier=excluded.solo_tier, solo_rank=excluded.solo_rank, solo_lp=excluded.solo_lp, solo_wins=excluded.solo_wins, solo_losses=excluded.solo_losses,
                    flex_tier=excluded.flex_tier, flex_rank=excluded.flex_rank, flex_lp=excluded.flex_lp, flex_wins=excluded.flex_wins, flex_losses=excluded.flex_losses
            ''', (puuid, solo['tier'], solo['rank'], solo['lp'], solo['wins'], solo['losses'], 
                  flex['tier'], flex['rank'], flex['lp'], flex['wins'], flex['losses']))
            conn.commit()

    def get_known_match_ids(self, puuid: str) -> Set[str]:
        """Returns a set of match IDs we have already processed for this player."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT match_id FROM MatchIndex WHERE puuid = ?", (puuid,))
            return {row['match_id'] for row in cursor.fetchall()}

    def get_oldest_local_match_time(self, puuid: str) -> Optional[int]:
        """Returns the game_creation_time of the oldest match we have locally for this player.
        Returns None if no matches exist."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT MIN(game_creation_time) as oldest_time FROM MatchIndex WHERE puuid = ?", (puuid,))
            row = cursor.fetchone()
            if row and row['oldest_time']:
                # The Riot API returns epoch milliseconds in gameCreation, but requires epoch seconds for endTime.
                # If we saved it as ms, we divide by 1000.
                val = row['oldest_time']
                return val // 1000 if val > 1000000000000 else val
            return None

    def get_full_account_data(self) -> List[Dict]:
        """Fetches all tracked accounts and their ranks, formatted for the UI."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT 
                    a.puuid, a.game_name, a.tag_line, a.summoner_level, a.profile_icon_id, a.login_name,
                    r.solo_tier, r.solo_rank, r.solo_lp, r.solo_wins, r.solo_losses,
                    r.flex_tier, r.flex_rank, r.flex_lp, r.flex_wins, r.flex_losses
                FROM Accounts a
                LEFT JOIN Ranks r ON a.puuid = r.puuid
                WHERE a.is_tracked = 1
            ''')
            
            rows = cursor.fetchall()
            ui_data = []
            
            for row in rows:
                acc_dict = {
                    "account_name": row["game_name"],
                    "riot_tagline": row["tag_line"],
                    "puuid": row["puuid"],
                    "summonerLevel": row["summoner_level"] or 0,
                    "profileIconId": row["profile_icon_id"] or 0,
                    "login_name": row["login_name"] or "",
                    "api_solo_duo": "Unranked",
                    "api_flex": "Unranked"
                }
                
                if row["solo_tier"] and row["solo_tier"] != "UNRANKED":
                    acc_dict["api_solo_duo"] = {
                        "tier": row["solo_tier"],
                        "rank": row["solo_rank"],
                        "leaguePoints": row["solo_lp"],
                        "wins": row["solo_wins"],
                        "losses": row["solo_losses"]
                    }
                    
                if row["flex_tier"] and row["flex_tier"] != "UNRANKED":
                    acc_dict["api_flex"] = {
                        "tier": row["flex_tier"],
                        "rank": row["flex_rank"],
                        "leaguePoints": row["flex_lp"],
                        "wins": row["flex_wins"],
                        "losses": row["flex_losses"]
                    }
                    
                ui_data.append(acc_dict)
                
            return ui_data

    def insert_match_index(self, match_id: str, puuid: str, creation_time: int = 0):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT OR IGNORE INTO MatchIndex (match_id, puuid, game_creation_time)
                VALUES (?, ?, ?)
            ''', (match_id, puuid, creation_time))
            conn.commit()

if __name__ == "__main__":
    # Test script to verify database creation
    print(f"Initializing database at: {SQLITE_DB_PATH}")
    db = DBManager()
    
    with db.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = [row['name'] for row in cursor.fetchall()]
        
    print(f"Database initialized successfully. Found tables: {', '.join(tables)}")
