import time
from sqlalchemy import Column, Integer, String, Text, Boolean, ForeignKey, JSON, UniqueConstraint
from sqlalchemy.orm import relationship

from .database import Base

class Account(Base):
    """
    Unified Account Table.
    game_type should be 'LOL' or 'SC2'.
    """
    __tablename__ = "accounts"

    id = Column(Integer, primary_key=True, index=True)
    game_type = Column(String, index=True, nullable=False)
    account_name = Column(String, nullable=False)
    login_name = Column(String, nullable=True)
    folder_id = Column(String, nullable=True) # Used for SC2 legacy identification
    is_tracked = Column(Boolean, default=True)
    created_at = Column(Integer, default=lambda: int(time.time()))

    # Relationships
    lol_profile = relationship("LoLProfile", back_populates="account", uselist=False, cascade="all, delete-orphan")
    sc2_profiles = relationship("SC2Profile", back_populates="account", cascade="all, delete-orphan")


# --- League of Legends Models ---

class LoLProfile(Base):
    __tablename__ = "lol_profiles"

    id = Column(Integer, primary_key=True, index=True)
    account_id = Column(Integer, ForeignKey("accounts.id"), unique=True)

    puuid = Column(String, unique=True, index=True, nullable=False)
    game_name = Column(String, nullable=False)
    tag_line = Column(String, nullable=False)
    summoner_id = Column(String, nullable=True)
    summoner_level = Column(Integer, nullable=True)
    profile_icon_id = Column(Integer, nullable=True)
    last_updated_epoch = Column(Integer, nullable=True)
    is_in_game = Column(Boolean, default=False, nullable=True)
    current_game_start = Column(Integer, nullable=True)
    current_game_queue_id = Column(Integer, nullable=True)
    last_game_result = Column(String, nullable=True)
    last_game_queue_id = Column(Integer, nullable=True)
    last_game_lp_change = Column(Integer, nullable=True)
    last_game_ended_at = Column(Integer, nullable=True)  # epoch seconds when game ended
    created_at = Column(Integer, default=lambda: int(time.time()))
    updated_at = Column(Integer, default=lambda: int(time.time()), onupdate=lambda: int(time.time()))

    account = relationship("Account", back_populates="lol_profile")
    ranks = relationship("LoLRank", back_populates="profile", cascade="all, delete-orphan")
    masteries = relationship("LoLMastery", back_populates="profile", cascade="all, delete-orphan")
    match_participations = relationship("LoLMatchParticipant", back_populates="profile", cascade="all, delete-orphan")


class LoLRank(Base):
    __tablename__ = "lol_ranks"
    __table_args__ = (UniqueConstraint("profile_id", "queue_type", name="uq_lol_rank_profile_queue"),)

    id = Column(Integer, primary_key=True, index=True)
    profile_id = Column(Integer, ForeignKey("lol_profiles.id"))

    queue_type = Column(String, nullable=False) # e.g., RANKED_SOLO_5x5, RANKED_FLEX_SR
    tier = Column(String, nullable=False)
    rank = Column(String, nullable=False)
    lp = Column(Integer, default=0)
    wins = Column(Integer, default=0)
    losses = Column(Integer, default=0)
    decay_start = Column(Integer, nullable=True)  # epoch seconds: when last promoted into Diamond+
    updated_at = Column(Integer, default=lambda: int(time.time()), onupdate=lambda: int(time.time()))

    profile = relationship("LoLProfile", back_populates="ranks")


class LoLMatch(Base):
    __tablename__ = "lol_matches"

    match_id = Column(String, primary_key=True, index=True)
    game_creation = Column(Integer, nullable=True)
    game_duration = Column(Integer, nullable=True)

    raw_details = Column(JSON, nullable=True)
    raw_timeline = Column(JSON, nullable=True)
    created_at = Column(Integer, default=lambda: int(time.time()))

    participations = relationship("LoLMatchParticipant", back_populates="match", cascade="all, delete-orphan")


class LoLMatchParticipant(Base):
    __tablename__ = "lol_match_participants"

    profile_id = Column(Integer, ForeignKey("lol_profiles.id"), primary_key=True)
    match_id = Column(String, ForeignKey("lol_matches.match_id"), primary_key=True)

    participant_id = Column(Integer, nullable=True)

    # Structured stats extracted from raw_details at ingest time
    champion_id = Column(Integer, nullable=True)
    kills = Column(Integer, nullable=True)
    deaths = Column(Integer, nullable=True)
    assists = Column(Integer, nullable=True)
    win = Column(Boolean, nullable=True)
    role = Column(String, nullable=True)
    lane = Column(String, nullable=True)
    gold_earned = Column(Integer, nullable=True)
    total_damage_dealt = Column(Integer, nullable=True)
    cs = Column(Integer, nullable=True)
    vision_score = Column(Integer, nullable=True)
    items = Column(JSON, nullable=True)

    profile = relationship("LoLProfile", back_populates="match_participations")
    match = relationship("LoLMatch", back_populates="participations")


class LoLMastery(Base):
    __tablename__ = "lol_masteries"
    __table_args__ = (UniqueConstraint("profile_id", "champion_id", name="uq_lol_mastery_profile_champion"),)

    id = Column(Integer, primary_key=True, index=True)
    profile_id = Column(Integer, ForeignKey("lol_profiles.id"))

    champion_id = Column(Integer, nullable=False)
    mastery_level = Column(Integer, default=0)
    champion_points = Column(Integer, default=0)
    last_play_time = Column(Integer, nullable=True)
    updated_at = Column(Integer, default=lambda: int(time.time()), onupdate=lambda: int(time.time()))

    profile = relationship("LoLProfile", back_populates="masteries")


# --- StarCraft II Models ---

class SC2Profile(Base):
    __tablename__ = "sc2_profiles"

    id = Column(Integer, primary_key=True, index=True)
    account_id = Column(Integer, ForeignKey("accounts.id"))

    profile_id = Column(String, nullable=False, index=True, unique=True)
    region_id = Column(Integer, nullable=False)
    realm_id = Column(Integer, nullable=False)
    display_name = Column(String, nullable=False)
    is_in_game = Column(Boolean, default=False, nullable=True)
    current_game_map = Column(String, nullable=True)
    current_opponent = Column(String, nullable=True)
    current_game_start = Column(Integer, nullable=True)  # epoch ms
    last_game_result = Column(String, nullable=True)     # Victory / Defeat / Tie
    last_game_opponent = Column(String, nullable=True)
    last_game_ended_at = Column(Integer, nullable=True)  # epoch seconds when game ended
    last_game_mmr_change = Column(Integer, nullable=True)  # MMR delta from post-game re-fetch
    last_game_mmr_race = Column(String, nullable=True)  # race the MMR delta applies to
    last_game_gm_rank_change = Column(Integer, nullable=True)  # GM rank delta from post-game re-fetch
    created_at = Column(Integer, default=lambda: int(time.time()))
    updated_at = Column(Integer, default=lambda: int(time.time()), onupdate=lambda: int(time.time()))

    account = relationship("Account", back_populates="sc2_profiles")
    ranks = relationship("SC2Rank", back_populates="profile", cascade="all, delete-orphan")
    raw_data = relationship("SC2RawData", back_populates="profile", uselist=False, cascade="all, delete-orphan")
    matches = relationship("SC2Match", back_populates="profile", cascade="all, delete-orphan")


class SC2Rank(Base):
    __tablename__ = "sc2_ranks"
    __table_args__ = (UniqueConstraint("profile_id", "season", "race", "queue_type", name="uq_sc2_rank_profile_season_race_queue"),)

    id = Column(Integer, primary_key=True, index=True)
    profile_id = Column(Integer, ForeignKey("sc2_profiles.id"))

    season = Column(Integer, nullable=False)
    race = Column(String, nullable=False) # e.g., 'zerg', 'terran', 'protoss'
    queue_type = Column(String, nullable=False) # e.g., '1v1', '2v2'
    mmr = Column(Integer, default=0)
    league = Column(String, nullable=True) # e.g., 'Grandmaster', 'Master', 'Unranked'
    is_grandmaster = Column(Boolean, default=False, nullable=True)
    updated_at = Column(Integer, default=lambda: int(time.time()), onupdate=lambda: int(time.time()))

    profile = relationship("SC2Profile", back_populates="ranks")


class SC2Match(Base):
    __tablename__ = "sc2_matches"
    __table_args__ = (UniqueConstraint("profile_id", "date", "match_type", name="uq_sc2_match_profile_date_type"),)

    id = Column(Integer, primary_key=True, index=True)
    profile_id = Column(Integer, ForeignKey("sc2_profiles.id"), index=True)

    map = Column(String, nullable=True)
    match_type = Column(String, nullable=True)   # e.g., "1v1", "2v2"
    decision = Column(String, nullable=True)     # e.g., "Win", "Loss"
    date = Column(Integer, nullable=True)        # unix epoch
    speed = Column(String, nullable=True)        # e.g., "Faster"
    created_at = Column(Integer, default=lambda: int(time.time()))

    profile = relationship("SC2Profile", back_populates="matches")


class SC2RawData(Base):
    __tablename__ = "sc2_raw_data"

    id = Column(Integer, primary_key=True, index=True)
    profile_id = Column(Integer, ForeignKey("sc2_profiles.id"), unique=True)

    profile_summary = Column(JSON, nullable=True)
    ladder_summary = Column(JSON, nullable=True)
    match_history = Column(JSON, nullable=True)
    updated_at = Column(Integer, default=lambda: int(time.time()), onupdate=lambda: int(time.time()))

    profile = relationship("SC2Profile", back_populates="raw_data")


# --- Rank Snapshot Tables (Phase 1B) ---

class LoLRankSnapshot(Base):
    __tablename__ = "lol_rank_snapshots"

    id = Column(Integer, primary_key=True, index=True)
    profile_id = Column(Integer, ForeignKey("lol_profiles.id"), nullable=False, index=True)
    queue_type = Column(String, nullable=False)
    tier = Column(String, nullable=False)
    rank = Column(String, nullable=False)
    lp = Column(Integer, default=0)
    wins = Column(Integer, default=0)
    losses = Column(Integer, default=0)
    recorded_at = Column(Integer, default=lambda: int(time.time()), nullable=False)


class SC2RankSnapshot(Base):
    __tablename__ = "sc2_rank_snapshots"

    id = Column(Integer, primary_key=True, index=True)
    profile_id = Column(Integer, ForeignKey("sc2_profiles.id"), nullable=False, index=True)
    season = Column(Integer, nullable=False)
    race = Column(String, nullable=False)
    queue_type = Column(String, nullable=False)
    mmr = Column(Integer, default=0)
    league = Column(String, nullable=True)
    recorded_at = Column(Integer, default=lambda: int(time.time()), nullable=False)


class SC2GMThreshold(Base):
    __tablename__ = "sc2_gm_thresholds"

    region_id = Column(Integer, primary_key=True)  # 1=NA, 2=EU, 3=KR
    min_gm_mmr = Column(Integer, nullable=False, default=0)
    ladder_mmrs = Column(Text, nullable=True)  # JSON array of all GM MMRs sorted descending
    season_id = Column(Integer, nullable=True)
    season_start = Column(Integer, nullable=True)  # epoch seconds
    season_end = Column(Integer, nullable=True)    # epoch seconds
    updated_at = Column(Integer, default=lambda: int(time.time()), onupdate=lambda: int(time.time()))
