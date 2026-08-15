"""Управление сообщениями ('экранами') в чате.

Автоудаление сообщений отключено — все функции-заглушки (no-op).
Сообщения бота и пользователя остаются в чате.
"""
from aiogram import types

from .runtime import bot
from .db import (
    get_active_message,
    set_active_message,
)


async def replace_dashboard(user_id: int, chat_id: int, message_id: int):
    """No-op: не удаляем предыдущие сообщения."""
    set_active_message(user_id, chat_id, message_id)


async def clear_dashboard(user_id: int):
    """No-op: не удаляем предыдущие сообщения."""
    pass


async def delete_user_message(message: types.Message):
    """No-op: не удаляем сообщение пользователя."""
    pass


async def answer_and_track(message: types.Message, text: str):
    """Простой ответ без автоудаления."""
    sent = await message.answer(text)
    set_active_message(message.from_user.id, sent.chat.id, sent.message_id)
    return sent
