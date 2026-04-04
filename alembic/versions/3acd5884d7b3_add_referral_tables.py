"""add_referral_tables

Adds referrals and referral_rewards tables.
Also migrates other schema changes detected during autogenerate
(alliance_join_requests, alliances.treasury_bio/privacy,
market_listings.item_id/mutation_id, TransactionReason.REFERRAL_REWARD).

Merges two parallel branches:
  - a1b2c3d4e5f6 (add_status_to_users)
  - c7e4f8b2a910 (bioexchange_new_listing_types)

Revision ID: 3acd5884d7b3
Revises: a1b2c3d4e5f6, c7e4f8b2a910
Create Date: 2026-04-04 21:32:34.416692

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

# revision identifiers, used by Alembic.
revision: str = '3acd5884d7b3'
down_revision: Union[str, tuple[str, ...], None] = ('a1b2c3d4e5f6', 'c7e4f8b2a910')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _table_exists(conn, name: str) -> bool:
    return inspect(conn).has_table(name)


def upgrade() -> None:
    conn = op.get_bind()

    # --- referral_rewards table ---
    if not _table_exists(conn, 'referral_rewards'):
        op.create_table(
            'referral_rewards',
            sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
            sa.Column('user_id', sa.BigInteger(), nullable=False),
            sa.Column('level', sa.Integer(), nullable=False),
            sa.Column('claimed_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
            sa.ForeignKeyConstraint(['user_id'], ['users.tg_id'], ondelete='CASCADE'),
            sa.PrimaryKeyConstraint('id'),
        )
        op.create_index(op.f('ix_referral_rewards_user_id'), 'referral_rewards', ['user_id'], unique=False)

    # --- referrals table ---
    if not _table_exists(conn, 'referrals'):
        op.create_table(
            'referrals',
            sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
            sa.Column('referrer_id', sa.BigInteger(), nullable=False),
            sa.Column('referred_id', sa.BigInteger(), nullable=False),
            sa.Column('created_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
            sa.Column('is_qualified', sa.Boolean(), nullable=False),
            sa.Column('last_active', sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(['referred_id'], ['users.tg_id'], ondelete='CASCADE'),
            sa.ForeignKeyConstraint(['referrer_id'], ['users.tg_id'], ondelete='CASCADE'),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('referred_id'),
        )
        op.create_index(op.f('ix_referrals_referrer_id'), 'referrals', ['referrer_id'], unique=False)

    # --- alliance_join_requests (other agent's work, guard against double-creation) ---
    if not _table_exists(conn, 'alliance_join_requests'):
        op.create_table(
            'alliance_join_requests',
            sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
            sa.Column('alliance_id', sa.Integer(), nullable=False),
            sa.Column('user_id', sa.BigInteger(), nullable=False),
            sa.Column('created_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
            sa.Column('status', sa.String(length=20), server_default='PENDING', nullable=False),
            sa.ForeignKeyConstraint(['alliance_id'], ['alliances.id'], ondelete='CASCADE'),
            sa.ForeignKeyConstraint(['user_id'], ['users.tg_id'], ondelete='CASCADE'),
            sa.PrimaryKeyConstraint('id'),
        )
        op.create_index(op.f('ix_alliance_join_requests_alliance_id'), 'alliance_join_requests', ['alliance_id'], unique=False)
        op.create_index(op.f('ix_alliance_join_requests_user_id'), 'alliance_join_requests', ['user_id'], unique=False)

    # --- alliances extra columns (guard with try/except for SQLite) ---
    alliance_cols = {col['name'] for col in inspect(conn).get_columns('alliances')}
    with op.batch_alter_table('alliances') as batch_op:
        if 'treasury_bio' not in alliance_cols:
            batch_op.add_column(sa.Column('treasury_bio', sa.Integer(), server_default='0', nullable=False))
        if 'privacy' not in alliance_cols:
            batch_op.add_column(sa.Column('privacy', sa.String(length=10), server_default='REQUEST', nullable=False))

    # --- market_listings extra columns ---
    listing_cols = {col['name'] for col in inspect(conn).get_columns('market_listings')}
    with op.batch_alter_table('market_listings') as batch_op:
        if 'item_id' not in listing_cols:
            batch_op.add_column(sa.Column('item_id', sa.Integer(), nullable=True))
        if 'mutation_id' not in listing_cols:
            batch_op.add_column(sa.Column('mutation_id', sa.Integer(), nullable=True))

    # NOTE: SQLite stores enums as plain VARCHAR — no DDL change needed for
    # TransactionReason.REFERRAL_REWARD or ListingType enum additions.


def downgrade() -> None:
    # Drop referral tables only; other schema changes belong to other migrations.
    op.drop_index(op.f('ix_referrals_referrer_id'), table_name='referrals')
    op.drop_table('referrals')
    op.drop_index(op.f('ix_referral_rewards_user_id'), table_name='referral_rewards')
    op.drop_table('referral_rewards')
