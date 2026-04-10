"""add bot_logs table

Revision ID: c3d4e5f6a7b8
Revises: a2b3c4d5e6f7
Create Date: 2026-04-10 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'c3d4e5f6a7b8'
down_revision: Union[str, None] = 'a2b3c4d5e6f7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'bot_logs',
        sa.Column('id', sa.BigInteger(), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column('level', sa.String(10), nullable=False, server_default='INFO'),
        sa.Column('event_type', sa.String(50), nullable=False),
        sa.Column('user_id', sa.BigInteger(), nullable=True),
        sa.Column('message', sa.Text(), nullable=False, server_default=''),
        sa.Column('extra', postgresql.JSONB(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_bot_logs_created_at', 'bot_logs', ['created_at'])
    op.create_index('ix_bot_logs_event_type', 'bot_logs', ['event_type'])
    op.create_index('ix_bot_logs_user_id', 'bot_logs', ['user_id'])


def downgrade() -> None:
    op.drop_index('ix_bot_logs_user_id', table_name='bot_logs')
    op.drop_index('ix_bot_logs_event_type', table_name='bot_logs')
    op.drop_index('ix_bot_logs_created_at', table_name='bot_logs')
    op.drop_table('bot_logs')
