import time
from typing import List, Optional, Dict, Any, Sequence

from sqlalchemy.orm import Session
from sqlalchemy import select, update, delete
from sqlalchemy.dialects.sqlite import insert

from src.data.models import (
    Account,
    LoLProfile,
    LoLRank,
    LoLMatch,
    LoLMatchParticipant,
    LoLMastery,
    SC2Profile,
    SC2Rank,
    SC2RawData,
)


# --- Accounts ---

def get_accounts(db: Session, game_type: Optional[str] = None) -> Sequence[Account]:
    """Retrieve all accounts, optionally filtered by game_type."""
    stmt = select(Account)
    if game_type:
        stmt = stmt.where(Account.game_type == game_type)
    return db.execute(stmt).scalars().all()


def get_tracked_accounts(db: Session, game_type: Optional[str] = None) -> Sequence[Account]:
    """Retrieve tracked accounts, optionally filtered by game_type."""
    stmt = select(Account).where(Account.is_tracked == True)
    if game_type:
        stmt = stmt.where(Account.game_type == game_type)
    return db.execute(stmt).scalars().all()


def create_account(
    db: Session,
    game_type: str,
    account_name: str,
    login_name: Optional[str] = None,
    folder_id: Optional[str] = None,
    is_tracked: bool = True
) -> Account:
    """Create a new core Account record."""
    acc = Account(
        game_type=game_type,
        account_name=account_name,
        login_name=login_name,
        folder_id=folder_id,
        is_tracked=is_tracked,
        created_at=int(time.time()),
    )
    db.add(acc)
    db.flush()
    return acc


def update_account(
    db: Session,
    account_id: int,
    account_name: Optional[str] = None,
    login_name: Optional[str] = None,
    is_tracked: Optional[bool] = None,
) -> Optional[Account]:
    """Update an existing account by its ID."""
    acc = db.execute(select(Account).where(Account.id == account_id)).scalar_one_or_none()
    if acc:
        if account_name is not None:
            acc.account_name = account_name
        if login_name is not None:
            acc.login_name = login_name
        if is_tracked is not None:
            acc.is_tracked = is_tracked
        db.flush()
    return acc


# --- League of Legends ---

def get_lol_profile(db: Session, puuid: str) -> Optional[LoLProfile]:
    """Fetch a LoL profile by its PUUID."""
    return db.execute(select(LoLProfile).where(LoLProfile.puuid == puuid)).scalar_one_or_none()


def upsert_lol_profile(
    db: Session,
    account_id: int,
    puuid: str,
    game_name: str,
    tag_line: str,
    summoner_id: Optional[str] = None,
    summoner_level: Optional[int] = None,
    profile_icon_id: Optional[int] = None,
    last_updated_epoch: Optional[int] = None,
) -> int:
    """Insert or update a LoL Profile using SQLite's native upsert."""
    stmt = insert(LoLProfile).values(
        account_id=account_id,
        puuid=puuid,
        game_name=game_name,
        tag_line=tag_line,
        summoner_id=summoner_id,
        summoner_level=summoner_level,
        profile_icon_id=profile_icon_id,
        last_updated_epoch=last_updated_epoch,
    )
    
    # On conflict of puuid, update the corresponding fields
    upsert_stmt = stmt.on_conflict_do_update(
        index_elements=["puuid"],
        set_=dict(
            game_name=stmt.excluded.game_name,
            tag_line=stmt.excluded.tag_line,
            summoner_id=stmt.excluded.summoner_id,
            summoner_level=stmt.excluded.summoner_level,
            profile_icon_id=stmt.excluded.profile_icon_id,
            last_updated_epoch=stmt.excluded.last_updated_epoch,
        )
    ).returning(LoLProfile.id)
    
    return db.execute(upsert_stmt).scalar_one()


def upsert_lol_ranks(
    db: Session,
    profile_id: int,
    queue_type: str,
    tier: str,
    rank: str,
    lp: int,
    wins: int,
    losses: int,
) -> None:
    """Upserts rank data. First deletes the existing rank for this queue and profile, then inserts."""
    # We could do a complex unique constraint upsert, but simple delete/insert is safe and explicit for compound keys here
    db.execute(
        delete(LoLRank).where(
            LoLRank.profile_id == profile_id,
            LoLRank.queue_type == queue_type
        )
    )
    db.add(LoLRank(
        profile_id=profile_id,
        queue_type=queue_type,
        tier=tier,
        rank=rank,
        lp=lp,
        wins=wins,
        losses=losses,
    ))
    db.flush()


def upsert_lol_masteries(
    db: Session,
    profile_id: int,
    masteries: List[Dict[str, Any]]
) -> None:
    """
    Clears out old masteries and inserts the new list.
    `masteries` should be a list of dicts:
    [{"champion_id": int, "mastery_level": int, "champion_points": int, "last_play_time": int}, ...]
    """
    db.execute(delete(LoLMastery).where(LoLMastery.profile_id == profile_id))
    
    objects = []
    for m in masteries:
        objects.append(LoLMastery(
            profile_id=profile_id,
            champion_id=m["champion_id"],
            mastery_level=m["mastery_level"],
            champion_points=m["champion_points"],
            last_play_time=m["last_play_time"]
        ))
    if objects:
        db.add_all(objects)
    db.flush()


def get_lol_match_ids(db: Session, profile_id: int) -> List[str]:
    """Retrieve all match IDs stored for a given profile."""
    stmt = select(LoLMatchParticipant.match_id).where(LoLMatchParticipant.profile_id == profile_id)
    return list(db.execute(stmt).scalars().all())


def add_lol_match(
    db: Session,
    profile_id: int,
    match_id: str,
    game_creation: Optional[int] = None,
    game_duration: Optional[int] = None,
    raw_details: Optional[dict] = None,
    raw_timeline: Optional[dict] = None,
) -> None:
    """
    Insert a match and its participant link if it doesn't already exist.
    Uses native upsert for the Match table to avoid Integrity errors.
    """
    # 1. Upsert Match
    stmt = insert(LoLMatch).values(
        match_id=match_id,
        game_creation=game_creation,
        game_duration=game_duration,
        raw_details=raw_details,
        raw_timeline=raw_timeline,
    )
    upsert_match_stmt = stmt.on_conflict_do_update(
        index_elements=["match_id"],
        set_=dict(
            game_creation=stmt.excluded.game_creation,
            game_duration=stmt.excluded.game_duration,
            raw_details=stmt.excluded.raw_details,
            raw_timeline=stmt.excluded.raw_timeline,
        )
    )
    db.execute(upsert_match_stmt)
    
    # 2. Add Participant relationship (Ignore if exists)
    part_stmt = insert(LoLMatchParticipant).values(
        profile_id=profile_id,
        match_id=match_id
    )
    # Using do_nothing for the join table
    upsert_part_stmt = part_stmt.on_conflict_do_nothing(
        index_elements=["profile_id", "match_id"]
    )
    db.execute(upsert_part_stmt)
    db.flush()


# --- StarCraft II ---

def get_sc2_profile(db: Session, profile_id: str) -> Optional[SC2Profile]:
    """Fetch an SC2 Profile by its global profile ID (region-realm-id)."""
    return db.execute(select(SC2Profile).where(SC2Profile.profile_id == profile_id)).scalar_one_or_none()


def upsert_sc2_profile(
    db: Session,
    account_id: int,
    profile_id: str,
    region_id: int,
    realm_id: int,
    display_name: str,
) -> int:
    """Insert or update an SC2 Profile."""
    stmt = insert(SC2Profile).values(
        account_id=account_id,
        profile_id=profile_id,
        region_id=region_id,
        realm_id=realm_id,
        display_name=display_name,
    )
    upsert_stmt = stmt.on_conflict_do_update(
        index_elements=["profile_id"],
        set_=dict(
            display_name=stmt.excluded.display_name,
        )
    ).returning(SC2Profile.id)
    
    return db.execute(upsert_stmt).scalar_one()


def upsert_sc2_ranks(
    db: Session,
    profile_id: int,
    season: int,
    race: str,
    queue_type: str,
    mmr: int,
    league: Optional[str],
) -> None:
    """
    Clears existing rank for this specific season, race, and queue, and inserts the new one.
    """
    db.execute(
        delete(SC2Rank).where(
            SC2Rank.profile_id == profile_id,
            SC2Rank.season == season,
            SC2Rank.race == race,
            SC2Rank.queue_type == queue_type
        )
    )
    db.add(SC2Rank(
        profile_id=profile_id,
        season=season,
        race=race,
        queue_type=queue_type,
        mmr=mmr,
        league=league,
    ))
    db.flush()


def upsert_sc2_raw_data(
    db: Session,
    profile_id: int,
    profile_summary: Optional[dict] = None,
    ladder_summary: Optional[dict] = None,
    match_history: Optional[dict] = None,
) -> None:
    """Insert or update raw SC2 JSON payloads."""
    stmt = insert(SC2RawData).values(
        profile_id=profile_id,
        profile_summary=profile_summary,
        ladder_summary=ladder_summary,
        match_history=match_history,
    )
    
    upsert_stmt = stmt.on_conflict_do_update(
        index_elements=["profile_id"],
        set_=dict(
            profile_summary=stmt.excluded.profile_summary,
            ladder_summary=stmt.excluded.ladder_summary,
            match_history=stmt.excluded.match_history,
        )
    )
    db.execute(upsert_stmt)
    db.flush()
