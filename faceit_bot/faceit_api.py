"""API-функции Faceit.

Перенесено из bot.py. Использует _api_cache из runtime и константы из config.
"""
import time

import aiohttp

from .config import FACEIT_API_BASE, HEADERS, ESTIMATED_ELO_STEP, CACHE_TTL
from .runtime import _api_cache
from .formatting import section, kv, table


async def fetch_faceit_data(url: str, use_cache: bool = False, headers=None):
    if use_cache:
        cached = _api_cache.get(url)
        if cached and (time.time() - cached[0]) < CACHE_TTL:
            return cached[1]

    async with aiohttp.ClientSession() as session_http:
        try:
            async with session_http.get(url, headers=headers or HEADERS, timeout=10) as response:
                if response.status == 200:
                    data = await response.json()
                    if use_cache:
                        _api_cache[url] = (time.time(), data)
                    return data
                return None
        except Exception:
            return None


async def get_player_by_nickname(nickname: str):
    return await fetch_faceit_data(f"{FACEIT_API_BASE}/players?nickname={nickname}", use_cache=True)


def _match_result_for_player(item: dict, player_id: str):
    """Возвращает True/False (победа/поражение) для игрока в конкретном матче
    из ответа /players/{id}/history, либо None если не удалось определить."""
    player_faction = None
    for faction_name, faction_data in item.get('teams', {}).items():
        for p in faction_data.get('players', []):
            if p['player_id'] == player_id:
                player_faction = faction_name
                break
    winner = item.get('results', {}).get('winner')
    if player_faction is None or winner is None:
        return None
    return player_faction == winner


async def fetch_remote_elo_points(player_id: str, size: int = 30):
    """Пробует получить реальную историю ELO с недокументированного эндпоинта
    Faceit (используется на самом сайте для графика прогресса). Публичный
    Data API v4 такого не отдаёт вообще, поэтому это best-effort попытка:
    если формат ответа изменится или эндпоинт окажется недоступен — просто
    возвращаем None, и вызывающий код переходит на оценку по матчам.
    """
    url = f"https://api.faceit.com/stats/v1/stats/time/users/{player_id}/games/cs2?page=0&size={size}"
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get(url, timeout=8) as resp:
                if resp.status != 200:
                    return None
                data = await resp.json()
    except Exception:
        return None

    if not isinstance(data, list) or not data:
        return None

    points = []
    for entry in reversed(data):  # у Faceit обычно свежее сверху -> разворачиваем в хронологию
        elo = entry.get('elo') or entry.get('Elo') or entry.get('faceit_elo')
        if elo is None:
            continue
        try:
            points.append(int(elo))
        except (TypeError, ValueError):
            continue

    return points if len(points) >= 2 else None


def estimate_elo_curve(current_elo: int, results_newest_first, step: int = ESTIMATED_ELO_STEP):
    """Грубая реконструкция динамики ELO по итогам матчей (W/L), когда точных
    исторических значений нет ни локально, ни на стороне Faceit. НЕ является
    точным значением — это визуальная оценка тренда."""
    curve = [current_elo]
    elo = current_elo
    for is_win in results_newest_first:
        elo = elo - step if is_win else elo + step
        curve.append(elo)
    curve.reverse()
    return curve


async def get_match_stats_text(match_id: str, player_id: str, nickname: str, index: int = None):
    match_stats = await fetch_faceit_data(f"{FACEIT_API_BASE}/matches/{match_id}/stats")
    if not match_stats or not match_stats.get('rounds'):
        return "Ошибка: не удалось загрузить детали матча с Faceit.", None

    player_match_stats = None
    user_team = None

    for team in match_stats['rounds'][0]['teams']:
        if any(p['player_id'] == player_id for p in team['players']):
            user_team = team
            for player in team['players']:
                if player['player_id'] == player_id:
                    player_match_stats = player['player_stats']
                    break

    if not player_match_stats or not user_team:
        return "Ошибка: статистика игрока в этом матче не найдена.", None

    result = player_match_stats.get('Result', '0')
    outcome = "ПОБЕДА" if result == "1" else "ПОРАЖЕНИЕ"
    map_name = match_stats['rounds'][0]['round_stats'].get('Map', 'Unknown')
    score = match_stats['rounds'][0]['round_stats'].get('Score', 'N/A')

    player_data = await fetch_faceit_data(f"{FACEIT_API_BASE}/players/{player_id}")
    current_elo = player_data.get('games', {}).get('cs2', {}).get('faceit_elo', 'N/A')

    sorted_players = sorted(user_team['players'], key=lambda x: int(x['player_stats'].get('Kills', 0)), reverse=True)
    rows = []
    for p in sorted_players:
        name = p['nickname']
        if p['player_id'] == player_id:
            name = "> " + name
        rows.append([
            name,
            p['player_stats'].get('Kills', '0'),
            p['player_stats'].get('Deaths', '0'),
            p['player_stats'].get('K/D Ratio', '0'),
        ])
    scoreboard = table(rows, headers=["Игрок", "K", "D", "K/D"])

    header = f"МАТЧ #{index} — {nickname}" if index else f"ПОСЛЕДНИЙ МАТЧ — {nickname}"

    text = (
        f"{section(header)}\n"
        f"{kv('Карта', map_name)}\n"
        f"{kv('Итог', outcome + ' [' + str(score) + ']')}\n"
        f"{kv('Текущий ELO', current_elo)}\n\n"
        f"{section('Статистика игрока')}\n"
        f"K/D: <b>{player_match_stats.get('K/D Ratio', '0')}</b> "
        f"({player_match_stats.get('Kills', '0')}K - {player_match_stats.get('Deaths', '0')}D)\n"
        f"K/R: <b>{player_match_stats.get('K/R Ratio', '0')}</b>\n"
        f"Headshots: <b>{player_match_stats.get('Headshots %', '0')}%</b> ({player_match_stats.get('Headshots', '0')})\n"
        f"Мультикиллы: 3K {player_match_stats.get('Triple Kills', '0')} | "
        f"4K {player_match_stats.get('Quadro Kills', '0')} | "
        f"5K {player_match_stats.get('Penta Kills', '0')}\n\n"
        f"{section('Команда в матче')}\n"
        f"<code>{scoreboard}</code>"
    )
    return text, current_elo


async def get_match_text_only(*args, **kwargs):
    text, _ = await get_match_stats_text(*args, **kwargs)
    return text


def _to_number(value):
    """Утилита для графиков: безопасное преобразование в float."""
    try:
        return float(str(value).replace(',', ''))
    except (TypeError, ValueError):
        return None
