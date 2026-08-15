"""Предматч-анализ: ИИ анализирует состав обеих команд перед началом игры.

Бот находит активный (ONGOING) матч, собирает статистику всех 10 игроков
и просит ИИ дать краткий анализ каждого игрока + вердикт (до 100 слов).
"""
import asyncio

from .config import (
    ANTHROPIC_BASE_URL,
    ANTHROPIC_AUTH_TOKEN,
    ANTHROPIC_MODEL,
    FACEIT_API_BASE,
)
from .faceit_api import fetch_faceit_data
from .coach import _sanitize_for_telegram, _ANTHROPIC_AVAILABLE
from .balance import get_balance_footer

try:
    from anthropic import Anthropic
except ImportError:
    Anthropic = None

# Кеш отправленных предматч-анализов (match_id → True), чтобы не дублировать
_prematch_sent: set[str] = set()


async def get_ongoing_match(player_id: str, faceit_session_token: str = None) -> dict | None:
    """Ищет активный (идущий) матч.

    Приоритет 1: api.faceit.com/match/v2 (нужен session token из браузера).
    Приоритет 2: open.faceit.com Data API v4 /history (fallback, работает плохо).

    Возвращает dict матча или None.
    """
    # --- Приоритет 1: браузерный API (api.faceit.com) ---
    if faceit_session_token:
        match = await _get_ongoing_match_browser(player_id, faceit_session_token)
        if match:
            return match

    # --- Приоритет 2: Data API v4 (fallback) ---
    return await _get_ongoing_match_data_api(player_id)


async def _get_ongoing_match_browser(player_id: str, session_token: str) -> dict | None:
    """Ищет идущий матч через api.faceit.com (нужен session token).

    api.faceit.com защищён Cloudflare, поэтому нужны заголовки как из браузера.
    Endpoint: /match/v2/matches?entityType=user&entityId={id}&game=cs2
    """
    import aiohttp
    from .config import FACEIT_BROWSER_API_BASE

    url = f"{FACEIT_BROWSER_API_BASE}/match/v2/matches?entityType=user&entityId={player_id}&game=cs2&limit=1&offset=0"

    headers = {
        "Authorization": f"Bearer {session_token}",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "application/json",
        "Origin": "https://www.faceit.com",
        "Referer": "https://www.faceit.com/",
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers, timeout=12) as resp:
                if resp.status != 200:
                    return None
                data = await resp.json()
                # api.faceit.com возвращает {payload: [...]} или {items: [...]}
                items = data.get('payload') or data.get('items') or data
                if isinstance(items, list) and items:
                    item = items[0]
                elif isinstance(items, dict) and items.get('id'):
                    item = items
                else:
                    return None
                # Проверяем что матч не завершён
                status = (item.get('status') or '').lower()
                if status in ('finished', 'cancelled'):
                    return None
                # Нормализуем формат к Data API v4 (для collect_prematch_data)
                return _normalize_browser_match(item)
    except Exception:
        return None

    return None


def _normalize_browser_match(raw: dict) -> dict:
    """Преобразует ответ api.faceit.com в формат, совместимый с Data API v4.

    collect_prematch_data ожидает: {match_id, teams: {faction1: {players: [...], nickname: ...}, ...}}
    """
    match_id = raw.get('id') or raw.get('match_id') or raw.get('matchId') or ''
    teams_raw = raw.get('teams') or raw.get('factions') or {}

    teams = {}
    for i, (key, team_data) in enumerate(teams_raw.items() if isinstance(teams_raw, dict) else enumerate(teams_raw), 1):
        faction_key = f'faction{i}'
        players_raw = team_data.get('players') or team_data.get('roster') or []
        players = []
        for p in players_raw:
            players.append({
                'player_id': p.get('id') or p.get('player_id') or p.get('playerId') or '',
                'nickname': p.get('nickname') or p.get('name') or '?',
                'avatar': p.get('avatar') or '',
                'skill_level': p.get('skill_level') or p.get('skillLevel') or p.get('game_skill_level') or '?',
            })
        teams[faction_key] = {
            'nickname': team_data.get('nickname') or f'team{i}',
            'players': players,
        }

    return {
        'match_id': match_id,
        'status': raw.get('status') or 'ongoing',
        'started_at': raw.get('started_at') or raw.get('startedAt'),
        'finished_at': raw.get('finished_at') or raw.get('finishedAt'),
        'teams': teams,
    }


async def _get_ongoing_match_data_api(player_id: str) -> dict | None:
    """Fallback: ищет идущий матч через Data API v4 /history.

    Faceit Data API v4 обычно НЕ показывает ONGOING матчи.
    Но иногда матч появляется с пустым finished_at во время игры.
    """
    import time as _time

    history = await fetch_faceit_data(
        f"{FACEIT_API_BASE}/players/{player_id}/history?game=cs2&offset=0&limit=5"
    )
    if not history or not history.get('items'):
        return None

    now_ts = int(_time.time())
    THREE_HOURS = 3 * 3600

    for item in history['items']:
        status = (item.get('status') or '').lower()
        started_at = item.get('started_at')
        finished_at = item.get('finished_at')

        if status != 'finished' and started_at and not finished_at:
            return item
        if started_at and not finished_at:
            if (now_ts - int(started_at)) < THREE_HOURS:
                return item
        if status == 'ongoing':
            return item

    return None

async def _collect_player_brief(player_id: str, nickname: str) -> str:
    """Собирает короткую сводку по одному игроку для промпта.

    Параллельно: профиль (ELO, уровень, страна) + lifetime статистика (K/D, HS%, ADR, винрейт).
    """
    # Запрос профиля и статистики параллельно
    profile_task = fetch_faceit_data(f"{FACEIT_API_BASE}/players/{player_id}")
    stats_task = fetch_faceit_data(f"{FACEIT_API_BASE}/players/{player_id}/stats/cs2")

    profile, stats_data = await asyncio.gather(profile_task, stats_task)

    if not profile:
        return f"{nickname}: данные недоступны"

    games = profile.get('games', {}).get('cs2', {})
    elo = games.get('faceit_elo', 'N/A')
    lvl = games.get('skill_level', 'N/A')
    country = (profile.get('country') or '').upper()

    if not stats_data or not stats_data.get('lifetime'):
        return f"{nickname}: ELO={elo}, Lvl={lvl}, {country} — нет статистики"

    lt = stats_data['lifetime']
    matches = lt.get('Matches', '0')
    winrate = lt.get('Win Rate %', '0')
    kd = lt.get('Average K/D Ratio', '0')
    hs = lt.get('Average Headshots %', '0')
    adr = lt.get('ADR', '0')
    recent = lt.get('Recent Results', [])
    recent_str = "".join(["W" if r == "1" else "L" for r in recent])

    return (
        f"{nickname}: ELO={elo}, Lvl={lvl}, {country}, "
        f"Матчей={matches}, WR={winrate}%, K/D={kd}, HS={hs}%, ADR={adr}, "
        f"Последние={recent_str}"
    )


async def collect_prematch_data(ongoing_match: dict, player_id: str) -> dict | None:
    """Собирает полные данные о составе обеих команд для ИИ-анализа.

    Возвращает dict:
    {
        'my_team': [строки сводок по каждому игроку],
        'enemy_team': [строки сводок по каждому игроку],
        'my_team_name': str,
        'enemy_team_name': str,
    }
    """
    teams = ongoing_match.get('teams', {})

    # Определяем какая команда наша
    my_faction = None
    my_faction_key = None

    for fname, fdata in teams.items():
        players = fdata.get('players', [])
        for p in players:
            if p.get('player_id') == player_id:
                my_faction = fdata
                my_faction_key = fname
                break
        if my_faction:
            break

    if not my_faction:
        # Игрок не найден ни в одной команде — берём первую
        my_faction = teams.get('faction1', {})

    enemy_faction_key = 'faction2' if my_faction_key == 'faction1' else 'faction1'
    enemy_faction = teams.get(enemy_faction_key, {})

    # Собираем брифы по всем 10 игрокам параллельно
    my_players = my_faction.get('players', [])
    enemy_players = enemy_faction.get('players', [])

    my_briefs = await asyncio.gather(
        *[_collect_player_brief(p.get('player_id', ''), p.get('nickname', '?')) for p in my_players]
    )
    enemy_briefs = await asyncio.gather(
        *[_collect_player_brief(p.get('player_id', ''), p.get('nickname', '?')) for p in enemy_players]
    )

    return {
        'my_team': list(my_briefs),
        'enemy_team': list(enemy_briefs),
        'my_team_name': my_faction.get('nickname', 'Моя команда'),
        'enemy_team_name': enemy_faction.get('nickname', 'Противники'),
    }


def call_prematch_llm(prematch_data: dict, nickname: str) -> str | None:
    """Синхронный вызов LLM для предматч-анализа.

    Системный промпт требует максимум 100 слов, HTML-форматирование.
    """
    if not _ANTHROPIC_AVAILABLE or not Anthropic:
        return None

    my_team = prematch_data.get('my_team', [])
    enemy_team = prematch_data.get('enemy_team', [])
    my_team_name = prematch_data.get('my_team_name', 'Твоя команда')
    enemy_team_name = prematch_data.get('enemy_team_name', 'Противники')

    system_prompt = (
        "Ты — CS2 аналитик. Игрок вот-вот начнёт матч на Faceit. "
        "Проанализируй состав обеих команд: кратко охарактеризуй каждого игрока "
        "(уровень, роль, сильные/слабые стороны) и дай вердикт о шансах на победу. "
        "ОТВЕТ МАКСИМУМ 100 СЛОВ. Будь кратким и конкретным. "
        "Используй HTML-теги <b>...</b> для акцентов. "
        "НЕ используй markdown (#, *, **, __). "
        "Пиши на русском языке."
    )

    user_prompt = (
        f"Игрок: {nickname}\n\n"
        f"{my_team_name}:\n" + "\n".join(my_team) + "\n\n"
        f"{enemy_team_name}:\n" + "\n".join(enemy_team) + "\n\n"
        f"Дай краткий анализ каждого игрока и вердикт. Максимум 100 слов."
    )

    try:
        client = Anthropic(api_key=ANTHROPIC_AUTH_TOKEN, base_url=ANTHROPIC_BASE_URL)
        resp = client.messages.create(
            model=ANTHROPIC_MODEL,
            max_tokens=256,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        )
        return resp.content[0].text
    except Exception:
        return None


async def get_prematch_analysis(player_id: str, nickname: str, faceit_session_token: str = None) -> tuple[str | None, str | None]:
    """Главная функция предматч-анализа.

    1. Ищет ONGOING матч.
    2. Собирает данные по всем 10 игрокам (параллельно).
    3. Вызывает ИИ для анализа (макс. 100 слов).

    Возвращает (текст_анализа, match_id) или (None, None).
    """
    ongoing = await get_ongoing_match(player_id, faceit_session_token)
    if not ongoing:
        return None, None

    match_id = ongoing.get('match_id', '')

    # Не отправляем повторно для одного и того же матча
    if match_id in _prematch_sent:
        return None, match_id

    prematch_data = await collect_prematch_data(ongoing, player_id)
    if not prematch_data:
        return None, match_id

    text = await asyncio.to_thread(call_prematch_llm, prematch_data, nickname)
    if not text:
        return None, match_id

    _prematch_sent.add(match_id)
    return _sanitize_for_telegram(text) + await get_balance_footer(), match_id


def is_prematch_sent(match_id: str) -> bool:
    """Проверяет, был ли уже отправлен предматч-анализ для данного матча."""
    return match_id in _prematch_sent


def mark_prematch_sent(match_id: str):
    """Отмечает матч как обработанный (предматч отправлен)."""
    _prematch_sent.add(match_id)
