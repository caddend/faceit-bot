"""Фоновые задачи: трекер матчей, воркер отложенного удаления,
вечерний ИИ-отчёт о сессии (22:00 МСК).

background_match_tracker — проверяет новые матчи у привязанных пользователей,
отправляет авто-отчёты и логирует ELO.

scheduled_delete_worker — раз в минуту удаляет сообщения, у которых истёк TTL.

evening_session_report — каждый день в 22:00 МСК (19:00 UTC) собирает
статистику дневной сессии для каждого игрока и просит ИИ написать отчёт ~200 слов.
"""
import asyncio
from datetime import datetime, timedelta, timezone

from .runtime import bot, _api_cache
from .config import FACEIT_API_BASE, ANTHROPIC_BASE_URL, ANTHROPIC_AUTH_TOKEN, ANTHROPIC_MODEL
from .db import (
    get_all_tracked_users,
    get_due_deletes,
    delete_scheduled_row,
    update_last_match,
    log_elo,
    schedule_delete,
)
from .faceit_api import get_player_by_nickname, fetch_faceit_data, get_match_stats_text, _match_result_for_player
from .coach import _sanitize_for_telegram, _ANTHROPIC_AVAILABLE
from .formatting import section
from .prematch import get_prematch_analysis, is_prematch_sent
from .db import get_faceit_session_token
from .balance import get_balance_footer

try:
    from anthropic import Anthropic as _Anthropic
except ImportError:
    _Anthropic = None


async def background_match_tracker():
    await asyncio.sleep(5)
    print("Фоновый трекер матчей запущен.")

    while True:
        try:
            users = get_all_tracked_users()

            for user_id, nickname, last_match_id, notify in users:
                player_data = await get_player_by_nickname(nickname)
                if not player_data:
                    continue
                player_id = player_data['player_id']

                history_data = await fetch_faceit_data(f"{FACEIT_API_BASE}/players/{player_id}/history?game=cs2&offset=0&limit=1")
                if not history_data or not history_data.get('items'):
                    continue

                latest_item = history_data['items'][0]
                latest_match_id = latest_item['match_id']
                match_status = latest_item.get('status', '')

                # --- Предматч-анализ: пытаемся найти идущий матч ---
                # Faceit может не показывать ONGOING в history, поэтому
                # get_prematch_analysis сама определяет идущий ли матч.
                if notify and not is_prematch_sent(latest_match_id):
                    try:
                        session_token = get_faceit_session_token(user_id)
                        prematch_text, prematch_mid = await get_prematch_analysis(player_id, nickname, session_token)
                        if prematch_text and prematch_mid:
                            sent = await bot.send_message(
                                chat_id=user_id,
                                text=f"{section('⚡ ПРЕДМАТЧ-АНАЛИЗ')}\n\n{prematch_text}"
                            )
                            schedule_delete(sent.chat.id, sent.message_id)
                    except Exception:
                        pass

                # --- Постматч: матч завершён ---
                if last_match_id is None:
                    update_last_match(user_id, latest_match_id)
                elif latest_match_id != last_match_id and match_status.lower() == 'finished':
                    update_last_match(user_id, latest_match_id)
                    text, current_elo = await get_match_stats_text(latest_match_id, player_id, nickname)

                    log_elo(user_id, latest_match_id, current_elo)

                    if notify:
                        sent = await bot.send_message(
                            chat_id=user_id,
                            text=f"{section('АВТО-ОТЧЕТ: МАТЧ ОКОНЧЕН')}\n\n{text}"
                        )
                        schedule_delete(sent.chat.id, sent.message_id)

                await asyncio.sleep(2)

        except Exception:
            pass

        await asyncio.sleep(60)


async def scheduled_delete_worker():
    """Фоновая задача: раз в минуту проверяет, какие сообщения пора удалить,
    и чистит их. Переживает перезапуск бота, т.к. хранится в БД."""
    await asyncio.sleep(10)
    print("Воркер отложенного удаления запущен.")
    while True:
        try:
            due = get_due_deletes()
            for rowid, chat_id, message_id in due:
                try:
                    await bot.delete_message(chat_id=chat_id, message_id=message_id)
                except Exception:
                    pass  # сообщение уже могло быть удалено вручную/заменено
                delete_scheduled_row(rowid)
        except Exception:
            pass
        await asyncio.sleep(60)


# ============================================================
#  Вечерний ИИ-отчёт о сессии — 22:00 МСК (19:00 UTC)
# ============================================================

_MSK = timezone(timedelta(hours=3))


def _seconds_until_evening() -> float:
    """Сколько секунд осталось до 22:00 МСК (19:00 UTC)."""
    now_utc = datetime.now(timezone.utc)
    target = now_utc.replace(hour=19, minute=0, second=0, microsecond=0)
    if now_utc >= target:
        target += timedelta(days=1)
    return (target - now_utc).total_seconds()


async def _collect_session_summary(user_id: int, nickname: str) -> str | None:
    """Собирает compact-текст дневной сессии для промпта.

    Возвращает None если матчей сегодня не было или данные недоступны.
    """
    player_data = await get_player_by_nickname(nickname)
    if not player_data:
        return None

    player_id = player_data['player_id']
    current_elo = player_data.get('games', {}).get('cs2', {}).get('faceit_elo', 'N/A')
    lvl = player_data.get('games', {}).get('cs2', {}).get('skill_level', 'N/A')

    # Полночь МСК сегодня → сейчас
    now_msk = datetime.now(_MSK)
    midnight_msk = now_msk.replace(hour=0, minute=0, second=0, microsecond=0)
    from_ts = int(midnight_msk.timestamp())
    to_ts = int(now_msk.timestamp())

    history_data = await fetch_faceit_data(
        f"{FACEIT_API_BASE}/players/{player_id}/history?game=cs2&from={from_ts}&to={to_ts}&limit=100"
    )
    items = history_data.get('items', []) if history_data else []
    if not items:
        return None

    wins = losses = 0
    match_lines = []
    for item in items:
        res = _match_result_for_player(item, player_id)
        outcome = "W" if res is True else ("L" if res is False else "?")
        if res is True:
            wins += 1
        elif res is False:
            losses += 1
        map_name = item.get('i1', {}).get('map', 'Unknown')
        if not map_name or map_name == 'Unknown':
            map_name = item.get('game_mode', 'Unknown')
        match_lines.append(f"{outcome} | {map_name}")

    # K/D последнего матча
    last_kd = "N/A"
    last_map = "N/A"
    last_match_id = items[0].get('match_id')
    if last_match_id:
        try:
            text, _ = await get_match_stats_text(last_match_id, player_id, nickname)
            import re
            m = re.search(r'K/D:\s*<b>([\d.]+)</b>', text)
            if m:
                last_kd = m.group(1)
            map_match = re.search(r'Карта:\s*<b>([^<]+)</b>', text)
            if map_match:
                last_map = map_match.group(1)
        except Exception:
            pass

    total_matches = wins + losses
    wr = round(wins / total_matches * 100) if total_matches else 0

    matches_str = "\n".join(match_lines)
    session_summary = (
        f"Игрок: {nickname}\n"
        f"ELO: {current_elo}, Уровень: {lvl}\n"
        f"Матчей сегодня: {total_matches} (W {wins} / L {losses}), Винрейт: {wr}%\n"
        f"Последний матч — карта: {last_map}, K/D: {last_kd}\n"
        f"Матчи (результат | карта):\n{matches_str}"
    )

    return session_summary


def _call_evening_llm(session_summary: str, nickname: str) -> str | None:
    """Синхронный вызов LLM для вечернего отчёта."""
    if not _ANTHROPIC_AVAILABLE or not _Anthropic:
        return None

    system_prompt = (
        "Ты — CS2 тренер. Игрок закончил игровую сессию за сегодня. "
        "Дай краткий отчёт (~200 слов) на русском: как прошла сессия, "
        "что получилось хорошо, что нужно подтянуть, совет на завтра. "
        "Используй HTML-теги <b>...</b> для акцентов. "
        "НЕ используй markdown (#, ##, *, **, __). "
        "Пиши обычный текст, выделяй важное через <b>...</b>."
    )
    user_prompt = (
        f"Сессия игрока {nickname} за сегодня:\n{session_summary}\n\n"
        "Дай вечерний отчёт (~200 слов)."
    )

    try:
        client = _Anthropic(api_key=ANTHROPIC_AUTH_TOKEN, base_url=ANTHROPIC_BASE_URL)
        resp = client.messages.create(
            model=ANTHROPIC_MODEL,
            max_tokens=512,
            system=system_prompt,
            messages=[
                {"role": "user", "content": user_prompt},
            ],
        )
        return resp.content[0].text
    except Exception:
        return None


async def evening_session_report():
    """Каждый день в 22:00 МСК собирает ИИ-отчёт о дневной сессии
    для всех привязанных игроков. Если матчей сегодня не было — пропускает."""
    await asyncio.sleep(15)
    print("Вечерний ИИ-отчёт запущен. Ожидание 22:00 МСК.")

    while True:
        try:
            sleep_s = _seconds_until_evening()
            print(f"Вечерний отчёт: следующее срабатывание через {int(sleep_s)} сек (~{int(sleep_s / 3600)} ч).")
            await asyncio.sleep(sleep_s)

            users = get_all_tracked_users()
            print(f"Вечерний отчёт 22:00 МСК: {len(users)} пользователь(ей).")

            for user_id, nickname, last_match_id, notify in users:
                try:
                    session_summary = await _collect_session_summary(user_id, nickname)
                    if not session_summary:
                        # Матчей сегодня не было — пропускаем, не спамим
                        continue

                    report = await asyncio.to_thread(_call_evening_llm, session_summary, nickname)
                    if not report:
                        continue

                    report = _sanitize_for_telegram(report)
                    balance_footer = await get_balance_footer()
                    text = f"{section('ВЕЧЕРНИЙ ОТЧЁТ: ' + nickname)}\n\n{report}{balance_footer}"

                    try:
                        await bot.send_message(chat_id=user_id, text=text)
                    except Exception:
                        try:
                            await bot.send_message(chat_id=user_id, text=text, parse_mode=None)
                        except Exception:
                            pass

                except Exception:
                    pass

                await asyncio.sleep(2)

        except Exception:
            pass

        await asyncio.sleep(30)
