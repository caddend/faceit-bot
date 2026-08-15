"""Хендлеры команд матчей: /last, /history, /<number>, /activity.
"""
import re
import time

from aiogram import types
from aiogram.filters import Command

from ..runtime import dp, bot, match_cache
from ..config import FACEIT_API_BASE
from ..db import resolve_nickname, schedule_delete
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
    get_match_text_only,
)
from ..charts import render_activity_chart
from ..formatting import section, kv, table
from ..prematch import get_prematch_analysis


@dp.message(Command("last"))
async def cmd_last(message: types.Message):
    await delete_user_message(message)
    user_id = message.from_user.id
    nickname = resolve_nickname(message, message.text.split())
    if not nickname:
        await answer_and_track(message, "Никнейм не указан и не сохранен. Используй /setnick [ник].")
        return

    player_data = await get_player_by_nickname(nickname)
    if not player_data:
        await answer_and_track(message, "Игрок не найден.")
        return
    player_id = player_data['player_id']

    history_data = await fetch_faceit_data(f"{FACEIT_API_BASE}/players/{player_id}/history?game=cs2&offset=0&limit=1")
    if not history_data or not history_data.get('items'):
        await answer_and_track(message, "История матчей пуста.")
        return

    match_id = history_data['items'][0]['match_id']

    await clear_dashboard(user_id)
    loading_msg = await message.answer("Генерирую сводку и скорборд...")
    text = await get_match_text_only(match_id, player_id, nickname)
    await loading_msg.edit_text(text)
    await replace_dashboard(user_id, loading_msg.chat.id, loading_msg.message_id)
    schedule_delete(loading_msg.chat.id, loading_msg.message_id)


@dp.message(Command("prematch"))
async def cmd_prematch(message: types.Message):
    await delete_user_message(message)
    user_id = message.from_user.id
    nickname = resolve_nickname(message, message.text.split())
    if not nickname:
        await answer_and_track(message, "Никнейм не указан и не сохранен. Используй /setnick [ник].")
        return

    player_data = await get_player_by_nickname(nickname)
    if not player_data:
        await answer_and_track(message, "Игрок не найден.")
        return
    player_id = player_data['player_id']

    await clear_dashboard(user_id)
    loading_msg = await message.answer("Ищу активный матч и анализирую составы...")

    text, match_id = await get_prematch_analysis(player_id, nickname)
    if not text:
        await loading_msg.edit_text(
            "Нет активного матча. Возможно, матч ещё не начался или уже завершён.\n"
            "Используй /prematch когда матч найден и идёт лобби."
        )
        await replace_dashboard(user_id, loading_msg.chat.id, loading_msg.message_id)
        return

    await loading_msg.edit_text(f"{section('ПРЕДМАТЧ-АНАЛИЗ')}\n\n{text}")
    await replace_dashboard(user_id, loading_msg.chat.id, loading_msg.message_id)
    schedule_delete(loading_msg.chat.id, loading_msg.message_id)


@dp.message(Command("history"))
async def cmd_history(message: types.Message):
    await delete_user_message(message)
    user_id = message.from_user.id
    nickname = resolve_nickname(message, message.text.split())
    if not nickname:
        await answer_and_track(message, "Никнейм не указан и не сохранен. Используй /setnick [ник].")
        return

    player_data = await get_player_by_nickname(nickname)
    if not player_data:
        await answer_and_track(message, "Игрок не найден.")
        return
    player_id = player_data['player_id']

    await clear_dashboard(user_id)
    loading_msg = await message.answer("Загружаю и анализирую историю матчей...")

    history_data = await fetch_faceit_data(f"{FACEIT_API_BASE}/players/{player_id}/history?game=cs2&offset=0&limit=15")
    if not history_data or not history_data.get('items'):
        await loading_msg.edit_text("История матчей пуста.")
        return

    matches = history_data['items']
    match_cache[user_id] = {'nickname': nickname, 'player_id': player_id, 'match_ids': []}

    async def get_history_row(item, index):
        match_id = item['match_id']
        res = _match_result_for_player(item, player_id)
        outcome = "WIN" if res else "LOSS" if res is False else "N/A"

        score_data = item.get('results', {}).get('score', {})
        s1 = score_data.get('faction1', 0)
        s2 = score_data.get('faction2', 0)

        match_stats = await fetch_faceit_data(f"{FACEIT_API_BASE}/matches/{match_id}/stats")
        map_name = "Unknown"
        kd = "0"

        if match_stats and match_stats.get('rounds'):
            map_name = match_stats['rounds'][0]['round_stats'].get('Map', 'Unknown')
            for team in match_stats['rounds'][0]['teams']:
                for p in team['players']:
                    if p['player_id'] == player_id:
                        kd = p['player_stats'].get('K/D Ratio', '0')
                        break

        return [f"/{index}", outcome, f"{s1}:{s2}", map_name, kd]

    tasks = []
    for i, item in enumerate(matches):
        match_cache[user_id]['match_ids'].append(item['match_id'])
        tasks.append(get_history_row(item, i + 1))

    import asyncio
    rows = await asyncio.gather(*tasks)
    body = table(rows, headers=["#", "Итог", "Счёт", "Карта", "K/D"])

    final_text = (
        f"{section('ИСТОРИЯ МАТЧЕЙ: ' + nickname)}\n\n"
        f"<code>{body}</code>\n\n"
        f"Отправь номер матча (например /1) для просмотра скорборда."
    )

    await loading_msg.edit_text(final_text)
    await replace_dashboard(user_id, loading_msg.chat.id, loading_msg.message_id)


@dp.message(lambda message: re.match(r'^/([1-9]|[1-2][0-9]|30)$', message.text))
async def cmd_specific_match(message: types.Message):
    await delete_user_message(message)
    user_id = message.from_user.id
    if user_id not in match_cache or not match_cache[user_id].get('match_ids'):
        await answer_and_track(message, "Кэш матчей пуст. Сначала вызови команду /history")
        return

    index = int(message.text[1:]) - 1
    match_ids = match_cache[user_id]['match_ids']

    if index >= len(match_ids):
        await answer_and_track(message, "Матч с таким номером не найден в истории.")
        return

    match_id = match_ids[index]
    player_id = match_cache[user_id]['player_id']
    nickname = match_cache[user_id]['nickname']

    await clear_dashboard(user_id)
    loading_msg = await message.answer("Генерирую сводку и скорборд...")
    text = await get_match_text_only(match_id, player_id, nickname, index=index + 1)
    await loading_msg.edit_text(text)
    await replace_dashboard(user_id, loading_msg.chat.id, loading_msg.message_id)
    schedule_delete(loading_msg.chat.id, loading_msg.message_id)


@dp.message(Command("activity"))
async def cmd_activity(message: types.Message):
    await delete_user_message(message)
    user_id = message.from_user.id
    nickname = resolve_nickname(message, message.text.split())
    if not nickname:
        await answer_and_track(message, "Никнейм не указан и не сохранен. Используй /setnick [ник].")
        return

    player_data = await get_player_by_nickname(nickname)
    if not player_data:
        await answer_and_track(message, "Игрок не найден.")
        return
    player_id = player_data['player_id']

    await clear_dashboard(user_id)
    loading_msg = await message.answer("Собираю активность за последние 30 дней...")

    now_ts = int(time.time())
    from_ts = now_ts - 30 * 86400

    # Пагинация на случай, если за 30 дней сыграно больше 100 матчей.
    items = []
    offset = 0
    while offset < 300:
        page = await fetch_faceit_data(
            f"{FACEIT_API_BASE}/players/{player_id}/history?game=cs2&from={from_ts}&to={now_ts}&offset={offset}&limit=100"
        )
        page_items = page.get('items', []) if page else []
        if not page_items:
            break
        items.extend(page_items)
        if len(page_items) < 100:
            break
        offset += 100

    if not items:
        await loading_msg.edit_text(f"За последние 30 дней матчей не найдено для {nickname}.")
        await replace_dashboard(user_id, loading_msg.chat.id, loading_msg.message_id)
        return

    # Бакеты по дням (UTC), от старых к новым, все 30 дней присутствуют
    # даже если в какой-то день матчей не было.
    day_buckets = {}
    for i in range(29, -1, -1):
        date_key = time.strftime('%Y-%m-%d', time.gmtime(now_ts - i * 86400))
        day_buckets[date_key] = {'wins': 0, 'losses': 0}

    for item in items:
        ts = item.get('finished_at') or item.get('started_at')
        if not ts:
            continue
        date_key = time.strftime('%Y-%m-%d', time.gmtime(ts))
        if date_key not in day_buckets:
            continue
        res = _match_result_for_player(item, player_id)
        if res is True:
            day_buckets[date_key]['wins'] += 1
        elif res is False:
            day_buckets[date_key]['losses'] += 1

    days_data = [{'date': d, 'wins': v['wins'], 'losses': v['losses']} for d, v in sorted(day_buckets.items())]

    total_matches = sum(d['wins'] + d['losses'] for d in days_data)
    active_days = sum(1 for d in days_data if (d['wins'] + d['losses']) > 0)
    avg_active = round(total_matches / active_days, 1) if active_days else 0
    busiest = max(days_data, key=lambda d: d['wins'] + d['losses'])
    busiest_count = busiest['wins'] + busiest['losses']
    busiest_str = f"{busiest['date']} ({busiest_count} матчей)" if busiest_count else "нет игр"

    summary_text = (
        f"{section('АКТИВНОСТЬ ЗА 30 ДНЕЙ: ' + nickname)}\n\n"
        f"{kv('Всего матчей', total_matches)}\n"
        f"{kv('Играл дней', f'{active_days} из 30')}\n"
        f"{kv('Среднее в игровой день', avg_active)}\n"
        f"{kv('Самый активный день', busiest_str)}\n\n"
        f"Даты приведены по UTC."
    )

    chart_bytes = render_activity_chart(days_data, nickname)
    if chart_bytes:
        await loading_msg.delete()
        photo = types.BufferedInputFile(chart_bytes, filename="activity.png")
        sent = await bot.send_photo(chat_id=message.chat.id, photo=photo, caption=summary_text)
    else:
        await loading_msg.edit_text(summary_text)
        sent = loading_msg
    await replace_dashboard(user_id, sent.chat.id, sent.message_id)
