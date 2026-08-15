"""Проверка баланса токенов Cerberus API.

Делает POST-запрос к endpoints check-balance, кеширует результат на
BALANCE_CACHE_TTL секунд (по умолчанию 60). Возвращает отформатированную
строку вида "Осталось токенов: 1 234 567" для подписи под ответами ИИ.
"""
import time

import aiohttp

from .config import CERBERUS_BALANCE_API_URL, CERBERUS_BALANCE_API_KEY, BALANCE_CACHE_TTL
from .runtime import _api_cache


async def fetch_token_balance() -> int | None:
    """Возвращает числовой баланс токенов или None при ошибке.

    Кешируется на BALANCE_CACHE_TTL секунд (по умолчанию 60), чтобы не
    дёргать balance-API при каждом ответе ИИ.
    """
    cache_key = "cerberus_balance"
    cached = _api_cache.get(cache_key)
    if cached and (time.time() - cached[0]) < BALANCE_CACHE_TTL:
        return cached[1]

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                CERBERUS_BALANCE_API_URL,
                json={"api_key": CERBERUS_BALANCE_API_KEY},
                headers={"Content-Type": "application/json", "Accept": "application/json"},
                timeout=12,
            ) as resp:
                if resp.status != 200:
                    return None
                data = await resp.json()
                if not data.get("success"):
                    return None
                balance = int(data.get("balance", 0))
                _api_cache[cache_key] = (time.time(), balance)
                return balance
    except Exception:
        return None


def format_balance(balance: int | None) -> str:
    """Форматирует число в строку вида '1 234 567' (с разделителями разрядов)."""
    if balance is None:
        return "недоступно"
    # Используем пробел как разделитель (рус. локаль)
    return f"{balance:,}".replace(",", " ")


async def get_balance_footer() -> str:
    """Возвращает готовую строку-подпись для добавления под ответ ИИ.

    Формат: '\n\n━━━\nОсталось токенов: 1 234 567'
    При ошибке: '\n\n━━━\nОсталось токенов: недоступно'
    """
    balance = await fetch_token_balance()
    return f"\n\n━━━\nОсталось токенов: {format_balance(balance)}"
