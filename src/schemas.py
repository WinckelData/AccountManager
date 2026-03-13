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

@dataclass
class LoLProfileDTO:
    account_name: str
    riot_tagline: str
    puuid: str
    summoner_level: int
    profile_icon_id: int
    login_name: str
    solo_duo_rank: Optional[RankDTO] = None
    flex_rank: Optional[RankDTO] = None


# --- StarCraft II DTOs ---

@dataclass
class SC2RankDTO:
    league: str
    mmr: int

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

@dataclass
class SC2AccountDTO:
    account_name: str
    email: str
    account_folder_id: str
    profiles: List[SC2ProfileDTO] = field(default_factory=list)
