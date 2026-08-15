"""Функции-обёртки для доступа ИИ к данным бота.

Эти функции вызываются через tool use в ai_chat.py, когда ИИ
хочет получить статистику, последний матч или динамику ELO.

Возвращают компактный текст для передачи обратно в ИИ.
"""
from .config import FACEIT_API_BASE, WEBAPP_URL, WEBAPP_AUTH_SECRET
from .faceit_api import (
    get_player_by_nickname,
    fetch_faceit_data,
    _match_result_for_player,
)
from .db import get_elo_history, get_user_data, get_link_token


async def fetch_stats_summary(nickname: str) -> str:
    """Возвращает компактную статистику игрока для ИИ.

    Включает: ELO, уровень, матчи, винрейт, K/D, HS%, стрик,
    мультикиллы, клатчи, энтри, топ-3 карты.
    """
    player_data = await get_player_by_nickname(nickname)
    if not player_data:
        return f"Игрок '{nickname}' не найден на Faceit."

    player_id = player_data['player_id']
    stats_data = await fetch_faceit_data(f"{FACEIT_API_BASE}/players/{player_id}/stats/cs2")

    if not stats_data:
        return f"Статистика CS2 для '{nickname}' недоступна."

    lifetime = stats_data.get('lifetime', {})
    segments = stats_data.get('segments', [])

    elo = player_data.get('games', {}).get('cs2', {}).get('faceit_elo', 'N/A')
    lvl = player_data.get('games', {}).get('cs2', {}).get('skill_level', 'N/A')
    country = player_data.get('country', 'N/A').upper()

    matches = lifetime.get('Matches', 'N/A')
    wins = lifetime.get('Wins', 'N/A')
    winrate = lifetime.get('Win Rate %', 'N/A')
    current_streak = lifetime.get('Current Win Streak', '0')
    longest_streak = lifetime.get('Longest Win Streak', '0')
    kd = lifetime.get('Average K/D Ratio', 'N/A')
    avg_hs = lifetime.get('Average Headshots %', 'N/A')

    recent_results = lifetime.get('Recent Results', [])
    recent_str = " ".join(["W" if res == "1" else "L" for res in recent_results])

    def _num(value, default=0):
        try:
            return int(str(value).replace(',', '') or default)
        except (TypeError, ValueError):
            return default

    total_kills = total_deaths = total_mvps = 0
    triple = quadro = penta = 0
    c1v1_count = c1v1_wins = c1v2_count = c1v2_wins = 0
    entry_count = entry_wins = 0

    maps_info = []
    for seg in segments:
        if seg.get('mode') == '5v5' and seg.get('type') == 'Map':
            ms = seg.get('stats', {})
            total_kills += _num(ms.get('Kills'))
            total_deaths += _num(ms.get('Deaths'))
            total_mvps += _num(ms.get('MVPs'))
            triple += _num(ms.get('Triple Kills'))
            quadro += _num(ms.get('Quadro Kills'))
            penta += _num(ms.get('Penta Kills'))
            c1v1_count += _num(ms.get('1v1Count'))
            c1v1_wins += _num(ms.get('1v1Wins'))
            c1v2_count += _num(ms.get('1v2Count'))
            c1v2_wins += _num(ms.get('1v2Wins'))
            entry_count += _num(ms.get('Entry Count'))
            entry_wins += _num(ms.get('Entry Wins'))

            m_played = _num(ms.get('Matches'))
            if m_played > 0:
                maps_info.append({
                    'name': seg.get('label', 'Unknown'),
                    'matches': m_played,
                    'winrate': ms.get('Win Rate %', '0'),
                    'kd': ms.get('Average K/D Ratio', '0'),
                })

    maps_info.sort(key=lambda x: x['matches'], reverse=True)

    def _pct(part, total):
        return f"{round(part / total * 100)}%" if total else "N/A"

    maps_str = ", ".join(
        f"{m['name']}({m['matches']}м,{m['winrate']}%WR,{m['kd']}KD)"
        for m in maps_info[:3]
    ) if maps_info else "нет данных"

    summary = (
        f"Игрок: {nickname}\n"
        f"ELO: {elo}, Уровень: {lvl}, Регион: {country}\n"
        f"Матчей: {matches} (W {wins}), Винрейт: {winrate}%\n"
        f"Стрик: {current_streak} (рекорд {longest_streak})\n"
        f"Последние 5 игр: {recent_str}\n"
        f"K/D: {kd}, HS%: {avg_hs}%\n"
        f"Убийства: {total_kills}, Смерти: {total_deaths}, MVP: {total_mvps}\n"
        f"Мультикиллы: 5K={penta}, 4K={quadro}, 3K={triple}\n"
        f"Энтри: {entry_wins}/{entry_count} ({_pct(entry_wins, entry_count)})\n"
        f"1v1: {c1v1_wins}/{c1v1_count} ({_pct(c1v1_wins, c1v1_count)})\n"
        f"1v2: {c1v2_wins}/{c1v2_count} ({_pct(c1v2_wins, c1v2_count)})\n"
        f"Топ карт: {maps_str}"
    )

    return summary


async def fetch_last_match_summary(nickname: str) -> str:
    """Возвращает компактную информацию о последнем матче для ИИ."""
    player_data = await get_player_by_nickname(nickname)
    if not player_data:
        return f"Игрок '{nickname}' не найден на Faceit."

    player_id = player_data['player_id']
    history_data = await fetch_faceit_data(
        f"{FACEIT_API_BASE}/players/{player_id}/history?game=cs2&offset=0&limit=1"
    )

    if not history_data or not history_data.get('items'):
        return f"История матчей для '{nickname}' пуста."

    item = history_data['items'][0]
    match_id = item['match_id']

    res = _match_result_for_player(item, player_id)
    outcome = "ПОБЕДА" if res is True else ("ПОРАЖЕНИЕ" if res is False else "N/A")

    score_data = item.get('results', {}).get('score', {})
    s1 = score_data.get('faction1', 0)
    s2 = score_data.get('faction2', 0)
    score = f"{s1}:{s2}"

    # Получаем детали матча
    match_stats = await fetch_faceit_data(f"{FACEIT_API_BASE}/matches/{match_id}/stats")
    map_name = "Unknown"
    kd = "0"
    kills = "0"
    deaths = "0"
    hs_pct = "0"

    if match_stats and match_stats.get('rounds'):
        map_name = match_stats['rounds'][0]['round_stats'].get('Map', 'Unknown')
        for team in match_stats['rounds'][0]['teams']:
            for p in team['players']:
                if p['player_id'] == player_id:
                    player_stats = p['player_stats']
                    kd = player_stats.get('K/D Ratio', '0')
                    kills = player_stats.get('Kills', '0')
                    deaths = player_stats.get('Deaths', '0')
                    hs_pct = player_stats.get('Headshots %', '0')
                    break

    summary = (
        f"Последний матч игрока {nickname}:\n"
        f"Карта: {map_name}\n"
        f"Результат: {outcome} ({score})\n"
        f"K/D: {kd} ({kills}K - {deaths}D)\n"
        f"Headshots: {hs_pct}%"
    )

    return summary


async def fetch_elo_summary(nickname: str, user_id: int) -> str:
    """Возвращает компактную информацию о динамике ELO для ИИ."""
    player_data = await get_player_by_nickname(nickname)
    if not player_data:
        return f"Игрок '{nickname}' не найден на Faceit."

    current_elo = player_data.get('games', {}).get('cs2', {}).get('faceit_elo', 'N/A')

    # Пытаемся достать локальную историю (если пользователь = владелец ника)
    user_data = get_user_data(user_id)
    local_history = []
    if user_data and user_data[0] == nickname:
        local_history = get_elo_history(user_id, limit=30)

    if len(local_history) >= 2:
        elos = [row[0] for row in local_history]
        delta = elos[-1] - elos[0]
        delta_str = f"{'+' if delta >= 0 else ''}{delta}"
        summary = (
            f"Динамика ELO игрока {nickname}:\n"
            f"Текущий ELO: {current_elo}\n"
            f"Изменение за {len(elos)} матчей: {delta_str}\n"
            f"История (последние 10): {' → '.join(map(str, elos[-10:]))}"
        )
        return summary

    # Если локальной истории нет — просто текущий ELO
    return (
        f"Динамика ELO игрока {nickname}:\n"
        f"Текущий ELO: {current_elo}\n"
        f"История пока не накоплена ботом (нужно несколько матчей для трека)."
    )


async def fetch_advanced_stats(nickname: str, user_id: int) -> str:
    """Расширенные данные, которых нет в публичном API: Faceit Rating 3.0, swing,
    детальный ELO. Доступно через расширение (Worker KV scrape:{link_token}:advanced).

    Если у пользователя нет link_token или данные устарели/отсутствуют —
    возвращает инструкцию попросить пользователя открыть профиль на faceit.com.
    """
    if not WEBAPP_URL:
        return "Расширенные данные недоступны (Worker не настроен)."

    # link_token нужен только если запрашивают свою статистику (self) —
    # расширенные данные привязаны к сессии браузера конкретного пользователя.
    user_data = get_user_data(user_id)
    is_self = bool(user_data and user_data[0] and user_data[0].lower() == nickname.lower())
    if not is_self:
        return (
            f"Расширенные данные (Rating 3.0, swing) доступны только для своего "
            f"профиля через расширение. Для '{nickname}' их получить нельзя."
        )

    link_token = get_link_token(user_id)
    if not link_token:
        return (
            "Расширенные данные недоступны: расширение не привязано. "
            "Попроси пользователя установить расширение через /facelogin."
        )

    import aiohttp
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get(
                f"{WEBAPP_URL}/api/scrape-data?link_token={link_token}&type=advanced",
                headers={"X-Auth-Secret": WEBAPP_AUTH_SECRET},
                timeout=10,
            ) as resp:
                if resp.status != 200:
                    return "Расширенные данные недоступны. Попроси пользователя открыть профиль на faceit.com."
                data = await resp.json()
                if not data or not data.get("payload"):
                    return "Расширенные данные пока не собраны. Попроси пользователя открыть свой профиль на faceit.com."
                payload = data["payload"]
                rating = payload.get("rating_3_0", "N/A")
                swing = payload.get("swing", "N/A")
                ts = payload.get("timestamp", 0)
                import time
                age = int(time.time() - ts) if ts else 0
                age_str = f"{age} сек назад" if ts else "давно"
                return (
                    f"Расширенные данные {nickname} (из расширения, {age_str}):\n"
                    f"Faceit Rating 3.0: {rating}\n"
                    f"Swing: {swing}"
                )
    except Exception as e:
        return f"Ошибка получения расширенных данных: {str(e)}"
