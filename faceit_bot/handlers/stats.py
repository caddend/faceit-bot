"""Хендлеры команд статистики: /stats (Faceit + Steam), /elo, /session,
/compare, /map, /top.

Все хендлеры декорируются через @dp.message(...) с импортом dp из runtime.
"""
import asyncio
import io
import time

from aiogram import types, F
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder

from ..runtime import dp, bot
from ..config import FACEIT_API_BASE
from ..db import (
    get_user_data,
    get_steam_id,
    save_steam_id,
    get_elo_history,
    save_session,
    get_session,
    resolve_nickname,
    get_distinct_nicknames,
    get_ai_mode,
)
from ..dashboard import (
    delete_user_message,
    clear_dashboard,
    replace_dashboard,
    answer_and_track,
)
from ..faceit_api import (
    get_player_by_nickname,
    fetch_faceit_data,
    _match_result_for_player,
    fetch_remote_elo_points,
    estimate_elo_curve,
)
from ..steam_api import (
    get_steam_player_summary,
    get_cs2_lifetime_stats,
    get_steam_id_from_faceit,
)
from ..charts import render_compare_chart, render_map_chart, render_stats_image
from ..coach import get_coach_analysis
from ..ai_chat import get_ai_chat_response
from ..formatting import section, kv, table


# ============================================================
#  /stats — Faceit статистика + Steam lifetime CS2
# ============================================================

@dp.message(Command("stats"))
async def cmd_stats(message: types.Message):
    await delete_user_message(message)
    user_id = message.from_user.id
    nickname = resolve_nickname(message, message.text.split())
    if not nickname:
        await answer_and_track(message, "Никнейм не указан и не сохранен. Используй /setnick [ник].")
        return

    await clear_dashboard(user_id)

    player_data = await get_player_by_nickname(nickname)
    if not player_data:
        await answer_and_track(message, "Игрок не найден.")
        return

    player_id = player_data['player_id']
    stats_data = await fetch_faceit_data(f"{FACEIT_API_BASE}/players/{player_id}/stats/cs2")

    if not stats_data:
        await answer_and_track(message, "Статистика CS2 не найдена.")
        return

    lifetime = stats_data.get('lifetime', {})
    segments = stats_data.get('segments', [])

    elo = player_data.get('games', {}).get('cs2', {}).get('faceit_elo', 'N/A')
    lvl = player_data.get('games', {}).get('cs2', {}).get('skill_level', 'N/A')
    country = player_data.get('country', 'N/A').upper()

    recent_results = lifetime.get('Recent Results', [])
    recent_str = " ".join(["W" if res == "1" else "L" for res in recent_results])

    # --- Steam lifetime CS2 stats (параллельно с Faceit рендером) ---
    steam_id = get_steam_id(user_id)
    if not steam_id:
        steam_id = await get_steam_id_from_faceit(player_data)
        if steam_id:
            save_steam_id(user_id, steam_id)

    steam_block = ""
    if steam_id:
        steam_stats = await get_cs2_lifetime_stats(steam_id)
        if steam_stats:
            steam_block = _build_steam_block(steam_stats, steam_id)
        else:
            steam_block = "\n\n<i>Steam профиль приватный или статистика недоступна.</i>"

    # Пробуем нарисовать расширенную картинку
    chart_bytes = render_stats_image(stats_data, player_data, nickname)

    if chart_bytes:
        # Caption: профиль + Steam блок
        caption = (
            f"{section('ПРОФИЛЬ: ' + nickname)}\n"
            f"{kv('Уровень', lvl)}   {kv('ELO', elo)}\n"
            f"{kv('Регион', country)}\n"
            f"{kv('Последние 5 игр', recent_str)}"
            f"{steam_block}"
        )
        photo = types.BufferedInputFile(chart_bytes, filename="stats.png")
        builder = InlineKeyboardBuilder()
        builder.button(text="🧠 ИИ-анализ", callback_data=f"coach:{user_id}")
        markup = builder.as_markup()
        sent = await bot.send_photo(
            chat_id=message.chat.id, photo=photo, caption=caption, reply_markup=markup
        )
        await replace_dashboard(user_id, sent.chat.id, sent.message_id)
        return

    # --- Fallback на текст ---
    matches = lifetime.get('Matches', 'N/A')
    wins = lifetime.get('Wins', 'N/A')
    winrate = lifetime.get('Win Rate %', 'N/A')
    current_streak = lifetime.get('Current Win Streak', '0')
    longest_streak = lifetime.get('Longest Win Streak', '0')

    kd = lifetime.get('Average K/D Ratio', 'N/A')
    avg_hs = lifetime.get('Average Headshots %', 'N/A')

    total_kills = total_deaths = total_assists = total_hs = total_rounds = total_mvps = 0
    triple = quadro = penta = 0
    c1v1_count = c1v1_wins = c1v2_count = c1v2_wins = 0
    entry_count = entry_wins = 0
    flash_count = flash_success = 0

    maps_info = []
    for seg in segments:
        if seg.get('mode') == '5v5' and seg.get('type') == 'Map':
            map_stats = seg.get('stats', {})

            def _num(key):
                return int(str(map_stats.get(key, '0')).replace(',', '') or 0)

            total_kills += _num('Kills')
            total_deaths += _num('Deaths')
            total_assists += _num('Assists')
            total_hs += _num('Headshots')
            total_rounds += _num('Rounds')
            total_mvps += _num('MVPs')

            triple += _num('Triple Kills')
            quadro += _num('Quadro Kills')
            penta += _num('Penta Kills')

            c1v1_count += _num('1v1Count')
            c1v1_wins += _num('1v1Wins')
            c1v2_count += _num('1v2Count')
            c1v2_wins += _num('1v2Wins')
            entry_count += _num('Entry Count')
            entry_wins += _num('Entry Wins')
            flash_count += _num('Flash Count')
            flash_success += _num('Flash Successes')

            m_played = _num('Matches')
            if m_played > 0:
                maps_info.append({
                    'name': seg.get('label', 'Unknown'),
                    'matches': m_played,
                    'winrate': map_stats.get('Win Rate %', '0'),
                    'kd': map_stats.get('Average K/D Ratio', '0')
                })

    maps_info.sort(key=lambda x: x['matches'], reverse=True)
    maps_block = ""
    if maps_info:
        rows = [[m['name'], m['matches'], f"{m['winrate']}%", m['kd']] for m in maps_info[:3]]
        maps_block = f"\n{section('Топ-3 карты')}\n<code>{table(rows, headers=['Карта', 'M', 'WR', 'K/D'])}</code>\n"

    def _pct(part, total):
        return f"{round(part / total * 100)}%" if total else "N/A"

    clutch_block = ""
    if c1v1_count or c1v2_count or entry_count or flash_count:
        clutch_block = (
            f"\n{section('Клатчи и утилити')}\n"
            f"{kv('1v1', f'{c1v1_wins}/{c1v1_count} ({_pct(c1v1_wins, c1v1_count)})')}\n"
            f"{kv('1v2', f'{c1v2_wins}/{c1v2_count} ({_pct(c1v2_wins, c1v2_count)})')}\n"
            f"{kv('Успешность энтри', f'{entry_wins}/{entry_count} ({_pct(entry_wins, entry_count)})')}\n"
            f"{kv('Успешность флешек', f'{flash_success}/{flash_count} ({_pct(flash_success, flash_count)})')}\n"
        )

    text = (
        f"{section('ПРОФИЛЬ: ' + nickname)}\n"
        f"{kv('Уровень', lvl)}   {kv('ELO', elo)}\n"
        f"{kv('Регион', country)}\n\n"
        f"{section('Статистика за всё время (Faceit)')}\n"
        f"{kv('Матчей', matches)}\n"
        f"{kv('Победы', f'{wins} ({winrate}%)')}\n"
        f"{kv('Стрик', f'{current_streak} (рекорд {longest_streak})')}\n"
        f"{kv('Последние 5 игр', recent_str)}\n\n"
        f"{section('Средние показатели')}\n"
        f"{kv('K/D', kd)}\n"
        f"{kv('Headshots', str(avg_hs) + '%')}\n"
        f"{kv('Всего убийств', total_kills)}\n"
        f"{kv('Всего смертей', total_deaths)}\n"
        f"{kv('Всего ассистов', total_assists)}\n"
        f"{kv('Всего раундов', total_rounds)}\n"
        f"{kv('Всего MVP', total_mvps)}\n"
        f"{kv('Всего хедшотов', total_hs)}\n\n"
        f"{section('Мультикиллы')}\n"
        f"5K: <b>{penta}</b>   4K: <b>{quadro}</b>   3K: <b>{triple}</b>\n"
        f"{clutch_block}"
        f"{maps_block}"
        f"{steam_block}"
    )
    sent = await message.answer(text)
    await replace_dashboard(user_id, sent.chat.id, sent.message_id)


def _build_steam_block(stats: dict, steam_id: str) -> str:
    """Формирует текстовый блок Steam lifetime CS2 статистики для /stats."""
    def _num(key, default=0):
        v = stats.get(key, default)
        try:
            return int(v)
        except (TypeError, ValueError):
            return default

    total_kills = _num('total_kills')
    total_deaths = _num('total_deaths')
    total_hs = _num('total_kills_headshot')
    total_mvps = _num('total_mvps')
    total_rounds = _num('total_rounds_played')
    total_matches_won = _num('total_matches_won')
    total_matches = _num('total_matches_played')
    total_shots_fired = _num('total_shots_fired')
    total_damage = _num('total_damage_done')
    total_planted = _num('total_planted_bombs')
    total_defused = _num('total_defused_bombs')
    total_knife = _num('total_kills_knife')
    total_he = _num('total_kills_hegrenade')
    total_molotov = _num('total_kills_molotov')
    total_flash = _num('total_kills_enemy_blinded')

    # total_shots_hit в Steam API сломан (всегда ~8), суммируем total_hits_*
    total_shots_hit = sum(v for k, v in stats.items() if k.startswith('total_hits_'))

    kd_ratio = round(total_kills / total_deaths, 2) if total_deaths else 0
    hs_pct = round(total_hs / total_kills * 100, 1) if total_kills else 0
    accuracy = round(total_shots_hit / total_shots_fired * 100, 1) if total_shots_fired else 0
    adr = round(total_damage / total_rounds, 1) if total_rounds else 0
    winrate = round(total_matches_won / total_matches * 100, 1) if total_matches else 0

    return (
        f"\n{section('Steam Lifetime CS2 (все режимы)')}\n"
        f"{kv('SteamID', steam_id)}\n"
        f"{kv('K/D', kd_ratio)}   {kv('HS%', hs_pct)}   {kv('Точность', f'{accuracy}%')}\n"
        f"{kv('Kills', total_kills)}   {kv('Deaths', total_deaths)}   {kv('MVP', total_mvps)}\n"
        f"{kv('Rounds', total_rounds)}   {kv('Матчей', total_matches)}   "
        f"{kv('Побед', f'{total_matches_won} ({winrate}%)')}\n"
        f"{kv('ADR', adr)}   {kv('Урон', total_damage)}\n"
        f"{kv('Выстрелы', f'{total_shots_hit}/{total_shots_fired}')}\n"
        f"{kv('Бомбы', f'{total_planted} planted / {total_defused} defused')}\n"
        f"{kv('Убийства', f'нож {total_knife} | HE {total_he} | molotov {total_molotov} | flash {total_flash}')}"
    )


# ============================================================
#  /elo
# ============================================================

@dp.message(Command("elo"))
async def cmd_elo(message: types.Message):
    await delete_user_message(message)
    user_id = message.from_user.id
    user_data = get_user_data(user_id)
    if not user_data or not user_data[0]:
        await answer_and_track(message, "Сначала привяжи никнейм через /setnick.")
        return
    nickname = user_data[0]

    await clear_dashboard(user_id)
    loading_msg = await message.answer("Собираю данные по ELO...")

    # 1. Локальная история (реальные данные, копится трекером со временем)
    local_history = get_elo_history(user_id, limit=30)
    source_label = None
    elos = None

    if len(local_history) >= 2:
        elos = [row[0] for row in local_history]
        source_label = "данные трекера бота"
    else:
        player_data = await get_player_by_nickname(nickname)
        if not player_data:
            await loading_msg.edit_text("Игрок не найден.")
            return
        player_id = player_data['player_id']
        current_elo = player_data.get('games', {}).get('cs2', {}).get('faceit_elo')

        # 2. Попытка достать реальную историю ELO напрямую с Faceit
        remote = await fetch_remote_elo_points(player_id, size=30)
        if remote:
            elos = remote
            source_label = "данные Faceit"
        else:
            # 3. Faceit не отдал историю — строим оценку по результатам матчей
            history_data = await fetch_faceit_data(
                f"{FACEIT_API_BASE}/players/{player_id}/history?game=cs2&offset=0&limit=20"
            )
            items = history_data.get('items', []) if history_data else []
            results_newest_first = []
            for item in items:
                res = _match_result_for_player(item, player_id)
                if res is not None:
                    results_newest_first.append(res)

            if not results_newest_first or current_elo is None:
                await loading_msg.edit_text(
                    "Не удалось получить ни точную, ни оценочную историю ELO — "
                    "у Faceit нет истории матчей по этому нику или API недоступен."
                )
                return

            elos = estimate_elo_curve(int(current_elo), results_newest_first)
            source_label = "оценка по результатам матчей, не точные значения Faceit"

    delta = elos[-1] - elos[0]
    delta_str = f"{'+' if delta >= 0 else ''}{delta}"

    try:
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt

        fig, ax = plt.subplots(figsize=(8, 4))
        ax.plot(range(1, len(elos) + 1), elos, marker='o', color='#444444', linewidth=1.5)
        ax.set_title(f"ELO: {len(elos)} матчей, изменение {delta_str}")
        ax.set_xlabel("Матч")
        ax.set_ylabel("ELO")
        ax.grid(True, alpha=0.3)

        buf = io.BytesIO()
        fig.tight_layout()
        fig.savefig(buf, format='png', dpi=140)
        plt.close(fig)
        buf.seek(0)

        photo = types.BufferedInputFile(buf.read(), filename="elo.png")
        caption = f"{nickname} — изменение ELO: {delta_str}\nИсточник: {source_label}"
        sent = await bot.send_photo(chat_id=message.chat.id, photo=photo, caption=caption)
        await loading_msg.delete()
        await replace_dashboard(user_id, sent.chat.id, sent.message_id)
    except ImportError:
        text = (
            f"{section('ДИНАМИКА ELO: ' + nickname)}\n\n"
            + " -> ".join(str(e) for e in elos)
            + f"\n\n{kv('Изменение', delta_str)}\n"
            f"Источник: {source_label}"
        )
        await loading_msg.edit_text(text)
        await replace_dashboard(user_id, loading_msg.chat.id, loading_msg.message_id)


# ============================================================
#  /session
# ============================================================

@dp.message(Command("session"))
async def cmd_session(message: types.Message):
    await delete_user_message(message)
    user_id = message.from_user.id
    user_data = get_user_data(user_id)
    if not user_data or not user_data[0]:
        await answer_and_track(message, "Сначала привяжи никнейм через /setnick.")
        return
    nickname = user_data[0]

    args = message.text.split()
    explicit_reset = len(args) > 1 and args[1].lower() == 'reset'

    player_data = await get_player_by_nickname(nickname)
    if not player_data:
        await answer_and_track(message, "Игрок не найден.")
        return
    player_id = player_data['player_id']
    current_elo = player_data.get('games', {}).get('cs2', {}).get('faceit_elo')

    await clear_dashboard(user_id)

    session_row = get_session(user_id)
    now_ts = int(time.time())

    if explicit_reset or not session_row or not session_row[0]:
        window_seconds = 8 * 3600
        session_start_ts = now_ts - window_seconds

        history_data = await fetch_faceit_data(
            f"{FACEIT_API_BASE}/players/{player_id}/history?game=cs2&from={session_start_ts}&to={now_ts}&limit=100"
        )
        items = history_data.get('items', []) if history_data else []

        wins = losses = 0
        for item in items:
            res = _match_result_for_player(item, player_id)
            if res is True:
                wins += 1
            elif res is False:
                losses += 1

        is_estimate = True
        session_start_elo = None
        if current_elo is not None and (wins or losses):
            results_for_estimate = [True] * wins + [False] * losses
            curve = estimate_elo_curve(int(current_elo), results_for_estimate)
            session_start_elo = curve[0]
        elif current_elo is not None:
            session_start_elo = int(current_elo)
            is_estimate = False

        if explicit_reset:
            save_session(user_id, current_elo, ts=now_ts, is_estimate=False)
            await answer_and_track(message, f"Сессия сброшена. Стартовый ELO: {current_elo}")
            return

        save_session(user_id, session_start_elo, ts=session_start_ts, is_estimate=is_estimate)

        elo_delta = "N/A"
        if session_start_elo is not None and current_elo is not None:
            elo_delta = int(current_elo) - int(session_start_elo)
            elo_delta = f"{'+' if elo_delta >= 0 else ''}{elo_delta}"

        note = (
            "Точка старта не была задана вручную, поэтому окно взято "
            "автоматически (последние 8 часов). Задать свою точку отсчёта: /session reset."
        )
        estimate_note = " ELO на начало окна — оценка, не точное значение Faceit." if is_estimate else ""

        text = (
            f"{section('ТЕКУЩАЯ СЕССИЯ: ' + nickname)}\n\n"
            f"{kv('Окно', 'последние 8 часов (авто)')}\n"
            f"{kv('Сыграно матчей', wins + losses)}\n"
            f"{kv('W/L', f'{wins}/{losses}')}\n"
            f"{kv('ELO на начало окна', session_start_elo)}\n"
            f"{kv('Текущий ELO', f'{current_elo} ({elo_delta})')}\n\n"
            f"{note}{estimate_note}"
        )
        sent = await message.answer(text)
        await replace_dashboard(user_id, sent.chat.id, sent.message_id)
        return

    session_start_ts, session_start_elo, session_is_estimate = session_row

    history_data = await fetch_faceit_data(
        f"{FACEIT_API_BASE}/players/{player_id}/history?game=cs2&from={session_start_ts}&to={now_ts}&limit=100"
    )
    items = history_data.get('items', []) if history_data else []

    wins = losses = 0
    for item in items:
        res = _match_result_for_player(item, player_id)
        if res is True:
            wins += 1
        elif res is False:
            losses += 1

    elo_delta = "N/A"
    if session_start_elo is not None and current_elo is not None:
        elo_delta = int(current_elo) - int(session_start_elo)
        elo_delta = f"{'+' if elo_delta >= 0 else ''}{elo_delta}"

    duration_min = int((now_ts - session_start_ts) / 60)
    estimate_note = " (оценка, точное значение Faceit не отдаёт)" if session_is_estimate else ""

    text = (
        f"{section('ТЕКУЩАЯ СЕССИЯ: ' + nickname)}\n\n"
        f"{kv('Длительность', str(duration_min) + ' мин')}\n"
        f"{kv('Сыграно матчей', wins + losses)}\n"
        f"{kv('W/L', f'{wins}/{losses}')}\n"
        f"{kv('ELO на старте', str(session_start_elo) + estimate_note)}\n"
        f"{kv('Текущий ELO', f'{current_elo} ({elo_delta})')}\n\n"
        f"Сбросить сессию: /session reset"
    )
    sent = await message.answer(text)
    await replace_dashboard(user_id, sent.chat.id, sent.message_id)


# ============================================================
#  /compare
# ============================================================

@dp.message(Command("compare"))
async def cmd_compare(message: types.Message):
    await delete_user_message(message)
    user_id = message.from_user.id
    args = message.text.split()
    if len(args) < 3:
        await answer_and_track(message, "Использование: /compare ник1 ник2")
        return

    nick1, nick2 = args[1], args[2]
    await clear_dashboard(user_id)
    loading_msg = await message.answer(f"Сравниваю {nick1} и {nick2}...")

    async def fetch_profile(nickname):
        player_data = await get_player_by_nickname(nickname)
        if not player_data:
            return None
        player_id = player_data['player_id']
        stats_data = await fetch_faceit_data(f"{FACEIT_API_BASE}/players/{player_id}/stats/cs2")
        lifetime = stats_data.get('lifetime', {}) if stats_data else {}
        return {
            'nickname': nickname,
            'elo': player_data.get('games', {}).get('cs2', {}).get('faceit_elo', 'N/A'),
            'lvl': player_data.get('games', {}).get('cs2', {}).get('skill_level', 'N/A'),
            'matches': lifetime.get('Matches', 'N/A'),
            'winrate': lifetime.get('Win Rate %', 'N/A'),
            'kd': lifetime.get('Average K/D Ratio', 'N/A'),
            'hs': lifetime.get('Average Headshots %', 'N/A'),
            'streak': lifetime.get('Current Win Streak', '0'),
        }

    p1, p2 = await asyncio.gather(fetch_profile(nick1), fetch_profile(nick2))

    if not p1 or not p2:
        missing = nick1 if not p1 else nick2
        await loading_msg.edit_text(f"Игрок '{missing}' не найден.")
        return

    rows = [
        ["ELO", p1['elo'], p2['elo']],
        ["Уровень", p1['lvl'], p2['lvl']],
        ["Матчей", p1['matches'], p2['matches']],
        ["Винрейт %", p1['winrate'], p2['winrate']],
        ["K/D", p1['kd'], p2['kd']],
        ["Headshots %", p1['hs'], p2['hs']],
        ["Стрик", p1['streak'], p2['streak']],
    ]
    body = table(rows, headers=["Параметр", p1['nickname'], p2['nickname']])
    text = f"{section('СРАВНЕНИЕ ИГРОКОВ')}\n\n<code>{body}</code>"

    chart_bytes = render_compare_chart(p1, p2)
    if chart_bytes:
        await loading_msg.delete()
        photo = types.BufferedInputFile(chart_bytes, filename="compare.png")
        sent = await bot.send_photo(chat_id=message.chat.id, photo=photo, caption=text)
        await replace_dashboard(user_id, sent.chat.id, sent.message_id)
    else:
        await loading_msg.edit_text(text)
        await replace_dashboard(user_id, loading_msg.chat.id, loading_msg.message_id)


# ============================================================
#  /map
# ============================================================

@dp.message(Command("map"))
async def cmd_map(message: types.Message):
    await delete_user_message(message)
    user_id = message.from_user.id
    args = message.text.split(maxsplit=1)
    map_filter = None
    nickname = None

    if len(args) > 1:
        raw = args[1].strip()
        known_maps = ('mirage', 'inferno', 'dust2', 'nuke', 'overpass', 'ancient', 'anubis', 'vertigo', 'train')
        if raw.lower().startswith('de_') or raw.lower() in known_maps:
            map_filter = raw.lower()
        else:
            nickname = raw

    if not nickname:
        user_data = get_user_data(message.from_user.id)
        nickname = user_data[0] if user_data else None

    if not nickname:
        await answer_and_track(message, "Никнейм не указан и не сохранен. Используй /setnick [ник] или /map <название карты>.")
        return

    player_data = await get_player_by_nickname(nickname)
    if not player_data:
        await answer_and_track(message, "Игрок не найден.")
        return

    player_id = player_data['player_id']
    stats_data = await fetch_faceit_data(f"{FACEIT_API_BASE}/players/{player_id}/stats/cs2")
    if not stats_data:
        await answer_and_track(message, "Статистика CS2 не найдена.")
        return

    segments = stats_data.get('segments', [])
    maps_info = []
    for seg in segments:
        if seg.get('mode') == '5v5' and seg.get('type') == 'Map':
            map_stats = seg.get('stats', {})
            m_played = int(map_stats.get('Matches', '0').replace(',', ''))
            if m_played == 0:
                continue
            label = seg.get('label', 'Unknown')
            if map_filter and map_filter not in label.lower().replace(' ', ''):
                continue
            maps_info.append({
                'name': label,
                'matches': m_played,
                'winrate': map_stats.get('Win Rate %', '0'),
                'kd': map_stats.get('Average K/D Ratio', '0'),
                'wins': map_stats.get('Wins', '0'),
                'triple': map_stats.get('Triple Kills', '0'),
                'quadro': map_stats.get('Quadro Kills', '0'),
                'penta': map_stats.get('Penta Kills', '0'),
            })

    if not maps_info:
        await answer_and_track(message, f"Нет данных по картам{(' для ' + map_filter) if map_filter else ''} для {nickname}.")
        return

    await clear_dashboard(user_id)

    if map_filter:
        m = maps_info[0]
        wins_str = f"{m['wins']} ({m['winrate']}%)"
        kills_str = f"3K {m['triple']} | 4K {m['quadro']} | 5K {m['penta']}"
        text = (
            f"{section(m['name'] + ' — ' + nickname)}\n"
            f"{kv('Матчей', m['matches'])}\n"
            f"{kv('Побед', wins_str)}\n"
            f"{kv('K/D', m['kd'])}\n"
            f"{kv('Мультикиллы', kills_str)}\n"
        )
        sent = await message.answer(text)
        await replace_dashboard(user_id, sent.chat.id, sent.message_id)
    else:
        maps_info.sort(key=lambda x: x['matches'], reverse=True)
        rows = [[m['name'], m['matches'], f"{m['winrate']}%", m['kd']] for m in maps_info[:10]]
        body = table(rows, headers=["Карта", "M", "WR", "K/D"])
        text = f"{section('КАРТЫ: ' + nickname)}\n\n<code>{body}</code>"

        chart_bytes = render_map_chart(maps_info, nickname)
        if chart_bytes:
            photo = types.BufferedInputFile(chart_bytes, filename="maps.png")
            sent = await bot.send_photo(chat_id=message.chat.id, photo=photo, caption=text)
        else:
            sent = await message.answer(text)
        await replace_dashboard(user_id, sent.chat.id, sent.message_id)


# ============================================================
#  /top
# ============================================================

@dp.message(Command("top"))
async def cmd_top(message: types.Message):
    await delete_user_message(message)
    user_id = message.from_user.id

    accounts = get_distinct_nicknames()

    if not accounts:
        await answer_and_track(message, "База данных пока пуста. Некого сравнивать.")
        return

    await clear_dashboard(user_id)
    loading_msg = await message.answer("Собираю статистику со всех серверов Faceit...")

    now_ts = int(time.time())
    day_ago_ts = now_ts - 86400
    week_ago_ts = now_ts - 604800

    async def fetch_user_stats(nickname):
        player_data = await get_player_by_nickname(nickname)
        if not player_data:
            return None

        player_id = player_data['player_id']
        elo = player_data.get('games', {}).get('cs2', {}).get('faceit_elo', 0)

        stats_data = await fetch_faceit_data(f"{FACEIT_API_BASE}/players/{player_id}/stats/cs2")
        winrate = 0
        if stats_data:
            winrate = int(stats_data.get('lifetime', {}).get('Win Rate %', 0))

        history_24h = await fetch_faceit_data(f"{FACEIT_API_BASE}/players/{player_id}/history?game=cs2&from={day_ago_ts}&to={now_ts}&limit=50")
        history_7d = await fetch_faceit_data(f"{FACEIT_API_BASE}/players/{player_id}/history?game=cs2&from={week_ago_ts}&to={now_ts}&limit=150")

        matches_24h = len(history_24h['items']) if history_24h and 'items' in history_24h else 0
        matches_7d = len(history_7d['items']) if history_7d and 'items' in history_7d else 0

        return {'nickname': nickname, 'elo': elo, 'winrate': winrate, 'm_24h': matches_24h, 'm_7d': matches_7d}

    tasks = [fetch_user_stats(nick) for nick in accounts]
    results = await asyncio.gather(*tasks)
    valid_results = [r for r in results if r]

    if not valid_results:
        await loading_msg.edit_text("Не удалось загрузить данные ни для одного аккаунта.")
        return

    top_elo = sorted(valid_results, key=lambda x: x['elo'], reverse=True)[:3]
    top_wr = sorted(valid_results, key=lambda x: x['winrate'], reverse=True)[:3]
    top_24h = [p for p in sorted(valid_results, key=lambda x: x['m_24h'], reverse=True)[:3] if p['m_24h'] > 0]
    top_7d = [p for p in sorted(valid_results, key=lambda x: x['m_7d'], reverse=True)[:3] if p['m_7d'] > 0]

    def ranked_table(items, value_key, value_label):
        rows = [[str(i), p['nickname'], p[value_key]] for i, p in enumerate((items), 1)]
        return table(rows, headers=["#", "Игрок", value_label]) if rows else "нет данных"

    text = (
        f"{section('РЕЙТИНГ ИГРОКОВ БОТА')}\n\n"
        f"{section('Топ по ELO')}\n<code>{ranked_table(top_elo, 'elo', 'ELO')}</code>\n\n"
        f"{section('Топ по винрейту')}\n<code>{ranked_table(top_wr, 'winrate', 'WR%')}</code>\n\n"
        f"{section('Активность за 24 часа')}\n<code>{ranked_table(top_24h, 'm_24h', 'Матчи')}</code>\n\n"
        f"{section('Активность за 7 дней')}\n<code>{ranked_table(top_7d, 'm_7d', 'Матчи')}</code>"
    )
    await loading_msg.edit_text(text)
    await replace_dashboard(user_id, loading_msg.chat.id, loading_msg.message_id)


# ============================================================
#  Catch-all: любой текст, не попавший ни под одну команду
# ============================================================

@dp.callback_query(F.data.startswith("coach:"))
async def on_coach_callback(callback: types.CallbackQuery):
    user_id = int(callback.data.split(":", 1)[1])
    user_data = get_user_data(user_id)
    if not user_data or not user_data[0]:
        await callback.answer("Сначала привяжи никнейм через /setnick.")
        return
    nickname = user_data[0]

    await callback.answer("Анализирую...")

    player_data = await get_player_by_nickname(nickname)
    if not player_data:
        await callback.message.answer("Игрок не найден.")
        return
    player_id = player_data['player_id']
    stats_data = await fetch_faceit_data(f"{FACEIT_API_BASE}/players/{player_id}/stats/cs2")
    if not stats_data:
        await callback.message.answer("Статистика недоступна.")
        return

    analysis = await get_coach_analysis(stats_data, player_data, nickname, player_id)
    if analysis:
        # Telegram limit: 4096 chars per message. Split long analysis.
        chunks = []
        if len(analysis) <= 4000:
            chunks = [analysis]
        else:
            parts = analysis.split(chr(10))
            current = ""
            for part in parts:
                if len(current) + len(part) + 1 > 4000:
                    if current:
                        chunks.append(current)
                    current = part
                else:
                    current = current + chr(10) + part if current else part
            if current:
                chunks.append(current)
        for i, chunk in enumerate(chunks):
            try:
                await callback.message.answer(chunk)
            except Exception:
                try:
                    await callback.message.answer(chunk, parse_mode=None)
                except Exception:
                    if i == 0:
                        await callback.message.answer("ИИ-анализ получен, но не удалось его отправить.")
    else:
        await callback.message.answer("ИИ-анализ недоступен. Проверьте настройки.")


@dp.message()
async def catch_all(message: types.Message):
    """Обработчик всех текстовых сообщений, не попавших под команды.

    Если ai_mode=1 — передаём сообщение ИИ-консультанту.
    Иначе — показываем главное меню."""
    await delete_user_message(message)
    user_id = message.from_user.id

    # Проверяем режим ИИ
    if get_ai_mode(user_id):
        # Режим ИИ-консультаций активен
        user_text = message.text.strip()
        if not user_text:
            await answer_and_track(message, "Напиши свой вопрос о CS2.")
            return

        await clear_dashboard(user_id)
        loading_msg = await message.answer("🤖 Думаю...")

        # Импортируем модуль с функциями для ИИ
        from .. import ai_functions
        response = await get_ai_chat_response(user_text, user_id, ai_functions)

        if response:
            try:
                await loading_msg.edit_text(response)
                await replace_dashboard(user_id, loading_msg.chat.id, loading_msg.message_id)
            except Exception:
                try:
                    await loading_msg.edit_text(response, parse_mode=None)
                    await replace_dashboard(user_id, loading_msg.chat.id, loading_msg.message_id)
                except Exception:
                    await loading_msg.edit_text("Ошибка при отправке ответа ИИ.")
        else:
            await loading_msg.edit_text("ИИ-консультант временно недоступен. Проверьте установку пакета anthropic.")
    else:
        # Обычный режим — показываем меню
        await clear_dashboard(user_id)
        from ..menu import menu_root_text, main_menu_keyboard
        sent = await message.answer(menu_root_text(), reply_markup=main_menu_keyboard())
        await replace_dashboard(user_id, sent.chat.id, sent.message_id)
