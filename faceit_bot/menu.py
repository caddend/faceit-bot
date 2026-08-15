"""Меню команд: разбивка на вкладки inline-кнопками.

Содержит CATEGORIES, BOT_COMMANDS, функции для клавиатур и текстов меню,
а также callback handler on_menu_callback (регистрируется на dp).
"""
from aiogram import types, F
from aiogram.utils.keyboard import InlineKeyboardBuilder

from .runtime import dp
from .db import set_active_message
from .config import WEBAPP_URL
from .formatting import section


CATEGORIES = {
    "profile": ("Профиль", [
        ("/setnick [ник]", "привязать никнейм"),
        ("/setsteam {SteamID}", "привязать SteamID для Steam-статистики"),
        ("/facelogin", "вход в Faceit аккаунт (для текущих матчей)"),
        ("/unlink", "отвязать никнейм"),
        ("/notify", "вкл/выкл авто-уведомления о матчах"),
        ("/aimode", "переключить режим: статистика ⇄ ИИ-чат"),
        ("/users", "список привязанных аккаунтов"),
    ]),
    "matches": ("Матчи", [
        ("/prematch [ник]", "ИИ-анализ состава команд перед матчем"),
        ("/last [ник]", "последняя игра со скорбордом"),
        ("/history [ник]", "история последних 15 матчей"),
        ("/activity", "активность за 30 дней (график)"),
    ]),
    "stats": ("Статистика", [
        ("/stats [ник]", "Faceit + Steam CS2 статистика + ИИ-анализ"),
        ("/elo", "динамика ELO (график)"),
        ("/session", "текущая игровая сессия"),
    ]),
    "compare": ("Сравнение и рейтинги", [
        ("/compare ник1 ник2", "сравнение игроков (график)"),
        ("/map [карта]", "статистика по картам (график)"),
        ("/top", "рейтинги пользователей бота"),
    ]),
}

BOT_COMMANDS = [
    types.BotCommand(command="start", description="Открыть меню команд"),
    types.BotCommand(command="setnick", description="Привязать никнейм"),
    types.BotCommand(command="setsteam", description="Привязать SteamID"),
    types.BotCommand(command="facelogin", description="Вход в Faceit аккаунт"),
    types.BotCommand(command="unlink", description="Отвязать никнейм"),
    types.BotCommand(command="notify", description="Вкл/выкл авто-уведомления"),
    types.BotCommand(command="aimode", description="Режим: статистика ⇄ ИИ-чат"),
    types.BotCommand(command="users", description="Список привязанных аккаунтов"),
    types.BotCommand(command="prematch", description="ИИ-анализ команд перед матчем"),
    types.BotCommand(command="last", description="Последняя игра"),
    types.BotCommand(command="history", description="История последних матчей"),
    types.BotCommand(command="activity", description="Активность за 30 дней"),
    types.BotCommand(command="stats", description="Faceit + Steam статистика"),
    types.BotCommand(command="elo", description="Динамика ELO"),
    types.BotCommand(command="session", description="Текущая игровая сессия"),
    types.BotCommand(command="compare", description="Сравнить двух игроков"),
    types.BotCommand(command="map", description="Статистика по картам"),
    types.BotCommand(command="top", description="Рейтинги пользователей"),
]


def main_menu_keyboard():
    builder = InlineKeyboardBuilder()
    for key, (title, _cmds) in CATEGORIES.items():
        builder.button(text=title, callback_data=f"menu:{key}")
    if WEBAPP_URL:
        builder.button(
            text="📱 Мини-приложение",
            web_app=types.WebAppInfo(url=WEBAPP_URL)
        )
    builder.adjust(2)
    return builder.as_markup()


def category_keyboard():
    builder = InlineKeyboardBuilder()
    builder.button(text="Назад", callback_data="menu:root")
    return builder.as_markup()


def menu_root_text():
    return f"{section('FACEIT TRACKER')}\n\nВыбери раздел:"


def menu_category_text(key: str):
    title, cmds = CATEGORIES[key]
    lines = [section(title), ""]
    for cmd, desc in cmds:
        lines.append(f"{cmd} — {desc}")
    return "\n".join(lines)


@dp.callback_query(F.data.startswith("menu:"))
async def on_menu_callback(callback: types.CallbackQuery):
    key = callback.data.split(":", 1)[1]
    user_id = callback.from_user.id

    # Снимаем спиннер ВСЕГДА первым — независимо от успеха ниже.
    # Раньше callback.answer() был в конце и при ошибке edit_text спиннер
    # зависал навсегда.
    await callback.answer()

    if key == "root" or key not in CATEGORIES:
        text, markup = menu_root_text(), main_menu_keyboard()
    else:
        text, markup = menu_category_text(key), category_keyboard()

    # Пробуем edit_text (работает на текстовых сообщениях)
    try:
        await callback.message.edit_text(text, reply_markup=markup)
        set_active_message(user_id, callback.message.chat.id, callback.message.message_id)
        return
    except Exception:
        pass

    # Если не получилось — возможно это фото-сообщение (от /stats, /elo, /map).
    # Пробуем edit_caption (меняет подпись к фото, сохраняя кнопки).
    try:
        await callback.message.edit_caption(caption=text, reply_markup=markup)
        set_active_message(user_id, callback.message.chat.id, callback.message.message_id)
        return
    except Exception:
        pass

    # Если edit_caption тоже не сработал — отправляем новое сообщение.
    try:
        sent = await callback.message.answer(text, reply_markup=markup)
        set_active_message(user_id, sent.chat.id, sent.message_id)
    except Exception:
        pass
