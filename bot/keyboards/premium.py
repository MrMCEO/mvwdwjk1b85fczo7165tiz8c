"""Premium / status system keyboards."""

from aiogram.enums import ButtonStyle
from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.services.premium import STATUS_CONFIG, UserStatus

# Statuses that can be purchased
_BUYABLE = [
    UserStatus.BIO_PLUS,
    UserStatus.BIO_PRO,
    UserStatus.BIO_ELITE,
]


def status_menu_kb(
    current_status: UserStatus,
    statuses: list[UserStatus] | None = None,
) -> InlineKeyboardMarkup:
    """
    Main status-selection keyboard.

    Shows one button per purchasable status.
    The currently active status is suffixed with '✅ АКТИВЕН'.
    BIO_LEGEND row is informational only (no callback).
    Also includes:
      - '✏️ Установить префикс' if current status has prefix_length > 0
      - '◀️ Назад' back to main menu
    """
    builder = InlineKeyboardBuilder()
    show = statuses if statuses is not None else _BUYABLE

    for s in show:
        cfg = STATUS_CONFIG[s]
        emoji = cfg["emoji"]
        name = cfg["name"]
        price = cfg["price"]
        if s == current_status:
            label = f"{emoji} {name} — {price} 💎/мес ✅ АКТИВЕН"
            builder.button(text=label, callback_data=f"status_buy:{s.value}", style=ButtonStyle.SUCCESS)
        else:
            label = f"{emoji} {name} — {price} 💎/мес"
            builder.button(text=label, callback_data=f"status_buy:{s.value}", style=ButtonStyle.PRIMARY)

    # Legend — informational, shows a popup on tap
    legend_cfg = STATUS_CONFIG[UserStatus.BIO_LEGEND]
    if current_status == UserStatus.BIO_LEGEND:
        legend_label = f"{legend_cfg['emoji']} {legend_cfg['name']} — через рефералов (50+) 👑 АКТИВЕН"
        builder.button(text=legend_label, callback_data="status_legend_info", style=ButtonStyle.SUCCESS)
    else:
        legend_label = f"{legend_cfg['emoji']} {legend_cfg['name']} — через рефералов (50+)"
        builder.button(text=legend_label, callback_data="status_legend_info")

    # Prefix button only for users who can set one
    if STATUS_CONFIG[current_status]["prefix_length"] > 0:
        builder.button(text="✏️ Установить префикс", callback_data="premium_set_prefix", style=ButtonStyle.PRIMARY)

    builder.button(text="◀️ Назад", callback_data="main_menu")
    builder.adjust(1)
    return builder.as_markup()


def status_confirm_kb(target: UserStatus) -> InlineKeyboardMarkup:
    """Confirmation keyboard for status purchase."""
    cfg = STATUS_CONFIG[target]
    builder = InlineKeyboardBuilder()
    builder.button(
        text=f"✅ Купить {cfg['emoji']} {cfg['name']} за {cfg['price']} 💎",
        callback_data=f"status_confirm:{target.value}",
        style=ButtonStyle.SUCCESS,
    )
    builder.button(text="❌ Отмена", callback_data="premium_menu", style=ButtonStyle.DANGER)
    builder.adjust(1)
    return builder.as_markup()


# ---------------------------------------------------------------------------
# Legacy wrappers — kept so imports in handlers that used the old API still work
# ---------------------------------------------------------------------------


def premium_menu_kb(is_active: bool) -> InlineKeyboardMarkup:
    """
    Backward-compatible keyboard.

    Delegates to status_menu_kb with FREE or BIO_PRO as current status.
    """
    status = UserStatus.BIO_PRO if is_active else UserStatus.FREE
    return status_menu_kb(current_status=status)


def premium_confirm_kb() -> InlineKeyboardMarkup:
    """Backward-compatible purchase confirmation for BIO_PRO."""
    return status_confirm_kb(UserStatus.BIO_PRO)
