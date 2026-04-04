import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from bot.models.base import Base

# Import all models so their tables are registered on Base.metadata
import bot.models  # noqa: F401


TEST_DB_URL = "sqlite+aiosqlite://"  # in-memory SQLite


@pytest_asyncio.fixture(scope="session")
async def engine():
    """Create an in-memory async engine for the test session."""
    _engine = create_async_engine(TEST_DB_URL, echo=False, future=True)
    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield _engine
    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await _engine.dispose()


@pytest_asyncio.fixture
async def session(engine):
    """Provide a transactional async session that is rolled back after each test."""
    _factory = async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
        autocommit=False,
    )
    async with _factory() as _session:
        yield _session
        await _session.rollback()
