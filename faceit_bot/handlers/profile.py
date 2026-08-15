"""Хендлеры команд профиля: /start, /setnick, /unlink, /notify, /users.

Все хендлеры декорируются через @dp.message(...) с импортом dp из runtime.
"""
import asyncio

from aiogram import types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from ..runtime import dp
from ..config import FACEIT_API_BASE, FACEIT_BROWSER_API_BASE
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
    save_faceit_session_token,
    get_faceit_session_token,
    is_faceit_verified,
    schedule_delete,
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
from ..menu import menu_root_text, main_menu_keyboard
from ..formatting import section, kv, table


@dp.message(Command("start", "help"))
async def cmd_start(message: types.Message):
    await delete_user_message(message)
    user_id = message.from_user.id
    await clear_dashboard(user_id)
    sent = await message.answer(menu_root_text(), reply_markup=main_menu_keyboard())
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


class FaceitLogin(StatesGroup):
    waiting_for_token = State()


# Faceit не отдаёт Bearer-токен ни через document.cookie, ни через Storage
# (cookie переименована/HttpOnly). Самый простой способ — наше расширение: оно
# само перехватывает заголовок Authorization из запросов к api.faceit.com,
# копирует токен в буфер и открывает чат бота. Работает в Chrome/Firefox/Edge.


@dp.message(Command("facelogin"))
async def cmd_facelogin(message: types.Message, state: FSMContext):
    await delete_user_message(message)
    user_id = message.from_user.id
    args = message.text.split(maxsplit=1)

    # Токен передан сразу — backward compatible (/facelogin <token>)
    if len(args) >= 2:
        await _process_faceit_token(message, user_id, args[1].strip(), state)
        return

    # Уже верифицирован
    if is_faceit_verified(user_id):
        await answer_and_track(message, "✅ Твой Faceit аккаунт уже верифицирован.")
        return

    # Входим в FSM-состояние «жду токен»
    await state.set_state(FaceitLogin.waiting_for_token)

    builder = InlineKeyboardBuilder()
    builder.button(text="📦 Установить расширение", url="https://github.com/cadd3nd/faceit-bot/raw/main/extension.zip")
    builder.button(text="❌ Отмена", callback_data="facelogin_cancel")
    builder.adjust(1)

    sent = await message.answer(
        "🔐 <b>Вход в Faceit аккаунт</b>\n\n"
        "Токен Faceit спрятан (HttpOnly), поэтому достаём его <b>расширением</b>. "
        "Оно само перехватит токен, скопирует в буфер и откроет этот чат:\n\n"
        "<b>Установка (1 раз):</b>\n"
        "1. Скачай и распакуй расширение по кнопке <b>«📦 Установить расширение»</b> ниже\n"
        "2. Chrome/Edge: открой <code>chrome://extensions</code> → включи "
        "<b>Режим разработчика</b> → <b>Загрузить распакованное</b> → выбери папку\n"
        "   Firefox: <code>about:debugging</code> → Firefox/Tools → "
        "<b>Temporary Extensions → Load Temporary Add-on</b> → выбери manifest.json\n\n"
        "<b>Логин (каждый раз):</b>\n"
        "3. Открой <a href=\"https://www.faceit.com\">faceit.com</a> и залогинься\n"
        "4. Кликни по иконке расширения (черный круг) на панели\n"
        "5. Токен скопируется в буфер, откроется этот чат — просто <b>отправь токен</b>\n\n"
        "⏳ Жду твой токен…",
        reply_markup=builder.as_markup(),
        disable_web_page_preview=True,
    )
    await replace_dashboard(user_id, sent.chat.id, sent.message_id)


@dp.callback_query(F.data == "facelogin_cancel")
async def on_facelogin_cancel(callback: types.CallbackQuery, state: FSMContext):
    """Отмена FSM-состояния."""
    await state.clear()
    await callback.answer("Отменено")
    try:
        await callback.message.edit_text("❌ Вход отменён.")
    except Exception:
        pass


@dp.message(FaceitLogin.waiting_for_token)
async def on_faceit_token_received(message: types.Message, state: FSMContext):
    """Ловит следующий message от пользователя как токен (без /facelogin)."""
    await delete_user_message(message)
    user_id = message.from_user.id
    token = message.text.strip()
    await _process_faceit_token(message, user_id, token, state)


async def _process_faceit_token(
    message: types.Message, user_id: int, token: str, state: FSMContext
):
    """Общая логика проверки и сохранения токена.

    Вызывается и из cmd_facelogin (с аргументом), и из FSM-хендлера.
    """
    if len(token) < 20:
        await answer_and_track(
            message, "Токен слишком короткий. Проверь, что скопировал полностью."
        )
        # Не сбрасываем state — даём попробовать ещё раз
        return

    await state.clear()

    import aiohttp
    await clear_dashboard(user_id)
    loading_msg = await message.answer("🔍 Проверяю токен…")

    try:
        async with aiohttp.ClientSession() as s:
            async with s.get(
                f"{FACEIT_BROWSER_API_BASE}/users/me",
                headers={
                    "Authorization": f"Bearer {token}",
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                    "Accept": "application/json",
                    "Origin": "https://www.faceit.com",
                    "Referer": "https://www.faceit.com/",
                },
                timeout=12,
            ) as resp:
                if resp.status != 200:
                    await loading_msg.edit_text(
                        "❌ Токен недействителен или истёк. Проверь, что скопировал правильно."
                    )
                    await replace_dashboard(user_id, loading_msg.chat.id, loading_msg.message_id)
                    return
                data = await resp.json()
                verified_nick = data.get("nickname", "")

                user_data = get_user_data(user_id)
                if user_data and user_data[0]:
                    if verified_nick.lower() != user_data[0].lower():
                        await loading_msg.edit_text(
                            f"❌ Несовпадение: токен от аккаунта <b>{verified_nick}</b>, "
                            f"а привязан <b>{user_data[0]}</b>.\n"
                            f"Сначала отвяжи ник и привяжи нужный через /setnick {verified_nick}"
                        )
                        await replace_dashboard(user_id, loading_msg.chat.id, loading_msg.message_id)
                        return

                save_faceit_session_token(user_id, token)
                from ..db import cursor, conn as db_conn
                cursor.execute(
                    "UPDATE users SET faceit_verified = 1 WHERE user_id = ?", (user_id,)
                )
                db_conn.commit()

                await loading_msg.edit_text(
                    f"✅ <b>Faceit аккаунт верифицирован!</b>\n\n"
                    f"Аккаунт: <b>{verified_nick}</b>\n"
                    f"Теперь бот видит текущие матчи и автоматически анализирует составы."
                )
                await replace_dashboard(user_id, loading_msg.chat.id, loading_msg.message_id)
                schedule_delete(loading_msg.chat.id, loading_msg.message_id)

    except Exception as e:
        await loading_msg.edit_text(f"❌ Ошибка при проверке токена: {str(e)}")
        await replace_dashboard(user_id, loading_msg.chat.id, loading_msg.message_id)


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

    mode_icon = "🤖" if new_state else "📊"
    mode_text = "ИИ-консультант (чат о CS2)" if new_state else "Статистика (обычный режим)"

    hint = ""
    if new_state:
        hint = "\n\n💡 Теперь любое сообщение — вопрос к ИИ о CS2. Для возврата к статистике используй /aimode снова."
    else:
        hint = "\n\n💡 Обычный режим восстановлен. Команды работают как раньше."

    sent = await message.answer(f"{mode_icon} Режим переключён: <b>{mode_text}</b>{hint}")
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

    # Получаем список верифицированных ников
    from ..db import cursor as db_cursor
    db_cursor.execute("SELECT nickname FROM users WHERE faceit_verified = 1 AND nickname IS NOT NULL")
    verified_nicks = set(row[0].lower() for row in db_cursor.fetchall())

    async def get_account_elo(nickname: str, count: int):
        player_data = await get_player_by_nickname(nickname)
        if player_data:
            elo = player_data.get('games', {}).get('cs2', {}).get('faceit_elo', 'N/A')
            lvl = player_data.get('games', {}).get('cs2', {}).get('skill_level', 'N/A')
        else:
            elo, lvl = "N/A", "N/A"
        badge = " ✅" if nickname.lower() in verified_nicks else ""
        name = nickname + badge + (f" (x{count})" if count > 1 else "")
        return [name, lvl, elo]

    tasks = [get_account_elo(nick, count) for nick, count in accounts]
    results = await asyncio.gather(*tasks)

    verified_count = sum(1 for nick, _ in accounts if nick.lower() in verified_nicks)

    body = table(results, headers=["Аккаунт", "Lvl", "ELO"])

    text = (
        f"{section('ПРИВЯЗАННЫЕ АККАУНТЫ')}\n"
        f"{kv('Пользователей бота', total_tg_users)}\n"
        f"{kv('Уникальных Faceit аккаунтов', len(accounts))}\n"
        f"{kv('Верифицированных', verified_count)}\n\n"
        f"<code>{body}</code>"
    )
    await loading_msg.edit_text(text)
    await replace_dashboard(user_id, loading_msg.chat.id, loading_msg.message_id)

