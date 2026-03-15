from dataclasses import dataclass, field
from typing import List, Dict, Optional, Any


# --- League of Legends DTOs ---

@dataclass
class RankDTO:
    tier: str
    rank: str
    lp: int
    wins: int
    losses: int
    lp_delta: int = 0  # LP change vs oldest recent snapshot (positive = gain)

@dataclass
class MasteryDTO:
    champion_id: int
    champion_points: int
    mastery_level: int
    champion_name: str = ""

@dataclass
class LoLProfileDTO:
    account_name: str
    riot_tagline: str
    puuid: str
    summoner_level: int
    profile_icon_id: int
    login_name: str
    account_id: int = 0
    solo_duo_rank: Optional[RankDTO] = None
    flex_rank: Optional[RankDTO] = None
    last_played: Optional[int] = None       # epoch ms (game_creation of most recent match)
    games_this_week: int = 0
    top_masteries: List[MasteryDTO] = field(default_factory=list)
    is_in_game: bool = False
    current_game_start: Optional[int] = None  # epoch ms
    current_game_queue_id: Optional[int] = None
    last_game_result: Optional[str] = None
    last_game_queue_id: Optional[int] = None
    last_game_lp_change: Optional[int] = None


# --- StarCraft II DTOs ---

@dataclass
class SC2RankDTO:
    league: str
    mmr: int
    mmr_delta: int = 0          # MMR change vs oldest recent snapshot
    is_grandmaster: bool = False

@dataclass
class SC2ProfileDTO:
    profile_id: str
    region: int
    realm: int
    name: str
    ranks: Dict[str, SC2RankDTO] = field(default_factory=dict)
    history: Dict[str, Any] = field(default_factory=dict)
    summary: Dict[str, Any] = field(default_factory=dict)
    ladders: Dict[str, Any] = field(default_factory=dict)
    match_count: int = 0
    is_in_game: bool = False
    current_opponent: Optional[str] = None
    current_game_start: Optional[int] = None  # epoch ms
    last_game_result: Optional[str] = None    # Victory / Defeat / Tie
    last_game_opponent: Optional[str] = None

@dataclass
class SC2AccountDTO:
    account_name: str
    email: str
    account_folder_id: str
    profiles: List[SC2ProfileDTO] = field(default_factory=list)
