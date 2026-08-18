"""OpenAI-совместимый вызов LLM через Tooken Club.

Единая функция call_llm для всех модулей (ai_chat, coach, prematch, tracker).
POST /v1/chat/completions, возвращает (text, finish_reason) или None при ошибке.
"""
import json
import aiohttp

from .config import TOOKEN_BASE_URL, TOOKEN_API_KEY, TOOKEN_MODEL


async def call_llm(messages: list, system: str = "", tools: list = None,
                   max_tokens: int = 1024, temperature: float = 0.7) -> dict | None:
    """Вызывает /v1/chat/completions.

    messages — [{"role":"user"|"assistant"|"tool", "content":"...", ...}]
    system — текст системного промпта (преобразуется в system-сообщение)
    tools — список в формате OpenAI function-calling (необязательно)
    Возвращает полный dict ответа API или None при ошибке.
    """
    full_messages = []
    if system:
        full_messages.append({"role": "system", "content": system})
    full_messages.extend(messages)

    payload = {
        "model": TOOKEN_MODEL,
        "messages": full_messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    if tools:
        payload["tools"] = [{"type": "function", "function": t} for t in tools]

    try:
        async with aiohttp.ClientSession() as s:
            async with s.post(
                f"{TOOKEN_BASE_URL}/chat/completions",
                json=payload,
                headers={
                    "Authorization": f"Bearer {TOOKEN_API_KEY}",
                    "Content-Type": "application/json",
                },
                timeout=60,
            ) as resp:
                if resp.status != 200:
                    return None
                return await resp.json()
    except Exception:
        return None
