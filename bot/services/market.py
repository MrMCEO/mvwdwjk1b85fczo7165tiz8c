"""
БиоБиржа service — P2P trading of items/mutations and hit contracts.

Trading flow:
  SELL_ITEM:     seller lists an item from inventory for a bio_coins price.
                 5% commission is deducted from buyer's payment upfront.
                 On purchase: item.owner_id → buyer.
  SELL_MUTATION: seller lists an unactivated buff mutation for a bio_coins price.
                 5% commission is deducted from buyer's payment upfront.
                 On purchase: mutation.owner_id → buyer.

Hit-contract flow:
  Client freezes reward (bio_coins). Hitman claims the contract.
  After a successful infection of the target, check_contract_completion() is called
  and pays out the reward automatically.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.models.alliance import AllianceMember
from bot.models.infection import Infection
from bot.models.item import ITEM_CONFIG, Item
from bot.models.market import ListingStatus, ListingType, MarketListing
from bot.models.mutation import Mutation
from bot.models.resource import Currency, ResourceTransaction, TransactionReason
from bot.models.user import User
from bot.services.mutation import MUTATION_CONFIG

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

LISTING_DURATION = timedelta(hours=24)
SELL_COMMISSION_PCT = 0.05  # 5% комиссия: удерживается с покупателя

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _now_utc() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


async def _get_user(session: AsyncSession, user_id: int, lock: bool = False) -> User | None:
    stmt = select(User).where(User.tg_id == user_id)
    if lock:
        stmt = stmt.with_for_update()
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def _get_listing(
    session: AsyncSession, listing_id: int, lock: bool = False
) -> MarketListing | None:
    stmt = select(MarketListing).where(MarketListing.id == listing_id)
    if lock:
        stmt = stmt.with_for_update()
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def _same_alliance(session: AsyncSession, user_a: int, user_b: int) -> bool:
    """Return True if both users are members of the same alliance."""
    result_a = await session.execute(
        select(AllianceMember.alliance_id).where(AllianceMember.user_id == user_a)
    )
    result_b = await session.execute(
        select(AllianceMember.alliance_id).where(AllianceMember.user_id == user_b)
    )
    alliance_a = result_a.scalar_one_or_none()
    alliance_b = result_b.scalar_one_or_none()
    if alliance_a is None or alliance_b is None:
        return False
    return alliance_a == alliance_b


def _listing_to_dict(listing: MarketListing) -> dict:
    """Convert a MarketListing ORM object to a plain dict for handler use."""
    return {
        "id": listing.id,
        "seller_id": listing.seller_id,
        "listing_type": listing.listing_type,
        "status": listing.status,
        "price": listing.price,
        "item_id": listing.item_id,
        "mutation_id": listing.mutation_id,
        "target_username": listing.target_username,
        "target_id": listing.target_id,
        "reward": listing.reward,
        "buyer_id": listing.buyer_id,
        "created_at": listing.created_at,
        "expires_at": listing.expires_at,
        "completed_at": listing.completed_at,
        # Устаревшие поля (для старых записей в БД)
        "amount": listing.amount,
    }


# ---------------------------------------------------------------------------
# Item listing
# ---------------------------------------------------------------------------


async def create_item_listing(
    session: AsyncSession,
    seller_id: int,
    item_id: int,
    price: int,
) -> tuple[bool, str]:
    """
    Seller puts an inventory item on sale for *price* bio_coins.

    The item must be unused and owned by *seller_id*.
    The item is "frozen" on the listing — it cannot be used or sold again until cancelled.

    Returns (success, message).
    """
    if price <= 0:
        return False, "❌ Цена должна быть больше нуля."

    # Verify item ownership and availability
    result = await session.execute(
        select(Item).where(
            and_(
                Item.id == item_id,
                Item.owner_id == seller_id,
                Item.is_used == False,  # noqa: E712
            )
        ).with_for_update()
    )
    item = result.scalar_one_or_none()
    if item is None:
        return False, "❌ Предмет не найден или уже использован."

    # Check item is not already listed
    existing = await session.execute(
        select(MarketListing).where(
            and_(
                MarketListing.item_id == item_id,
                MarketListing.status == ListingStatus.ACTIVE,
            )
        )
    )
    if existing.scalar_one_or_none() is not None:
        return False, "❌ Этот предмет уже выставлен на бирже."

    cfg = ITEM_CONFIG.get(item.item_type, {})
    item_name = cfg.get("name", item.item_type.value)
    item_emoji = cfg.get("emoji", "📦")

    listing = MarketListing(
        seller_id=seller_id,
        listing_type=ListingType.SELL_ITEM,
        status=ListingStatus.ACTIVE,
        price=price,
        item_id=item_id,
        expires_at=_now_utc() + LISTING_DURATION,
    )
    session.add(listing)
    await session.flush()

    return True, (
        f"✅ Лот #{listing.id} создан!\n"
        f"Товар: {item_emoji} <b>{item_name}</b>\n"
        f"Цена: <b>{price:,}</b> 🧫\n"
        f"Активен до: {listing.expires_at.strftime('%d.%m %H:%M')} UTC"
    )


# ---------------------------------------------------------------------------
# Mutation listing
# ---------------------------------------------------------------------------


async def create_mutation_listing(
    session: AsyncSession,
    seller_id: int,
    mutation_id: int,
    price: int,
) -> tuple[bool, str]:
    """
    Seller puts an unactivated buff mutation on sale for *price* bio_coins.

    The mutation must be in inventory (is_active=False, is_used=False) and owned by *seller_id*.

    Returns (success, message).
    """
    if price <= 0:
        return False, "❌ Цена должна быть больше нуля."

    result = await session.execute(
        select(Mutation).where(
            and_(
                Mutation.id == mutation_id,
                Mutation.owner_id == seller_id,
                Mutation.is_active == False,  # noqa: E712
                Mutation.is_used == False,    # noqa: E712
            )
        ).with_for_update()
    )
    mutation = result.scalar_one_or_none()
    if mutation is None:
        return False, "❌ Мутация не найдена или уже активирована/использована."

    # Check not already listed
    existing = await session.execute(
        select(MarketListing).where(
            and_(
                MarketListing.mutation_id == mutation_id,
                MarketListing.status == ListingStatus.ACTIVE,
            )
        )
    )
    if existing.scalar_one_or_none() is not None:
        return False, "❌ Эта мутация уже выставлена на бирже."

    cfg = MUTATION_CONFIG.get(mutation.mutation_type, {})
    description = cfg.get("description", mutation.mutation_type.value)
    rarity_label = mutation.rarity.value

    listing = MarketListing(
        seller_id=seller_id,
        listing_type=ListingType.SELL_MUTATION,
        status=ListingStatus.ACTIVE,
        price=price,
        mutation_id=mutation_id,
        expires_at=_now_utc() + LISTING_DURATION,
    )
    session.add(listing)
    await session.flush()

    return True, (
        f"✅ Лот #{listing.id} создан!\n"
        f"Мутация: 🧬 <b>{description}</b> [{rarity_label}]\n"
        f"Цена: <b>{price:,}</b> 🧫\n"
        f"Активен до: {listing.expires_at.strftime('%d.%m %H:%M')} UTC"
    )


# ---------------------------------------------------------------------------
# Purchase a listing (SELL_ITEM / SELL_MUTATION)
# ---------------------------------------------------------------------------


async def purchase_listing(
    session: AsyncSession,
    buyer_id: int,
    listing_id: int,
) -> tuple[bool, str]:
    """
    Buy an item or mutation from the БиоБиржа.

    5% commission is charged on top of the listing price (buyer pays price * 1.05).
    Seller receives the full listed price.
    Ownership of the item/mutation is transferred to the buyer.

    Returns (success, message).
    """
    listing = await _get_listing(session, listing_id, lock=True)

    if listing is None:
        return False, "❌ Лот не найден."
    if listing.status != ListingStatus.ACTIVE:
        return False, "❌ Лот уже не активен."
    if listing.listing_type not in (ListingType.SELL_ITEM, ListingType.SELL_MUTATION):
        return False, "❌ Это не торговый лот."
    if listing.seller_id == buyer_id:
        return False, "❌ Нельзя купить собственный лот."
    if listing.expires_at < _now_utc():
        listing.status = ListingStatus.EXPIRED
        await session.flush()
        return False, "❌ Лот истёк."

    commission = max(1, round(listing.price * SELL_COMMISSION_PCT))
    total_cost = listing.price + commission

    buyer = await _get_user(session, buyer_id, lock=True)
    if buyer is None:
        return False, "❌ Игрок не найден."

    if buyer.bio_coins < total_cost:
        return False, (
            f"❌ Недостаточно 🧫 BioCoins.\n"
            f"Цена: <b>{listing.price:,}</b> 🧫 + комиссия <b>{commission:,}</b> 🧫\n"
            f"Итого: <b>{total_cost:,}</b> 🧫\n"
            f"Твой баланс: <b>{buyer.bio_coins:,}</b> 🧫"
        )

    seller = await _get_user(session, listing.seller_id, lock=True)
    if seller is None:
        return False, "❌ Продавец не найден."

    # Deduct from buyer
    buyer.bio_coins -= total_cost
    session.add(ResourceTransaction(
        user_id=buyer_id,
        amount=-total_cost,
        currency=Currency.BIO_COINS,
        reason=TransactionReason.DONATION,
    ))

    # Pay seller (full price, commission stays with the system)
    seller.bio_coins += listing.price
    session.add(ResourceTransaction(
        user_id=listing.seller_id,
        amount=listing.price,
        currency=Currency.BIO_COINS,
        reason=TransactionReason.DONATION,
    ))

    # Transfer ownership
    if listing.listing_type == ListingType.SELL_ITEM and listing.item_id is not None:
        item_result = await session.execute(
            select(Item).where(Item.id == listing.item_id).with_for_update()
        )
        item = item_result.scalar_one_or_none()
        if item is None:
            return False, "❌ Предмет не найден (возможно, уже использован)."
        item.owner_id = buyer_id
        cfg = ITEM_CONFIG.get(item.item_type, {})
        goods_label = f"{cfg.get('emoji', '📦')} {cfg.get('name', item.item_type.value)}"

    elif listing.listing_type == ListingType.SELL_MUTATION and listing.mutation_id is not None:
        mut_result = await session.execute(
            select(Mutation).where(Mutation.id == listing.mutation_id).with_for_update()
        )
        mutation = mut_result.scalar_one_or_none()
        if mutation is None:
            return False, "❌ Мутация не найдена."
        mutation.owner_id = buyer_id
        cfg = MUTATION_CONFIG.get(mutation.mutation_type, {})
        goods_label = f"🧬 {cfg.get('description', mutation.mutation_type.value)}"

    else:
        return False, "❌ Неверный тип лота."

    listing.status = ListingStatus.COMPLETED
    listing.buyer_id = buyer_id
    listing.completed_at = _now_utc()
    await session.flush()

    return True, (
        f"✅ Покупка #{listing_id} выполнена!\n"
        f"Получено: <b>{goods_label}</b>\n"
        f"Заплачено: <b>{listing.price:,}</b> 🧫 + комиссия <b>{commission:,}</b> 🧫"
    )


# ---------------------------------------------------------------------------
# Cancel a listing
# ---------------------------------------------------------------------------


async def cancel_listing(
    session: AsyncSession,
    user_id: int,
    listing_id: int,
) -> tuple[bool, str]:
    """
    Cancel an active listing.

    Only the listing creator can cancel. No funds are frozen for item/mutation
    listings, so cancellation is always free (just unlocks the item/mutation).

    Returns (success, message).
    """
    listing = await _get_listing(session, listing_id, lock=True)
    if listing is None:
        return False, "❌ Лот не найден."
    if listing.seller_id != user_id:
        return False, "❌ Ты можешь отменить только свой лот."
    if listing.status != ListingStatus.ACTIVE:
        return False, "❌ Лот уже не активен."

    if listing.listing_type == ListingType.HIT_CONTRACT:
        owner = await _get_user(session, user_id, lock=True)
        if owner is None:
            return False, "❌ Игрок не найден."
        owner.bio_coins += listing.reward
        session.add(ResourceTransaction(
            user_id=user_id,
            amount=listing.reward,
            currency=Currency.BIO_COINS,
            reason=TransactionReason.DONATION,
        ))
        refund_text = f"Возвращено: <b>{listing.reward:,}</b> 🧫 (награда)"
    else:
        # SELL_ITEM / SELL_MUTATION — ничего не было заморожено
        refund_text = "Предмет/мутация снова доступны в инвентаре."

    listing.status = ListingStatus.CANCELLED
    await session.flush()

    return True, (
        f"✅ Лот #{listing_id} отменён.\n"
        f"{refund_text}"
    )


# ---------------------------------------------------------------------------
# Hit contracts
# ---------------------------------------------------------------------------


async def create_hit_contract(
    session: AsyncSession,
    client_id: int,
    target_username: str,
    reward_bio: int,
) -> tuple[bool, str]:
    """
    Create a hit contract targeting *target_username* for *reward_bio* bio_coins.

    Checks:
    - Cannot target yourself.
    - Cannot target an alliance member.
    - Target must exist.
    - Client has enough bio_coins.

    Returns (success, message).
    """
    if reward_bio <= 0:
        return False, "❌ Награда должна быть больше нуля."

    # Strip leading @
    clean_username = target_username.lstrip("@").strip()
    if not clean_username:
        return False, "❌ Укажи @username цели."

    # Find target by username
    result = await session.execute(
        select(User).where(User.username == clean_username)
    )
    target = result.scalar_one_or_none()
    if target is None:
        return False, f"❌ Игрок @{clean_username} не найден."

    if target.tg_id == client_id:
        return False, "❌ Нельзя создать контракт на самого себя."

    if await _same_alliance(session, client_id, target.tg_id):
        return False, "❌ Нельзя создать контракт на члена своего альянса."

    client = await _get_user(session, client_id, lock=True)
    if client is None:
        return False, "❌ Игрок не найден. Сначала создай профиль через /start."

    if client.bio_coins < reward_bio:
        return False, (
            f"❌ Недостаточно 🧫 BioCoins.\n"
            f"Нужно: <b>{reward_bio:,}</b> 🧫\n"
            f"Твой баланс: <b>{client.bio_coins:,}</b>"
        )

    client.bio_coins -= reward_bio

    session.add(ResourceTransaction(
        user_id=client_id,
        amount=-reward_bio,
        currency=Currency.BIO_COINS,
        reason=TransactionReason.DONATION,
    ))

    listing = MarketListing(
        seller_id=client_id,
        listing_type=ListingType.HIT_CONTRACT,
        status=ListingStatus.ACTIVE,
        reward=reward_bio,
        target_username=clean_username,
        target_id=target.tg_id,
        expires_at=_now_utc() + LISTING_DURATION,
    )
    session.add(listing)
    await session.flush()

    return True, (
        f"✅ Контракт #{listing.id} размещён!\n"
        f"🎯 Цель: @{clean_username}\n"
        f"💰 Награда: <b>{reward_bio:,}</b> 🧫\n"
        f"Активен до: {listing.expires_at.strftime('%d.%m %H:%M')} UTC\n\n"
        f"Киллер должен заразить цель, чтобы получить награду."
    )


async def claim_hit_contract(
    session: AsyncSession,
    hitman_id: int,
    listing_id: int,
) -> tuple[bool, str]:
    """
    Hitman takes a hit contract.

    - Sets buyer_id to hitman_id.
    - If the hitman has already infected the target → auto-complete.
    - Otherwise marks the hitman and waits for check_contract_completion().

    Returns (success, message).
    """
    listing = await _get_listing(session, listing_id, lock=True)
    if listing is None:
        return False, "❌ Контракт не найден."
    if listing.listing_type != ListingType.HIT_CONTRACT:
        return False, "❌ Это не контракт на заражение."
    if listing.status != ListingStatus.ACTIVE:
        return False, "❌ Контракт уже не активен."
    if listing.seller_id == hitman_id:
        return False, "❌ Нельзя взять собственный контракт."
    if listing.buyer_id is not None:
        return False, "❌ Контракт уже взят другим игроком."
    if listing.expires_at < _now_utc():
        listing.status = ListingStatus.EXPIRED
        await session.flush()
        return False, "❌ Контракт истёк."

    # Check if hitman already has an active infection on the target
    already_result = await session.execute(
        select(Infection).where(
            and_(
                Infection.attacker_id == hitman_id,
                Infection.victim_id == listing.target_id,
                Infection.is_active == True,  # noqa: E712
            )
        )
    )
    already_infected = already_result.scalar_one_or_none()

    if already_infected is not None:
        # Auto-complete: hitman already infected the target
        hitman = await _get_user(session, hitman_id, lock=True)
        if hitman is None:
            return False, "❌ Игрок не найден."

        hitman.bio_coins += listing.reward
        session.add(ResourceTransaction(
            user_id=hitman_id,
            amount=listing.reward,
            currency=Currency.BIO_COINS,
            reason=TransactionReason.INFECTION_INCOME,
        ))
        listing.buyer_id = hitman_id
        listing.status = ListingStatus.COMPLETED
        listing.completed_at = _now_utc()
        await session.flush()

        return True, (
            f"🎯 Контракт #{listing_id} выполнен мгновенно!\n"
            f"Цель @{listing.target_username} уже заражена тобой.\n"
            f"💰 Награда: <b>{listing.reward:,}</b> 🧫 зачислена."
        )

    # Mark hitman and wait
    listing.buyer_id = hitman_id
    await session.flush()

    return True, (
        f"✅ Контракт #{listing_id} принят!\n"
        f"🎯 Цель: @{listing.target_username}\n"
        f"💰 Награда: <b>{listing.reward:,}</b> 🧫\n\n"
        f"Заразь цель, чтобы получить награду.\n"
        f"Награда выплатится автоматически после успешного заражения."
    )


async def check_contract_completion(
    session: AsyncSession,
    attacker_id: int,
    victim_id: int,
) -> None:
    """
    Called after a successful infection to check for pending hit contracts.

    If *attacker_id* has claimed an active contract targeting *victim_id*,
    the contract is completed and the reward is paid out.

    This function is intentionally NOT integrated into combat.py — call it
    from the attack handler after a confirmed successful infection.
    """
    # Find active contract claimed by this attacker for this victim
    result = await session.execute(
        select(MarketListing).where(
            and_(
                MarketListing.listing_type == ListingType.HIT_CONTRACT,
                MarketListing.status == ListingStatus.ACTIVE,
                MarketListing.buyer_id == attacker_id,
                MarketListing.target_id == victim_id,
            )
        ).with_for_update()
    )
    listing = result.scalar_one_or_none()
    if listing is None:
        return

    # Pay out reward
    hitman = await _get_user(session, attacker_id, lock=True)
    if hitman is None:
        return

    hitman.bio_coins += listing.reward
    session.add(ResourceTransaction(
        user_id=attacker_id,
        amount=listing.reward,
        currency=Currency.BIO_COINS,
        reason=TransactionReason.INFECTION_INCOME,
    ))
    listing.status = ListingStatus.COMPLETED
    listing.completed_at = _now_utc()
    await session.flush()


# ---------------------------------------------------------------------------
# Listing queries
# ---------------------------------------------------------------------------


async def get_active_listings(
    session: AsyncSession,
    listing_type: ListingType | None = None,
    limit: int = 20,
) -> list[dict]:
    """Return active (non-expired) listings, optionally filtered by type."""
    stmt = select(MarketListing).where(
        and_(
            MarketListing.status == ListingStatus.ACTIVE,
            MarketListing.expires_at > _now_utc(),
        )
    )
    if listing_type is not None:
        stmt = stmt.where(MarketListing.listing_type == listing_type)
    stmt = stmt.order_by(MarketListing.created_at.desc()).limit(limit)
    result = await session.execute(stmt)
    return [_listing_to_dict(r) for r in result.scalars().all()]


async def get_my_listings(
    session: AsyncSession,
    user_id: int,
) -> list[dict]:
    """Return all listings created by *user_id* (any status), newest first."""
    result = await session.execute(
        select(MarketListing)
        .where(MarketListing.seller_id == user_id)
        .order_by(MarketListing.created_at.desc())
        .limit(50)
    )
    return [_listing_to_dict(r) for r in result.scalars().all()]


async def expire_listings(session: AsyncSession) -> int:
    """
    Mark all overdue ACTIVE listings as EXPIRED and refund frozen funds.

    For SELL_ITEM / SELL_MUTATION: nothing was frozen, so just mark as expired.
    For HIT_CONTRACT: refund the reward to the client.

    Returns the number of listings expired.
    """
    now = _now_utc()
    result = await session.execute(
        select(MarketListing).where(
            and_(
                MarketListing.status == ListingStatus.ACTIVE,
                MarketListing.expires_at <= now,
            )
        ).with_for_update()
    )
    expired = result.scalars().all()

    for listing in expired:
        if listing.listing_type == ListingType.HIT_CONTRACT:
            owner = await _get_user(session, listing.seller_id, lock=True)
            if owner is not None:
                owner.bio_coins += listing.reward
                session.add(ResourceTransaction(
                    user_id=listing.seller_id,
                    amount=listing.reward,
                    currency=Currency.BIO_COINS,
                    reason=TransactionReason.DONATION,
                ))
        # SELL_ITEM / SELL_MUTATION: nothing to refund

        listing.status = ListingStatus.EXPIRED

    await session.flush()
    return len(expired)
