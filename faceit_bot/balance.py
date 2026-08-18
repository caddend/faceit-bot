"""Проверка баланса токенов Tooken Club.

Делает GET-запрос к cabinet (с bearer token), парсит остаток токенов.
Кеширует результат на BALANCE_CACHE_TTL секунд (по умолчанию 60).
Возвращает строку вида "Осталось токенов: 1 234 567" для подписи под ответами ИИ.
"""
import re
import time

import aiohttp

from .config import TOOKEN_CABINET_URL, TOOKEN_API_KEY, BALANCE_CACHE_TTL
from .runtime import _api_cache


async def fetch_token_balance() -> int | None:
    """Возвращает числовой баланс токенов или None при ошибке.

    Tooken cabinet — HTML/JSON. Пробуем JSON-поля, затем regex по тексту.
    """
    cache_key = "tooken_balance"
    cached = _api_cache.get(cache_key)
    if cached and (time.time() - cached[0]) < BALANCE_CACHE_TTL:
        return cached[1]

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                TOOKEN_CABINET_URL,
                headers={
                    "Authorization": f"Bearer {TOOKEN_API_KEY}",
                    "Accept": "application/json, text/html",
                },
                timeout=12,
            ) as resp:
                if resp.status != 200:
                    return None
                text = await resp.text()
    except Exception:
        return None

    balance = _extract_balance(text)
    if balance is not None:
        _api_cache[cache_key] = (time.time(), balance)
    return balance


def _extract_balance(text: str) -> int | None:
    """Достаёт число баланса из JSON или HTML.

    Ищем JSON-поля (balance, tokens, remaining, credits, amount),
    затем regex по тексту рядом с ключевыми словами.
    """
    # Пробуем JSON-поля
    import json
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            for key in ("balance", "tokens", "remaining", "credits", "amount", "left"):
                if key in data:
                    try:
                        return int(float(str(data[key])))
                    except (TypeError, ValueError):
                        pass
                # вложенные объекты
                for sub in data.values():
                    if isinstance(sub, dict) and key in sub:
                        try:
                            return int(float(str(sub[key])))
                        except (TypeError, ValueError):
                            pass
    except Exception:
        pass

    # Regex по тексту: число рядом с balance/токен/осталось/remaining
    patterns = [
        r'(?:balance|remaining|left|credits|токен[а-я]*|осталось)\D{0,20}(\d[\d\s.,]*)',
        r'(\d[\d\s.,]*)\D{0,20}(?:balance|remaining|токен[а-я]*|осталось)',
    ]
    for pat in patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            num = re.sub(r'[^\d]', '', m.group(1))
            if num:
                try:
                    return int(num)
                except ValueError:
                    pass
    return None


def format_balance(balance: int | None) -> str:
    """Форматирует число в строку вида '1 234 567' (с разделителями разрядов)."""
    if balance is None:
        return "недоступно"
    return f"{balance:,}".replace(",", " ")


async def get_balance_footer() -> str:
    """Возвращает готовую строку-подпись для добавления под ответ ИИ.

    Формат: '\n\n━━━\nОсталось токенов: 1 234 567'
    """
    balance = await fetch_token_balance()
    return f"\n\n━━━\nОсталось токенов: {format_balance(balance)}"
