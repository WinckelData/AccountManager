"""structured_match_data_in_game_gm_flag

Revision ID: a8f3c2d1e5b4
Revises: 4e3ba1b85a1f
Create Date: 2026-03-13 23:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a8f3c2d1e5b4'
down_revision: Union[str, Sequence[str], None] = '4e3ba1b85a1f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 3A: Structured match stats on lol_match_participants
    with op.batch_alter_table('lol_match_participants', schema=None) as batch_op:
        batch_op.add_column(sa.Column('champion_id', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('kills', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('deaths', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('assists', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('win', sa.Boolean(), nullable=True))
        batch_op.add_column(sa.Column('role', sa.String(), nullable=True))
        batch_op.add_column(sa.Column('lane', sa.String(), nullable=True))
        batch_op.add_column(sa.Column('gold_earned', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('total_damage_dealt', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('cs', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('vision_score', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('items', sa.JSON(), nullable=True))

    # 3B: In-game status on lol_profiles
    with op.batch_alter_table('lol_profiles', schema=None) as batch_op:
        batch_op.add_column(sa.Column('is_in_game', sa.Boolean(), nullable=True))
        batch_op.add_column(sa.Column('current_game_start', sa.Integer(), nullable=True))

    # 3C: Grandmaster flag on sc2_ranks
    with op.batch_alter_table('sc2_ranks', schema=None) as batch_op:
        batch_op.add_column(sa.Column('is_grandmaster', sa.Boolean(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('sc2_ranks', schema=None) as batch_op:
        batch_op.drop_column('is_grandmaster')

    with op.batch_alter_table('lol_profiles', schema=None) as batch_op:
        batch_op.drop_column('current_game_start')
        batch_op.drop_column('is_in_game')

    with op.batch_alter_table('lol_match_participants', schema=None) as batch_op:
        batch_op.drop_column('items')
        batch_op.drop_column('vision_score')
        batch_op.drop_column('cs')
        batch_op.drop_column('total_damage_dealt')
        batch_op.drop_column('gold_earned')
        batch_op.drop_column('lane')
        batch_op.drop_column('role')
        batch_op.drop_column('win')
        batch_op.drop_column('assists')
        batch_op.drop_column('deaths')
        batch_op.drop_column('kills')
        batch_op.drop_column('champion_id')
