"""Steam Web API: запросы к api.steampowered.com.

В отличие от Faceit (Bearer header), Steam использует ?key=XXX в query.
Кешируется в общий _api_cache (TTL=STEAM_STATS_CACHE_TTL — lifetime данные
меняются редко).
"""
import time

import aiohttp

from .config import (
    STEAM_API_KEY,
    STEAM_API_BASE,
    STEAM_STATS_CACHE_TTL,
    CS2_APP_ID,
)
from .runtime import _api_cache


async def fetch_steam_data(url: str, use_cache: bool = False, ttl: int = STEAM_STATS_CACHE_TTL):
    """Аналог fetch_faceit_data, но без заголовков (key уже в URL).

    Steam при невалидном ключе возвращает 403 с HTML-телом, при приватном
    профиле — 400. Любой не-200 → None.
    """
    if use_cache:
        cached = _api_cache.get(url)
        if cached and (time.time() - cached[0]) < ttl:
            return cached[1]

    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(url, timeout=10) as response:
                if response.status == 200:
                    data = await response.json()
                    if use_cache:
                        _api_cache[url] = (time.time(), data)
                    return data
                return None
        except Exception:
            return None


async def resolve_steam_id(identifier: str) -> str | None:
    """Превращает SteamID64 или vanity-имя в SteamID64.

    Если identifier — 17-значное число, возвращаем как есть.
    Иначе пытаемся резолвить через ResolveVanityURL/v1.
    """
    if not identifier:
        return None

    identifier = identifier.strip()

    # SteamID64 — 17-значное число, начинается с 7656
    if identifier.isdigit() and len(identifier) == 17:
        return identifier

    # Убираем возможный URL-префикс vanity (/id/foobar или https://steamcommunity.com/id/foobar)
    vanity = identifier
    if "steamcommunity.com/id/" in vanity:
        vanity = vanity.split("steamcommunity.com/id/", 1)[1]
        vanity = vanity.split("?")[0].split("/")[0].strip()
    elif "steamcommunity.com/profiles/" in vanity:
        # Прямая ссылка на профиль по SteamID64
        sid = vanity.split("steamcommunity.com/profiles/", 1)[1]
        sid = sid.split("?")[0].split("/")[0].strip()
        if sid.isdigit() and len(sid) == 17:
            return sid
    elif vanity.startswith("/id/"):
        vanity = vanity[4:]
        vanity = vanity.split("/")[0].strip()

    if not vanity:
        return None

    # Если после очистки осталось 17-значное число — это SteamID64
    if vanity.isdigit() and len(vanity) == 17:
        return vanity

    url = f"{STEAM_API_BASE}/ISteamUser/ResolveVanityURL/v1/?key={STEAM_API_KEY}&vanityurl={vanity}"
    data = await fetch_steam_data(url)
    if not data:
        return None

    response = data.get('response', {})
    if response.get('success') == 1 and response.get('steamid'):
        return response['steamid']

    return None


async def get_steam_player_summary(steam_id: str) -> dict | None:
    """GetPlayerSummaries/v2 — профиль Steam.

    Возвращает players[0] или None. Содержит:
    - personaname (ник)
    - communityvisibilitystate (3=public, иначе приватный)
    - avatarfull, profileurl
    """
    if not steam_id:
        return None

    url = f"{STEAM_API_BASE}/ISteamUser/GetPlayerSummaries/v2/?key={STEAM_API_KEY}&steamids={steam_id}"
    data = await fetch_steam_data(url, use_cache=True)
    if not data:
        return None

    players = data.get('response', {}).get('players', [])
    return players[0] if players else None


async def get_cs2_lifetime_stats(steam_id: str) -> dict | None:
    """GetUserStatsForGame/v2 для CS2 (appid=730).

    Возвращает {name: value} dict для удобного поиска по ключам
    (total_kills, total_deaths, total_headshots и т.д.).
    Если профиль приватный — stats пустой → возвращаем None.
    """
    if not steam_id:
        return None

    url = (
        f"{STEAM_API_BASE}/ISteamUserStats/GetUserStatsForGame/v2/"
        f"?appid={CS2_APP_ID}&key={STEAM_API_KEY}&steamid={steam_id}"
    )
    data = await fetch_steam_data(url, use_cache=True)
    if not data:
        return None

    stats_list = data.get('playerstats', {}).get('stats', [])
    if not stats_list:
        return None

    return {item['name']: item['value'] for item in stats_list if 'name' in item and 'value' in item}


async def get_steam_id_from_faceit(player_data: dict) -> str | None:
    """Достаёт steam_id_64 из ответа Faceit /players.

    Faceit возвращает это поле на верхнем уровне вместе с player_id, nickname.
    Не у всех игроков Steam привязан — может быть None.
    """
    if not player_data:
        return None
    return player_data.get('steam_id_64') or None
