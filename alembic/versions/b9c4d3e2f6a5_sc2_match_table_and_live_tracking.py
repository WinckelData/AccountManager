"""sc2_match_table_and_live_tracking

Revision ID: b9c4d3e2f6a5
Revises: a8f3c2d1e5b4
Create Date: 2026-03-15 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b9c4d3e2f6a5'
down_revision: Union[str, Sequence[str], None] = 'a8f3c2d1e5b4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # New sc2_matches table
    op.create_table(
        'sc2_matches',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('profile_id', sa.Integer(), sa.ForeignKey('sc2_profiles.id'), nullable=True),
        sa.Column('map', sa.String(), nullable=True),
        sa.Column('match_type', sa.String(), nullable=True),
        sa.Column('decision', sa.String(), nullable=True),
        sa.Column('date', sa.Integer(), nullable=True),
        sa.Column('speed', sa.String(), nullable=True),
        sa.Column('created_at', sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('profile_id', 'date', 'match_type', name='uq_sc2_match_profile_date_type'),
    )
    op.create_index('ix_sc2_matches_id', 'sc2_matches', ['id'])
    op.create_index('ix_sc2_matches_profile_id', 'sc2_matches', ['profile_id'])

    # Live tracking columns on sc2_profiles
    with op.batch_alter_table('sc2_profiles', schema=None) as batch_op:
        batch_op.add_column(sa.Column('is_in_game', sa.Boolean(), nullable=True))
        batch_op.add_column(sa.Column('current_game_map', sa.String(), nullable=True))
        batch_op.add_column(sa.Column('current_opponent', sa.String(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('sc2_profiles', schema=None) as batch_op:
        batch_op.drop_column('current_opponent')
        batch_op.drop_column('current_game_map')
        batch_op.drop_column('is_in_game')

    op.drop_index('ix_sc2_matches_profile_id', table_name='sc2_matches')
    op.drop_index('ix_sc2_matches_id', table_name='sc2_matches')
    op.drop_table('sc2_matches')
