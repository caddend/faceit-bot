"""Точка входа: main(), asyncio.run.

Импортирует все handler-модули для регистрации хендлеров ДО запуска polling.
"""
import asyncio

from .runtime import bot, dp
# Импорт handler-модулей для регистрации хендлеров на dp (побочный эффект):
from . import menu  # noqa: F401  (регистрирует on_menu_callback)
from .handlers import profile, matches, stats, admin  # noqa: F401
from .tracker import background_match_tracker, scheduled_delete_worker, evening_session_report, extension_match_worker
from .webapp_sync import bulk_sync_to_worker
from .db import get_all_tracked_users, get_all_for_sync
from .menu import BOT_COMMANDS


async def sync_users_on_startup():
    """Пушит всех привязанных пользователей (nick + link_token) в Worker KV.

    link_token нужен Worker'у, чтобы тянуть scrape-данные (Rating 3.0, swing)
    для мини-приложения.
    """
    await asyncio.sleep(5)  # подождать пока всё инициализируется
    rows = get_all_for_sync()
    users = [(uid, nick, lt) for uid, nick, lt in rows if nick]
    if users:
        print(f"Синхронизация {len(users)} пользователей с Worker KV...")
        await bulk_sync_to_worker(users)
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
