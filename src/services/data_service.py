import time
from typing import List

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
