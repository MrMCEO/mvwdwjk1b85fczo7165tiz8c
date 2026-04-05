import random

# Пулы стикеров по контексту — file_id из паков Fromg, DinDino, Scream
# Индексы соответствуют позициям в паках (0-based):
#   Fromg:  [0]😂 [1]😘 [2]👍 [3]😱 [4]👋 [5]😭 [6]🤮 [7]👌 [8]😞 [9]🤔
#           [10]🤝 [11]😡 [12]📸 [13]😵 [14]🤨 [15]😮‍💨 [16]😬 [17]🫡 [18]🍿 [19]😉
#           [20]🍺 [21]🤩 [22]😽 [23]😴 [24]📈 [25]🏃‍♂️ [26]😤 [27]☕️ [28]🧐 [29]🥳
#           [30]💃 [31]💡 [32]🛀 [33]😍 [34]🤡 [35]👋 [36]😵 [37]🤔
#   DinDino:[0]😂 [1]😏 [2]👍 [3]😱 [4]👋 [5]😟 [6]🙂 [7]🤔 [8]😃 [9]😴
#           [10]😐 [11]😍 [12]🥺 [13]😋 [14]👌 [15]😑 [16]🥴 [17]💸 [18]😈 [19]😭
#           [20]😘 [21]🥳 [22]🤒
#   Scream: [0]😂 [1]😉 [2]👍 [3]😨 [4]👻 [5]👻 [6]😊 [7]🎃 [8]🤫 [9]😭
#           [10]🎁 [11]🍑 [12]🎉 [13]💔 [14]😏 [15]🤔 [16]👂 [17]⏳ [18]😴 [19]😠
#           [20]🥺 [21]🚲 [22]😍 [23]🚶‍♀️ [24]🌃 [25]👻 [26]🫀 [27]💪

STICKER_POOLS: dict[str, list[str]] = {
    # 👋 — Fromg[4], Fromg[35], DinDino[4]
    "greeting": [
        "CAACAgIAAxkBAAICQGnSHxgtqCba-ZVkDHA27YPw-LO8AALgLwACVZ3YSyF8m4QxrOqnOwQ",  # Fromg[4] 👋
        "CAACAgIAAxkBAAICPmnSHv-o_zKEkzE9er2S5NEWOYhuAAJFAwACtXHaBpOIEByJ3A0bOwQ",  # DinDino[4] 👋
    ],
    # 😃 DinDino[8], 🥳 Fromg[29]/DinDino[21], 🎉 Scream[12], 👍 Fromg[2]/DinDino[2]/Scream[2]
    "success": [
        "CAACAgIAAxkBAAICJGnSFXObjVXfT-54IJ6UoM_qCHBBAAJHAwACtXHaBjV7c9kAAYsdpDsE",  # DinDino[8] 😃
    ],
    # 😭 DinDino[19]/Fromg[5]/Scream[9], 😟 DinDino[5], 😞 Fromg[8], 💔 Scream[13]
    "sad": [
        "CAACAgIAAxkBAAICJWnSFXnCmPAcNMIQiUMaJWRUsEZeAAJXAwACtXHaBrZ7t_uAheuSOwQ",  # DinDino[19] 😭
        "CAACAgIAAxkBAAICP2nSHxHOxNCY4S-g36Fg5iTDT60VAAKNMgAC61GoSapb3U8-ZBMWOwQ",  # Fromg[5] 😭
    ],
    # 😈 DinDino[18], 😡 Fromg[11], 😤 Fromg[26], 😠 Scream[19]
    "attack": [
        "CAACAgIAAxkBAAICPGnSHvU884qJQMavQU6BMDn2kEGDAAJWAwACtXHaBjr6z5C3CbgEOwQ",  # DinDino[18] 😈
    ],
    # 🤔 Fromg[9], Fromg[37], DinDino[7], Scream[15]
    # TODO: добавить file_id когда будут получены из пака
    "thinking": [],
    # 💸 DinDino[17], 📈 Fromg[24]
    # TODO: добавить Fromg[24] 📈 когда будет получен из пака
    "money": [
        "CAACAgIAAxkBAAICO2nSHuoRuGulKElI2KiemtwZD_sAA1UDAAK1cdoGEyKX4-yJCQc7BA",  # DinDino[17] 💸
    ],
    # 🎁 Scream[10]
    "gift": [
        "CAACAgIAAxkBAAICQWnSHywvq5vtwEUf4h8Ww8J8GVyhAAJUEwACtK3YSntkuve3cfvfOwQ",  # Scream[10] 🎁
    ],
    # 🤝 Fromg[10]
    "handshake": [
        "CAACAgIAAxkBAAICImnSFWs0HshuDUjPIFPPMBgmvLdvAAJONQACszABSr3eWnrZgvQGOwQ",  # Fromg[10] 🤝
    ],
    # 🙂 DinDino[6]
    "profile": [
        "CAACAgIAAxkBAAICI2nSFXGqBONFURx9kJvCEW_O7nTcAAJKAwACtXHaBsJ-BvqbSB7EOwQ",  # DinDino[6] 🙂
    ],
    # 😱 Fromg[3]/DinDino[3], 😨 Scream[3], 😵 Fromg[13]/Fromg[36]
    # TODO: добавить file_id когда будут получены из паков
    "shock": [],
    # 😴 Fromg[23], DinDino[9], Scream[18]
    # TODO: добавить file_id когда будут получены из паков
    "sleep": [],
    # 🧐 Fromg[28], 💡 Fromg[31]
    # TODO: добавить file_id когда будут получены из пака
    "science": [],
    # 💪 Scream[27]
    # TODO: добавить file_id когда будет получен из пака
    "strong": [],
    # 🥳 Fromg[29]/DinDino[21], 🎉 Scream[12], 💃 Fromg[30], 🤩 Fromg[21]
    # TODO: добавить file_id когда будут получены из паков
    "party": [],
    # 😍 Fromg[33]/DinDino[11]/Scream[22], 😘 Fromg[1]/DinDino[20], 😽 Fromg[22]
    # TODO: добавить file_id когда будут получены из паков
    "love": [],
    # 😂 Fromg[0], DinDino[0], Scream[0]
    # TODO: добавить file_id когда будут получены из паков
    "laugh": [],
}


# Fallback-маппинг: если пул пустой — использовать другой контекст
FALLBACK: dict[str, str] = {
    "thinking": "profile",
    "shock": "attack",
    "sleep": "profile",
    "science": "thinking",
    "strong": "attack",
    "party": "success",
    "love": "success",
    "laugh": "success",
}


def get_sticker(context: str) -> str:
    """Вернуть рандомный file_id стикера по контексту.

    Если пул пуст — использовать fallback-контекст.
    Если и он пуст или контекст не найден — вернуть пустую строку.
    """
    pool = STICKER_POOLS.get(context, [])
    if not pool:
        fallback_ctx = FALLBACK.get(context, "")
        pool = STICKER_POOLS.get(fallback_ctx, [])
    if not pool:
        return ""
    return random.choice(pool)
