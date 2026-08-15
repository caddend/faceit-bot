"""Синхронизация user_id → nickname с Cloudflare Worker (KV).

Бот пушит mapping в Worker при /setnick и при старте (bulk).
Worker хранит в KV и использует для мини-приложения.

Если WEBAPP_URL пуст — функции no-op (backward compatible).
"""
import aiohttp

from .config import WEBAPP_URL, WEBAPP_AUTH_SECRET


async def push_user_to_worker(user_id: int, nickname: str):
    """Пушит один user_id → nickname в Worker KV.

    Вызывается из cmd_setnick после save_nick.
    Не падает если Worker недоступен — бот продолжает работать.
    """
    if not WEBAPP_URL:
        return
    try:
        async with aiohttp.ClientSession() as s:
            async with s.post(
                f"{WEBAPP_URL}/api/update-user",
                json={"user_id": user_id, "nickname": nickname},
                headers={"X-Auth-Secret": WEBAPP_AUTH_SECRET},
                timeout=5,
            ) as resp:
                if resp.status == 200:
                    print(f"Worker KV: user {user_id} → {nickname} synced.")
                else:
                    print(f"Worker KV sync failed for {user_id}: {resp.status}")
    except Exception as e:
        print(f"Worker KV sync error for {user_id}: {e}")


async def bulk_sync_to_worker(users: list[tuple[int, str]]):
    """Пушит пачку user_id → nickname в Worker KV при старте бота.

    users — список (user_id, nickname) пар.
    """
    if not WEBAPP_URL or not users:
        return
    try:
        payload = {
            "users": [
                {"user_id": uid, "nickname": nick}
                for uid, nick in users
            ]
        }
        async with aiohttp.ClientSession() as s:
            async with s.post(
                f"{WEBAPP_URL}/api/bulk-update",
                json=payload,
                headers={"X-Auth-Secret": WEBAPP_AUTH_SECRET},
                timeout=10,
            ) as resp:
                if resp.status == 200:
                    print(f"Worker KV: {len(users)} users bulk-synced.")
                else:
                    print(f"Worker KV bulk-sync failed: {resp.status}")
    except Exception as e:
        print(f"Worker KV bulk-sync error: {e}")
