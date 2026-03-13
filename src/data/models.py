import time
from sqlalchemy import Column, Integer, String, Boolean, ForeignKey, JSON
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

    account = relationship("Account", back_populates="lol_profile")
    ranks = relationship("LoLRank", back_populates="profile", cascade="all, delete-orphan")
    masteries = relationship("LoLMastery", back_populates="profile", cascade="all, delete-orphan")
    match_participations = relationship("LoLMatchParticipant", back_populates="profile", cascade="all, delete-orphan")


class LoLRank(Base):
    __tablename__ = "lol_ranks"

    id = Column(Integer, primary_key=True, index=True)
    profile_id = Column(Integer, ForeignKey("lol_profiles.id"))
    
    queue_type = Column(String, nullable=False) # e.g., RANKED_SOLO_5x5, RANKED_FLEX_SR
    tier = Column(String, nullable=False)
    rank = Column(String, nullable=False)
    lp = Column(Integer, default=0)
    wins = Column(Integer, default=0)
    losses = Column(Integer, default=0)

    profile = relationship("LoLProfile", back_populates="ranks")


class LoLMatch(Base):
    __tablename__ = "lol_matches"

    match_id = Column(String, primary_key=True, index=True)
    game_creation = Column(Integer, nullable=True)
    game_duration = Column(Integer, nullable=True)
    
    raw_details = Column(JSON, nullable=True)
    raw_timeline = Column(JSON, nullable=True)

    participations = relationship("LoLMatchParticipant", back_populates="match", cascade="all, delete-orphan")


class LoLMatchParticipant(Base):
    __tablename__ = "lol_match_participants"

    profile_id = Column(Integer, ForeignKey("lol_profiles.id"), primary_key=True)
    match_id = Column(String, ForeignKey("lol_matches.match_id"), primary_key=True)
    
    # Store relationship to the specific participation record in a match
    # e.g. participant_id inside the JSON, so we can join if needed later
    participant_id = Column(Integer, nullable=True) 

    profile = relationship("LoLProfile", back_populates="match_participations")
    match = relationship("LoLMatch", back_populates="participations")


class LoLMastery(Base):
    __tablename__ = "lol_masteries"

    id = Column(Integer, primary_key=True, index=True)
    profile_id = Column(Integer, ForeignKey("lol_profiles.id"))
    
    champion_id = Column(Integer, nullable=False)
    mastery_level = Column(Integer, default=0)
    champion_points = Column(Integer, default=0)
    last_play_time = Column(Integer, nullable=True)

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

    account = relationship("Account", back_populates="sc2_profiles")
    ranks = relationship("SC2Rank", back_populates="profile", cascade="all, delete-orphan")
    raw_data = relationship("SC2RawData", back_populates="profile", uselist=False, cascade="all, delete-orphan")


class SC2Rank(Base):
    __tablename__ = "sc2_ranks"

    id = Column(Integer, primary_key=True, index=True)
    profile_id = Column(Integer, ForeignKey("sc2_profiles.id"))
    
    season = Column(Integer, nullable=False)
    race = Column(String, nullable=False) # e.g., 'zerg', 'terran', 'protoss'
    queue_type = Column(String, nullable=False) # e.g., '1v1', '2v2'
    mmr = Column(Integer, default=0)
    league = Column(String, nullable=True) # e.g., 'Grandmaster', 'Master', 'Unranked'

    profile = relationship("SC2Profile", back_populates="ranks")


class SC2RawData(Base):
    __tablename__ = "sc2_raw_data"

    id = Column(Integer, primary_key=True, index=True)
    profile_id = Column(Integer, ForeignKey("sc2_profiles.id"), unique=True)
    
    profile_summary = Column(JSON, nullable=True)
    ladder_summary = Column(JSON, nullable=True)
    match_history = Column(JSON, nullable=True)

    profile = relationship("SC2Profile", back_populates="raw_data")