"""
Alliance service — business logic for the clan/guild system.

All functions return (success: bool, message: str) tuples so handlers
can display feedback without containing any business logic.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from bot.models.alliance import Alliance, AllianceMember, AllianceRole, ROLE_LABELS
from bot.models.user import User

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ALLIANCE_CREATE_COST = 500  # bio_coins
MAX_MEMBERS_DEFAULT = 20
DEFENSE_BONUS_PER_MEMBER = 0.02   # +2% per member
DEFENSE_BONUS_CAP = 0.40          # max +40% at 20 members

# Tag: 2-5 chars, latin/cyrillic letters and digits
_TAG_RE = re.compile(r"^[A-Za-zА-Яа-яЁё0-9]{2,5}$")
# Name: 3-32 chars (allow spaces and common punctuation)
_NAME_RE = re.compile(r"^[A-Za-zА-Яа-яЁё0-9 _\-]{3,32}$")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _now_utc() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


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
# Public API
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
            f"❌ Недостаточно bio_coins для создания альянса.\n"
            f"Требуется: {ALLIANCE_CREATE_COST} 🧫\n"
            f"У тебя: {user.bio_coins} 🧫"
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
        f"Потрачено: {ALLIANCE_CREATE_COST} bio_coins 🧫\n\n"
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
    Alliance must not be full.
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

    if member_count >= alliance.max_members:
        return False, (
            f"❌ Альянс заполнен ({member_count}/{alliance.max_members} участников)."
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


async def get_alliance_info(session: AsyncSession, user_id: int) -> dict | None:
    """
    Return info about the alliance the user belongs to.

    Returns None if the user is not in any alliance.
    Returns a dict with keys:
        id, name, tag, description, leader_id, leader_username,
        member_count, max_members, defense_bonus, created_at,
        user_role (AllianceRole)
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

    bonus = min(DEFENSE_BONUS_PER_MEMBER * member_count, DEFENSE_BONUS_CAP)

    return {
        "id": alliance.id,
        "name": alliance.name,
        "tag": alliance.tag,
        "description": alliance.description,
        "leader_id": alliance.leader_id,
        "leader_username": leader_display,
        "member_count": member_count,
        "max_members": alliance.max_members,
        "defense_bonus": bonus,
        "created_at": alliance.created_at,
        "user_role": member.role,
    }


async def get_alliance_members(
    session: AsyncSession, alliance_id: int
) -> list[dict]:
    """
    Return a list of members for the given alliance.

    Each dict has: user_id, username, role (AllianceRole), joined_at.
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
            }
        )

    members.sort(key=lambda m: (role_order[m["role"]], m["joined_at"] or _now_utc()))
    return members


async def get_alliance_defense_bonus(session: AsyncSession, user_id: int) -> float:
    """
    Return the alliance defense bonus for a player.

    Formula: 0.02 * member_count, capped at 0.40 (40%).
    Returns 0.0 if the user is not in any alliance.
    """
    member = await _get_member(session, user_id)
    if member is None:
        return 0.0

    count_result = await session.execute(
        select(func.count(AllianceMember.id)).where(
            AllianceMember.alliance_id == member.alliance_id
        )
    )
    count: int = count_result.scalar_one()
    return min(DEFENSE_BONUS_PER_MEMBER * count, DEFENSE_BONUS_CAP)


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
    if query:
        q = query.strip()
        stmt = stmt.where(
            func.lower(Alliance.name).contains(q.lower())
            | func.upper(Alliance.tag).contains(q.upper())
        )
    stmt = stmt.limit(limit)

    result = await session.execute(stmt)
    alliances = result.scalars().all()

    out = []
    for a in alliances:
        count_result = await session.execute(
            select(func.count(AllianceMember.id)).where(
                AllianceMember.alliance_id == a.id
            )
        )
        count: int = count_result.scalar_one()
        bonus = min(DEFENSE_BONUS_PER_MEMBER * count, DEFENSE_BONUS_CAP)
        out.append(
            {
                "id": a.id,
                "name": a.name,
                "tag": a.tag,
                "description": a.description,
                "member_count": count,
                "max_members": a.max_members,
                "defense_bonus": bonus,
            }
        )

    # Sort by member count descending
    out.sort(key=lambda x: x["member_count"], reverse=True)
    return out
