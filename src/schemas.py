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
    decay_bank_days: Optional[int] = None   # banked days remaining (None = not Diamond+)
    decay_active: bool = False               # True if bank is 0 and losing LP
    decay_lp_per_day: Optional[int] = None   # 50 for Diamond, 75 for Apex

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
    last_game_ended_at: Optional[int] = None  # epoch seconds


# --- StarCraft II DTOs ---

@dataclass
class SC2RankDTO:
    league: str
    mmr: int
    mmr_delta: int = 0          # MMR change vs oldest recent snapshot
    is_grandmaster: bool = False
    gm_demotion_days: Optional[int] = None            # days until game count drops below 30 (without games)
    gm_games_to_safety: Optional[int] = None          # games needed today to extend demotion by 1+ day
    gm_mmr_threshold: Optional[int] = None           # lowest GM MMR on server (Masters only)
    mmr_above_gm: Optional[int] = None               # mmr - gm_threshold (Masters only)
    gm_rank: Optional[int] = None                    # actual GM ladder rank (GM accounts only)
    gm_projected_rank: Optional[int] = None          # projected rank if promoted (Masters above threshold)
    gm_games_played_3weeks: Optional[int] = None     # games in last 21 days (Masters above threshold)

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
    last_game_ended_at: Optional[int] = None  # epoch seconds
    last_game_mmr_change: Optional[int] = None  # MMR delta from post-game re-fetch
    last_game_mmr_race: Optional[str] = None  # race the MMR delta applies to
    last_game_gm_rank_change: Optional[int] = None  # GM rank delta from post-game re-fetch

@dataclass
class SC2AccountDTO:
    account_name: str
    email: str
    account_folder_id: str
    profiles: List[SC2ProfileDTO] = field(default_factory=list)
