from typing import List
from src.data.database import SessionLocal
from src.data.models import Account
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from src.schemas import (
    LoLProfileDTO, RankDTO, 
    SC2AccountDTO, SC2ProfileDTO, SC2RankDTO
)

def get_lol_dashboard_data() -> List[LoLProfileDTO]:
    """Fetches all tracked LoL accounts and maps them to clean DTOs."""
    db = SessionLocal()
    try:
        dtos = []
        # Use selectinload to eagerly fetch the profile and ranks, avoiding N+1 and lazy-load errors
        stmt = select(Account).where(
            Account.game_type == "LOL",
            Account.is_tracked == True
        ).options(
            selectinload(Account.lol_profile).selectinload(Account.lol_profile.property.mapper.class_.ranks)
        )
        accounts = db.execute(stmt).scalars().all()
        
        for acc in accounts:
            prof = acc.lol_profile
            if not prof:
                continue
                
            dto = LoLProfileDTO(
                account_name=acc.account_name,
                riot_tagline=prof.tag_line,
                puuid=prof.puuid,
                summoner_level=prof.summoner_level or 0,
                profile_icon_id=prof.profile_icon_id or 0,
                login_name=acc.login_name or ""
            )
            
            for rank in prof.ranks:
                rank_dto = RankDTO(
                    tier=rank.tier,
                    rank=rank.rank,
                    lp=rank.lp,
                    wins=rank.wins,
                    losses=rank.losses
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
        dtos = []
        
        # Use selectinload to eagerly fetch the profiles, ranks, and raw data
        stmt = select(Account).where(
            Account.game_type == "SC2",
            Account.is_tracked == True
        ).options(
            selectinload(Account.sc2_profiles).selectinload(Account.sc2_profiles.property.mapper.class_.ranks),
            selectinload(Account.sc2_profiles).selectinload(Account.sc2_profiles.property.mapper.class_.raw_data)
        )
        accounts = db.execute(stmt).scalars().all()
        
        for acc in accounts:
            account_dto = SC2AccountDTO(
                account_name=acc.account_name,
                email=acc.login_name or "",
                account_folder_id=acc.folder_id or "0",
            )
            
            for prof in acc.sc2_profiles:
                # Extract pure profile ID from DB's global ID (Region-Realm-ID)
                raw_pid = prof.profile_id.split("-")[-1] if "-" in prof.profile_id else prof.profile_id
                
                profile_dto = SC2ProfileDTO(
                    profile_id=raw_pid,
                    region=prof.region_id,
                    realm=prof.realm_id,
                    name=prof.display_name,
                )
                
                for rank in prof.ranks:
                    if rank.league and rank.league != "Unranked":
                        profile_dto.ranks[rank.race] = SC2RankDTO(
                            league=rank.league,
                            mmr=rank.mmr
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
