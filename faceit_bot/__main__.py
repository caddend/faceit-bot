"""Точка входа: main(), asyncio.run.

Импортирует все handler-модули для регистрации хендлеров ДО запуска polling.
"""
import asyncio

from .runtime import bot, dp
# Импорт handler-модулей для регистрации хендлеров на dp (побочный эффект):
from . import menu  # noqa: F401  (регистрирует on_menu_callback)
from .handlers import profile, matches, stats  # noqa: F401
from .tracker import background_match_tracker, scheduled_delete_worker, evening_session_report, extension_match_worker
from .webapp_sync import bulk_sync_to_worker
from .db import get_all_tracked_users
from .menu import BOT_COMMANDS


async def sync_users_on_startup():
    """Пушит всех привязанных пользователей в Worker KV при старте бота.

    Запускается до polling, но не блокирует его надолго.
    Если WEBAPP_URL пуст — no-op.
    """
    await asyncio.sleep(5)  # подождать пока всё инициализируется
    users = get_all_tracked_users()
    pairs = [(uid, nick) for uid, nick, _, _ in users if nick]
    if pairs:
        print(f"Синхронизация {len(pairs)} пользователей с Worker KV...")
        await bulk_sync_to_worker(pairs)
        print("Синхронизация завершена.")


async def main():
    print("Запуск бота.")
    await bot.set_my_commands(BOT_COMMANDS)
    await sync_users_on_startup()
    await asyncio.gather(
        dp.start_polling(bot),
        background_match_tracker(),
        scheduled_delete_worker(),
        evening_session_report(),
        extension_match_worker(),
    )


if __name__ == "__main__":
    asyncio.run(main())
