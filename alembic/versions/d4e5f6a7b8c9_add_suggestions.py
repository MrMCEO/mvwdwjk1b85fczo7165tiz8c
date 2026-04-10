"""add suggestions tables

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-04-10 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd4e5f6a7b8c9'
down_revision: Union[str, None] = 'c3d4e5f6a7b8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'suggestions',
        sa.Column('id', sa.BigInteger(), nullable=False, autoincrement=True),
        sa.Column('user_id', sa.BigInteger(), nullable=False),
        sa.Column('username', sa.String(64), nullable=False, server_default=''),
        sa.Column('text', sa.Text(), nullable=False),
        sa.Column(
            'status',
            sa.Enum('pending', 'approved', 'rejected', name='suggestionstatus'),
            nullable=False,
            server_default='pending',
        ),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column('moderated_at', sa.DateTime(), nullable=True),
        sa.Column('moderated_by', sa.BigInteger(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_suggestions_user_id', 'suggestions', ['user_id'])
    op.create_index('ix_suggestions_created_at', 'suggestions', ['created_at'])
    op.create_index('ix_suggestions_status', 'suggestions', ['status'])

    op.create_table(
        'suggest_blocks',
        sa.Column('user_id', sa.BigInteger(), nullable=False),
        sa.Column('blocked_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column('blocked_by', sa.BigInteger(), nullable=False),
        sa.PrimaryKeyConstraint('user_id'),
    )


def downgrade() -> None:
    op.drop_table('suggest_blocks')
    op.drop_index('ix_suggestions_status', table_name='suggestions')
    op.drop_index('ix_suggestions_created_at', table_name='suggestions')
    op.drop_index('ix_suggestions_user_id', table_name='suggestions')
    op.drop_table('suggestions')
    op.execute("DROP TYPE IF EXISTS suggestionstatus")
