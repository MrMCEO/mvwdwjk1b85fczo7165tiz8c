"""
Create a Telegraph page with the BioWars game guide and print the resulting URL.

Usage:
    python scripts/create_telegraph.py

The script honours HTTP_PROXY / HTTPS_PROXY environment variables automatically
because urllib picks them up via urllib.request.getproxies().
"""

import json
import os
import urllib.request


# ---------------------------------------------------------------------------
# Telegraph content — full game guide
# ---------------------------------------------------------------------------

CONTENT = [
    # ── Intro ──────────────────────────────────────────────────────────────
    {"tag": "p", "children": [
        "BioWars — PvP-игра в Telegram, где вы развиваете собственный вирус "
        "для атаки других игроков и укрепляете иммунитет для защиты. "
        "Заражайте соперников, прокачивайте ветки улучшений и поднимайтесь в рейтинге!"
    ]},

    # ── Вирус ──────────────────────────────────────────────────────────────
    {"tag": "h3", "children": ["🦠 Вирус (атака)"]},
    {"tag": "p", "children": [
        "Ваш вирус — главное оружие в игре. Базовые характеристики вируса:"
    ]},
    {"tag": "ul", "children": [
        {"tag": "li", "children": ["Сила атаки — базовый урон при попытке заражения."]},
        {"tag": "li", "children": [
            "Заразность (spread_rate) — множитель шанса успешного заражения."
        ]},
        {"tag": "li", "children": [
            "Очки мутации — специальные очки для особых улучшений (в будущем)."
        ]},
    ]},

    {"tag": "p", "children": [{"tag": "b", "children": ["Ветки прокачки вируса:"]}]},
    {"tag": "ul", "children": [
        {"tag": "li", "children": [
            {"tag": "b", "children": ["☠️ Летальность"]},
            " — увеличивает урон заражённым. Чем выше уровень, тем больше bio_coins "
            "вы забираете у жертвы каждый тик (1 час). Идеальна для агрессивной игры "
            "— максимизирует пассивный доход от заражений."
        ]},
        {"tag": "li", "children": [
            {"tag": "b", "children": ["🦠 Заразность"]},
            " — увеличивает шанс успешного заражения. Влияет на формулу: "
            "attack_score = сила_атаки × заразность × (1 + бонус_заразности). "
            "Чем выше уровень, тем сложнее противнику отбиться."
        ]},
        {"tag": "li", "children": [
            {"tag": "b", "children": ["👁 Скрытность"]},
            " — уменьшает шанс того, что жертва узнает, кто её атаковал. "
            "Противодействует ветке «Детекция» иммунитета."
        ]},
    ]},

    # ── Иммунитет ──────────────────────────────────────────────────────────
    {"tag": "h3", "children": ["🛡 Иммунитет (защита)"]},
    {"tag": "p", "children": [
        "Иммунитет защищает вас от вирусов других игроков. "
        "Базовые характеристики иммунитета:"
    ]},
    {"tag": "ul", "children": [
        {"tag": "li", "children": [
            "Сопротивляемость (resistance) — базовая защита от заражения."
        ]},
        {"tag": "li", "children": [
            "Детекция — шанс обнаружить атакующего игрока."
        ]},
        {"tag": "li", "children": [
            "Скорость регенерации — шанс автоматически вылечиться каждый тик."
        ]},
    ]},

    {"tag": "p", "children": [{"tag": "b", "children": ["Ветки прокачки иммунитета:"]}]},
    {"tag": "ul", "children": [
        {"tag": "li", "children": [
            {"tag": "b", "children": ["🛡 Барьер"]},
            " — снижает шанс заражения. "
            "defense_score = сопротивляемость × (1 + бонус_барьера). "
            "Лучший выбор для пассивной обороны."
        ]},
        {"tag": "li", "children": [
            {"tag": "b", "children": ["🔍 Детекция"]},
            " — позволяет видеть, кто вас атаковал. "
            "Без этой ветки все атаки анонимны! "
            "Противодействует ветке «Скрытность» вируса."
        ]},
        {"tag": "li", "children": [
            {"tag": "b", "children": ["💊 Регенерация"]},
            " — увеличивает шанс автоизлечения каждый тик. "
            "Базовый шанс 5%, каждый уровень добавляет к нему. "
            "Также уменьшает damage_per_tick от активных заражений."
        ]},
    ]},

    # ── Механика атаки ─────────────────────────────────────────────────────
    {"tag": "h3", "children": ["⚔️ Как работает атака"]},
    {"tag": "ol", "children": [
        {"tag": "li", "children": ["Нажмите «Атаковать» в главном меню."]},
        {"tag": "li", "children": ["Введите @username цели."]},
        {"tag": "li", "children": [
            "Система рассчитает шанс заражения: "
            "chance = attack_score / (attack_score + defense_score)."
        ]},
        {"tag": "li", "children": [
            "Если успешно — создаётся заражение, "
            "жертва начинает терять bio_coins каждый тик."
        ]},
        {"tag": "li", "children": [
            "Кулдаун: 30 минут между атаками."
        ]},
    ]},

    # ── Тики ───────────────────────────────────────────────────────────────
    {"tag": "h3", "children": ["🔄 Тики и пассивный урон"]},
    {"tag": "p", "children": [
        "Каждый час система обрабатывает все активные заражения:"
    ]},
    {"tag": "ul", "children": [
        {"tag": "li", "children": [
            "Жертва теряет bio_coins "
            "(зависит от Летальности атакующего минус Регенерация жертвы)."
        ]},
        {"tag": "li", "children": [
            "Атакующий получает 70% от украденного."
        ]},
        {"tag": "li", "children": [
            "Есть шанс автоизлечения (5% + бонус Регенерации)."
        ]},
        {"tag": "li", "children": [
            "Баланс жертвы не уходит в минус."
        ]},
    ]},

    # ── Излечение ──────────────────────────────────────────────────────────
    {"tag": "h3", "children": ["💊 Излечение"]},
    {"tag": "ul", "children": [
        {"tag": "li", "children": [
            {"tag": "b", "children": ["Автоматическое:"]},
            " каждый тик есть шанс вылечиться (зависит от ветки Регенерации)."
        ]},
        {"tag": "li", "children": [
            {"tag": "b", "children": ["Ручное:"]},
            " в разделе «Мои заражения» можно вылечиться за bio_coins "
            "(стоимость = damage_per_tick × 10)."
        ]},
    ]},

    # ── Ресурсы ────────────────────────────────────────────────────────────
    {"tag": "h3", "children": ["💰 Ресурсы"]},
    {"tag": "ul", "children": [
        {"tag": "li", "children": [
            {"tag": "b", "children": ["bio_coins"]},
            " — основная валюта. Добывается и тратится на прокачку."
        ]},
        {"tag": "li", "children": [
            {"tag": "b", "children": ["premium_coins"]},
            " — донат-валюта. Конвертируется в bio_coins (1:10)."
        ]},
    ]},

    {"tag": "p", "children": [{"tag": "b", "children": ["Способы получения bio_coins:"]}]},
    {"tag": "ul", "children": [
        {"tag": "li", "children": [
            {"tag": "b", "children": ["Добыча:"]},
            " раз в час, 10–50 bio_coins случайно."
        ]},
        {"tag": "li", "children": [
            {"tag": "b", "children": ["Ежедневный бонус:"]},
            " 100 bio_coins + стрик-бонус "
            "(+10% за каждый последовательный день, макс +70% на 7-й день)."
        ]},
        {"tag": "li", "children": [
            {"tag": "b", "children": ["Пассивный доход:"]},
            " 70% от того, что забирает ваш вирус у заражённых."
        ]},
        {"tag": "li", "children": [
            {"tag": "b", "children": ["Конвертация premium_coins:"]},
            " обменяйте донат-монеты в разделе «Магазин»."
        ]},
    ]},

    # ── Стоимость прокачки ─────────────────────────────────────────────────
    {"tag": "h3", "children": ["📊 Стоимость прокачки"]},
    {"tag": "p", "children": [
        "Формула: base_cost × multiplier^current_level. "
        "Например, при base_cost = 100 и multiplier = 1.5:"
    ]},
    {"tag": "ul", "children": [
        {"tag": "li", "children": ["Уровень 0 → 1: 100 bio"]},
        {"tag": "li", "children": ["Уровень 1 → 2: 150 bio"]},
        {"tag": "li", "children": ["Уровень 2 → 3: 225 bio"]},
        {"tag": "li", "children": ["Уровень 5 → 6: 759 bio"]},
        {"tag": "li", "children": ["Уровень 10 → 11: 5 766 bio"]},
    ]},
    {"tag": "p", "children": ["Максимальный уровень каждой ветки: 50."]},

    # ── Рейтинги ───────────────────────────────────────────────────────────
    {"tag": "h3", "children": ["🏆 Рейтинги"]},
    {"tag": "ul", "children": [
        {"tag": "li", "children": ["По заражениям — кто заразил больше всего активных игроков."]},
        {"tag": "li", "children": ["По уровню вируса."]},
        {"tag": "li", "children": ["По уровню иммунитета."]},
        {"tag": "li", "children": ["По богатству (bio_coins)."]},
    ]},

    # ── Советы новичкам ────────────────────────────────────────────────────
    {"tag": "h3", "children": ["💡 Советы новичкам"]},
    {"tag": "ol", "children": [
        {"tag": "li", "children": [
            "Начните с добычи ресурсов — копите на первые прокачки."
        ]},
        {"tag": "li", "children": [
            "Не забывайте ежедневный бонус — стрик даёт +70% на 7-й день."
        ]},
        {"tag": "li", "children": [
            "Баланс атака/защита важен: чистый атакер уязвим, "
            "чистый дефендер не зарабатывает."
        ]},
        {"tag": "li", "children": [
            "Заразность — лучшая первая ветка: увеличивает шанс ЛЮБОЙ атаки."
        ]},
        {"tag": "li", "children": [
            "Барьер — лучшая защитная ветка для начала."
        ]},
        {"tag": "li", "children": [
            "Следите за рейтингами — топовые игроки часто становятся целями."
        ]},
    ]},
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_opener() -> urllib.request.OpenerDirector:
    """Return an opener that uses HTTP_PROXY / HTTPS_PROXY if set."""
    proxy_url = (
        os.environ.get("HTTP_PROXY")
        or os.environ.get("http_proxy")
        or os.environ.get("HTTPS_PROXY")
        or os.environ.get("https_proxy")
    )
    if proxy_url:
        handler = urllib.request.ProxyHandler({
            "http": proxy_url,
            "https": proxy_url,
        })
        return urllib.request.build_opener(handler)
    return urllib.request.build_opener()


def _post(opener: urllib.request.OpenerDirector, url: str, payload: dict) -> dict:
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"}
    )
    with opener.open(req, timeout=30) as resp:
        return json.loads(resp.read())


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    opener = _make_opener()

    # 1. Create account
    acc = _post(opener, "https://api.telegra.ph/createAccount", {
        "short_name": "BioWars",
        "author_name": "BioWars Bot",
    })
    if not acc.get("ok"):
        raise RuntimeError(f"createAccount failed: {acc}")
    token = acc["result"]["access_token"]
    print(f"[+] Account created, token: {token[:8]}...")

    # 2. Create page
    page = _post(opener, "https://api.telegra.ph/createPage", {
        "access_token": token,
        "title": "BioWars — Полный гайд",
        "author_name": "BioWars Bot",
        "content": CONTENT,
        "return_content": False,
    })
    if not page.get("ok"):
        raise RuntimeError(f"createPage failed: {page}")

    url = page["result"]["url"]
    print(f"[+] Page created successfully!")
    print(f"URL: {url}")


if __name__ == "__main__":
    main()
