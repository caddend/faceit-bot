"""Команда /announce — рассылка уведомления всем пользователям.

Доступна только админам (config.ADMIN_IDS). Использование:
  /announce <текст>            — разослать этот текст всем с привязанным ником
  /announce                    — разослать дефолтное сообщение про расширение
"""
import asyncio

from aiogram import types, F
from aiogram.filters import Command

from ..runtime import dp, bot
from ..config import ADMIN_IDS
from ..db import get_all_user_ids_with_nick
from ..dashboard import answer_and_track


def _is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


DEFAULT_ANNOUNCE = (
    "<b>Обновление бота</b>\n\n"
    "Появилось <b>расширение для текущих матчей</b> — теперь бот видит "
    "идущий матч на faceit.com, собирает составы команд и шлёт ИИ-анализ "
    "прямо в этот чат. Токен Faceit добывать вручную больше не нужно.\n\n"
    "Установка (один раз):\n"
    "1. /facelogin — получи токен привязки и ссылку на расширение\n"
    "2. Скачай, распакуй, загрузи в браузер (Chrome/Edge/Яндекс/Firefox)\n"
    "3. Кликни иконку расширения → вставь токен\n\n"
    "Подробно — /facelogin."
)


async def broadcast(text: str) -> tuple[int, int]:
    """Рассылает text всем с привязанным ником. Возвращает (sent, failed)."""
    user_ids = get_all_user_ids_with_nick()
    sent = 0
    failed = 0
    for uid in user_ids:
        try:
            await bot.send_message(chat_id=uid, text=text, disable_web_page_preview=True)
            sent += 1
        except Exception:
            failed += 1
        await asyncio.sleep(0.05)  # бережём Telegram rate-limit
    return sent, failed


@dp.message(Command("announce"))
async def cmd_announce(message: types.Message):
    if not _is_admin(message.from_user.id):
        await answer_and_track(message, "Команда доступна только администратору.")
        return

    args = message.text.split(maxsplit=1)
    text = (args[1].strip() if len(args) >= 2 and args[1].strip() else DEFAULT_ANNOUNCE)

    sent, failed = await broadcast(text)
    await answer_and_track(
        message,
        f"Рассылка завершена.\nДоставлено: {sent}\nНе удалось: {failed}\nВсего: {sent + failed}",
    )
