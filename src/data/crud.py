import time
from typing import List, Optional, Dict, Any, Sequence

from sqlalchemy.orm import Session
from sqlalchemy import select, delete, update
from sqlalchemy.dialects.sqlite import insert

from sqlalchemy import literal_column

from src.data.models import (
    Account,
    LoLProfile,
    LoLRank,
    LoLRankSnapshot,
    LoLMatch,
    LoLMatchParticipant,
    LoLMastery,
    SC2Profile,
    SC2Rank,
    SC2RankSnapshot,
    SC2RawData,
    SC2Match,
    SC2GMThreshold,
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


def delete_account(db: Session, account_id: int) -> None:
    """Delete an account and all its associated data."""
    acc = db.get(Account, account_id)
    if not acc:
        return

    # Manually delete rank snapshots (no ORM cascade relationship defined)
    if acc.lol_profile:
        profile_id = acc.lol_profile.id
        db.execute(delete(LoLRankSnapshot).where(LoLRankSnapshot.profile_id == profile_id))

    for sc2_prof in acc.sc2_profiles:
        db.execute(delete(SC2RankSnapshot).where(SC2RankSnapshot.profile_id == sc2_prof.id))

    db.delete(acc)  # ORM cascade handles: LoLProfile, LoLRank, LoLMastery, LoLMatchParticipant, SC2Profile, SC2Rank, SC2RawData
    db.flush()


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
    now = int(time.time())
    stmt = insert(LoLProfile).values(
        account_id=account_id,
        puuid=puuid,
        game_name=game_name,
        tag_line=tag_line,
        summoner_id=summoner_id,
        summoner_level=summoner_level,
        profile_icon_id=profile_icon_id,
        last_updated_epoch=last_updated_epoch,
        created_at=now,
        updated_at=now,
    )

    upsert_stmt = stmt.on_conflict_do_update(
        index_elements=["puuid"],
        set_=dict(
            game_name=stmt.excluded.game_name,
            tag_line=stmt.excluded.tag_line,
            summoner_id=stmt.excluded.summoner_id,
            summoner_level=stmt.excluded.summoner_level,
            profile_icon_id=stmt.excluded.profile_icon_id,
            last_updated_epoch=stmt.excluded.last_updated_epoch,
            updated_at=now,
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
) -> bool:
    """
    True upsert for LoL rank using the unique constraint (profile_id, queue_type).
    Records a snapshot if the rank data changed. Returns True if data changed.
    """
    now = int(time.time())
    decay_tiers = {"DIAMOND", "MASTER", "GRANDMASTER", "CHALLENGER"}

    # Fetch current rank to detect change before upserting
    existing = db.execute(
        select(LoLRank).where(
            LoLRank.profile_id == profile_id,
            LoLRank.queue_type == queue_type,
        )
    ).scalar_one_or_none()

    # Determine decay_start value
    new_is_decay = tier.upper() in decay_tiers
    old_is_decay = existing is not None and existing.tier.upper() in decay_tiers
    if new_is_decay and not old_is_decay:
        # Fresh promotion into Diamond+ → set decay_start
        decay_start = now
    elif new_is_decay and old_is_decay:
        # Already Diamond+ → preserve existing decay_start
        decay_start = existing.decay_start if existing.decay_start else now
    else:
        # Below Diamond → no decay
        decay_start = None

    stmt = insert(LoLRank).values(
        profile_id=profile_id,
        queue_type=queue_type,
        tier=tier,
        rank=rank,
        lp=lp,
        wins=wins,
        losses=losses,
        decay_start=decay_start,
        updated_at=now,
    )
    upsert_stmt = stmt.on_conflict_do_update(
        index_elements=["profile_id", "queue_type"],
        set_=dict(
            tier=stmt.excluded.tier,
            rank=stmt.excluded.rank,
            lp=stmt.excluded.lp,
            wins=stmt.excluded.wins,
            losses=stmt.excluded.losses,
            decay_start=decay_start,
            updated_at=now,
        )
    )
    db.execute(upsert_stmt)

    # Record snapshot if anything changed (or first time)
    changed = (
        existing is None
        or existing.tier != tier
        or existing.rank != rank
        or existing.lp != lp
        or existing.wins != wins
        or existing.losses != losses
    )
    if changed:
        db.add(LoLRankSnapshot(
            profile_id=profile_id,
            queue_type=queue_type,
            tier=tier,
            rank=rank,
            lp=lp,
            wins=wins,
            losses=losses,
            recorded_at=now,
        ))

    db.flush()
    return changed


def upsert_lol_masteries(
    db: Session,
    profile_id: int,
    masteries: List[Dict[str, Any]]
) -> None:
    """
    True upsert for mastery records using the unique constraint (profile_id, champion_id).
    `masteries` should be a list of dicts:
    [{"champion_id": int, "mastery_level": int, "champion_points": int, "last_play_time": int}, ...]
    """
    now = int(time.time())
    for m in masteries:
        stmt = insert(LoLMastery).values(
            profile_id=profile_id,
            champion_id=m["champion_id"],
            mastery_level=m["mastery_level"],
            champion_points=m["champion_points"],
            last_play_time=m["last_play_time"],
            updated_at=now,
        )
        upsert_stmt = stmt.on_conflict_do_update(
            index_elements=["profile_id", "champion_id"],
            set_=dict(
                mastery_level=stmt.excluded.mastery_level,
                champion_points=stmt.excluded.champion_points,
                last_play_time=stmt.excluded.last_play_time,
                updated_at=now,
            )
        )
        db.execute(upsert_stmt)
    db.flush()


def get_lol_match_ids(db: Session, profile_id: int) -> List[str]:
    """Retrieve all match IDs stored for a given profile."""
    stmt = select(LoLMatchParticipant.match_id).where(LoLMatchParticipant.profile_id == profile_id)
    return list(db.execute(stmt).scalars().all())


def add_lol_match(
    db: Session,
    profile_id: int,
    match_id: str,
    puuid: Optional[str] = None,
    game_creation: Optional[int] = None,
    game_duration: Optional[int] = None,
    raw_details: Optional[dict] = None,
    raw_timeline: Optional[dict] = None,
) -> None:
    """
    Insert a match and its participant link if it doesn't already exist.
    Extracts structured stats from raw_details when puuid is provided.
    """
    now = int(time.time())

    # 1. Upsert Match
    stmt = insert(LoLMatch).values(
        match_id=match_id,
        game_creation=game_creation,
        game_duration=game_duration,
        raw_details=raw_details,
        raw_timeline=raw_timeline,
        created_at=now,
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

    # 2. Extract structured participant stats
    participant_stats: Dict[str, Any] = {}
    if puuid and raw_details:
        participants = raw_details.get("info", {}).get("participants", [])
        p = next((x for x in participants if x.get("puuid") == puuid), None)
        if p:
            participant_stats = {
                "champion_id": p.get("championId"),
                "kills": p.get("kills"),
                "deaths": p.get("deaths"),
                "assists": p.get("assists"),
                "win": p.get("win"),
                "role": p.get("role"),
                "lane": p.get("lane"),
                "gold_earned": p.get("goldEarned"),
                "total_damage_dealt": p.get("totalDamageDealtToChampions"),
                "cs": (p.get("totalMinionsKilled") or 0) + (p.get("neutralMinionsKilled") or 0),
                "vision_score": p.get("visionScore"),
                "items": [p.get(f"item{i}") for i in range(7)],
            }

    # 3. Upsert Participant relationship with stats
    part_stmt = insert(LoLMatchParticipant).values(
        profile_id=profile_id,
        match_id=match_id,
        **participant_stats,
    )
    upsert_part_stmt = part_stmt.on_conflict_do_update(
        index_elements=["profile_id", "match_id"],
        set_={k: part_stmt.excluded[k] for k in participant_stats} if participant_stats else {"profile_id": part_stmt.excluded.profile_id},
    )
    db.execute(upsert_part_stmt)
    db.flush()


def set_lol_in_game_status(
    db: Session,
    profile_id: int,
    is_in_game: bool,
    current_game_start: Optional[int] = None,
    current_game_queue_id: Optional[int] = None,
    last_game_result: Optional[str] = None,
    last_game_queue_id: Optional[int] = None,
    last_game_lp_change: Optional[int] = None,
    clear_result: bool = False,
) -> None:
    """Update the in-game status for a LoL profile.

    Pass clear_result=True to explicitly null out last_game_* fields.
    Otherwise those fields are only updated when a non-None value is provided.
    """
    values: Dict[str, Any] = {
        "is_in_game": is_in_game,
        "current_game_start": current_game_start,
        "current_game_queue_id": current_game_queue_id,
    }
    if last_game_result is not None or clear_result:
        values["last_game_result"] = last_game_result
    if last_game_queue_id is not None or clear_result:
        values["last_game_queue_id"] = last_game_queue_id
    if last_game_lp_change is not None or clear_result:
        values["last_game_lp_change"] = last_game_lp_change
    # Record game end timestamp when transitioning to not-in-game with a result
    if not is_in_game and last_game_result is not None:
        values["last_game_ended_at"] = int(time.time())
    if clear_result:
        values["last_game_ended_at"] = None

    db.execute(
        update(LoLProfile)
        .where(LoLProfile.id == profile_id)
        .values(**values)
    )
    db.flush()


def get_lol_current_rank(db: Session, profile_id: int, queue_type: str) -> Optional[LoLRank]:
    """Fetch the current LoL rank for a profile and queue type."""
    return db.execute(
        select(LoLRank).where(
            LoLRank.profile_id == profile_id,
            LoLRank.queue_type == queue_type,
        )
    ).scalar_one_or_none()


def clear_all_live_states(db: Session) -> None:
    """Reset all in-game and post-game state for both LoL and SC2 profiles.

    Called on app startup so stale live status from a previous session
    doesn't persist in the UI.
    """
    db.execute(
        update(LoLProfile).values(
            is_in_game=False,
            current_game_start=None,
            current_game_queue_id=None,
            last_game_result=None,
            last_game_queue_id=None,
            last_game_lp_change=None,
            last_game_ended_at=None,
        )
    )
    db.execute(
        update(SC2Profile).values(
            is_in_game=False,
            current_game_map=None,
            current_opponent=None,
            current_game_start=None,
            last_game_result=None,
            last_game_opponent=None,
            last_game_ended_at=None,
            last_game_mmr_change=None,
            last_game_mmr_race=None,
            last_game_gm_rank_change=None,
        )
    )
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
    now = int(time.time())
    stmt = insert(SC2Profile).values(
        account_id=account_id,
        profile_id=profile_id,
        region_id=region_id,
        realm_id=realm_id,
        display_name=display_name,
        created_at=now,
        updated_at=now,
    )
    upsert_stmt = stmt.on_conflict_do_update(
        index_elements=["profile_id"],
        set_=dict(
            display_name=stmt.excluded.display_name,
            updated_at=now,
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
    is_grandmaster: bool = False,
) -> bool:
    """
    True upsert for SC2 rank using the unique constraint.
    Records a snapshot if the rank data changed. Returns True if data changed.
    """
    now = int(time.time())

    existing = db.execute(
        select(SC2Rank).where(
            SC2Rank.profile_id == profile_id,
            SC2Rank.season == season,
            SC2Rank.race == race,
            SC2Rank.queue_type == queue_type,
        )
    ).scalar_one_or_none()

    stmt = insert(SC2Rank).values(
        profile_id=profile_id,
        season=season,
        race=race,
        queue_type=queue_type,
        mmr=mmr,
        league=league,
        is_grandmaster=is_grandmaster,
        updated_at=now,
    )
    upsert_stmt = stmt.on_conflict_do_update(
        index_elements=["profile_id", "season", "race", "queue_type"],
        set_=dict(
            mmr=stmt.excluded.mmr,
            league=stmt.excluded.league,
            is_grandmaster=stmt.excluded.is_grandmaster,
            updated_at=now,
        )
    )
    db.execute(upsert_stmt)

    changed = existing is None or existing.mmr != mmr or existing.league != league
    if changed:
        db.add(SC2RankSnapshot(
            profile_id=profile_id,
            season=season,
            race=race,
            queue_type=queue_type,
            mmr=mmr,
            league=league,
            recorded_at=now,
        ))

    db.flush()
    return changed


def upsert_sc2_raw_data(
    db: Session,
    profile_id: int,
    profile_summary: Optional[dict] = None,
    ladder_summary: Optional[dict] = None,
    match_history: Optional[dict] = None,
) -> None:
    """Insert or update raw SC2 JSON payloads."""
    now = int(time.time())
    stmt = insert(SC2RawData).values(
        profile_id=profile_id,
        profile_summary=profile_summary,
        ladder_summary=ladder_summary,
        match_history=match_history,
        updated_at=now,
    )

    upsert_stmt = stmt.on_conflict_do_update(
        index_elements=["profile_id"],
        set_=dict(
            profile_summary=stmt.excluded.profile_summary,
            ladder_summary=stmt.excluded.ladder_summary,
            match_history=stmt.excluded.match_history,
            updated_at=now,
        )
    )
    db.execute(upsert_stmt)
    db.flush()


def set_sc2_in_game_status(
    db: Session,
    profile_id: int,
    is_in_game: bool,
    current_game_map: Optional[str] = None,
    current_opponent: Optional[str] = None,
    current_game_start: Optional[int] = None,
    last_game_result: Optional[str] = None,
    last_game_opponent: Optional[str] = None,
    last_game_mmr_change: Optional[int] = None,
    last_game_mmr_race: Optional[str] = None,
    last_game_gm_rank_change: Optional[int] = None,
    clear_result: bool = False,
) -> None:
    """Update the in-game status for an SC2 profile.

    Pass clear_result=True to explicitly null out last_game_result/last_game_opponent.
    Otherwise those fields are only updated when a non-None value is provided.
    """
    values: Dict[str, Any] = {
        "is_in_game": is_in_game,
        "current_game_map": current_game_map,
        "current_opponent": current_opponent,
        "current_game_start": current_game_start,
    }
    if last_game_result is not None or clear_result:
        values["last_game_result"] = last_game_result
    if last_game_opponent is not None or clear_result:
        values["last_game_opponent"] = last_game_opponent
    if last_game_mmr_change is not None:
        values["last_game_mmr_change"] = last_game_mmr_change
    if last_game_mmr_race is not None:
        values["last_game_mmr_race"] = last_game_mmr_race
    if last_game_gm_rank_change is not None:
        values["last_game_gm_rank_change"] = last_game_gm_rank_change
    # Record game end timestamp when transitioning to not-in-game with a result
    if not is_in_game and last_game_result is not None:
        values["last_game_ended_at"] = int(time.time())
    if clear_result:
        values["last_game_ended_at"] = None
        values["last_game_mmr_change"] = None
        values["last_game_mmr_race"] = None
        values["last_game_gm_rank_change"] = None

    db.execute(
        update(SC2Profile)
        .where(SC2Profile.id == profile_id)
        .values(**values)
    )
    db.flush()


def upsert_sc2_matches(db: Session, profile_id: int, match_history: dict) -> int:
    """Extract and upsert SC2 matches from raw match_history JSON. Returns count of NEW inserts."""
    matches = match_history.get("matches", []) if match_history else []
    if not matches:
        return 0

    # Fetch existing match keys for this profile to skip known matches
    existing = set(
        db.execute(
            select(SC2Match.date, SC2Match.match_type)
            .where(SC2Match.profile_id == profile_id)
        ).all()
    )

    new_count = 0
    for m in matches:
        date = m.get("date")
        match_type = m.get("type")
        if not date or not match_type:
            continue
        if (date, match_type) in existing:
            continue  # Already known — skip

        stmt = insert(SC2Match).values(
            profile_id=profile_id,
            map=m.get("map"),
            match_type=match_type,
            decision=m.get("decision"),
            date=date,
            speed=m.get("speed"),
            created_at=int(time.time()),
        )
        upsert_stmt = stmt.on_conflict_do_update(
            index_elements=["profile_id", "date", "match_type"],
            set_=dict(
                map=stmt.excluded.map,
                decision=stmt.excluded.decision,
                speed=stmt.excluded.speed,
            )
        )
        db.execute(upsert_stmt)
        new_count += 1
    db.flush()
    return new_count


# --- LoL Query Helpers ---

def get_earliest_match_creation(db: Session, profile_id: int) -> Optional[LoLMatch]:
    """Fetch the oldest LoL match for a profile (by game_creation ascending)."""
    from sqlalchemy.orm import aliased
    stmt = (
        select(LoLMatch)
        .join(LoLMatchParticipant, LoLMatch.match_id == LoLMatchParticipant.match_id)
        .where(LoLMatchParticipant.profile_id == profile_id)
        .order_by(LoLMatch.game_creation.asc())
        .limit(1)
    )
    return db.execute(stmt).scalar_one_or_none()


def get_lol_match_by_id(db: Session, match_id: str) -> Optional[LoLMatch]:
    """Fetch a LoL match by its match_id."""
    return db.execute(select(LoLMatch).where(LoLMatch.match_id == match_id)).scalar_one_or_none()


def update_lol_profile_puuid(db: Session, profile_id: int, new_puuid: str) -> None:
    """Update the PUUID for a LoL profile by its DB id."""
    db.execute(
        update(LoLProfile)
        .where(LoLProfile.id == profile_id)
        .values(puuid=new_puuid)
    )
    db.flush()


def get_all_sc2_display_names(db: Session) -> List[SC2Profile]:
    """Fetch all SC2 profiles (id and display_name)."""
    return list(db.execute(select(SC2Profile)).scalars().all())


# --- Rank Snapshot Queries ---

def get_lol_rank_snapshots(
    db: Session,
    profile_id: int,
    queue_type: str,
    limit: int = 30,
) -> List[LoLRankSnapshot]:
    """Fetch most recent LoL rank snapshots for a profile/queue, newest first."""
    stmt = (
        select(LoLRankSnapshot)
        .where(
            LoLRankSnapshot.profile_id == profile_id,
            LoLRankSnapshot.queue_type == queue_type,
        )
        .order_by(LoLRankSnapshot.recorded_at.desc())
        .limit(limit)
    )
    return list(db.execute(stmt).scalars().all())


def get_sc2_rank_snapshots(
    db: Session,
    profile_id: int,
    race: str,
    queue_type: str = "1v1",
    limit: int = 30,
) -> List[SC2RankSnapshot]:
    """Fetch most recent SC2 rank snapshots for a profile/race/queue, newest first."""
    stmt = (
        select(SC2RankSnapshot)
        .where(
            SC2RankSnapshot.profile_id == profile_id,
            SC2RankSnapshot.race == race,
            SC2RankSnapshot.queue_type == queue_type,
        )
        .order_by(SC2RankSnapshot.recorded_at.desc())
        .limit(limit)
    )
    return list(db.execute(stmt).scalars().all())


# --- Decay / GM Threshold Queries ---

def get_lol_ranked_matches_since(
    db: Session,
    profile_id: int,
    queue_id: int,
    since_epoch_ms: int,
) -> List[LoLMatch]:
    """Fetch LoL matches for a profile filtered by queue ID and recency."""
    stmt = (
        select(LoLMatch)
        .join(LoLMatchParticipant, LoLMatch.match_id == LoLMatchParticipant.match_id)
        .where(
            LoLMatchParticipant.profile_id == profile_id,
            LoLMatch.game_creation >= since_epoch_ms,
            literal_column("json_extract(lol_matches.raw_details, '$.info.queueId')") == queue_id,
        )
        .order_by(LoLMatch.game_creation.asc())
    )
    return list(db.execute(stmt).scalars().all())


def get_sc2_matches_since(
    db: Session,
    profile_id: int,
    since_epoch: int,
) -> List[SC2Match]:
    """Fetch SC2 matches for a profile since a given epoch timestamp."""
    stmt = (
        select(SC2Match)
        .where(
            SC2Match.profile_id == profile_id,
            SC2Match.date >= since_epoch,
        )
        .order_by(SC2Match.date.asc())
    )
    return list(db.execute(stmt).scalars().all())


def upsert_sc2_gm_threshold(
    db: Session,
    region_id: int,
    min_gm_mmr: int,
    ladder_mmrs: Optional[str] = None,
    season_id: Optional[int] = None,
    season_start: Optional[int] = None,
    season_end: Optional[int] = None,
) -> None:
    """Store/update the lowest GM MMR, ladder MMR list, and season data for a region."""
    now = int(time.time())
    stmt = insert(SC2GMThreshold).values(
        region_id=region_id,
        min_gm_mmr=min_gm_mmr,
        ladder_mmrs=ladder_mmrs,
        season_id=season_id,
        season_start=season_start,
        season_end=season_end,
        updated_at=now,
    )
    update_set = dict(min_gm_mmr=min_gm_mmr, ladder_mmrs=ladder_mmrs, updated_at=now)
    if season_id is not None:
        update_set["season_id"] = season_id
    if season_start is not None:
        update_set["season_start"] = season_start
    if season_end is not None:
        update_set["season_end"] = season_end
    upsert_stmt = stmt.on_conflict_do_update(
        index_elements=["region_id"],
        set_=update_set,
    )
    db.execute(upsert_stmt)


def get_sc2_gm_threshold(db: Session, region_id: int) -> Optional[int]:
    """Return the lowest GM MMR for a region, or None if not yet populated."""
    row = db.execute(
        select(SC2GMThreshold.min_gm_mmr).where(SC2GMThreshold.region_id == region_id)
    ).scalar_one_or_none()
    return row


def get_sc2_gm_ladder(db: Session, region_id: int) -> Optional[tuple]:
    """Return (min_mmr, List[int]) for a region's GM ladder, or None if not populated."""
    import json
    row = db.execute(
        select(SC2GMThreshold.min_gm_mmr, SC2GMThreshold.ladder_mmrs)
        .where(SC2GMThreshold.region_id == region_id)
    ).one_or_none()
    if row is None:
        return None
    min_mmr, ladder_json = row
    mmrs = json.loads(ladder_json) if ladder_json else []
    return (min_mmr, mmrs)


def get_latest_sc2_match_date(db: Session, profile_id: int) -> Optional[int]:
    """Return the most recent match date (epoch) for a profile, or None."""
    return db.execute(
        select(SC2Match.date)
        .where(SC2Match.profile_id == profile_id)
        .order_by(SC2Match.date.desc())
        .limit(1)
    ).scalar_one_or_none()


def get_sc2_season_info(db: Session, region_id: int) -> Optional[dict]:
    """Return season metadata for a region, or None if not populated."""
    row = db.execute(
        select(
            SC2GMThreshold.season_id,
            SC2GMThreshold.season_start,
            SC2GMThreshold.season_end,
        ).where(SC2GMThreshold.region_id == region_id)
    ).one_or_none()
    if row is None or row[0] is None:
        return None
    return {"season_id": row[0], "season_start": row[1], "season_end": row[2]}
