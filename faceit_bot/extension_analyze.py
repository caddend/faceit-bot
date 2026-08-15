"""Обработчик запросов анализа чужих игроков из расширения.

Расширение шлёт nickname → Worker кладёт в KV → этот модуль поллит KV →
находит активный матч → вызывает prematch.py → отправляет результат в бот.
"""
import asyncio
import logging

from aiogram import Bot

from .config import CLOUDFLARE_WORKER_URL, CLOUDFLARE_AUTH_SECRET
from .prematch import get_ongoing_match, collect_prematch_data, call_prematch_llm
from .coach import _sanitize_for_telegram
from .balance import get_balance_footer
from .faceit_api import fetch_faceit_data
from .config import FACEIT_API_BASE

logger = logging.getLogger(__name__)


async def poll_analyze_requests(bot: Bot):
    """Поллит Worker KV для запросов анализа чужих игроков из расширения.

    Формат ключа в KV: analyze_request:{link_token}:{timestamp}
    Запускается как фоновая задача.
    """
    import aiohttp

    while True:
        try:
            # Получаем все ключи с префиксом analyze_request:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{CLOUDFLARE_WORKER_URL}/api/kv-list?prefix=analyze_request:",
                    headers={"X-Auth-Secret": CLOUDFLARE_AUTH_SECRET},
                    timeout=10
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        keys = data.get('keys', [])

                        for key in keys:
                            await process_analyze_request(bot, session, key)
        except Exception as e:
            logger.error(f"[extension_analyze] poll error: {e}")

        await asyncio.sleep(5)  # Поллим каждые 5 секунд


async def process_analyze_request(bot: Bot, session, key: str):
    """Обрабатывает один запрос анализа.

    1. Читает данные из KV (user_id, target_nickname)
    2. Получает player_id по nickname
    3. Ищет активный матч игрока
    4. Собирает данные команд
    5. Вызывает ИИ-анализ
    6. Отправляет результат в Telegram
    7. Удаляет ключ из KV
    """
    try:
        # Читаем данные запроса
        async with session.get(
            f"{CLOUDFLARE_WORKER_URL}/api/kv-get?key={key}",
            headers={"X-Auth-Secret": CLOUDFLARE_AUTH_SECRET},
            timeout=10
        ) as resp:
            if resp.status != 200:
                return
            request_data = await resp.json()

        user_id = request_data.get('user_id')
        target_nickname = request_data.get('target_nickname')

        if not user_id or not target_nickname:
            await delete_kv_key(session, key)
            return

        # Получаем player_id по nickname
        profile = await fetch_faceit_data(
            f"{FACEIT_API_BASE}/players?nickname={target_nickname}"
        )
        if not profile or not profile.get('player_id'):
            await bot.send_message(
                user_id,
                f"❌ Игрок <b>{target_nickname}</b> не найден на Faceit.",
                parse_mode="HTML"
            )
            await delete_kv_key(session, key)
            return

        player_id = profile['player_id']

        # Ищем активный матч (без session token — только Data API)
        ongoing_match = await get_ongoing_match(player_id, faceit_session_token=None)
        if not ongoing_match:
            await bot.send_message(
                user_id,
                f"⚠️ У игрока <b>{target_nickname}</b> нет активного матча.",
                parse_mode="HTML"
            )
            await delete_kv_key(session, key)
            return

        match_id = ongoing_match.get('match_id', '')

        # Собираем данные команд
        prematch_data = await collect_prematch_data(ongoing_match, player_id)
        if not prematch_data:
            await bot.send_message(
                user_id,
                f"⚠️ Не удалось собрать данные о матче игрока <b>{target_nickname}</b>.",
                parse_mode="HTML"
            )
            await delete_kv_key(session, key)
            return

        # Вызываем ИИ-анализ
        text = await asyncio.to_thread(call_prematch_llm, prematch_data, target_nickname)
        if not text:
            await bot.send_message(
                user_id,
                f"⚠️ ИИ-анализ недоступен для игрока <b>{target_nickname}</b>.",
                parse_mode="HTML"
            )
            await delete_kv_key(session, key)
            return

        # Отправляем результат
        final_text = (
            f"<b>Анализ матча игрока {target_nickname}</b>\n"
            f"Match ID: <code>{match_id}</code>\n\n"
            f"{_sanitize_for_telegram(text)}"
            f"{await get_balance_footer()}"
        )

        await bot.send_message(user_id, final_text, parse_mode="HTML")

        # Удаляем обработанный запрос
        await delete_kv_key(session, key)
        logger.info(f"[extension_analyze] Sent analysis for {target_nickname} to user {user_id}")

    except Exception as e:
        logger.error(f"[extension_analyze] process error for key {key}: {e}")
        # Удаляем ключ чтобы не зациклиться
        try:
            await delete_kv_key(session, key)
        except:
            pass


async def delete_kv_key(session, key: str):
    """Удаляет ключ из Worker KV."""
    try:
        async with session.delete(
            f"{CLOUDFLARE_WORKER_URL}/api/kv-delete?key={key}",
            headers={"X-Auth-Secret": CLOUDFLARE_AUTH_SECRET},
            timeout=5
        ) as resp:
            pass
    except:
        pass
