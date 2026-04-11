# BioWars — Полный справочник формул

**Обновлено:** 2026-04-11
**Ветка:** dev

Этот файл содержит все численные формулы, константы и конфигурации игры. Держится в синхронизации с кодом — при изменении баланса обновлять его.

---

## ⚔️ БОЙ И PVP

**Файл:** `bot/services/combat.py`

### Константы
- `BASE_DAMAGE_PER_TICK = 5.0` — базовый урон за тик
- `CURE_COST_MULTIPLIER = 8.0` — множитель стоимости ручного лечения
- `BIO_BOMB chance = 0.97` — почти гарантированное попадание с предметом

### Формула шанса атаки (база)
```python
base_chance = 0.35 + 0.55 * (1 - math.exp(-virus_level * 0.08))
chance = base_chance - barrier_level * 0.025
chance = max(0.05, min(0.90, chance))
```
**Диапазон:** 5%–90%. `virus_level` = сумма всех веток вируса.

### Модификаторы шанса (применяются после базы)
```python
chance = min(0.90, chance * 1.5)          # PLAGUE_SEASON ивент
chance += atk_mods["chance_bonus"]         # мутации
chance -= def_mods["chance_penalty"] * def_alliance_bonus
chance += atk_alliance_bonus * 0.05        # moral бонус альянса
chance -= 0.10                             # если у жертвы SHIELD_BOOST
chance = max(0.05, min(0.90, chance))      # финальный кламп
```

### Формула награды за атаку
```python
victim_mining = max(50, 120 - 4 * (immunity_level + victim_virus_total))
base_reward = victim_mining * 3            # ≈ 3 часа дохода жертвы

level_diff = virus_level - immunity_level
if level_diff > 0:                         # атака ВНИЗ — штраф
    loot_mult = max(0.05, 1.0 - level_diff * 0.04)
else:                                      # атака ВВЕРХ — бонус
    loot_mult = min(1.5, 1.0 + abs(level_diff) * 0.02)

reward = max(10, int(base_reward * loot_mult))
```

### Минимальный баланс жертвы (кап долга)
```python
victim_min_balance = -(victim_total_level * 200)
victim.bio_coins = max(victim_min_balance, victim.bio_coins - reward)
```

### Damage per tick (LETHALITY)
```python
damage_per_tick = max(1.0, BASE_DAMAGE_PER_TICK + lethality_effect)
# С VIRUS_ENHANCER предметом:
damage_per_tick *= 2.0
```
`lethality_effect = lethality_level * 2.0`

### Длительность инфекции (CONTAGION)
```python
duration_ticks = 6 + contagion_level * 2
```

### Стоимость лечения
```python
cost = math.ceil(damage_per_tick * CURE_COST_MULTIPLIER * cost_multiplier)
# cost_multiplier — из calc_cost_multiplier() в laboratory.py
```

### Защита новичка
- 24 часа после регистрации — атаки запрещены

---

## ⏰ TICK (ИНФЕКЦИОННЫЙ ДВИЖОК)

**Файл:** `bot/services/tick.py`

### Константы
- `TICK_INTERVAL_MINUTES = 60` — тик раз в час
- `ATTACKER_SHARE = 0.50` — атакующий получает 50% дрейна
- `BASE_CURE_CHANCE = 0.05` — 5% базовый шанс авто-лечения
- `_ALLIANCE_REGEN_EFFECT_PER_LEVEL = 0.01`

### Снижение дрейна (BARRIER)
```python
barrier_effect = barrier_level * 1.5 * (1 - barrier_level / 120)
actual_drain = max(math.floor(base_drain * 0.30), base_drain - barrier_effect)
actual_drain = max(1, int(actual_drain))   # минимум 1 монета
```
**Barrier не может снизить урон больше чем на 70%.**

### Шанс авто-лечения за тик
```python
cure_chance = BASE_CURE_CHANCE + recovery_speed + regen_bonus + alliance_regen
cure_chance = max(0.0, min(0.60, cure_chance))   # кап 60%
```
У новичка: 5% + 3% = 8% → средняя длительность ~12 тиков.

---

## 💰 ЭКОНОМИКА — ДОБЫЧА И ДНЕВНОЙ БОНУС

**Файл:** `bot/services/resource.py`

### Константы
- `DAILY_COOLDOWN = timedelta(hours=24)`
- `DAILY_STREAK_BONUS = 0.04` — +4% за каждый день стрика
- `DAILY_STREAK_MAX = 21` — кап стрика 21 день (+80%)

### Награда за добычу
```python
base_reward = max(50, 120 - 4 * total_level)   # total_level = все ветки
amount = int(base_reward * premium_multiplier * event_mult * mutation_mult
             * (1.0 + alliance_mining_bonus))
# Если bio_coins < 0 (в долге): amount *= 1.5
```

### Дневной бонус
```python
streak_multiplier = 1.0 + DAILY_STREAK_BONUS * (new_streak - 1)
daily_base = 600 + total_level * 15
amount = int(daily_base * streak_multiplier * premium_multiplier * event_mult)
```

---

## 📈 ЭКОНОМИКА — УЛУЧШЕНИЯ

**Файл:** `bot/services/upgrade.py`

### Формула стоимости
```python
def calc_upgrade_cost(base_cost, multiplier, current_level):
    L = current_level + 1
    return 300 * L + 8 * L * L     # квадратичная
```
Стоимость покупки уровня N = `300N + 8N²`. Lvl 1 = 308, Lvl 10 = 3800, Lvl 20 = 9200, Lvl 50 = 35000.

### Формула эффекта
```python
effect_value = cfg["base_effect"] * new_level   # линейная
```

### UPGRADE_CONFIG

| Дерево | Ветка | base_cost | multiplier | base_effect | Что делает |
|--------|-------|-----------|------------|-------------|-----------|
| virus | LETHALITY | 80 | 1.25 | 2.0 | +2 damage_per_tick/lvl |
| virus | CONTAGION | 80 | 1.25 | 0.08 | +0.08 длительности инфекции |
| virus | STEALTH | 90 | 1.25 | 0.05 | -0.05 эффективной детекции |
| immunity | BARRIER | 80 | 1.25 | 3.0 | +3 снижение дрейна/lvl |
| immunity | DETECTION | 80 | 1.25 | 0.05 | +0.05 detection_power |
| immunity | REGENERATION | 90 | 1.25 | 0.02 | +0.02 шанс авто-лечения |

⚠️ `base_cost` и `multiplier` хранятся в конфиге, но **фактическая формула квадратичная** (см. выше).

---

## 💸 ЭКОНОМИКА — ПЕРЕДАЧИ, БИРЖА, ДОНАТ

### Donation
**Файл:** `bot/services/donation.py`
- `EXCHANGE_RATE = 15` — 1 premium = 15 bio_coins

### Transfer
**Файл:** `bot/services/transfer.py`
- `TRANSFER_COMMISSION = 0.05` — 5% комиссия
- `DEFAULT_DAILY_LIMIT = 1500` — дневной лимит FREE
- Получатель получает: `amount - ceil(amount * 0.05)`

### Market
**Файл:** `bot/services/market.py`
- `LISTING_DURATION = timedelta(hours=24)` — лоты живут 24 часа
- `SELL_COMMISSION_PCT = 0.025` — 2.5% комиссия с покупателя (продавец получает полную цену)

---

## 🔬 ЛАБОРАТОРИЯ И ПРЕДМЕТЫ

**Файл:** `bot/services/laboratory.py`

### Формула множителя стоимости
```python
def calc_cost_multiplier(total_level, balance):
    level_factor = total_level * 0.2
    balance_factor = min(10.0, max(0, balance) / 10000)
    return max(1.0, min(15.0, 1.0 + level_factor + balance_factor))
```
**Диапазон:** 1.0× – 15.0×. Новичок = ×1, ветеран (lvl30, 100k) = ×15.

### Стоимость предмета
```python
cost = int(ITEM_CONFIG[item_type]["cost"] * calc_cost_multiplier(total_level, balance))
```

### ITEM_CONFIG (базовые цены)

| Предмет | Base Cost | Эффект |
|---------|-----------|--------|
| VACCINE | 200 | Моментально лечит 1 инфекцию |
| SHIELD_BOOST | 300 | +50% защиты на 2 часа |
| ANTIDOTE | 800 | Лечит ВСЕ инфекции |
| BIO_BOMB | 500 | 97% гарантия попадания |
| VIRUS_ENHANCER | 400 | ×2 урон на 1 атаку |
| STEALTH_CLOAK | 350 | Полный стелс на 1 атаку |
| RESOURCE_BOOSTER | 250 | ×2 добыча на 3 часа |
| LUCKY_CHARM | 150 | ×3 дневной бонус (1 раз) |
| SPY_DRONE | 300 | Полная инфа о цели |
| MUTATION_SERUM | 600 | Гарантированная рандомная мутация |

---

## 🧬 МУТАЦИИ

**Файл:** `bot/services/mutation.py`

### Константы
- `MUTATION_ROLL_CHANCE = 0.15` — 15% шанс после атаки (×3 во время MUTATION_STORM)

### Весы редкости
```python
RARITY_WEIGHTS = {
    COMMON: 60,
    UNCOMMON: 25,
    RARE: 12,
    LEGENDARY: 3,
}
```

### MUTATION_CONFIG

| Тип | Редкость | Эффект | Длительность | Дебафф |
|-----|---------|--------|--------------|--------|
| TOXIC_SPIKE | COMMON | +0.30 атака | 6ч | — |
| UNSTABLE_CODE | COMMON | −0.20 атака | 4ч | ✓ |
| SLOW_REPLICATION | COMMON | −0.30 распространение | 4ч | ✓ |
| IMMUNE_LEAK | COMMON | −0.15 защита | 6ч | ✓ |
| RAPID_SPREAD | UNCOMMON | +0.50 распространение | 4ч | — |
| REGENERATIVE_CORE | UNCOMMON | +0.30 регенерация | 6ч | — |
| BIO_MAGNET | UNCOMMON | +1.00 добыча (×2) | 2ч | — |
| PHANTOM_STRAIN | RARE | +0.40 стелс | 8ч | — |
| RESOURCE_DRAIN | RARE | +0.20 лут | 6ч | — |
| ADAPTIVE_SHELL | RARE | +0.25 защита | 4ч | — |
| DOUBLE_STRIKE | RARE | — | one-shot | — |
| PLAGUE_BURST | LEGENDARY | — | one-shot | — |
| ABSOLUTE_IMMUNITY | LEGENDARY | 1.0 | 1ч | — |
| EVOLUTION_LEAP | LEGENDARY | 1.0 | permanent | — |

---

## 👑 ПРЕМИУМ

**Файл:** `bot/services/premium.py`

### Константы
- `PREMIUM_DURATION_DAYS = 30`
- `PREFIX_MAX_CHARS = 5`
- `DISPLAY_NAME_MAX_CHARS = 20`

### STATUS_CONFIG

| Статус | Цена (💎) | mining_bonus | daily_bonus | mining_cd | attack_cd | max_attempts_target | max_infections_hour | transfer_limit | prefix_len | virus_name_len |
|--------|-----------|-------------|------------|-----------|-----------|--------------------|--------------------|-----------------|-----------|---------------|
| FREE | 0 | 0.0 | 0.0 | 60м | 30м | 3 | 5 | 1,500 | 0 | 20 |
| BIO_PLUS | 100 | 0.10 | 0.0 | 55м | 30м | 3 | 5 | 3,000 | 3 | 25 |
| BIO_PRO | 200 | 0.20 | 0.30 | 50м | 25м | 4 | 6 | 5,000 | 5 | 30 |
| BIO_ELITE | 400 | 0.25 | 0.50 | 45м | 25м | 5 | 7 | 8,000 | 5 | 30 |
| BIO_LEGEND | 0 (рефералы) | 0.25 | 0.50 | 45м | 25м | 5 | 7 | 10,000 | 5 | 30 |
| OWNER | 0 (админ) | 0.25 | 0.50 | 45м | 25м | 5 | 7 | 999,999 | 999 | 999 |

`mining_multiplier = 1.0 + mining_bonus`, `daily_multiplier = 1.0 + daily_bonus`.

---

## 🤝 АЛЬЯНСЫ

**Файл:** `bot/services/alliance.py`

### Константы
- `ALLIANCE_CREATE_COST = 500` bio_coins
- `MAX_MEMBERS_DEFAULT = 20`
- `BIO_TO_ALLIANCE_RATE = 100` — 100 bio = 1 🔷
- `TREASURY_MIN_DONATION = 100` bio_coins
- `ALLIANCE_COIN_RATE = 1` — 1 💎 = 1 🔷

### Стоимость апгрейда альянса
```python
cost = math.ceil(cfg["base_cost"] * (cfg["multiplier"] ** current_level))
```

### ALLIANCE_UPGRADE_CONFIG

| Ключ | max_level | base_cost (🔷) | multiplier | effect_per_level | Описание |
|------|-----------|---------------|------------|------------------|----------|
| shield | 10 | 100 | 1.3 | 0.03 | +3% защиты |
| morale | 10 | 150 | 1.3 | 0.03 | +3% атаки |
| capacity | 10 | 200 | 1.5 | +5 слотов | +5 членов |
| mining | 8 | 150 | 1.3 | 0.05 | +5% добычи |
| regen | 8 | 120 | 1.3 | 0.01 | +1% авто-лечения |

### Применение бонусов в бою
```python
atk_alliance_bonus = alliance.morale_level * 0.03   # потом * 0.05 к шансу
def_alliance_bonus = alliance.shield_level * 0.03
```

---

## 🆕 СТАРТОВЫЕ ЗНАЧЕНИЯ ИГРОКА

**Файл:** `bot/services/player.py`

- `bio_coins = 2500` — стартовый баланс
- `premium_coins = 0`
- `DEFAULT_ATTACK_POWER = 10`
- `DEFAULT_SPREAD_RATE = 1.0`
- `DEFAULT_MUTATION_POINTS = 0`
- `DEFAULT_VIRUS_LEVEL = 0`
- `DEFAULT_IMMUNITY_LEVEL = 0`
- `DEFAULT_RESISTANCE = 10`
- `DEFAULT_DETECTION_POWER = 0.1`
- `DEFAULT_RECOVERY_SPEED = 0.03`

---

## 👥 РЕФЕРАЛЬНАЯ ПРОГРАММА

**Файл:** `bot/services/referral.py`

### Константы
- `QUALIFICATION_UPGRADES = 5` — реферал должен купить 5 апгрейдов
- `INACTIVITY_DAYS = 7` — квалифицированные рефералы неактивные >7 дней исключаются
- `REPEATABLE_BASE_THRESHOLD = 50`
- `REPEATABLE_STEP = 10` — каждые 10 рефералов сверх 50 = 1 клейм
- `REPEATABLE_BIO = 1000` — bio_coins за повторяемый клейм

### Формула повторяемых клеймов
```python
available = (active_count - REPEATABLE_BASE_THRESHOLD) // REPEATABLE_STEP - already_claimed
```

### REFERRAL_REWARDS

| Уровень | Рефералов | Bio | Premium 💎 | Статус | Дней |
|---------|-----------|-----|------------|--------|------|
| 1 | 1 | 100 | 0 | — | 0 |
| 2 | 3 | 300 | 0 | — | 0 |
| 3 | 5 | 500 | 10 | — | 0 |
| 4 | 10 | 1,000 | 30 | — | 0 |
| 5 | 20 | 2,000 | 50 | BIO_PLUS | 7 |
| 6 | 35 | 5,000 | 100 | BIO_PRO | 14 |
| 7 | 50 | 10,000 | 200 | BIO_LEGEND | permanent |

---

## 🎉 ИВЕНТЫ

**Файл:** `bot/services/event.py`

### Модификаторы ивентов

| Ключ | Ивент | Активное значение | Default |
|------|-------|-------------------|---------|
| `mining_mult` | GOLD_RUSH | 2.0 | 1.0 |
| `upgrade_cost_mult` | ARMS_RACE | 0.5 | 1.0 |
| `attack_chance_mult` | PLAGUE_SEASON | 1.5 | 1.0 |
| `defense_mult` | IMMUNITY_WAVE | 1.5 | 1.0 |
| `mutation_chance_mult` | MUTATION_STORM | 3.0 | 1.0 |
| `can_attack` | CEASEFIRE | False | True |

### Пандемия (босс)
- `DEFAULT_BOSS_HP = 10_000`
- `BOSS_ATTACK_COOLDOWN = timedelta(minutes=30)`

### Урон по боссу
```python
base_damage = int(virus.attack_power * (1 + upgrade_level_sum))
damage = int(base_damage * random.uniform(0.8, 1.2))
is_crit = random.random() < 0.10   # 10% → ×2
streak_bonus = min(0.50, streak_count * 0.05)   # +5% за атаку, макс +50%
damage = int(damage * (1 + streak_bonus))
# Динамический кулдаун: min(30, max(10, upgrade_level_sum * 0.6)) минут
```

### Награды за пандемию
- Ранг 1: `1000 + 100 = 1100` bio
- Ранг 2-3: `500 + 100 = 600` bio
- Остальные: `100` bio

### Топ-5 призы ивентов

| Место | Pandemic bio | Pandemic 💎 | Pandemic мутация | Event bio | Event 💎 |
|-------|-------------|------------|-----------------|-----------|---------|
| 1 | 2000 | 50 | LEGENDARY | 1000 | 25 |
| 2 | 1500 | 30 | RARE | 700 | 15 |
| 3 | 1000 | 20 | RARE | 500 | 10 |
| 4 | 500 | 10 | UNCOMMON | 300 | 5 |
| 5 | 300 | 5 | UNCOMMON | 200 | 0 |

---

## 💡 /SUGGEST — ЛИМИТЫ

**Файл:** `bot/handlers/suggest.py`

- `RATE_LIMIT_COUNT = 5` — максимум 5 предложений за окно
- `RATE_LIMIT_WINDOW_MIN = 30` — окно 30 минут (sliding)
- `MIN_LENGTH = 10` — минимум 10 символов
- `MAX_LENGTH = 4000` — максимум 4000 символов (лимит Telegram 4096)

---

## 📝 Заметки

- **Балансы могут уходить в минус** (долговая механика). Кап долга = `-(total_level * 200)`. В долге: качаться нельзя, добыча +50%, лечение и атаки разрешены.
- **Цены в лаборатории** масштабируются по `power_score = level * 0.2 + balance / 10000`, кап 15×.
- **Кулдаун атаки** считается от последней записи в `attack_attempts`, не от инфекций (чтобы круговая блокировка не ломала таймер).
- **Circular infection** запрещена: если A заражает B, то B не может заражать A пока не вылечится.
- **Лут асимметричный:** атака вниз штрафуется, атака вверх даёт бонус (до 1.5×).
