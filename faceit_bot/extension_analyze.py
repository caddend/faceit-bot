"""Обработчик запросов анализа матчей из расширения.

Расширение шлёт match_id → Worker кладёт в KV → этот модуль поллит KV →
загружает данные матча → вызывает prematch.py → отправляет результат в бот.
"""
import asyncio
import logging

from aiogram import Bot

from .config import WEBAPP_URL, WEBAPP_AUTH_SECRET, FACEIT_API_BASE
from .prematch import collect_prematch_data, call_prematch_llm
from .coach import _sanitize_for_telegram
from .balance import get_balance_footer

logger = logging.getLogger(__name__)


async def poll_analyze_requests(bot: Bot):
    """Поллит Worker KV для запросов анализа матчей из расширения.

    Формат ключа в KV: analyze_request:{link_token}:{timestamp}
    Запускается как фоновая задача.
    """
    import aiohttp

    while True:
        try:
            # Получаем все ключи с префиксом analyze_request:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{WEBAPP_URL}/api/kv-list?prefix=analyze_request:",
                    headers={"X-Auth-Secret": WEBAPP_AUTH_SECRET},
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

    1. Читает данные из KV (user_id, match_id, faceit_session_token)
    2. Загружает данные матча через Browser API
    3. Собирает данные команд
    4. Вызывает ИИ-анализ
    5. Отправляет результат в Telegram
    6. Удаляет ключ из KV
    """
    try:
        # Читаем данные запроса
        async with session.get(
            f"{WEBAPP_URL}/api/kv-get?key={key}",
            headers={"X-Auth-Secret": WEBAPP_AUTH_SECRET},
            timeout=10
        ) as resp:
            if resp.status != 200:
                return
            request_data = await resp.json()

        user_id = request_data.get('user_id')
        match_id = request_data.get('match_id')
        faceit_session_token = request_data.get('faceit_session_token')

        print(f"[ANALYZE] user_id={user_id}, match_id={match_id}, has_token={bool(faceit_session_token)}")

        if not user_id or not match_id:
            await delete_kv_key(session, key)
            return

        # Загружаем данные матча напрямую через Browser API
        match_data = await fetch_match_data(session, match_id, faceit_session_token)
        if not match_data:
            await bot.send_message(user_id, "⚠️ Не удалось загрузить данные матча. Проверь ссылку.")
            await delete_kv_key(session, key)
            return

        # Собираем данные команд (как в prematch.py)
        prematch_data = await collect_prematch_data(match_data, faceit_session_token)
        if not prematch_data:
            await bot.send_message(user_id, "⚠️ Не удалось собрать данные команд.")
            await delete_kv_key(session, key)
            return

        # Вызываем ИИ-анализ
        analysis = await call_prematch_llm(prematch_data)
        if not analysis:
            await bot.send_message(user_id, "⚠️ ИИ-анализ не удался.")
            await delete_kv_key(session, key)
            return

        # Форматируем и отправляем результат
        text = _sanitize_for_telegram(analysis)
        footer = await get_balance_footer()
        final_text = f"{text}\n\n{footer}" if footer else text

        await bot.send_message(user_id, final_text, parse_mode="Markdown")

        # Удаляем ключ из KV
        await delete_kv_key(session, key)

    except Exception as e:
        logger.error(f"[extension_analyze] process error for {key}: {e}")
        # Всё равно удаляем ключ чтобы не зациклиться
        try:
            await delete_kv_key(session, key)
        except:
            pass


async def fetch_match_data(session, match_id: str, faceit_session_token: str = None):
    """Загружает данные матча через Browser API (если есть токен) или Data API.

    Возвращает dict с ключами: match_id, teams (faction1, faction2), rosters, etc.
    """
    # Пробуем Browser API (если есть session token)
    if faceit_session_token:
        url = f"https://api.faceit.com/match/v2/match/{match_id}"
        headers = {
            "Authorization": f"Bearer {faceit_session_token}",
            "User-Agent": "Mozilla/5.0"
        }
        try:
            async with session.get(url, headers=headers, timeout=12) as resp:
                print(f"[Browser API] match status={resp.status}, match_id={match_id}")
                if resp.status == 200:
                    data = await resp.json()
                    payload = data.get('payload')
                    if payload:
                        return payload
        except Exception as e:
            print(f"[Browser API] match error: {e}")

    # Fallback: Data API (публичный, но может не видеть матчи в лобби)
    url = f"{FACEIT_API_BASE}/matches/{match_id}"
    try:
        async with session.get(url, timeout=12) as resp:
            print(f"[Data API] match status={resp.status}, match_id={match_id}")
            if resp.status == 200:
                return await resp.json()
    except Exception as e:
        print(f"[Data API] match error: {e}")

    return None


async def delete_kv_key(session, key: str):
    """Удаляет ключ из Worker KV."""
    try:
        async with session.delete(
            f"{WEBAPP_URL}/api/kv-delete?key={key}",
            headers={"X-Auth-Secret": WEBAPP_AUTH_SECRET},
            timeout=10
        ) as resp:
            pass
    except Exception as e:
        logger.error(f"[extension_analyze] delete key error: {e}")
