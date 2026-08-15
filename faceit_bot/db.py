"""База данных: инициализация, миграции, все DB-функции.

Хранит conn/cursor на уровне модуля (как в оригинальном bot.py).
Бот однопотоковый (asyncio), поэтому check_same_thread не нужен.
НЕ импортирует runtime — чтобы избежать циклических зависимостей.
"""
import sqlite3
import time

from aiogram import types

# --- Настройка базы данных ---
conn = sqlite3.connect('users.db')
cursor = conn.cursor()

cursor.execute('''
    CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        nickname TEXT,
        last_match_id TEXT
    )
''')
conn.commit()


def _safe_migrate(sql: str):
    """Миграции для новых полей (безопасно для уже существующих БД)."""
    try:
        cursor.execute(sql)
        conn.commit()
    except sqlite3.OperationalError:
        pass  # колонка уже существует


_safe_migrate("ALTER TABLE users ADD COLUMN notify INTEGER DEFAULT 1")
_safe_migrate("ALTER TABLE users ADD COLUMN session_start_ts INTEGER")
_safe_migrate("ALTER TABLE users ADD COLUMN session_start_elo INTEGER")
_safe_migrate("ALTER TABLE users ADD COLUMN session_is_estimate INTEGER DEFAULT 0")
_safe_migrate("ALTER TABLE users ADD COLUMN steam_id TEXT")
_safe_migrate("ALTER TABLE users ADD COLUMN ai_mode INTEGER DEFAULT 0")
_safe_migrate("ALTER TABLE users ADD COLUMN faceit_session_token TEXT")
_safe_migrate("ALTER TABLE users ADD COLUMN faceit_verified INTEGER DEFAULT 0")

cursor.execute('''
    CREATE TABLE IF NOT EXISTS elo_history (
        user_id INTEGER,
        match_id TEXT,
        elo INTEGER,
        timestamp INTEGER
    )
''')
cursor.execute('''
    CREATE TABLE IF NOT EXISTS scheduled_deletes (
        chat_id INTEGER,
        message_id INTEGER,
        delete_at INTEGER
    )
''')
cursor.execute('''
    CREATE TABLE IF NOT EXISTS active_message (
        user_id INTEGER PRIMARY KEY,
        chat_id INTEGER,
        message_id INTEGER
    )
''')
conn.commit()


# ============================================================
#  DB-функции
# ============================================================

def get_user_data(user_id: int):
    cursor.execute("SELECT nickname, last_match_id, steam_id FROM users WHERE user_id = ?", (user_id,))
    return cursor.fetchone()


def save_nick(user_id: int, nickname: str):
    cursor.execute("SELECT last_match_id FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    last_match = row[0] if row else None

    cursor.execute('''
        INSERT INTO users (user_id, nickname, last_match_id, notify)
        VALUES (?, ?, ?, 1)
        ON CONFLICT(user_id) DO UPDATE SET nickname = excluded.nickname
    ''', (user_id, nickname, last_match))
    conn.commit()


def save_steam_id(user_id: int, steam_id: str):
    """Upsert SteamID для пользователя. Если строка не существует — создаёт."""
    cursor.execute("SELECT nickname, last_match_id FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    nickname, last_match = (row[0], row[1]) if row else (None, None)

    cursor.execute('''
        INSERT INTO users (user_id, nickname, last_match_id, notify, steam_id)
        VALUES (?, ?, ?, 1, ?)
        ON CONFLICT(user_id) DO UPDATE SET steam_id = excluded.steam_id
    ''', (user_id, nickname, last_match, steam_id))
    conn.commit()


def get_steam_id(user_id: int) -> str | None:
    """Возвращает сохранённый SteamID64 или None."""
    cursor.execute("SELECT steam_id FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    return row[0] if row else None


def save_faceit_session_token(user_id: int, token: str):
    """Сохраняет Faceit session token (из браузерных cookies)."""
    cursor.execute(
        "UPDATE users SET faceit_session_token = ? WHERE user_id = ?",
        (token, user_id)
    )
    conn.commit()


def get_faceit_session_token(user_id: int) -> str | None:
    """Возвращает сохранённый Faceit session token или None."""
    cursor.execute("SELECT faceit_session_token FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    return row[0] if row else None



def is_faceit_verified(user_id: int) -> bool:
    """Возвращает True если аккаунт Faceit верифицирован (есть session token)."""
    cursor.execute("SELECT faceit_verified FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    return bool(row[0]) if row and row[0] is not None else False
def unlink_user(user_id: int):
    cursor.execute("DELETE FROM users WHERE user_id = ?", (user_id,))
    conn.commit()


def update_last_match(user_id: int, match_id: str):
    cursor.execute("UPDATE users SET last_match_id = ? WHERE user_id = ?", (match_id, user_id))
    conn.commit()


def get_notify(user_id: int) -> bool:
    cursor.execute("SELECT notify FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    return bool(row[0]) if row and row[0] is not None else True


def toggle_notify(user_id: int) -> bool:
    new_val = 0 if get_notify(user_id) else 1
    cursor.execute("UPDATE users SET notify = ? WHERE user_id = ?", (new_val, user_id))
    conn.commit()
    return bool(new_val)


def log_elo(user_id: int, match_id: str, elo):
    try:
        elo_int = int(elo)
    except (TypeError, ValueError):
        return
    cursor.execute(
        "INSERT INTO elo_history (user_id, match_id, elo, timestamp) VALUES (?, ?, ?, ?)",
        (user_id, match_id, elo_int, int(time.time()))
    )
    conn.commit()


def get_elo_history(user_id: int, limit: int = 30):
    cursor.execute(
        "SELECT elo, timestamp FROM elo_history WHERE user_id = ? ORDER BY timestamp ASC LIMIT ?",
        (user_id, limit)
    )
    return cursor.fetchall()


def save_session(user_id: int, elo, ts=None, is_estimate: bool = False):
    try:
        elo_int = int(elo) if elo is not None else None
    except (TypeError, ValueError):
        elo_int = None
    cursor.execute(
        "UPDATE users SET session_start_ts = ?, session_start_elo = ?, session_is_estimate = ? WHERE user_id = ?",
        (ts or int(time.time()), elo_int, 1 if is_estimate else 0, user_id)
    )
    conn.commit()


def get_session(user_id: int):
    cursor.execute(
        "SELECT session_start_ts, session_start_elo, session_is_estimate FROM users WHERE user_id = ?",
        (user_id,)
    )
    return cursor.fetchone()


def get_active_message(user_id: int):
    cursor.execute("SELECT chat_id, message_id FROM active_message WHERE user_id = ?", (user_id,))
    return cursor.fetchone()


def set_active_message(user_id: int, chat_id: int, message_id: int):
    cursor.execute('''
        INSERT INTO active_message (user_id, chat_id, message_id) VALUES (?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET chat_id = excluded.chat_id, message_id = excluded.message_id
    ''', (user_id, chat_id, message_id))
    conn.commit()


def schedule_delete(chat_id: int, message_id: int, delay_seconds: int = None):
    """Запланировать отложенное удаление сообщения.
    delay_seconds по умолчанию берётся из config.GAME_MESSAGE_TTL."""
    if delay_seconds is None:
        from .config import GAME_MESSAGE_TTL
        delay_seconds = GAME_MESSAGE_TTL
    cursor.execute(
        "INSERT INTO scheduled_deletes (chat_id, message_id, delete_at) VALUES (?, ?, ?)",
        (chat_id, message_id, int(time.time()) + delay_seconds)
    )
    conn.commit()


def get_due_deletes():
    """Возвращает список (rowid, chat_id, message_id) сообщений, подлежащих удалению."""
    now_ts = int(time.time())
    cursor.execute("SELECT rowid, chat_id, message_id FROM scheduled_deletes WHERE delete_at <= ?", (now_ts,))
    return cursor.fetchall()


def delete_scheduled_row(rowid: int):
    cursor.execute("DELETE FROM scheduled_deletes WHERE rowid = ?", (rowid,))
    conn.commit()


def get_all_active_messages():
    """Для startup_cleanup: возвращает (user_id, chat_id, message_id)."""
    cursor.execute("SELECT user_id, chat_id, message_id FROM active_message")
    return cursor.fetchall()


def get_all_tracked_users():
    """Для background_match_tracker: (user_id, nickname, last_match_id, notify)."""
    cursor.execute("SELECT user_id, nickname, last_match_id, notify FROM users WHERE nickname IS NOT NULL")
    return cursor.fetchall()


def count_users():
    cursor.execute("SELECT COUNT(*) FROM users")
    return cursor.fetchone()[0]


def get_unique_nicknames_with_counts():
    """Для /users: [(nickname, count), ...]."""
    cursor.execute("SELECT nickname, COUNT(*) FROM users WHERE nickname IS NOT NULL GROUP BY nickname")
    return cursor.fetchall()


def get_distinct_nicknames():
    """Для /top: [nickname, ...]."""
    cursor.execute("SELECT DISTINCT nickname FROM users WHERE nickname IS NOT NULL")
    return [row[0] for row in cursor.fetchall()]


def get_ai_mode(user_id: int) -> bool:
    """Возвращает режим ИИ-консультаций (True = режим чата с ИИ, False = режим статистики)."""
    cursor.execute("SELECT ai_mode FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    return bool(row[0]) if row and row[0] is not None else False


def toggle_ai_mode(user_id: int) -> bool:
    """Переключает режим ИИ-консультаций. Возвращает новое состояние."""
    current = get_ai_mode(user_id)
    new_val = 0 if current else 1
    cursor.execute("UPDATE users SET ai_mode = ? WHERE user_id = ?", (new_val, user_id))
    conn.commit()
    return bool(new_val)


def resolve_nickname(message: types.Message, args: list):
    """Если в args есть второй элемент — берём его как никнейм,
    иначе ищем сохранённый ник пользователя в БД."""
    if len(args) > 1:
        return args[1]
    user_data = get_user_data(message.from_user.id)
    return user_data[0] if user_data else None
