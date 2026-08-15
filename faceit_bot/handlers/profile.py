"""Хендлеры команд профиля: /start, /setnick, /unlink, /notify, /users.

Все хендлеры декорируются через @dp.message(...) с импортом dp из runtime.
"""
import asyncio

from aiogram import types, F
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder

from ..runtime import dp
from ..config import FACEIT_API_BASE, EXTENSION_DOWNLOAD_URL
from ..db import (
    get_user_data,
    save_nick,
    save_steam_id,
    unlink_user,
    update_last_match,
    get_notify,
    toggle_notify,
    get_ai_mode,
    toggle_ai_mode,
    save_session,
    count_users,
    get_unique_nicknames_with_counts,
    schedule_delete,
    create_link_token,
    has_link_token,
    clear_chat_history,
)
from ..dashboard import (
    delete_user_message,
    clear_dashboard,
    replace_dashboard,
    answer_and_track,
)
from ..faceit_api import get_player_by_nickname, fetch_faceit_data
from ..steam_api import resolve_steam_id
from ..webapp_sync import push_user_to_worker
from ..menu import menu_root_text, main_menu_keyboard, menu_ext_text
from ..formatting import section, kv, table


@dp.message(Command("start", "help"))
async def cmd_start(message: types.Message):
    await delete_user_message(message)
    user_id = message.from_user.id
    await clear_dashboard(user_id)

    user_data = get_user_data(user_id)
    has_nick = bool(user_data and user_data[0])

    # Онбординг: нет ника → пошаговый гайд для новичков
    if not has_nick:
        builder = InlineKeyboardBuilder()
        builder.button(text="Установить расширение", callback_data="menu:ext")
        builder.button(text="ИИ-тренер", callback_data="menu:ai")
        builder.adjust(1)
        sent = await message.answer(
            f"{section('ДОБРО ПОЖАЛОВАТЬ')}\n\n"
            f"Я — бот-трекер CS2 на Faceit: статистика, матчи, ELO, ИИ-анализ.\n\n"
            f"<b>С чего начать:</b>\n"
            f"1. Привяжи никнейм: <code>/setnick твой_ник</code>\n"
            f"2. Установи расширение (видит текущие матчи): кнопка ниже\n"
            f"3. Включи ИИ-тренера — план тренировок, разбор статистики\n\n"
            f"Все команды — в меню кнопок ниже.",
            reply_markup=builder.as_markup(),
            disable_web_page_preview=True,
        )
        await replace_dashboard(user_id, sent.chat.id, sent.message_id)
        return

    # Есть ник, но нет расширения → предложить установку + обычное меню
    if not has_link_token(user_id):
        builder = InlineKeyboardBuilder()
        builder.button(text="Статистика", callback_data="menu:stats")
        builder.button(text="Матчи", callback_data="menu:matches")
        builder.button(text="ИИ-тренер", callback_data="menu:ai")
        builder.button(text="Настройки", callback_data="menu:settings")
        builder.button(text="Установить расширение", callback_data="menu:ext")
        builder.adjust(2)
        sent = await message.answer(
            f"{menu_root_text()}\n\n"
            f"<i>Расширение ещё не установлено — с ним бот видит "
            f"текущие матчи и Rating 3.0. Установить:</i>",
            reply_markup=builder.as_markup(),
        )
        await replace_dashboard(user_id, sent.chat.id, sent.message_id)
        return

    # Всё настроено → обычное меню
    sent = await message.answer(menu_root_text(), reply_markup=main_menu_keyboard())
    await replace_dashboard(user_id, sent.chat.id, sent.message_id)


@dp.message(Command("clear"))
async def cmd_clear(message: types.Message):
    """Очищает историю чата с ИИ (сбрасывает multi-turn контекст)."""
    await delete_user_message(message)
    user_id = message.from_user.id
    clear_chat_history(user_id)
    sent = await message.answer("История чата с ИИ очищена. Контекст сброшен.")
    await replace_dashboard(user_id, sent.chat.id, sent.message_id)


@dp.message(Command("setnick"))
async def cmd_setnick(message: types.Message):
    await delete_user_message(message)
    user_id = message.from_user.id
    args = message.text.split()
    if len(args) < 2:
        await clear_dashboard(user_id)
        sent = await message.answer("Укажи никнейм. Использование: /setnick nickname")
        await replace_dashboard(user_id, sent.chat.id, sent.message_id)
        return

    nickname = args[1]

    player_data = await get_player_by_nickname(nickname)
    if not player_data:
        await clear_dashboard(user_id)
        sent = await message.answer("Игрок с таким никнеймом не найден на Faceit.")
        await replace_dashboard(user_id, sent.chat.id, sent.message_id)
        return

    save_nick(user_id, nickname)
    await push_user_to_worker(user_id, nickname)

    player_id = player_data['player_id']
    history_data = await fetch_faceit_data(f"{FACEIT_API_BASE}/players/{player_id}/history?game=cs2&offset=0&limit=1")
    if history_data and history_data.get('items'):
        update_last_match(user_id, history_data['items'][0]['match_id'])

    current_elo = player_data.get('games', {}).get('cs2', {}).get('faceit_elo')
    save_session(user_id, current_elo, is_estimate=False)

    await clear_dashboard(user_id)
    sent = await message.answer(f"Никнейм '{nickname}' сохранен. Автоматическое отслеживание матчей активировано.")
    await replace_dashboard(user_id, sent.chat.id, sent.message_id)


@dp.message(Command("setsteam"))
async def cmd_setsteam(message: types.Message):
    await delete_user_message(message)
    user_id = message.from_user.id
    args = message.text.split()
    if len(args) < 2:
        await answer_and_track(
            message,
            "Укажи SteamID64 или vanity URL. Пример: /setsteam 76561198849692120"
        )
        return

    identifier = args[1]
    steam_id = await resolve_steam_id(identifier)
    if not steam_id:
        await answer_and_track(
            message,
            "Не удалось определить SteamID. Проверь ввод.\n"
            "Принимает: SteamID64, vanity URL или ссылку на профиль."
        )
        return

    save_steam_id(user_id, steam_id)
    await answer_and_track(message, f"SteamID <code>{steam_id}</code> привязан.")



# Faceit не отдаёт Bearer-токен ни через document.cookie, ни через Storage.
# Поэтому бот работает с матчем через расширение: расширение сидит на faceit.com,
# само видит идущий матч (в сессии браузера) и шлёт его на Worker. /facelogin
# выдаёт link_token — он связывает расширение с конкретным пользователем бота.


@dp.message(Command("facelogin"))
async def cmd_facelogin(message: types.Message):
    """Выдаёт link_token и инструкцию по установке расширения.

    Расширение перехватывает идущий матч прямо из ответов api.faceit.com
    и шлёт его на Worker. Бот забирает матч, делает ИИ-анализ и пишет пользователю.
    Токен Faceit пользователю добывать не нужно вообще.
    """
    await delete_user_message(message)
    user_id = message.from_user.id

    user_data = get_user_data(user_id)
    if not user_data or not user_data[0]:
        await answer_and_track(
            message, "Сначала привяжи никнейм через /setnick — иначе матч не с чем связать."
        )
        return

    link_token = create_link_token(user_id)
    # Пушим link_token в Worker, чтобы мини-приложение могло тянуть scrape-данные
    user_data = get_user_data(user_id)
    if user_data and user_data[0]:
        await push_user_to_worker(user_id, user_data[0], link_token)

    builder = InlineKeyboardBuilder()
    builder.button(text="Скачать расширение", url=EXTENSION_DOWNLOAD_URL)
    builder.adjust(1)

    sent = await message.answer(
        f"<b>Расширение для текущих матчей</b>\n\n"
        f"Расширение само видит идущий матч на faceit.com (в твоей сессии браузера), "
        f"собирает составы команд и шлёт их боту на ИИ-анализ. "
        f"Токен Faceit добывать вручную <b>не нужно</b>.\n\n"
        f"<b>1. Установка (один раз):</b>\n"
        f"Нажми «Скачать расширение» выше, распакуй zip в папку.\n\n"
        f"<b>2. Загрузка в браузер:</b>\n"
        f"<b>Chrome / Edge / Яндекс:</b> открой <code>chrome://extensions</code> "
        f"(в Яндексе — <code>browser://extensions/</code>), включи "
        f"<b>Режим разработчика</b> справа сверху → <b>Загрузить распакованное</b> → "
        f"выбери распакованную папку\n"
        f"<b>Firefox:</b> открой <code>about:debugging</code> → "
        f"<b>This Firefox → Temporary Extensions → Load Temporary Add-on</b> → "
        f"выбери <b>manifest.json</b> внутри распакованной папки\n\n"
        f"<b>3. Привязка к боту:</b>\n"
        f"Кликни по иконке расширения на панели → вставь этот токен:\n"
        f"<code>{link_token}</code>\n\n"
        f"<b>4. Использование:</b>\n"
        f"Открой <a href=\"https://www.faceit.com\">faceit.com</a> залогиненным, "
        f"когда найдёшь/начнёшь матч — расширение само пришлёт составы команд, "
        f"бот пришлёт ИИ-анализ прямо сюда.\n\n"
        f"Браузер должен быть открыт на faceit.com во время матча.",
        reply_markup=builder.as_markup(),
        disable_web_page_preview=True,
    )
    await replace_dashboard(user_id, sent.chat.id, sent.message_id)


@dp.message(Command("unlink"))
async def cmd_unlink(message: types.Message):
    await delete_user_message(message)
    user_id = message.from_user.id
    user_data = get_user_data(user_id)
    if not user_data or not user_data[0]:
        await clear_dashboard(user_id)
        sent = await message.answer("У тебя и так нет привязанного никнейма.")
        await replace_dashboard(user_id, sent.chat.id, sent.message_id)
        return
    unlink_user(user_id)
    await clear_dashboard(user_id)
    sent = await message.answer("Никнейм отвязан. Отслеживание матчей остановлено.")
    await replace_dashboard(user_id, sent.chat.id, sent.message_id)


@dp.message(Command("notify"))
async def cmd_notify(message: types.Message):
    await delete_user_message(message)
    user_id = message.from_user.id
    user_data = get_user_data(user_id)
    if not user_data:
        await clear_dashboard(user_id)
        sent = await message.answer("Сначала привяжи никнейм через /setnick.")
        await replace_dashboard(user_id, sent.chat.id, sent.message_id)
        return
    new_state = toggle_notify(user_id)
    await clear_dashboard(user_id)
    sent = await message.answer(f"Авто-уведомления о новых матчах: {'включены' if new_state else 'выключены'}.")
    await replace_dashboard(user_id, sent.chat.id, sent.message_id)


@dp.message(Command("aimode"))
async def cmd_aimode(message: types.Message):
    await delete_user_message(message)
    user_id = message.from_user.id

    # Проверяем, есть ли пользователь в БД (хотя бы одна запись)
    # Если нет — создаём пустую запись для возможности переключения режима
    user_data = get_user_data(user_id)
    if not user_data:
        # Создаём пустую запись с ai_mode=0
        from ..db import cursor, conn
        cursor.execute(
            "INSERT INTO users (user_id, nickname, last_match_id, notify, ai_mode) VALUES (?, NULL, NULL, 1, 0)",
            (user_id,)
        )
        conn.commit()

    new_state = toggle_ai_mode(user_id)
    await clear_dashboard(user_id)

    mode_text = "ИИ-консультант (чат о CS2)" if new_state else "Статистика (обычный режим)"

    hint = ""
    if new_state:
        hint = "\n\nТеперь любое сообщение — вопрос к ИИ о CS2. Для возврата к статистике используй /aimode снова."
    else:
        hint = "\n\nОбычный режим восстановлен. Команды работают как раньше."

    sent = await message.answer(f"Режим переключён: <b>{mode_text}</b>{hint}")
    await replace_dashboard(user_id, sent.chat.id, sent.message_id)


@dp.message(Command("users"))
async def cmd_users(message: types.Message):
    await delete_user_message(message)
    user_id = message.from_user.id

    total_tg_users = count_users()
    accounts = get_unique_nicknames_with_counts()

    if not accounts:
        await answer_and_track(message, "База данных пока пуста.")
        return

    await clear_dashboard(user_id)
    loading_msg = await message.answer("Загружаю список аккаунтов...")

    # Никнеймы, у которых установлено расширение (есть link_token)
    from ..db import cursor as db_cursor
    db_cursor.execute("SELECT DISTINCT lower(nickname) FROM users WHERE link_token IS NOT NULL AND nickname IS NOT NULL")
    ext_nicks = set(row[0] for row in db_cursor.fetchall())

    async def get_account_elo(nickname: str, count: int):
        player_data = await get_player_by_nickname(nickname)
        if player_data:
            elo = player_data.get('games', {}).get('cs2', {}).get('faceit_elo', 'N/A')
            lvl = player_data.get('games', {}).get('cs2', {}).get('skill_level', 'N/A')
        else:
            elo, lvl = "N/A", "N/A"
        badge = " [extension]" if nickname.lower() in ext_nicks else ""
        name = nickname + badge + (f" (x{count})" if count > 1 else "")
        return [name, lvl, elo]

    tasks = [get_account_elo(nick, count) for nick, count in accounts]
    results = await asyncio.gather(*tasks)

    ext_count = sum(1 for nick, _ in accounts if nick.lower() in ext_nicks)

    body = table(results, headers=["Аккаунт", "Lvl", "ELO"])

    text = (
        f"{section('ПРИВЯЗАННЫЕ АККАУНТЫ')}\n"
        f"{kv('Пользователей бота', total_tg_users)}\n"
        f"{kv('Уникальных Faceit аккаунтов', len(accounts))}\n"
        f"{kv('С расширением', ext_count)}\n\n"
        f"<code>{body}</code>"
    )
    await loading_msg.edit_text(text)
    await replace_dashboard(user_id, loading_msg.chat.id, loading_msg.message_id)

