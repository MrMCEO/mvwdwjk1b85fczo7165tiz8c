"""add known_chats table

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-04-10 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e5f6a7b8c9d0'
down_revision: Union[str, None] = 'd4e5f6a7b8c9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'known_chats',
        sa.Column('chat_id', sa.BigInteger(), nullable=False),
        sa.Column('chat_type', sa.String(20), nullable=False),
        sa.Column('title', sa.String(255), nullable=False, server_default=''),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('first_seen', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('last_seen', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint('chat_id'),
    )
    op.create_index('ix_known_chats_chat_type', 'known_chats', ['chat_type'])


def downgrade() -> None:
    op.drop_index('ix_known_chats_chat_type', table_name='known_chats')
    op.drop_table('known_chats')
