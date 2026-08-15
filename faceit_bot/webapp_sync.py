"""Синхронизация user_id → nickname (и link_token) с Cloudflare Worker (KV).

Бот пушит mapping в Worker при /setnick и при старте (bulk).
Worker хранит в KV: nickname по user_id, link_token по user_id.
link_token нужен Worker'у, чтобы тянуть scrape-данные (Rating 3.0, swing)
из KV scrape:{link_token}:advanced для мини-приложения.

Если WEBAPP_URL пуст — функции no-op (backward compatible).
"""
import aiohttp

from .config import WEBAPP_URL, WEBAPP_AUTH_SECRET


async def push_user_to_worker(user_id: int, nickname: str, link_token: str = None):
    """Пушит user_id → nickname (+ link_token) в Worker KV.

    Вызывается из cmd_setnick после save_nick.
    """
    if not WEBAPP_URL:
        return
    try:
        payload = {"user_id": user_id, "nickname": nickname}
        if link_token:
            payload["link_token"] = link_token
        async with aiohttp.ClientSession() as s:
            async with s.post(
                f"{WEBAPP_URL}/api/update-user",
                json=payload,
                headers={"X-Auth-Secret": WEBAPP_AUTH_SECRET},
                timeout=5,
            ) as resp:
                if resp.status == 200:
                    print(f"Worker KV: user {user_id} → {nickname} synced.")
                else:
                    print(f"Worker KV sync failed for {user_id}: {resp.status}")
    except Exception as e:
        print(f"Worker KV sync error for {user_id}: {e}")


async def bulk_sync_to_worker(users: list):
    """Пушит пачку user_id → nickname (+ link_token) в Worker KV при старте бота.

    users — список (user_id, nickname) или (user_id, nickname, link_token).
    """
    if not WEBAPP_URL or not users:
        return
    try:
        items = []
        for row in users:
            uid = row[0]
            nick = row[1]
            lt = row[2] if len(row) > 2 else None
            item = {"user_id": uid, "nickname": nick}
            if lt:
                item["link_token"] = lt
            items.append(item)
        payload = {"users": items}
        async with aiohttp.ClientSession() as s:
            async with s.post(
                f"{WEBAPP_URL}/api/bulk-update",
                json=payload,
                headers={"X-Auth-Secret": WEBAPP_AUTH_SECRET},
                timeout=10,
            ) as resp:
                if resp.status == 200:
                    print(f"Worker KV: {len(items)} users bulk-synced.")
                else:
                    print(f"Worker KV bulk-sync failed: {resp.status}")
    except Exception as e:
        print(f"Worker KV bulk-sync error: {e}")
