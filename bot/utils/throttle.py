import time

_last_action: dict[tuple[int, str], float] = {}


def check_throttle(user_id: int, action: str, cooldown: float = 2.0) -> float:
    """Return remaining seconds if throttled, 0.0 if OK."""
    key = (user_id, action)
    now = time.monotonic()
    last = _last_action.get(key, 0.0)
    remaining = cooldown - (now - last)
    if remaining > 0:
        return remaining
    _last_action[key] = now
    return 0.0
