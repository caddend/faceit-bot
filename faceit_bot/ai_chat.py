"""ИИ-консультант: краткие ответы на вопросы о CS2 + доступ к функциям бота.

Используется когда пользователь в режиме ai_mode=1 (режим чата с ИИ).
Отвечает только на вопросы, связанные с CS2/CS:GO. Ответы краткие (до 200 слов).

Может вызывать функции бота (stats, last match, elo и т.д.) по запросу пользователя.
"""
import asyncio
import time
import json

from .config import ANTHROPIC_BASE_URL, ANTHROPIC_AUTH_TOKEN, ANTHROPIC_MODEL
from .runtime import _api_cache
from .coach import _sanitize_for_telegram
from .balance import get_balance_footer

try:
    from anthropic import Anthropic
    _ANTHROPIC_AVAILABLE = True
except ImportError:
    Anthropic = None
    _ANTHROPIC_AVAILABLE = False

# TTL кеша для ИИ-чата: 5 минут (короче чем для полного анализа)
AI_CHAT_CACHE_TTL = 300


# Определение доступных инструментов (tools) для ИИ
TOOLS = [
    {
        "name": "get_player_stats",
        "description": "Получает полную статистику игрока Faceit (K/D, винрейт, ELO, мультикиллы, клатчи и т.д.). Используй когда пользователь просит показать/посмотреть статистику.",
        "input_schema": {
            "type": "object",
            "properties": {
                "nickname": {
                    "type": "string",
                    "description": "Никнейм игрока Faceit (если пользователь не указал — используй 'self' для его собственной статистики)"
                }
            },
            "required": ["nickname"]
        }
    },
    {
        "name": "get_last_match",
        "description": "Получает детали последнего матча игрока (карта, результат, K/D, скорборд). Используй когда пользователь просит показать последний матч/игру.",
        "input_schema": {
            "type": "object",
            "properties": {
                "nickname": {
                    "type": "string",
                    "description": "Никнейм игрока Faceit (если пользователь не указал — используй 'self')"
                }
            },
            "required": ["nickname"]
        }
    },
    {
        "name": "get_elo_dynamics",
        "description": "Получает динамику ELO игрока за последние матчи. Используй когда пользователь спрашивает про изменение ELO или прогресс.",
        "input_schema": {
            "type": "object",
            "properties": {
                "nickname": {
                    "type": "string",
                    "description": "Никнейм игрока Faceit (если пользователь не указал — используй 'self')"
                }
            },
            "required": ["nickname"]
        }
    }
]


async def _execute_tool(tool_name: str, tool_input: dict, user_id: int, functions_module) -> str:
    """Выполняет вызов инструмента (функции бота) и возвращает результат в текстовом виде."""
    nickname = tool_input.get("nickname", "self")

    # Если nickname == 'self' — берём из БД пользователя
    if nickname == "self":
        from .db import get_user_data
        user_data = get_user_data(user_id)
        if not user_data or not user_data[0]:
            return "Ошибка: никнейм не привязан. Пользователь должен использовать /setnick сначала."
        nickname = user_data[0]

    try:
        if tool_name == "get_player_stats":
            result = await functions_module.fetch_stats_summary(nickname)
            return result or "Не удалось загрузить статистику."

        elif tool_name == "get_last_match":
            result = await functions_module.fetch_last_match_summary(nickname)
            return result or "Не удалось загрузить последний матч."

        elif tool_name == "get_elo_dynamics":
            result = await functions_module.fetch_elo_summary(nickname, user_id)
            return result or "Не удалось загрузить динамику ELO."

        else:
            return f"Неизвестный инструмент: {tool_name}"

    except Exception as e:
        return f"Ошибка при выполнении {tool_name}: {str(e)}"


async def get_ai_chat_response(user_message: str, user_id: int, functions_module) -> str | None:
    """Получает краткий ответ от ИИ на вопрос пользователя с возможностью вызова функций бота.

    Кеш: последние 5 минут по ключу chat:{user_id}:{hash(message)}.
    Ограничения:
    - Только вопросы о CS2/CS:GO
    - Краткие ответы (~100-200 слов)
    - max_tokens=512 (с учётом tool use)
    """
    if not _ANTHROPIC_AVAILABLE or not Anthropic:
        return None

    # Кеш по хешу сообщения (для повторных одинаковых вопросов)
    cache_key = f"chat:{user_id}:{hash(user_message)}"
    cached = _api_cache.get(cache_key)
    if cached and (time.time() - cached[0]) < AI_CHAT_CACHE_TTL:
        return cached[1] + await get_balance_footer()

    system_prompt = (
        "Ты — краткий CS2 консультант с доступом к статистике игроков через Faceit API. "
        "Отвечай ТОЛЬКО на вопросы о Counter-Strike 2 и CS:GO. "
        "Если вопрос не связан с CS2/CS:GO — вежливо откажи и напомни, что ты специализируешься только на CS2. "
        "\n\n"
        "У тебя есть инструменты для получения реальной статистики:\n"
        "- get_player_stats: полная статистика игрока (K/D, винрейт, ELO, клатчи, энтри и т.д.)\n"
        "- get_last_match: последний матч игрока (карта, результат, K/D, скорборд)\n"
        "- get_elo_dynamics: динамика ELO за последние матчи\n"
        "\n"
        "Используй эти инструменты ВСЕГДА, когда пользователь просит показать/посмотреть статистику, "
        "последний матч, ELO или что-то связанное с его данными. "
        "Если пользователь не указал никнейм — используй 'self' в параметре nickname.\n"
        "\n"
        "После получения данных — кратко прокомментируй их (1-2 предложения), "
        "выдели ключевые моменты через <b>...</b>.\n"
        "\n"
        "Ответы должны быть краткими (до 150 слов), конкретными и полезными. "
        "Используй HTML-теги <b>...</b> для акцентов. "
        "НЕ используй markdown (#, ##, *, **, __). "
        "Пиши на русском языке."
    )

    def _call_api():
        client = Anthropic(api_key=ANTHROPIC_AUTH_TOKEN, base_url=ANTHROPIC_BASE_URL)

        messages = [{"role": "user", "content": user_message}]

        # Первый запрос к API (с tools)
        resp = client.messages.create(
            model=ANTHROPIC_MODEL,
            max_tokens=512,
            system=system_prompt,
            tools=TOOLS,
            messages=messages,
        )

        return resp

    try:
        response = await asyncio.to_thread(_call_api)
    except Exception as e:
        return f"Ошибка ИИ: {str(e)}"

    # Обрабатываем ответ (может быть text или tool_use)
    final_text = ""

    # Проверяем stop_reason
    if response.stop_reason == "tool_use":
        # ИИ хочет вызвать инструмент
        tool_results = []

        for block in response.content:
            if block.type == "tool_use":
                tool_name = block.name
                tool_input = block.input
                tool_use_id = block.id

                # Выполняем инструмент
                tool_result_text = await _execute_tool(tool_name, tool_input, user_id, functions_module)

                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tool_use_id,
                    "content": tool_result_text,
                })

        # Второй запрос к API с результатами tool_use
        def _call_api_with_tool_results():
            client = Anthropic(api_key=ANTHROPIC_AUTH_TOKEN, base_url=ANTHROPIC_BASE_URL)

            messages = [
                {"role": "user", "content": user_message},
                {"role": "assistant", "content": response.content},
                {"role": "user", "content": tool_results},
            ]

            resp2 = client.messages.create(
                model=ANTHROPIC_MODEL,
                max_tokens=512,
                system=system_prompt,
                tools=TOOLS,
                messages=messages,
            )
            return resp2

        try:
            response2 = await asyncio.to_thread(_call_api_with_tool_results)
            # Извлекаем текстовый ответ
            for block in response2.content:
                if block.type == "text":
                    final_text += block.text
        except Exception as e:
            return f"Ошибка при обработке результатов инструмента: {str(e)}"

    else:
        # Обычный текстовый ответ без инструментов
        for block in response.content:
            if block.type == "text":
                final_text += block.text

    if not final_text:
        return None

    final_text = _sanitize_for_telegram(final_text)

    # Кешируем на 5 минут
    # Кешируем на 5 минут
    _api_cache[cache_key] = (time.time(), final_text)
    return final_text + await get_balance_footer()

