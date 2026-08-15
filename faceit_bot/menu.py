"""Меню команд: навигация inline-кнопками с подменю.

Топ-уровень: Статистика, Матчи, ИИ-тренер, Настройки, Расширение.
Каждая ведёт в подменю со списком команд. menu:ai включает/выключает ai_mode.
menu:ext показывает инструкцию установки расширения.
"""
from aiogram import types, F
from aiogram.utils.keyboard import InlineKeyboardBuilder

from .runtime import dp
from .db import set_active_message, toggle_ai_mode, get_ai_mode
from .config import WEBAPP_URL, EXTENSION_DOWNLOAD_URL
from .formatting import section

# Подменю (кнопки топ-уровня → callback menu:<key>)
CATEGORIES = {
    "stats": ("Статистика", [
        ("/stats [ник]", "Faceit + Steam статистика + ИИ-анализ"),
        ("/elo", "динамика ELO (график)"),
        ("/session", "текущая игровая сессия"),
    ]),
    "matches": ("Матчи", [
        ("/prematch [ник]", "ИИ-анализ состава команд перед матчем"),
        ("/last [ник]", "последняя игра со скорбордом"),
        ("/history [ник]", "история последних 15 матчей"),
        ("/activity", "активность за 30 дней (график)"),
    ]),
    "settings": ("Настройки", [
        ("/setnick [ник]", "привязать никнейм"),
        ("/setsteam {SteamID}", "привязать SteamID"),
        ("/unlink", "отвязать никнейм"),
        ("/notify", "вкл/выкл авто-уведомления"),
        ("/aimode", "режим: статистика ⇄ ИИ-чат"),
        ("/clear", "очистить историю чата с ИИ"),
        ("/users", "список привязанных аккаунтов"),
    ]),
    "compare": ("Сравнение", [
        ("/compare ник1 ник2", "сравнение игроков"),
        ("/map [карта]", "статистика по картам"),
        ("/top", "рейтинги пользователей"),
    ]),
}

BOT_COMMANDS = [
    types.BotCommand(command="start", description="Меню и онбординг"),
    types.BotCommand(command="setnick", description="Привязать никнейм"),
    types.BotCommand(command="setsteam", description="Привязать SteamID"),
    types.BotCommand(command="facelogin", description="Расширение для текущих матчей"),
    types.BotCommand(command="unlink", description="Отвязать никнейм"),
    types.BotCommand(command="notify", description="Вкл/выкл авто-уведомления"),
    types.BotCommand(command="aimode", description="Режим: статистика ⇄ ИИ-чат"),
    types.BotCommand(command="clear", description="Очистить историю чата с ИИ"),
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
    """Топ-уровень: 5 кнопок + опционально мини-приложение."""
    builder = InlineKeyboardBuilder()
    builder.button(text="Статистика", callback_data="menu:stats")
    builder.button(text="Матчи", callback_data="menu:matches")
    builder.button(text="ИИ-тренер", callback_data="menu:ai")
    builder.button(text="Настройки", callback_data="menu:settings")
    builder.button(text="Расширение", callback_data="menu:ext")
    if WEBAPP_URL:
        builder.button(text="Мини-приложение", web_app=types.WebAppInfo(url=WEBAPP_URL))
    builder.adjust(2)
    return builder.as_markup()


def category_keyboard(back_callback="menu:root"):
    """Кнопка «Назад»."""
    builder = InlineKeyboardBuilder()
    builder.button(text="Назад", callback_data=back_callback)
    return builder.as_markup()


def menu_root_text():
    return f"{section('FACEIT TRACKER')}\n\nВыбери раздел:"


def menu_category_text(key: str):
    title, cmds = CATEGORIES[key]
    lines = [section(title), ""]
    for cmd, desc in cmds:
        lines.append(f"{cmd} — {desc}")
    return "\n".join(lines)


def menu_ai_text(user_id: int) -> str:
    """Текст для раздела ИИ-тренер (показывает текущий режим)."""
    ai_on = get_ai_mode(user_id)
    if ai_on:
        return (
            f"{section('ИИ-ТРЕНЕР')}\n\n"
            f"Режим: <b>ИИ-чат активен</b>\n\n"
            f"Пиши любой вопрос по CS2/Faceit/боту — отвечу с памятью контекста.\n"
            f"Могу: план тренировок, разбор статистики, помощь с командами, "
            f"вопросы про CS2/Faceit.\n\n"
            f"Очистить контекст: /clear\n"
            f"Вернуться к статистике: /aimode"
        )
    return (
        f"{section('ИИ-ТРЕНЕР')}\n\n"
        f"Режим: <b>статистика</b>\n\n"
        f"Включи ИИ-чат, чтобы задавать вопросы по CS2/Faceit, получать "
        f"планы тренировок и разбор статистики с памятью контекста.\n\n"
        f"Включить: /aimode или кнопка ниже."
    )


def menu_ext_text():
    """Текст инструкции установки расширения (переиспользуется в /start и /facelogin)."""
    return (
        f"{section('РАСШИРЕНИЕ')}\n\n"
        f"Расширение видит идущий матч на faceit.com и шлёт боту составы команд "
        f"для ИИ-анализа. Также собирает расширенную статистику (Rating 3.0, swing, ELO).\n\n"
        f"<b>1. Получи токен привязки:</b> /facelogin\n"
        f"<b>2. Скачай расширение:</b> <a href=\"{EXTENSION_DOWNLOAD_URL}\">по ссылке</a>, распакуй\n"
        f"<b>3. Загрузи в браузер:</b>\n"
        f"Chrome/Edge/Яндекс: <code>chrome://extensions</code> "
        f"(Яндекс: <code>browser://extensions/</code>) → Режим разработчика → "
        f"Загрузить распакованное → выбери папку\n"
        f"Firefox: <code>about:debugging</code> → Load Temporary Add-on → manifest.json\n"
        f"<b>4. Кликни иконку расширения</b> → вставь токен из /facelogin"
    )


async def _edit_or_send(callback, text, markup):
    """Снимает спиннер, пробует edit_text → edit_caption → новое сообщение."""
    user_id = callback.from_user.id
    await callback.answer()
    try:
        await callback.message.edit_text(text, reply_markup=markup)
        set_active_message(user_id, callback.message.chat.id, callback.message.message_id)
        return
    except Exception:
        pass
    try:
        await callback.message.edit_caption(caption=text, reply_markup=markup)
        set_active_message(user_id, callback.message.chat.id, callback.message.message_id)
        return
    except Exception:
        pass
    try:
        sent = await callback.message.answer(text, reply_markup=markup, disable_web_page_preview=True)
        set_active_message(user_id, sent.chat.id, sent.message_id)
    except Exception:
        pass


@dp.callback_query(F.data.startswith("menu:"))
async def on_menu_callback(callback: types.CallbackQuery):
    key = callback.data.split(":", 1)[1]

    if key == "root" or key == "":
        await _edit_or_send(callback, menu_root_text(), main_menu_keyboard())
        return

    if key == "ai":
        # Переключаем режим и показываем статус
        new_state = toggle_ai_mode(callback.from_user.id)
        builder = InlineKeyboardBuilder()
        builder.button(text="В меню", callback_data="menu:root")
        await _edit_or_send(callback, menu_ai_text(callback.from_user.id), builder.as_markup())
        return

    if key == "ext":
        builder = InlineKeyboardBuilder()
        builder.button(text="В меню", callback_data="menu:root")
        await _edit_or_send(callback, menu_ext_text(), builder.as_markup())
        return

    if key in CATEGORIES:
        await _edit_or_send(callback, menu_category_text(key), category_keyboard())
        return

    # Неизвестный ключ → корень
    await _edit_or_send(callback, menu_root_text(), main_menu_keyboard())
