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

def calculate_decay_bank(puuid, match_history, queue_type):
    """
    Computes the decayed-bank balance for a Diamond+ account.

    Rules (simulated over the last 30 days):
      - Bank starts at 10 days.
      - Each ranked game played adds 1 banked day (cap 14).
      - Each calendar day with no ranked game subtracts 1 banked day (floor 0).

    Returns the estimated banked days remaining (int).
    """
    if not match_history:
        return 0

    valid_match_times = []
    for m in match_history:
        info = m.get("info", {})
        if info.get("queueId") == queue_type:
            valid_match_times.append(info.get("gameCreation", 0) / 1000)

    valid_match_times.sort()

    now = time.time()
    thirty_days_ago = now - (30 * 24 * 3600)
    recent = [t for t in valid_match_times if t > thirty_days_ago]

    bank = 10
    MAX_BANK = 14

    for day_offset in range(30):
        day_start = thirty_days_ago + (day_offset * 86400)
        day_end = day_start + 86400
        games_today = sum(1 for t in recent if day_start <= t < day_end)

        if games_today > 0:
            bank = min(MAX_BANK, bank + games_today)
        else:
            bank = max(0, bank - 1)

    return bank


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
            )

            for rank in prof.ranks:
                lp_delta = _compute_lp_delta(db, prof.id, rank.queue_type)
                rank_dto = RankDTO(
                    tier=rank.tier,
                    rank=rank.rank,
                    lp=rank.lp,
                    wins=rank.wins,
                    losses=rank.losses,
                    lp_delta=lp_delta,
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
                )

                for rank in prof.ranks:
                    if rank.league and rank.league != "Unranked":
                        mmr_delta = _compute_mmr_delta(db, prof.id, rank.race)
                        profile_dto.ranks[rank.race] = SC2RankDTO(
                            league=rank.league,
                            mmr=rank.mmr,
                            mmr_delta=mmr_delta,
                            is_grandmaster=bool(rank.is_grandmaster),
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
