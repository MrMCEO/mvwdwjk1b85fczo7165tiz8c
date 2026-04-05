"""
Migrate data from SQLite (data/biowars.db) to PostgreSQL.

Usage:
    python scripts/migrate_sqlite_to_pg.py

Requires:
    - PostgreSQL DB already created and alembic migrations applied:
        alembic upgrade head
    - .env with DB_URL pointing to PostgreSQL
    - data/biowars.db containing the SQLite source data

Order of migration respects FK constraints:
    users
    -> viruses, immunities, infections, resource_transactions,
       mutations, items, promo_codes, alliances, events
    -> virus_upgrades (FK viruses.id)
    -> immunity_upgrades (FK immunities.id)
    -> attack_attempts, market_listings, promo_activations,
       referrals, referral_rewards, alliance_members,
       alliance_join_requests, pandemic_participants, event_participants
"""

import asyncio
import os
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

# Add project root to sys.path so bot.config is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import asyncpg  # noqa: E402

_DT_FORMATS = ["%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d"]


def _convert_value(val):
    """Convert SQLite string datetimes to Python datetime objects."""
    if isinstance(val, str):
        for fmt in _DT_FORMATS:
            try:
                return datetime.strptime(val, fmt)
            except ValueError:
                continue
    return val

SQLITE_PATH = Path(__file__).resolve().parent.parent / "data" / "biowars.db"

# Tables in FK-safe insertion order.
# Each entry: (table_name, list_of_columns_or_None_for_auto)
# None means "fetch columns from SQLite cursor description".
TABLE_ORDER = [
    "users",
    "viruses",
    "immunities",
    "infections",
    "resource_transactions",
    "mutations",
    "items",
    "promo_codes",
    "alliances",
    "events",
    "virus_upgrades",
    "immunity_upgrades",
    "attack_attempts",
    "market_listings",
    "promo_activations",
    "referrals",
    "referral_rewards",
    "alliance_members",
    "alliance_join_requests",
    "pandemic_participants",
    "event_participants",
]


def get_pg_dsn() -> str:
    """Read PostgreSQL DSN from .env or environment."""
    # Try to load .env manually to avoid importing pydantic_settings
    env_path = Path(__file__).resolve().parent.parent / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip()
            if key == "DB_URL" and value and not value.startswith("#"):
                os.environ.setdefault("DB_URL", value)

    db_url = os.environ.get("DB_URL", "")
    if not db_url.startswith("postgresql"):
        raise ValueError(
            f"DB_URL does not point to PostgreSQL: {db_url!r}\n"
            "Set DB_URL=postgresql+asyncpg://... in .env"
        )

    # Convert SQLAlchemy URL to asyncpg DSN:
    # postgresql+asyncpg://user:pass@host/db  ->  postgresql://user:pass@host/db
    return db_url.replace("postgresql+asyncpg://", "postgresql://", 1)


def fetch_table(sqlite_conn: sqlite3.Connection, table: str) -> tuple[list[str], list[tuple]]:
    """Return (columns, rows) from SQLite table."""
    cur = sqlite_conn.execute(f"SELECT * FROM {table}")  # noqa: S608
    columns = [desc[0] for desc in cur.description]
    rows = cur.fetchall()
    return columns, rows


async def _get_bool_columns(pg_conn: asyncpg.Connection, table: str) -> set[str]:
    """Return set of column names that are BOOLEAN in PostgreSQL."""
    rows = await pg_conn.fetch(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_name = $1 AND data_type = 'boolean'",
        table,
    )
    return {r["column_name"] for r in rows}


def _convert_row(row: tuple, columns: list[str], bool_cols: set[str]) -> tuple:
    """Convert SQLite values to PostgreSQL-compatible types."""
    result = []
    for col, val in zip(columns, row):
        if col in bool_cols and isinstance(val, int):
            val = bool(val)
        else:
            val = _convert_value(val)
        result.append(val)
    return tuple(result)


async def migrate_table(
    pg_conn: asyncpg.Connection,
    table: str,
    columns: list[str],
    rows: list[tuple],
) -> int:
    """Insert rows into PostgreSQL table, returning count of inserted rows."""
    if not rows:
        print(f"  {table}: 0 rows (empty), skipping")
        return 0

    bool_cols = await _get_bool_columns(pg_conn, table)
    col_list = ", ".join(f'"{c}"' for c in columns)
    placeholders = ", ".join(f"${i + 1}" for i in range(len(columns)))
    sql = f'INSERT INTO "{table}" ({col_list}) VALUES ({placeholders}) ON CONFLICT DO NOTHING'  # noqa: S608

    records = [_convert_row(row, columns, bool_cols) for row in rows]
    await pg_conn.executemany(sql, records)
    print(f"  {table}: {len(records)} rows migrated")
    return len(records)


async def reset_sequences(pg_conn: asyncpg.Connection) -> None:
    """Reset all sequences to max(id)+1 so future INSERTs don't conflict."""
    seqs = await pg_conn.fetch(
        """
        SELECT
            t.relname  AS table_name,
            a.attname  AS col_name,
            s.relname  AS seq_name
        FROM pg_class s
        JOIN pg_depend d ON d.objid = s.oid
        JOIN pg_class t ON t.oid = d.refobjid
        JOIN pg_attribute a ON a.attrelid = t.oid AND a.attnum = d.refobjsubid
        WHERE s.relkind = 'S'
        """
    )
    for row in seqs:
        tbl = row["table_name"]
        col = row["col_name"]
        seq = row["seq_name"]
        await pg_conn.execute(
            f"SELECT setval('{seq}', COALESCE((SELECT MAX(\"{col}\") FROM \"{tbl}\"), 0) + 1, false)"  # noqa: S608
        )
    print(f"\nReset {len(seqs)} sequences.")


async def main() -> None:
    if not SQLITE_PATH.exists():
        print(f"ERROR: SQLite file not found: {SQLITE_PATH}")
        sys.exit(1)

    pg_dsn = get_pg_dsn()
    print(f"Source: {SQLITE_PATH}")
    print(f"Target: {pg_dsn}\n")

    sqlite_conn = sqlite3.connect(str(SQLITE_PATH))
    sqlite_conn.row_factory = sqlite3.Row

    # Get all tables present in SQLite
    existing_tables = {
        row[0]
        for row in sqlite_conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )
    }
    print(f"Tables found in SQLite: {sorted(existing_tables)}\n")

    pg_conn = await asyncpg.connect(pg_dsn)

    try:
        total = 0
        for table in TABLE_ORDER:
            if table not in existing_tables:
                print(f"  {table}: not in SQLite, skipping")
                continue
            try:
                columns, rows = fetch_table(sqlite_conn, table)
                # Convert sqlite3.Row to plain tuples
                plain_rows = [tuple(row) for row in rows]
                count = await migrate_table(pg_conn, table, columns, plain_rows)
                total += count
            except Exception as exc:
                print(f"  {table}: ERROR — {exc}")
                raise

        # Handle any tables present in SQLite but not in our order list
        extra = existing_tables - set(TABLE_ORDER)
        for table in sorted(extra):
            print(f"  {table}: not in migration order list, skipping (add manually if needed)")

        await reset_sequences(pg_conn)
        print(f"\nDone. Total rows migrated: {total}")

    finally:
        sqlite_conn.close()
        await pg_conn.close()


if __name__ == "__main__":
    asyncio.run(main())
