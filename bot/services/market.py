"""
Market service — black market P2P trading and hit contracts.

Trading flow:
  SELL: seller freezes bio_coins (deducted immediately, 5% commission applied).
        Buyer pays premium_coins → receives bio_coins.
  BUY:  buyer freezes premium_coins.
        Fulfiller provides bio_coins → receives premium_coins.

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
from bot.models.market import ListingStatus, ListingType, MarketListing
from bot.models.resource import Currency, ResourceTransaction, TransactionReason
from bot.models.user import User

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

LISTING_DURATION = timedelta(hours=24)
SELL_COMMISSION_PCT = 0.05  # 5% комиссия при продаже bio_coins

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
        "amount": listing.amount,
        "price": listing.price,
        "target_username": listing.target_username,
        "target_id": listing.target_id,
        "reward": listing.reward,
        "buyer_id": listing.buyer_id,
        "created_at": listing.created_at,
        "expires_at": listing.expires_at,
        "completed_at": listing.completed_at,
    }


# ---------------------------------------------------------------------------
# Trading — SELL listings
# ---------------------------------------------------------------------------


async def create_sell_listing(
    session: AsyncSession,
    seller_id: int,
    bio_amount: int,
    premium_price: int,
) -> tuple[bool, str]:
    """
    Seller freezes bio_coins (deducted immediately) and creates a SELL listing.

    5% commission is taken from the bio_amount upfront so the seller receives
    price * premium_coins when fulfilled; the buyer always receives the full amount.

    Returns (success, message).
    """
    if bio_amount <= 0:
        return False, "❌ Количество 🧫 BioCoins должно быть больше нуля."
    if premium_price <= 0:
        return False, "❌ Цена должна быть больше нуля."

    seller = await _get_user(session, seller_id, lock=True)
    if seller is None:
        return False, "❌ Игрок не найден. Сначала создай профиль через /start."

    # Commission: take 5% from amount to freeze (seller pays it)
    commission = max(1, round(bio_amount * SELL_COMMISSION_PCT))
    total_freeze = bio_amount + commission

    if seller.bio_coins < total_freeze:
        return False, (
            f"❌ Недостаточно 🧫 BioCoins.\n"
            f"Нужно: <b>{total_freeze:,}</b> (включая комиссию {commission:,})\n"
            f"Твой баланс: <b>{seller.bio_coins:,}</b>"
        )

    seller.bio_coins -= total_freeze

    # Record outgoing transaction
    session.add(ResourceTransaction(
        user_id=seller_id,
        amount=-total_freeze,
        currency=Currency.BIO_COINS,
        reason=TransactionReason.DONATION,  # reuse closest reason; market is post-MVP
    ))

    listing = MarketListing(
        seller_id=seller_id,
        listing_type=ListingType.SELL_COINS,
        status=ListingStatus.ACTIVE,
        amount=bio_amount,
        price=premium_price,
        expires_at=_now_utc() + LISTING_DURATION,
    )
    session.add(listing)
    await session.flush()

    return True, (
        f"✅ Предложение #{listing.id} создано!\n"
        f"Продаёшь: <b>{bio_amount:,}</b> 🧫 bio\n"
        f"Цена: <b>{premium_price:,}</b> 💎 premium\n"
        f"Комиссия: <b>{commission:,}</b> 🧫 (5%)\n"
        f"Активно до: {listing.expires_at.strftime('%d.%m %H:%M')} UTC"
    )


# ---------------------------------------------------------------------------
# Trading — BUY listings
# ---------------------------------------------------------------------------


async def create_buy_listing(
    session: AsyncSession,
    buyer_id: int,
    bio_amount: int,
    premium_price: int,
) -> tuple[bool, str]:
    """
    Buyer freezes premium_coins and creates a BUY listing.

    Returns (success, message).
    """
    if bio_amount <= 0:
        return False, "❌ Количество 🧫 BioCoins должно быть больше нуля."
    if premium_price <= 0:
        return False, "❌ Цена должна быть больше нуля."

    buyer = await _get_user(session, buyer_id, lock=True)
    if buyer is None:
        return False, "❌ Игрок не найден. Сначала создай профиль через /start."

    if buyer.premium_coins < premium_price:
        return False, (
            f"❌ Недостаточно 💎 PremiumCoins.\n"
            f"Нужно: <b>{premium_price:,}</b> 💎\n"
            f"Твой баланс: <b>{buyer.premium_coins:,}</b>"
        )

    buyer.premium_coins -= premium_price

    session.add(ResourceTransaction(
        user_id=buyer_id,
        amount=-premium_price,
        currency=Currency.PREMIUM_COINS,
        reason=TransactionReason.DONATION,
    ))

    listing = MarketListing(
        seller_id=buyer_id,
        listing_type=ListingType.BUY_COINS,
        status=ListingStatus.ACTIVE,
        amount=bio_amount,
        price=premium_price,
        expires_at=_now_utc() + LISTING_DURATION,
    )
    session.add(listing)
    await session.flush()

    return True, (
        f"✅ Запрос #{listing.id} создан!\n"
        f"Хочешь купить: <b>{bio_amount:,}</b> 🧫 bio\n"
        f"Готов заплатить: <b>{premium_price:,}</b> 💎 premium\n"
        f"Активно до: {listing.expires_at.strftime('%d.%m %H:%M')} UTC"
    )


# ---------------------------------------------------------------------------
# Fulfill a listing
# ---------------------------------------------------------------------------


async def fulfill_listing(
    session: AsyncSession,
    fulfiller_id: int,
    listing_id: int,
) -> tuple[bool, str]:
    """
    Execute a SELL or BUY trade.

    SELL: fulfiller pays premium_price → receives bio_amount.
    BUY:  fulfiller provides bio_amount → receives premium_price.

    Returns (success, message).
    """
    listing = await _get_listing(session, listing_id, lock=True)

    if listing is None:
        return False, "❌ Предложение не найдено."
    if listing.status != ListingStatus.ACTIVE:
        return False, "❌ Предложение уже не активно."
    if listing.listing_type == ListingType.HIT_CONTRACT:
        return False, "❌ Это контракт, не торговое предложение."
    if listing.seller_id == fulfiller_id:
        return False, "❌ Нельзя выполнить собственное предложение."
    if listing.expires_at < _now_utc():
        listing.status = ListingStatus.EXPIRED
        await session.flush()
        return False, "❌ Предложение истекло."

    fulfiller = await _get_user(session, fulfiller_id, lock=True)
    if fulfiller is None:
        return False, "❌ Игрок не найден."

    seller = await _get_user(session, listing.seller_id, lock=True)
    if seller is None:
        return False, "❌ Продавец не найден."

    now = _now_utc()

    if listing.listing_type == ListingType.SELL_COINS:
        # Fulfiller pays premium, receives bio
        if fulfiller.premium_coins < listing.price:
            return False, (
                f"❌ Недостаточно 💎 PremiumCoins.\n"
                f"Нужно: <b>{listing.price:,}</b> 💎\n"
                f"Твой баланс: <b>{fulfiller.premium_coins:,}</b>"
            )
        fulfiller.premium_coins -= listing.price
        fulfiller.bio_coins += listing.amount
        seller.premium_coins += listing.price

        session.add(ResourceTransaction(
            user_id=fulfiller_id,
            amount=-listing.price,
            currency=Currency.PREMIUM_COINS,
            reason=TransactionReason.DONATION,
        ))
        session.add(ResourceTransaction(
            user_id=fulfiller_id,
            amount=listing.amount,
            currency=Currency.BIO_COINS,
            reason=TransactionReason.DONATION,
        ))
        session.add(ResourceTransaction(
            user_id=listing.seller_id,
            amount=listing.price,
            currency=Currency.PREMIUM_COINS,
            reason=TransactionReason.DONATION,
        ))

        msg = (
            f"✅ Сделка #{listing_id} выполнена!\n"
            f"Ты заплатил: <b>{listing.price:,}</b> 💎 premium\n"
            f"Ты получил: <b>{listing.amount:,}</b> 🧫 bio"
        )

    else:  # BUY_COINS — fulfiller provides bio, receives premium
        if fulfiller.bio_coins < listing.amount:
            return False, (
                f"❌ Недостаточно 🧫 BioCoins.\n"
                f"Нужно: <b>{listing.amount:,}</b> 🧫\n"
                f"Твой баланс: <b>{fulfiller.bio_coins:,}</b>"
            )
        fulfiller.bio_coins -= listing.amount
        fulfiller.premium_coins += listing.price
        seller.bio_coins += listing.amount  # buyer (creator of BUY listing) receives bio

        session.add(ResourceTransaction(
            user_id=fulfiller_id,
            amount=-listing.amount,
            currency=Currency.BIO_COINS,
            reason=TransactionReason.DONATION,
        ))
        session.add(ResourceTransaction(
            user_id=fulfiller_id,
            amount=listing.price,
            currency=Currency.PREMIUM_COINS,
            reason=TransactionReason.DONATION,
        ))
        session.add(ResourceTransaction(
            user_id=listing.seller_id,
            amount=listing.amount,
            currency=Currency.BIO_COINS,
            reason=TransactionReason.DONATION,
        ))

        msg = (
            f"✅ Сделка #{listing_id} выполнена!\n"
            f"Ты продал: <b>{listing.amount:,}</b> 🧫 bio\n"
            f"Ты получил: <b>{listing.price:,}</b> 💎 premium"
        )

    listing.status = ListingStatus.COMPLETED
    listing.buyer_id = fulfiller_id
    listing.completed_at = now
    await session.flush()

    return True, msg


# ---------------------------------------------------------------------------
# Cancel a listing
# ---------------------------------------------------------------------------


async def cancel_listing(
    session: AsyncSession,
    user_id: int,
    listing_id: int,
) -> tuple[bool, str]:
    """
    Cancel an active listing and refund the frozen funds.

    Only the listing creator can cancel.

    Returns (success, message).
    """
    listing = await _get_listing(session, listing_id, lock=True)
    if listing is None:
        return False, "❌ Предложение не найдено."
    if listing.seller_id != user_id:
        return False, "❌ Ты можешь отменить только своё предложение."
    if listing.status != ListingStatus.ACTIVE:
        return False, "❌ Предложение уже не активно."

    owner = await _get_user(session, user_id, lock=True)
    if owner is None:
        return False, "❌ Игрок не найден."

    # Refund depending on listing type
    if listing.listing_type == ListingType.SELL_COINS:
        commission = max(1, round(listing.amount * SELL_COMMISSION_PCT))
        refund = listing.amount + commission
        owner.bio_coins += refund
        session.add(ResourceTransaction(
            user_id=user_id,
            amount=refund,
            currency=Currency.BIO_COINS,
            reason=TransactionReason.DONATION,
        ))
        refund_text = f"<b>{refund:,}</b> 🧫 bio (включая комиссию {commission:,})"

    elif listing.listing_type == ListingType.BUY_COINS:
        owner.premium_coins += listing.price
        session.add(ResourceTransaction(
            user_id=user_id,
            amount=listing.price,
            currency=Currency.PREMIUM_COINS,
            reason=TransactionReason.DONATION,
        ))
        refund_text = f"<b>{listing.price:,}</b> 💎 premium"

    else:  # HIT_CONTRACT
        owner.bio_coins += listing.reward
        session.add(ResourceTransaction(
            user_id=user_id,
            amount=listing.reward,
            currency=Currency.BIO_COINS,
            reason=TransactionReason.DONATION,
        ))
        refund_text = f"<b>{listing.reward:,}</b> 🧫 bio (награда)"

    listing.status = ListingStatus.CANCELLED
    await session.flush()

    return True, (
        f"✅ Предложение #{listing_id} отменено.\n"
        f"Возвращено: {refund_text}"
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
        f"💰 Награда: <b>{reward_bio:,}</b> 🧫 bio\n"
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
            f"💰 Награда: <b>{listing.reward:,}</b> 🧫 bio зачислена."
        )

    # Mark hitman and wait
    listing.buyer_id = hitman_id
    await session.flush()

    return True, (
        f"✅ Контракт #{listing_id} принят!\n"
        f"🎯 Цель: @{listing.target_username}\n"
        f"💰 Награда: <b>{listing.reward:,}</b> 🧫 bio\n\n"
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
        owner = await _get_user(session, listing.seller_id, lock=True)
        if owner is None:
            listing.status = ListingStatus.EXPIRED
            continue

        if listing.listing_type == ListingType.SELL_COINS:
            commission = max(1, round(listing.amount * SELL_COMMISSION_PCT))
            refund = listing.amount + commission
            owner.bio_coins += refund
            session.add(ResourceTransaction(
                user_id=listing.seller_id,
                amount=refund,
                currency=Currency.BIO_COINS,
                reason=TransactionReason.DONATION,
            ))
        elif listing.listing_type == ListingType.BUY_COINS:
            owner.premium_coins += listing.price
            session.add(ResourceTransaction(
                user_id=listing.seller_id,
                amount=listing.price,
                currency=Currency.PREMIUM_COINS,
                reason=TransactionReason.DONATION,
            ))
        elif listing.listing_type == ListingType.HIT_CONTRACT:
            owner.bio_coins += listing.reward
            session.add(ResourceTransaction(
                user_id=listing.seller_id,
                amount=listing.reward,
                currency=Currency.BIO_COINS,
                reason=TransactionReason.DONATION,
            ))

        listing.status = ListingStatus.EXPIRED

    await session.flush()
    return len(expired)
