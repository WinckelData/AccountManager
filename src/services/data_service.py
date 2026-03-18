import os
import re
import time
from typing import List, Optional, Tuple

from sqlalchemy import select, func
from sqlalchemy.orm import selectinload, Session

from src.data.database import SessionLocal
from src.data.models import Account, LoLProfile, LoLMatch, LoLMatchParticipant, LoLMastery
from src.data import crud
from src.schemas import (
    LoLProfileDTO, RankDTO, MasteryDTO,
    SC2AccountDTO, SC2ProfileDTO, SC2RankDTO,
)
from src.static_data import StaticDataManager

_DECAY_TIERS = {"DIAMOND", "MASTER", "GRANDMASTER", "CHALLENGER"}
_APEX_TIERS = {"MASTER", "GRANDMASTER", "CHALLENGER"}
_QUEUE_ID_MAP = {"RANKED_SOLO_5x5": 420, "RANKED_FLEX_SR": 440}


def _compute_lol_decay(
    db: Session, profile_id: int, tier: str, queue_type: str, decay_start: Optional[int]
) -> dict:
    """Compute decay bank for a Diamond+ LoL rank.

    Uses the official rules from:
    https://support-leagueoflegends.riotgames.com/hc/en-us/articles/4405783687443

    Returns dict with bank_days/active/lp_per_day (all None if below Diamond).
    """
    tier_upper = tier.upper()
    if tier_upper not in _DECAY_TIERS:
        return {"bank_days": None, "active": False, "lp_per_day": None}

    is_apex = tier_upper in _APEX_TIERS
    initial_bank = 14 if is_apex else 28
    days_per_game = 1 if is_apex else 7
    max_bank = 14 if is_apex else 28
    lp_per_day = 75 if is_apex else 50

    now = time.time()

    # Determine simulation window start
    if decay_start:
        window_start = max(decay_start, now - max_bank * 86400)
    else:
        # Fallback: no decay_start recorded (pre-existing data) — assume full window
        window_start = now - max_bank * 86400

    queue_id = _QUEUE_ID_MAP.get(queue_type, 420)
    since_ms = int(window_start * 1000)
    matches = crud.get_lol_ranked_matches_since(db, profile_id, queue_id, since_ms)
    match_times = sorted([m.game_creation / 1000 for m in matches if m.game_creation])

    # Simulate day-by-day from window_start to now
    total_days = max(1, int((now - window_start) / 86400) + 1)
    bank = initial_bank

    for day_offset in range(total_days):
        day_start = window_start + (day_offset * 86400)
        day_end = day_start + 86400
        games_today = sum(1 for t in match_times if day_start <= t < day_end)

        if games_today > 0:
            bank = min(max_bank, bank + (games_today * days_per_game))
        else:
            bank = max(0, bank - 1)

    return {
        "bank_days": bank,
        "active": bank == 0,
        "lp_per_day": lp_per_day,
    }


def _simulate_gm_demotion(match_dates: list, now: float) -> tuple:
    """Day-by-day simulation of GM game count requirement.

    Returns (demotion_days, games_to_safety):
      - demotion_days: days from today until game count drops below 30 (without playing)
      - games_to_safety: games needed today to push demotion 1+ day further
    """
    DAY = 86400
    today_start = int(now // DAY) * DAY

    # Simulate up to 22 days into the future (max window is 21 days)
    demotion_days = None
    for day_offset in range(22):
        future_day = today_start + day_offset * DAY
        window_start = future_day - 21 * DAY
        count = sum(1 for d in match_dates if window_start <= d < future_day + DAY)
        if count < 30:
            demotion_days = day_offset
            break

    if demotion_days is None:
        demotion_days = 22  # safe for longer than simulation window

    # Calculate games_to_safety: how many games today to extend demotion by at least 1 day
    games_to_safety = 0
    if demotion_days < 22:
        # Simulate: if we play N games "today", how does demotion_day shift?
        for extra in range(1, 31):
            # Add extra games at today's timestamp
            test_dates = match_dates + [today_start + DAY // 2] * extra
            new_demotion = None
            for day_offset in range(22):
                future_day = today_start + day_offset * DAY
                window_start = future_day - 21 * DAY
                count = sum(1 for d in test_dates if window_start <= d < future_day + DAY)
                if count < 30:
                    new_demotion = day_offset
                    break
            if new_demotion is None:
                new_demotion = 22
            if new_demotion > demotion_days:
                games_to_safety = extra
                break

    return demotion_days, games_to_safety if games_to_safety > 0 else None


def _compute_sc2_gm_info(
    db: Session, profile_db_id: int, rank, region_id: int
) -> dict:
    """Compute GM tracking info for an SC2 rank.

    For GM: day-by-day demotion simulation, games to extend safety, actual rank.
    For Masters: MMR gap vs GM threshold, projected rank + demotion info if above threshold.
    """
    result = {}
    ladder_data = crud.get_sc2_gm_ladder(db, region_id)
    ladder_mmrs = ladder_data[1] if ladder_data else []
    threshold = ladder_data[0] if ladder_data else None

    now = time.time()

    if rank.is_grandmaster:
        three_weeks_ago = int(now) - (21 * 86400)
        matches = crud.get_sc2_matches_since(db, profile_db_id, three_weeks_ago)
        match_dates = [m.date for m in matches if m.date]

        demotion_days, games_to_safety = _simulate_gm_demotion(match_dates, now)
        result["gm_demotion_days"] = demotion_days
        result["gm_games_to_safety"] = games_to_safety

        # Compute actual GM rank from ladder MMRs
        if ladder_mmrs:
            result["gm_rank"] = sum(1 for m in ladder_mmrs if m > rank.mmr) + 1

    elif rank.league and rank.league.lower() == "master":
        if threshold is not None:
            result["gm_mmr_threshold"] = threshold
            result["mmr_above_gm"] = rank.mmr - threshold

            # For Masters above threshold: projected rank + games toward 30-game promotion req
            if rank.mmr >= threshold and ladder_mmrs:
                result["gm_projected_rank"] = sum(1 for m in ladder_mmrs if m > rank.mmr) + 1
                three_weeks_ago = int(now) - (21 * 86400)
                matches = crud.get_sc2_matches_since(db, profile_db_id, three_weeks_ago)
                result["gm_games_played_3weeks"] = len(matches)

    return result


_LP_PER_RANK = {"IV": 0, "III": 100, "II": 200, "I": 300}
_TIER_LP = {
    "IRON": 0, "BRONZE": 400, "SILVER": 800, "GOLD": 1200,
    "PLATINUM": 1600, "EMERALD": 2000, "DIAMOND": 2400,
    "MASTER": 2800, "GRANDMASTER": 2800, "CHALLENGER": 2800,
}

def _absolute_lp(tier: str, rank: str, lp: int) -> int:
    """Convert tier/rank/lp to a single comparable integer."""
    return _TIER_LP.get(tier.upper(), 0) + _LP_PER_RANK.get(rank.upper(), 0) + lp


def _compute_lol_extras(db: Session, profile: LoLProfile, champ_map: dict) -> dict:
    """Return last_played (ms epoch), games_this_week, top 3 masteries."""
    week_ago_ms = (int(time.time()) - 7 * 86400) * 1000

    last_played = db.execute(
        select(func.max(LoLMatch.game_creation))
        .join(LoLMatchParticipant, LoLMatch.match_id == LoLMatchParticipant.match_id)
        .where(LoLMatchParticipant.profile_id == profile.id)
    ).scalar()

    games_this_week = db.execute(
        select(func.count())
        .select_from(LoLMatchParticipant)
        .join(LoLMatch, LoLMatch.match_id == LoLMatchParticipant.match_id)
        .where(
            LoLMatchParticipant.profile_id == profile.id,
            LoLMatch.game_creation >= week_ago_ms,
        )
    ).scalar() or 0

    top_masteries_rows = db.execute(
        select(LoLMastery)
        .where(LoLMastery.profile_id == profile.id)
        .order_by(LoLMastery.champion_points.desc())
        .limit(3)
    ).scalars().all()

    top_masteries = [
        MasteryDTO(
            champion_id=m.champion_id,
            champion_points=m.champion_points,
            mastery_level=m.mastery_level,
            champion_name=champ_map.get(m.champion_id, f"C{m.champion_id}"),
        )
        for m in top_masteries_rows
    ]

    return {
        "last_played": last_played,
        "games_this_week": games_this_week,
        "top_masteries": top_masteries,
    }


def _compute_lp_delta(db: Session, profile_id: int, queue_type: str) -> int:
    """LP gained since oldest rank snapshot in the last 30 entries."""
    snapshots = crud.get_lol_rank_snapshots(db, profile_id, queue_type, limit=30)
    if len(snapshots) < 2:
        return 0
    newest = snapshots[0]
    oldest = snapshots[-1]
    return (
        _absolute_lp(newest.tier, newest.rank, newest.lp)
        - _absolute_lp(oldest.tier, oldest.rank, oldest.lp)
    )


def _compute_mmr_delta(db: Session, profile_id: int, race: str) -> int:
    """MMR gained since oldest SC2 rank snapshot in the last 30 entries."""
    snapshots = crud.get_sc2_rank_snapshots(db, profile_id, race, queue_type="1v1", limit=30)
    if len(snapshots) < 2:
        return 0
    return snapshots[0].mmr - snapshots[-1].mmr


def get_lol_dashboard_data() -> List[LoLProfileDTO]:
    """Fetches all tracked LoL accounts and maps them to clean DTOs."""
    db = SessionLocal()
    champ_map = StaticDataManager().get_champion_id_to_name()
    try:
        stmt = select(Account).where(
            Account.game_type == "LOL",
            Account.is_tracked == True,
        ).options(
            selectinload(Account.lol_profile).selectinload(Account.lol_profile.property.mapper.class_.ranks)
        )
        accounts = db.execute(stmt).scalars().all()

        dtos = []
        for acc in accounts:
            prof = acc.lol_profile
            if not prof:
                continue

            extras = _compute_lol_extras(db, prof, champ_map)

            dto = LoLProfileDTO(
                account_name=acc.account_name,
                riot_tagline=prof.tag_line,
                puuid=prof.puuid,
                summoner_level=prof.summoner_level or 0,
                profile_icon_id=prof.profile_icon_id or 0,
                login_name=acc.login_name or "",
                account_id=acc.id,
                last_played=extras["last_played"],
                games_this_week=extras["games_this_week"],
                top_masteries=extras["top_masteries"],
                is_in_game=bool(prof.is_in_game),
                current_game_start=prof.current_game_start,
                current_game_queue_id=prof.current_game_queue_id,
                last_game_result=prof.last_game_result,
                last_game_queue_id=prof.last_game_queue_id,
                last_game_lp_change=prof.last_game_lp_change,
                last_game_ended_at=prof.last_game_ended_at,
            )

            for rank in prof.ranks:
                lp_delta = _compute_lp_delta(db, prof.id, rank.queue_type)
                decay = _compute_lol_decay(db, prof.id, rank.tier, rank.queue_type, rank.decay_start)
                rank_dto = RankDTO(
                    tier=rank.tier,
                    rank=rank.rank,
                    lp=rank.lp,
                    wins=rank.wins,
                    losses=rank.losses,
                    lp_delta=lp_delta,
                    decay_bank_days=decay["bank_days"],
                    decay_active=decay["active"],
                    decay_lp_per_day=decay["lp_per_day"],
                )
                if rank.queue_type == "RANKED_SOLO_5x5":
                    dto.solo_duo_rank = rank_dto
                elif rank.queue_type == "RANKED_FLEX_SR":
                    dto.flex_rank = rank_dto

            dtos.append(dto)
        return dtos
    finally:
        db.close()


def get_sc2_dashboard_data() -> List[SC2AccountDTO]:
    """Fetches all tracked SC2 accounts and maps them to clean DTOs."""
    db = SessionLocal()
    try:
        stmt = select(Account).where(
            Account.game_type == "SC2",
            Account.is_tracked == True,
        ).options(
            selectinload(Account.sc2_profiles).selectinload(Account.sc2_profiles.property.mapper.class_.ranks),
            selectinload(Account.sc2_profiles).selectinload(Account.sc2_profiles.property.mapper.class_.raw_data),
        )
        accounts = db.execute(stmt).scalars().all()

        dtos = []
        for acc in accounts:
            account_dto = SC2AccountDTO(
                account_name=acc.account_name,
                email=acc.login_name or "",
                account_folder_id=acc.folder_id or "0",
            )

            for prof in acc.sc2_profiles:
                raw_pid = prof.profile_id.split("-")[-1] if "-" in prof.profile_id else prof.profile_id

                # Count matches from raw match history
                match_count = 0
                if prof.raw_data and prof.raw_data.match_history:
                    matches = prof.raw_data.match_history.get("matches", [])
                    match_count = len(matches)

                profile_dto = SC2ProfileDTO(
                    profile_id=raw_pid,
                    region=prof.region_id,
                    realm=prof.realm_id,
                    name=prof.display_name,
                    match_count=match_count,
                    is_in_game=bool(prof.is_in_game),
                    current_opponent=prof.current_opponent,
                    current_game_start=prof.current_game_start,
                    last_game_result=prof.last_game_result,
                    last_game_opponent=prof.last_game_opponent,
                    last_game_ended_at=prof.last_game_ended_at,
                    last_game_mmr_change=prof.last_game_mmr_change,
                    last_game_mmr_race=prof.last_game_mmr_race,
                    last_game_gm_rank_change=prof.last_game_gm_rank_change,
                )

                for rank in prof.ranks:
                    if rank.league and rank.league != "Unranked":
                        mmr_delta = _compute_mmr_delta(db, prof.id, rank.race)
                        gm_info = _compute_sc2_gm_info(db, prof.id, rank, prof.region_id)
                        profile_dto.ranks[rank.race] = SC2RankDTO(
                            league=rank.league,
                            mmr=rank.mmr,
                            mmr_delta=mmr_delta,
                            is_grandmaster=bool(rank.is_grandmaster),
                            gm_demotion_days=gm_info.get("gm_demotion_days"),
                            gm_games_to_safety=gm_info.get("gm_games_to_safety"),
                            gm_mmr_threshold=gm_info.get("gm_mmr_threshold"),
                            mmr_above_gm=gm_info.get("mmr_above_gm"),
                            gm_rank=gm_info.get("gm_rank"),
                            gm_projected_rank=gm_info.get("gm_projected_rank"),
                            gm_games_played_3weeks=gm_info.get("gm_games_played_3weeks"),
                        )

                if prof.raw_data:
                    profile_dto.history = prof.raw_data.match_history or {}
                    profile_dto.summary = prof.raw_data.profile_summary or {}
                    profile_dto.ladders = prof.raw_data.ladder_summary or {}

                account_dto.profiles.append(profile_dto)

            dtos.append(account_dto)
        return dtos
    finally:
        db.close()


# --- Account Management ---

def add_lol_account(login_name: str, game_name: str, tag_line: str) -> Tuple[bool, str]:
    """Verify a LoL Riot ID via API and create the account.

    Returns (success, error_message).
    """
    from src.lol.api_client import RiotClient

    client = RiotClient(
        primary_key=os.getenv("RIOT_API_KEY_PRIMARY"),
        fallback_key=os.getenv("RIOT_API_KEY_FALLBACK"),
    )

    tag_upper = tag_line.upper()
    if tag_upper in ("EUW", "EUW1", "EUNE"):
        region = "europe"
    elif tag_upper in ("NA", "NA1"):
        region = "americas"
    elif tag_upper in ("KR", "KR1"):
        region = "asia"
    else:
        region = "europe"

    account_data = client.get_puuid_by_riot_id(region, game_name, tag_line)
    if not account_data or "puuid" not in account_data:
        return False, "API Error: Could not resolve Riot ID."

    dummy_puuid = f"PENDING_{game_name}_{tag_line}"

    db = SessionLocal()
    try:
        account = crud.create_account(db, game_type="LOL", account_name=game_name, login_name=login_name)
        crud.upsert_lol_profile(db, account_id=account.id, puuid=dummy_puuid, game_name=game_name, tag_line=tag_line)
        db.commit()
        return True, ""
    except Exception as e:
        db.rollback()
        return False, f"Database Error: {e}"
    finally:
        db.close()


def add_sc2_account(folder_id: str, email: str) -> Tuple[bool, str]:
    """Scan a local SC2 account folder and create the account with profiles.

    Returns (success, error_message).
    """
    base_dir = os.path.expanduser(f"~/Documents/StarCraft II/Accounts/{folder_id}")
    profiles_found = []

    for root, dirs, files in os.walk(base_dir):
        match = re.search(r"(\d)-S2-(\d)-(\d+)", root)
        if match:
            reg_id, realm_id, prof_id = int(match.group(1)), int(match.group(2)), int(match.group(3))
            composite_id = f"{reg_id}-{realm_id}-{prof_id}"
            if not any(p["composite_id"] == composite_id for p in profiles_found):
                profiles_found.append({
                    "composite_id": composite_id,
                    "region": reg_id,
                    "realm": realm_id,
                    "profile_id": prof_id,
                })

    if not profiles_found:
        return False, "No valid profiles found in that folder."

    db = SessionLocal()
    try:
        account = crud.create_account(db, game_type="SC2", account_name=email, login_name=email, folder_id=folder_id)
        for p in profiles_found:
            crud.upsert_sc2_profile(
                db,
                account_id=account.id,
                profile_id=p["composite_id"],
                region_id=p["region"],
                realm_id=p["realm"],
                display_name=email,
            )
        db.commit()
        return True, ""
    except Exception as e:
        db.rollback()
        return False, f"Database Error: {e}"
    finally:
        db.close()


def delete_account(account_id: int) -> None:
    """Delete an account and all associated data."""
    db = SessionLocal()
    try:
        crud.delete_account(db, account_id)
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def get_gm_threshold_for_region(region_id: int) -> Optional[int]:
    """Return the GM MMR threshold for a region, or None if not populated."""
    db = SessionLocal()
    try:
        return crud.get_sc2_gm_threshold(db, region_id)
    finally:
        db.close()


def get_sc2_season_info(region_id: int) -> Optional[dict]:
    """Return season metadata for a region: {season_id, season_start, season_end}."""
    db = SessionLocal()
    try:
        return crud.get_sc2_season_info(db, region_id)
    finally:
        db.close()
