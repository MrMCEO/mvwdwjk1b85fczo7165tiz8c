"""
Alliance service — business logic for the clan/guild system.

All functions return (success: bool, message: str) tuples so handlers
can display feedback without containing any business logic.
"""

from __future__ import annotations

import math
import re
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from bot.models.alliance import (
    PRIVACY_LABELS,
    ROLE_LABELS,
    Alliance,
    AllianceJoinRequest,
    AllianceMember,
    AlliancePrivacy,
    AllianceRole,
    JoinRequestStatus,
)
from bot.models.immunity import Immunity
from bot.models.resource import Currency, ResourceTransaction, TransactionReason
from bot.models.user import User
from bot.models.virus import Virus
from bot.utils.chat import dlvl

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ALLIANCE_CREATE_COST = 500  # bio_coins
MAX_MEMBERS_DEFAULT = 20

# Tag: 2-5 chars, latin/cyrillic letters and digits
_TAG_RE = re.compile(r"^[A-Za-zА-Яа-яЁё0-9]{2,5}$")
# Name: 3-32 chars (allow spaces and common punctuation)
_NAME_RE = re.compile(r"^[A-Za-zА-Яа-яЁё0-9 _\-]{3,32}$")

# ---------------------------------------------------------------------------
# Alliance upgrade configuration
# ---------------------------------------------------------------------------

ALLIANCE_UPGRADE_CONFIG: dict[str, dict] = {
    "shield": {
        "field": "shield_level",
        "max_level": 10,
        "base_cost": 100,        # 🔷
        "multiplier": 1.3,
        "effect_per_level": 0.03,  # +3% защиты
        "emoji": "🛡",
        "name": "Клановый щит",
        "desc": "+3% защиты всем участникам",
    },
    "morale": {
        "field": "morale_level",
        "max_level": 10,
        "base_cost": 150,
        "multiplier": 1.3,
        "effect_per_level": 0.03,  # +3% атаки
        "emoji": "⚔️",
        "name": "Боевой дух",
        "desc": "+3% атаки всем участникам",
    },
    "capacity": {
        "field": "capacity_level",
        "max_level": 10,
        "base_cost": 200,
        "multiplier": 1.5,
        "effect_per_level": 5,   # +5 слотов
        "emoji": "👥",
        "name": "Расширение",
        "desc": "+5 слотов для участников",
    },
    "mining": {
        "field": "mining_level",
        "max_level": 8,
        "base_cost": 150,
        "multiplier": 1.3,
        "effect_per_level": 0.05,  # +5% добычи
        "emoji": "🧫",
        "name": "Клановая добыча",
        "desc": "+5% к добыче всем участникам",
    },
    "regen": {
        "field": "regen_level",
        "max_level": 8,
        "base_cost": 120,
        "multiplier": 1.3,
        "effect_per_level": 0.01,  # +1% автолечения
        "emoji": "💊",
        "name": "Клановая регенерация",
        "desc": "+1% авто-лечения всем участникам",
    },
}

ALLIANCE_COIN_RATE = 1  # 1 💎 = 1 🔷

# Treasury: bio_coins → alliance_coins conversion
BIO_TO_ALLIANCE_RATE = 100  # 100 🧫 = 1 🔷
TREASURY_MIN_DONATION = 100  # минимальный взнос


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _now_utc() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _upgrade_cost(cfg: dict, current_level: int) -> int:
    """Calculate cost to upgrade from current_level to current_level+1."""
    return math.ceil(cfg["base_cost"] * (cfg["multiplier"] ** current_level))


async def _get_member(
    session: AsyncSession, user_id: int
) -> AllianceMember | None:
    result = await session.execute(
        select(AllianceMember).where(AllianceMember.user_id == user_id)
    )
    return result.scalar_one_or_none()


async def _get_alliance_by_id(
    session: AsyncSession, alliance_id: int
) -> Alliance | None:
    result = await session.execute(
        select(Alliance)
        .where(Alliance.id == alliance_id)
        .options(selectinload(Alliance.members).selectinload(AllianceMember.user))
    )
    return result.scalar_one_or_none()


async def _get_alliance_for_user(
    session: AsyncSession, user_id: int
) -> tuple[Alliance | None, AllianceMember | None]:
    """Return (alliance, member) pair for a user, or (None, None) if not in one."""
    member = await _get_member(session, user_id)
    if member is None:
        return None, None
    alliance = await _get_alliance_by_id(session, member.alliance_id)
    return alliance, member


# ---------------------------------------------------------------------------
# Public API — core CRUD
# ---------------------------------------------------------------------------


async def create_alliance(
    session: AsyncSession, leader_id: int, name: str, tag: str
) -> tuple[bool, str]:
    """
    Create a new alliance.

    Checks:
    - name: 3-32 chars (letters/digits/space/_/-)
    - tag: 2-5 chars (letters/digits, no spaces)
    - name and tag uniqueness (case-insensitive)
    - leader is not already in an alliance
    - leader has enough bio_coins (500)

    Returns (True, success_msg) or (False, error_msg).
    """
    name = name.strip()
    tag = tag.strip().upper()

    if not _NAME_RE.match(name):
        return False, (
            "❌ Некорректное название альянса.\n"
            "Допустимы буквы (рус/лат), цифры, пробел, _ и -.\n"
            "Длина: 3–32 символа."
        )

    if not _TAG_RE.match(tag):
        return False, (
            "❌ Некорректный тег альянса.\n"
            "Допустимы буквы (рус/лат) и цифры без пробелов.\n"
            "Длина: 2–5 символов."
        )

    # Check user is not already in an alliance
    existing_member = await _get_member(session, leader_id)
    if existing_member is not None:
        return False, "❌ Ты уже состоишь в альянсе. Сначала покинь его."

    # Check name uniqueness (case-insensitive)
    name_result = await session.execute(
        select(Alliance).where(func.lower(Alliance.name) == name.lower())
    )
    if name_result.scalar_one_or_none() is not None:
        return False, f"❌ Альянс с названием «{name}» уже существует."

    # Check tag uniqueness (case-insensitive, stored uppercase)
    tag_result = await session.execute(
        select(Alliance).where(func.upper(Alliance.tag) == tag.upper())
    )
    if tag_result.scalar_one_or_none() is not None:
        return False, f"❌ Тег [{tag}] уже занят другим альянсом."

    # Check and deduct bio_coins
    user_result = await session.execute(
        select(User).where(User.tg_id == leader_id).with_for_update()
    )
    user = user_result.scalar_one_or_none()
    if user is None:
        return False, "❌ Пользователь не найден."

    if user.bio_coins < ALLIANCE_CREATE_COST:
        return False, (
            f"❌ Недостаточно 🧫 BioCoins для создания альянса.\n"
            f"Требуется: {ALLIANCE_CREATE_COST} 🧫 BioCoins\n"
            f"У тебя: {user.bio_coins} 🧫 BioCoins"
        )

    user.bio_coins -= ALLIANCE_CREATE_COST

    # Create alliance
    alliance = Alliance(
        name=name,
        tag=tag,
        leader_id=leader_id,
        description="",
        max_members=MAX_MEMBERS_DEFAULT,
        defense_bonus=0.0,
    )
    session.add(alliance)
    await session.flush()  # get alliance.id

    # Create leader membership
    leader_member = AllianceMember(
        alliance_id=alliance.id,
        user_id=leader_id,
        role=AllianceRole.LEADER,
    )
    session.add(leader_member)
    await session.flush()

    return True, (
        f"✅ Альянс <b>[{tag}] {name}</b> успешно создан!\n"
        f"Потрачено: {ALLIANCE_CREATE_COST} 🧫 BioCoins\n\n"
        "Ты становишься лидером альянса 👑"
    )


async def dissolve_alliance(
    session: AsyncSession, user_id: int
) -> tuple[bool, str]:
    """Dissolve the alliance. Only the LEADER can do this."""
    alliance, member = await _get_alliance_for_user(session, user_id)
    if alliance is None:
        return False, "❌ Ты не состоишь ни в одном альянсе."

    if member.role != AllianceRole.LEADER:
        return False, "❌ Только лидер может распустить альянс."

    name = alliance.name
    tag = alliance.tag

    # cascade="all, delete-orphan" will remove all AllianceMember rows
    await session.delete(alliance)
    await session.flush()

    return True, f"✅ Альянс <b>[{tag}] {name}</b> распущен."


async def invite_player(
    session: AsyncSession, inviter_id: int, target_username: str
) -> tuple[bool, str]:
    """
    Invite a player to the alliance by username.

    Inviter must be LEADER or OFFICER.
    Target must exist and not already be in an alliance.
    Alliance must not be full (uses get_alliance_max_members).
    """
    alliance, inviter_member = await _get_alliance_for_user(session, inviter_id)
    if alliance is None:
        return False, "❌ Ты не состоишь ни в одном альянсе."

    if inviter_member.role not in (AllianceRole.LEADER, AllianceRole.OFFICER):
        return False, "❌ Только лидер или офицер могут приглашать игроков."

    # Load fresh member count
    member_count_result = await session.execute(
        select(func.count(AllianceMember.id)).where(
            AllianceMember.alliance_id == alliance.id
        )
    )
    member_count: int = member_count_result.scalar_one()
    max_members = MAX_MEMBERS_DEFAULT + alliance.capacity_level * int(
        ALLIANCE_UPGRADE_CONFIG["capacity"]["effect_per_level"]
    )

    if member_count >= max_members:
        return False, (
            f"❌ Альянс заполнен ({member_count}/{max_members} участников)."
        )

    # Find target user
    raw = target_username.strip().lstrip("@")
    target_result = await session.execute(
        select(User).where(func.lower(User.username) == raw.lower())
    )
    target: User | None = target_result.scalar_one_or_none()
    if target is None:
        return False, f"❌ Игрок <b>@{raw}</b> не найден в игре."

    if target.tg_id == inviter_id:
        return False, "❌ Нельзя пригласить самого себя."

    # Check target is not in an alliance already
    existing = await _get_member(session, target.tg_id)
    if existing is not None:
        return False, f"❌ Игрок @{raw} уже состоит в другом альянсе."

    new_member = AllianceMember(
        alliance_id=alliance.id,
        user_id=target.tg_id,
        role=AllianceRole.MEMBER,
    )
    session.add(new_member)
    await session.flush()

    display = f"@{target.username}" if target.username else f"id{target.tg_id}"
    return True, (
        f"✅ Игрок <b>{display}</b> добавлен в альянс <b>[{alliance.tag}] {alliance.name}</b>."
    )


async def kick_member(
    session: AsyncSession, kicker_id: int, target_id: int
) -> tuple[bool, str]:
    """
    Kick a member from the alliance.

    - LEADER can kick anyone (except themselves).
    - OFFICER can only kick MEMBER-role players.
    - Cannot kick yourself.
    """
    if kicker_id == target_id:
        return False, "❌ Нельзя исключить самого себя. Используй «Покинуть альянс»."

    alliance, kicker_member = await _get_alliance_for_user(session, kicker_id)
    if alliance is None:
        return False, "❌ Ты не состоишь ни в одном альянсе."

    if kicker_member.role not in (AllianceRole.LEADER, AllianceRole.OFFICER):
        return False, "❌ Только лидер или офицер могут исключать участников."

    # Find target member
    target_member_result = await session.execute(
        select(AllianceMember).where(
            AllianceMember.user_id == target_id,
            AllianceMember.alliance_id == alliance.id,
        )
    )
    target_member: AllianceMember | None = target_member_result.scalar_one_or_none()
    if target_member is None:
        return False, "❌ Этот игрок не является участником твоего альянса."

    if kicker_member.role == AllianceRole.OFFICER and target_member.role != AllianceRole.MEMBER:
        return False, "❌ Офицер может исключать только рядовых участников."

    if target_member.role == AllianceRole.LEADER:
        return False, "❌ Нельзя исключить лидера альянса."

    # Fetch username for response
    target_user_result = await session.execute(
        select(User).where(User.tg_id == target_id)
    )
    target_user = target_user_result.scalar_one_or_none()
    display = f"@{target_user.username}" if target_user and target_user.username else f"id{target_id}"

    await session.delete(target_member)
    await session.flush()

    return True, f"✅ Игрок <b>{display}</b> исключён из альянса."


async def leave_alliance(
    session: AsyncSession, user_id: int
) -> tuple[bool, str]:
    """
    Leave the alliance.

    If the leaving player is the LEADER, the alliance is dissolved entirely.
    """
    alliance, member = await _get_alliance_for_user(session, user_id)
    if alliance is None:
        return False, "❌ Ты не состоишь ни в одном альянсе."

    if member.role == AllianceRole.LEADER:
        name = alliance.name
        tag = alliance.tag
        await session.delete(alliance)
        await session.flush()
        return True, (
            f"✅ Ты покинул альянс <b>[{tag}] {name}</b>.\n"
            "Поскольку ты был лидером, альянс распущен."
        )

    alliance_name = alliance.name
    alliance_tag = alliance.tag
    await session.delete(member)
    await session.flush()

    return True, f"✅ Ты покинул альянс <b>[{alliance_tag}] {alliance_name}</b>."


async def promote_member(
    session: AsyncSession, leader_id: int, target_id: int
) -> tuple[bool, str]:
    """Promote a MEMBER to OFFICER. Only the LEADER can do this."""
    if leader_id == target_id:
        return False, "❌ Нельзя изменить роль самому себе."

    alliance, leader_member = await _get_alliance_for_user(session, leader_id)
    if alliance is None:
        return False, "❌ Ты не состоишь ни в одном альянсе."

    if leader_member.role != AllianceRole.LEADER:
        return False, "❌ Только лидер может повышать участников."

    target_member_result = await session.execute(
        select(AllianceMember).where(
            AllianceMember.user_id == target_id,
            AllianceMember.alliance_id == alliance.id,
        )
    )
    target_member: AllianceMember | None = target_member_result.scalar_one_or_none()
    if target_member is None:
        return False, "❌ Этот игрок не является участником твоего альянса."

    if target_member.role == AllianceRole.OFFICER:
        return False, "❌ Игрок уже является офицером."

    if target_member.role == AllianceRole.LEADER:
        return False, "❌ Нельзя повысить лидера."

    target_user_result = await session.execute(
        select(User).where(User.tg_id == target_id)
    )
    target_user = target_user_result.scalar_one_or_none()
    display = f"@{target_user.username}" if target_user and target_user.username else f"id{target_id}"

    target_member.role = AllianceRole.OFFICER
    await session.flush()

    return True, f"✅ Игрок <b>{display}</b> повышен до ⚔️ Офицера."


async def demote_member(
    session: AsyncSession, leader_id: int, target_id: int
) -> tuple[bool, str]:
    """Demote an OFFICER to MEMBER. Only the LEADER can do this."""
    if leader_id == target_id:
        return False, "❌ Нельзя изменить роль самому себе."

    alliance, leader_member = await _get_alliance_for_user(session, leader_id)
    if alliance is None:
        return False, "❌ Ты не состоишь ни в одном альянсе."

    if leader_member.role != AllianceRole.LEADER:
        return False, "❌ Только лидер может понижать участников."

    target_member_result = await session.execute(
        select(AllianceMember).where(
            AllianceMember.user_id == target_id,
            AllianceMember.alliance_id == alliance.id,
        )
    )
    target_member: AllianceMember | None = target_member_result.scalar_one_or_none()
    if target_member is None:
        return False, "❌ Этот игрок не является участником твоего альянса."

    if target_member.role == AllianceRole.MEMBER:
        return False, "❌ Игрок уже является рядовым участником."

    if target_member.role == AllianceRole.LEADER:
        return False, "❌ Нельзя понизить лидера."

    target_user_result = await session.execute(
        select(User).where(User.tg_id == target_id)
    )
    target_user = target_user_result.scalar_one_or_none()
    display = f"@{target_user.username}" if target_user and target_user.username else f"id{target_id}"

    target_member.role = AllianceRole.MEMBER
    await session.flush()

    return True, f"✅ Игрок <b>{display}</b> понижен до 👤 Участника."


# ---------------------------------------------------------------------------
# Public API — info getters
# ---------------------------------------------------------------------------


async def get_alliance_info(session: AsyncSession, user_id: int) -> dict | None:
    """
    Return info about the alliance the user belongs to.

    Returns None if the user is not in any alliance.
    Returns a dict with keys:
        id, name, tag, description, leader_id, leader_username,
        member_count, max_members, defense_bonus, created_at,
        user_role (AllianceRole), alliance_coins
    """
    alliance, member = await _get_alliance_for_user(session, user_id)
    if alliance is None:
        return None

    # Load leader username
    leader_result = await session.execute(
        select(User).where(User.tg_id == alliance.leader_id)
    )
    leader = leader_result.scalar_one_or_none()
    leader_display = f"@{leader.username}" if leader and leader.username else f"id{alliance.leader_id}"

    member_count_result = await session.execute(
        select(func.count(AllianceMember.id)).where(
            AllianceMember.alliance_id == alliance.id
        )
    )
    member_count: int = member_count_result.scalar_one()

    max_members = MAX_MEMBERS_DEFAULT + alliance.capacity_level * int(
        ALLIANCE_UPGRADE_CONFIG["capacity"]["effect_per_level"]
    )
    defense_bonus = alliance.shield_level * ALLIANCE_UPGRADE_CONFIG["shield"]["effect_per_level"]

    privacy_val = alliance.privacy if isinstance(alliance.privacy, str) else alliance.privacy.value
    try:
        privacy_enum = AlliancePrivacy(privacy_val)
    except ValueError:
        privacy_enum = AlliancePrivacy.REQUEST

    return {
        "id": alliance.id,
        "name": alliance.name,
        "tag": alliance.tag,
        "description": alliance.description,
        "leader_id": alliance.leader_id,
        "leader_username": leader_display,
        "member_count": member_count,
        "max_members": max_members,
        "defense_bonus": defense_bonus,
        "created_at": alliance.created_at,
        "user_role": member.role,
        "alliance_coins": alliance.alliance_coins,
        "treasury_bio": alliance.treasury_bio,
        "privacy": privacy_enum,
    }


async def get_alliance_members(
    session: AsyncSession, alliance_id: int
) -> list[dict]:
    """
    Return a list of members for the given alliance.

    Each dict has: user_id, username, role (AllianceRole), joined_at,
    virus_level, immunity_level.
    Sorted by role priority (LEADER first, then OFFICER, then MEMBER),
    then by joined_at ascending.
    """
    result = await session.execute(
        select(AllianceMember, User)
        .join(User, AllianceMember.user_id == User.tg_id)
        .where(AllianceMember.alliance_id == alliance_id)
        .order_by(AllianceMember.joined_at)
    )
    rows = result.all()

    # Fetch virus and immunity levels in bulk
    user_ids = [user.tg_id for _, user in rows]

    virus_result = await session.execute(
        select(Virus.owner_id, Virus.level).where(Virus.owner_id.in_(user_ids))
    )
    virus_levels: dict[int, int] = dict(virus_result.all())

    immunity_result = await session.execute(
        select(Immunity.owner_id, Immunity.level).where(Immunity.owner_id.in_(user_ids))
    )
    immunity_levels: dict[int, int] = dict(immunity_result.all())

    role_order = {AllianceRole.LEADER: 0, AllianceRole.OFFICER: 1, AllianceRole.MEMBER: 2}

    members = []
    for am, user in rows:
        members.append(
            {
                "user_id": user.tg_id,
                "username": user.username or f"id{user.tg_id}",
                "role": am.role,
                "role_label": ROLE_LABELS[am.role],
                "joined_at": am.joined_at,
                "virus_level": virus_levels.get(user.tg_id, 0),
                "immunity_level": immunity_levels.get(user.tg_id, 0),
            }
        )

    members.sort(key=lambda m: (role_order[m["role"]], m["joined_at"] or _now_utc()))
    return members


async def search_alliances(
    session: AsyncSession,
    query: str | None = None,
    limit: int = 10,
) -> list[dict]:
    """
    Search alliances by name or tag (case-insensitive substring match).
    If query is None/empty, returns the top alliances ordered by member count.

    Each dict: id, name, tag, description, member_count, max_members, defense_bonus.
    """
    stmt = select(Alliance)
    # Exclude CLOSED alliances at the DB level (before LIMIT is applied)
    stmt = stmt.where(Alliance.privacy != AlliancePrivacy.CLOSED.value)
    if query:
        q = query.strip()
        stmt = stmt.where(
            func.lower(Alliance.name).contains(q.lower())
            | func.upper(Alliance.tag).contains(q.upper())
        )
    stmt = stmt.limit(limit)

    result = await session.execute(stmt)
    alliances = result.scalars().all()

    alliance_ids = [a.id for a in alliances]
    counts_result = await session.execute(
        select(
            AllianceMember.alliance_id,
            func.count(AllianceMember.id),
        )
        .where(AllianceMember.alliance_id.in_(alliance_ids))
        .group_by(AllianceMember.alliance_id)
    )
    counts: dict[int, int] = dict(counts_result.all())

    out = []
    for a in alliances:
        count = counts.get(a.id, 0)
        max_members = 20 + a.capacity_level * 5
        defense_bonus = a.shield_level * ALLIANCE_UPGRADE_CONFIG["shield"]["effect_per_level"]
        privacy_str = a.privacy if isinstance(a.privacy, str) else a.privacy.value
        try:
            privacy_enum = AlliancePrivacy(privacy_str)
        except ValueError:
            privacy_enum = AlliancePrivacy.REQUEST
        out.append(
            {
                "id": a.id,
                "name": a.name,
                "tag": a.tag,
                "description": a.description,
                "member_count": count,
                "max_members": max_members,
                "defense_bonus": defense_bonus,
                "privacy": privacy_enum,
            }
        )

    # Sort by member count descending
    out.sort(key=lambda x: x["member_count"], reverse=True)
    return out


# ---------------------------------------------------------------------------
# Public API — bonus getters
# ---------------------------------------------------------------------------


async def get_alliance_defense_bonus(session: AsyncSession, user_id: int) -> float:
    """
    Return the alliance shield defense bonus for a player.

    Formula: shield_level × 0.03
    Returns 0.0 if the user is not in any alliance.
    """
    member = await _get_member(session, user_id)
    if member is None:
        return 0.0

    alliance_result = await session.execute(
        select(Alliance).where(Alliance.id == member.alliance_id)
    )
    alliance = alliance_result.scalar_one_or_none()
    if alliance is None:
        return 0.0

    return alliance.shield_level * ALLIANCE_UPGRADE_CONFIG["shield"]["effect_per_level"]


async def get_alliance_attack_bonus(session: AsyncSession, user_id: int) -> float:
    """
    Return the alliance morale attack bonus for a player.

    Formula: morale_level × 0.03
    Returns 0.0 if the user is not in any alliance.
    """
    member = await _get_member(session, user_id)
    if member is None:
        return 0.0

    alliance_result = await session.execute(
        select(Alliance).where(Alliance.id == member.alliance_id)
    )
    alliance = alliance_result.scalar_one_or_none()
    if alliance is None:
        return 0.0

    return alliance.morale_level * ALLIANCE_UPGRADE_CONFIG["morale"]["effect_per_level"]


async def get_alliance_mining_bonus(session: AsyncSession, user_id: int) -> float:
    """
    Return the alliance mining bonus for a player.

    Formula: mining_level × 0.05
    Returns 0.0 if the user is not in any alliance.
    """
    member = await _get_member(session, user_id)
    if member is None:
        return 0.0

    alliance_result = await session.execute(
        select(Alliance).where(Alliance.id == member.alliance_id)
    )
    alliance = alliance_result.scalar_one_or_none()
    if alliance is None:
        return 0.0

    return alliance.mining_level * ALLIANCE_UPGRADE_CONFIG["mining"]["effect_per_level"]


async def get_alliance_regen_bonus(session: AsyncSession, user_id: int) -> float:
    """
    Return the alliance regen bonus for a player.

    Formula: regen_level × 0.01
    Returns 0.0 if the user is not in any alliance.
    """
    member = await _get_member(session, user_id)
    if member is None:
        return 0.0

    alliance_result = await session.execute(
        select(Alliance).where(Alliance.id == member.alliance_id)
    )
    alliance = alliance_result.scalar_one_or_none()
    if alliance is None:
        return 0.0

    return alliance.regen_level * ALLIANCE_UPGRADE_CONFIG["regen"]["effect_per_level"]


async def get_all_alliance_bonuses(
    session: AsyncSession,
    user_id: int,
) -> dict[str, float]:
    """
    Return all alliance bonuses for a user in a single DB query.

    Loads AllianceMember + Alliance together with selectinload so only one
    round-trip is needed (compared to calling the four individual bonus
    getters which each fire two queries).

    Returns dict with keys: 'attack', 'defense', 'mining', 'regen'.
    All zeros if the user has no alliance.
    """
    result = await session.execute(
        select(AllianceMember)
        .where(AllianceMember.user_id == user_id)
        .options(selectinload(AllianceMember.alliance))
    )
    member = result.scalar_one_or_none()
    if member is None or member.alliance is None:
        return {"attack": 0.0, "defense": 0.0, "mining": 0.0, "regen": 0.0}

    alliance = member.alliance
    cfg = ALLIANCE_UPGRADE_CONFIG
    return {
        "attack": alliance.morale_level * cfg["morale"]["effect_per_level"],
        "defense": alliance.shield_level * cfg["shield"]["effect_per_level"],
        "mining": alliance.mining_level * cfg["mining"]["effect_per_level"],
        "regen": alliance.regen_level * cfg["regen"]["effect_per_level"],
    }


async def get_alliance_max_members(session: AsyncSession, alliance_id: int) -> int:
    """
    Return the maximum number of members for the given alliance.

    Formula: 20 + capacity_level × 5
    """
    alliance_result = await session.execute(
        select(Alliance).where(Alliance.id == alliance_id)
    )
    alliance = alliance_result.scalar_one_or_none()
    if alliance is None:
        return MAX_MEMBERS_DEFAULT

    return MAX_MEMBERS_DEFAULT + alliance.capacity_level * int(
        ALLIANCE_UPGRADE_CONFIG["capacity"]["effect_per_level"]
    )


# ---------------------------------------------------------------------------
# Public API — AllianceCoins & upgrades
# ---------------------------------------------------------------------------


async def buy_alliance_coins(
    session: AsyncSession, user_id: int, amount: int
) -> tuple[bool, str]:
    """
    Purchase AllianceCoins (🔷) for the alliance by spending PremiumCoins (💎).

    Rate: ALLIANCE_COIN_RATE 💎 per 🔷 (currently 1:1).
    Only LEADER or OFFICER can do this.
    """
    if amount <= 0:
        return False, "❌ Количество должно быть больше нуля."

    alliance, member = await _get_alliance_for_user(session, user_id)
    if alliance is None:
        return False, "❌ Ты не состоишь ни в одном альянсе."

    if member.role not in (AllianceRole.LEADER, AllianceRole.OFFICER):
        return False, "❌ Только лидер или офицер могут покупать 🔷 AllianceCoins."

    cost = amount * ALLIANCE_COIN_RATE

    # Lock user row and check balance
    user_result = await session.execute(
        select(User).where(User.tg_id == user_id).with_for_update()
    )
    user = user_result.scalar_one_or_none()
    if user is None:
        return False, "❌ Пользователь не найден."

    if user.premium_coins < cost:
        return False, (
            f"❌ Недостаточно 💎 PremiumCoins.\n"
            f"Нужно: {cost} 💎, у тебя: {user.premium_coins} 💎"
        )

    # Lock alliance row
    alliance_result = await session.execute(
        select(Alliance).where(Alliance.id == alliance.id).with_for_update()
    )
    alliance = alliance_result.scalar_one_or_none()

    user.premium_coins -= cost
    alliance.alliance_coins += amount
    await session.flush()

    return True, (
        f"✅ Куплено <b>{amount} 🔷 AllianceCoins</b>!\n"
        f"Потрачено: {cost} 💎 PremiumCoins\n"
        f"Баланс альянса: {alliance.alliance_coins} 🔷"
    )


async def upgrade_alliance(
    session: AsyncSession, user_id: int, upgrade_key: str
) -> tuple[bool, str]:
    """
    Upgrade an alliance improvement.

    Only LEADER or OFFICER can perform upgrades.
    Deducts AllianceCoins from the alliance balance.
    """
    cfg = ALLIANCE_UPGRADE_CONFIG.get(upgrade_key)
    if cfg is None:
        return False, "❌ Неизвестное улучшение."

    alliance, member = await _get_alliance_for_user(session, user_id)
    if alliance is None:
        return False, "❌ Ты не состоишь ни в одном альянсе."

    if member.role not in (AllianceRole.LEADER, AllianceRole.OFFICER):
        return False, "❌ Только лидер или офицер могут прокачивать альянс."

    # Lock alliance for update
    alliance_result = await session.execute(
        select(Alliance).where(Alliance.id == alliance.id).with_for_update()
    )
    alliance = alliance_result.scalar_one_or_none()

    current_level: int = getattr(alliance, cfg["field"])

    if current_level >= cfg["max_level"]:
        return False, (
            f"❌ {cfg['emoji']} {cfg['name']} уже на максимальном уровне ({dlvl(cfg['max_level'])})."
        )

    cost = _upgrade_cost(cfg, current_level)

    if alliance.alliance_coins < cost:
        return False, (
            f"❌ Недостаточно 🔷 AllianceCoins.\n"
            f"Нужно: {cost} 🔷, в казне: {alliance.alliance_coins} 🔷"
        )

    alliance.alliance_coins -= cost
    setattr(alliance, cfg["field"], current_level + 1)
    new_level = current_level + 1
    await session.flush()

    effect = new_level * cfg["effect_per_level"]
    if upgrade_key == "capacity":
        effect_str = f"{MAX_MEMBERS_DEFAULT + int(new_level * cfg['effect_per_level'])} слотов"
    elif upgrade_key in ("shield", "morale", "mining"):
        effect_str = f"+{int(effect * 100)}%"
    else:  # regen
        effect_str = f"+{effect * 100:.0f}%"

    return True, (
        f"✅ {cfg['emoji']} <b>{cfg['name']}</b> прокачан до уровня <b>{dlvl(new_level)}</b>!\n"
        f"Эффект: {effect_str}\n"
        f"Потрачено: {cost} 🔷\n"
        f"Остаток в казне: {alliance.alliance_coins} 🔷"
    )


async def get_alliance_upgrades(session: AsyncSession, alliance_id: int) -> dict:
    """
    Return current upgrade info for all improvements.

    Returns dict: {key: {level, max_level, effect, next_cost, name, emoji, desc}}
    """
    alliance_result = await session.execute(
        select(Alliance).where(Alliance.id == alliance_id)
    )
    alliance = alliance_result.scalar_one_or_none()
    if alliance is None:
        return {}

    out = {}
    for key, cfg in ALLIANCE_UPGRADE_CONFIG.items():
        level: int = getattr(alliance, cfg["field"])
        effect = level * cfg["effect_per_level"]
        next_cost = _upgrade_cost(cfg, level) if level < cfg["max_level"] else None
        out[key] = {
            "level": level,
            "max_level": cfg["max_level"],
            "effect": effect,
            "next_cost": next_cost,
            "name": cfg["name"],
            "emoji": cfg["emoji"],
            "desc": cfg["desc"],
        }

    return out


# ---------------------------------------------------------------------------
# Public API — Treasury (Казна альянса)
# ---------------------------------------------------------------------------


async def donate_to_treasury(
    session: AsyncSession, user_id: int, bio_amount: int
) -> tuple[bool, str]:
    """
    Участник жертвует bio_coins в казну альянса.

    Пожертвования накапливаются в treasury_bio (не конвертируются сразу).
    Минимальный взнос — TREASURY_MIN_DONATION (100 🧫).
    Создаёт ResourceTransaction для аудит-трейла.
    """
    if bio_amount < TREASURY_MIN_DONATION:
        return False, (
            f"❌ Минимальное пожертвование: {TREASURY_MIN_DONATION} 🧫 BioCoins "
            f"(= 1 🔷 AllianceCoin)."
        )

    alliance, member = await _get_alliance_for_user(session, user_id)
    if alliance is None:
        return False, "❌ Ты не состоишь ни в одном альянсе."

    # Lock user row
    user_result = await session.execute(
        select(User).where(User.tg_id == user_id).with_for_update()
    )
    user = user_result.scalar_one_or_none()
    if user is None:
        return False, "❌ Пользователь не найден."

    if user.bio_coins < bio_amount:
        return False, (
            f"❌ Недостаточно 🧫 BioCoins.\n"
            f"Нужно: {bio_amount} 🧫, у тебя: {user.bio_coins} 🧫"
        )

    # Lock alliance row
    alliance_result = await session.execute(
        select(Alliance).where(Alliance.id == alliance.id).with_for_update()
    )
    alliance = alliance_result.scalar_one_or_none()

    user.bio_coins -= bio_amount
    alliance.treasury_bio += bio_amount

    # Audit transaction
    tx = ResourceTransaction(
        user_id=user_id,
        amount=-bio_amount,
        currency=Currency.BIO_COINS,
        reason=TransactionReason.ALLIANCE_DONATION,
    )
    session.add(tx)
    await session.flush()

    pending_coins = alliance.treasury_bio // BIO_TO_ALLIANCE_RATE
    return True, (
        f"✅ Пожертвовано <b>{bio_amount} 🧫 BioCoins</b> в казну альянса!\n"
        f"Казна: <b>{alliance.treasury_bio} 🧫</b> (≈ {pending_coins} 🔷 при конвертации)\n\n"
        f"Твой баланс: <b>{user.bio_coins} 🧫</b>"
    )


async def convert_treasury(
    session: AsyncSession, user_id: int
) -> tuple[bool, str]:
    """
    Лидер или офицер конвертирует накопленные bio из казны в alliance_coins.

    Курс: BIO_TO_ALLIANCE_RATE 🧫 = 1 🔷.
    Остаток < 100 остаётся в казне.
    """
    alliance, member = await _get_alliance_for_user(session, user_id)
    if alliance is None:
        return False, "❌ Ты не состоишь ни в одном альянсе."

    if member.role not in (AllianceRole.LEADER, AllianceRole.OFFICER):
        return False, "❌ Только лидер или офицер могут конвертировать казну."

    # Lock alliance row
    alliance_result = await session.execute(
        select(Alliance).where(Alliance.id == alliance.id).with_for_update()
    )
    alliance = alliance_result.scalar_one_or_none()

    if alliance.treasury_bio < BIO_TO_ALLIANCE_RATE:
        return False, (
            f"❌ Недостаточно 🧫 в казне для конвертации.\n"
            f"Текущий запас: {alliance.treasury_bio} 🧫\n"
            f"Минимум для конвертации: {BIO_TO_ALLIANCE_RATE} 🧫 = 1 🔷"
        )

    coins_gained = alliance.treasury_bio // BIO_TO_ALLIANCE_RATE
    remainder = alliance.treasury_bio % BIO_TO_ALLIANCE_RATE

    alliance.treasury_bio = remainder
    alliance.alliance_coins += coins_gained
    await session.flush()

    return True, (
        f"✅ Конвертация казны завершена!\n"
        f"Получено: <b>+{coins_gained} 🔷 AllianceCoins</b>\n"
        f"Остаток в казне: <b>{remainder} 🧫</b>\n"
        f"Баланс альянса: <b>{alliance.alliance_coins} 🔷</b>"
    )


# ---------------------------------------------------------------------------
# Public API — Privacy (Приватность альянса)
# ---------------------------------------------------------------------------


async def set_privacy(
    session: AsyncSession, user_id: int, privacy: AlliancePrivacy
) -> tuple[bool, str]:
    """Установить режим приватности альянса. Только лидер."""
    alliance, member = await _get_alliance_for_user(session, user_id)
    if alliance is None:
        return False, "❌ Ты не состоишь ни в одном альянсе."

    if member.role != AllianceRole.LEADER:
        return False, "❌ Только лидер может менять приватность альянса."

    alliance_result = await session.execute(
        select(Alliance).where(Alliance.id == alliance.id).with_for_update()
    )
    alliance = alliance_result.scalar_one_or_none()
    alliance.privacy = privacy.value
    await session.flush()

    label = PRIVACY_LABELS[privacy]
    return True, f"✅ Режим альянса изменён: <b>{label}</b>"


async def request_join(
    session: AsyncSession, user_id: int, alliance_id: int
) -> tuple[bool, str]:
    """
    Подать заявку на вступление в альянс (режим REQUEST).

    Возвращает (True, msg) если заявка создана.
    Возвращает список user_id офицеров/лидера для уведомлений через extra dict.
    """
    # Check not already in alliance (lock to guard against race conditions)
    existing_member_result = await session.execute(
        select(AllianceMember)
        .where(AllianceMember.user_id == user_id)
        .with_for_update()
    )
    if existing_member_result.scalar_one_or_none() is not None:
        return False, "❌ Ты уже состоишь в альянсе."

    # Load alliance with lock to prevent concurrent capacity race
    alliance_result = await session.execute(
        select(Alliance).where(Alliance.id == alliance_id).with_for_update()
    )
    alliance = alliance_result.scalar_one_or_none()
    if alliance is None:
        return False, "❌ Альянс не найден."

    privacy_str = alliance.privacy if isinstance(alliance.privacy, str) else alliance.privacy.value
    if privacy_str == AlliancePrivacy.CLOSED.value:
        return False, "❌ Этот альянс закрытый — вступить можно только по приглашению."

    if privacy_str == AlliancePrivacy.OPEN.value:
        return False, "❌ Этот альянс открытый — нажми «Вступить» напрямую."

    # Check capacity
    count_result = await session.execute(
        select(func.count(AllianceMember.id)).where(AllianceMember.alliance_id == alliance_id)
    )
    count: int = count_result.scalar_one()
    max_members = await get_alliance_max_members(session, alliance_id)
    if count >= max_members:
        return False, f"❌ Альянс заполнен ({count}/{max_members})."

    # Check no duplicate pending request
    existing_req_result = await session.execute(
        select(AllianceJoinRequest).where(
            AllianceJoinRequest.alliance_id == alliance_id,
            AllianceJoinRequest.user_id == user_id,
            AllianceJoinRequest.status == JoinRequestStatus.PENDING,
        )
    )
    if existing_req_result.scalar_one_or_none() is not None:
        return False, "❌ Ты уже подал заявку в этот альянс. Ожидай решения."

    req = AllianceJoinRequest(
        alliance_id=alliance_id,
        user_id=user_id,
        status=JoinRequestStatus.PENDING,
    )
    session.add(req)
    await session.flush()

    return True, (
        f"✅ Заявка на вступление в <b>[{alliance.tag}] {alliance.name}</b> отправлена!\n"
        "Ожидай решения лидера или офицера."
    )


async def get_pending_requests(
    session: AsyncSession, alliance_id: int
) -> list[dict]:
    """Вернуть список активных (PENDING) заявок на вступление."""
    result = await session.execute(
        select(AllianceJoinRequest, User)
        .join(User, AllianceJoinRequest.user_id == User.tg_id)
        .where(
            AllianceJoinRequest.alliance_id == alliance_id,
            AllianceJoinRequest.status == JoinRequestStatus.PENDING,
        )
        .order_by(AllianceJoinRequest.created_at)
    )
    rows = result.all()
    out = []
    for req, user in rows:
        out.append(
            {
                "request_id": req.id,
                "user_id": user.tg_id,
                "username": user.username or f"id{user.tg_id}",
                "created_at": req.created_at,
            }
        )
    return out


async def get_officer_ids(session: AsyncSession, alliance_id: int) -> list[int]:
    """Вернуть tg_id всех лидеров и офицеров альянса (для уведомлений)."""
    result = await session.execute(
        select(AllianceMember.user_id).where(
            AllianceMember.alliance_id == alliance_id,
            AllianceMember.role.in_([AllianceRole.LEADER, AllianceRole.OFFICER]),
        )
    )
    return [row[0] for row in result.all()]


async def handle_request(
    session: AsyncSession, officer_id: int, request_id: int, accept: bool
) -> tuple[bool, str]:
    """
    Лидер/офицер принимает или отклоняет заявку на вступление.

    Если принять: создаёт AllianceMember, помечает заявку ACCEPTED.
    Если отклонить: помечает заявку DECLINED.
    """
    # Get officer's alliance
    alliance, officer_member = await _get_alliance_for_user(session, officer_id)
    if alliance is None:
        return False, "❌ Ты не состоишь ни в одном альянсе."

    if officer_member.role not in (AllianceRole.LEADER, AllianceRole.OFFICER):
        return False, "❌ Только лидер или офицер могут обрабатывать заявки."

    # Load the request
    req_result = await session.execute(
        select(AllianceJoinRequest).where(
            AllianceJoinRequest.id == request_id,
            AllianceJoinRequest.alliance_id == alliance.id,
            AllianceJoinRequest.status == JoinRequestStatus.PENDING,
        )
    )
    req = req_result.scalar_one_or_none()
    if req is None:
        return False, "❌ Заявка не найдена или уже обработана."

    # Load applicant
    applicant_result = await session.execute(
        select(User).where(User.tg_id == req.user_id)
    )
    applicant = applicant_result.scalar_one_or_none()
    display = f"@{applicant.username}" if applicant and applicant.username else f"id{req.user_id}"

    if not accept:
        req.status = JoinRequestStatus.DECLINED
        await session.flush()
        return True, f"✅ Заявка игрока <b>{display}</b> отклонена."

    # Accept: check capacity and not already a member
    existing = await _get_member(session, req.user_id)
    if existing is not None:
        req.status = JoinRequestStatus.DECLINED
        await session.flush()
        return False, f"❌ Игрок <b>{display}</b> уже состоит в другом альянсе. Заявка отклонена."

    count_result = await session.execute(
        select(func.count(AllianceMember.id)).where(
            AllianceMember.alliance_id == alliance.id
        )
    )
    count: int = count_result.scalar_one()
    max_members = await get_alliance_max_members(session, alliance.id)
    if count >= max_members:
        return False, f"❌ Альянс заполнен ({count}/{max_members}). Заявка не может быть принята."

    new_member = AllianceMember(
        alliance_id=alliance.id,
        user_id=req.user_id,
        role=AllianceRole.MEMBER,
    )
    session.add(new_member)
    req.status = JoinRequestStatus.ACCEPTED
    await session.flush()

    return True, (
        f"✅ Игрок <b>{display}</b> принят в альянс "
        f"<b>[{alliance.tag}] {alliance.name}</b>!"
    )
