"""ИИ-ассистент по CS2/Faceit/боту — с multi-turn памятью (OpenAI tool format).

Отвечает ТОЛЬКО на темы: CS2, платформа Faceit, команды бота. На всё остальное —
короткий отказ. Помнит контекст последних N сообщений (БД chat_history).
"""
import json

from .config import TOOKEN_MODEL
from .coach import _sanitize_for_telegram
from .balance import get_balance_footer
from .db import get_chat_history, save_chat_message
from . import llm

# Лимит истории сообщений.
HISTORY_LIMIT = 20
HISTORY_MAX_CHARS = 8000

# Список команд бота для системного промпта.
try:
    from .menu import BOT_COMMANDS
    _COMMANDS_LIST = "\n".join(f"/{c.command} — {c.description}" for c in BOT_COMMANDS)
except Exception:
    _COMMANDS_LIST = "(список недоступен)"


# Доступные инструменты (OpenAI function format)
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_player_stats",
            "description": "Полная статистика игрока Faceit (K/D, винрейт, ELO, мультикиллы, клатчи, энтри).",
            "parameters": {
                "type": "object",
                "properties": {"nickname": {"type": "string", "description": "Никнейм Faceit или 'self'"}},
                "required": ["nickname"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_last_match",
            "description": "Детали последнего матча (карта, результат, K/D, скорборд).",
            "parameters": {
                "type": "object",
                "properties": {"nickname": {"type": "string", "description": "Никнейм Faceit или 'self'"}},
                "required": ["nickname"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_elo_dynamics",
            "description": "Динамика ELO за последние матчи.",
            "parameters": {
                "type": "object",
                "properties": {"nickname": {"type": "string", "description": "Никнейм Faceit или 'self'"}},
                "required": ["nickname"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_advanced_stats",
            "description": "Расширенные данные: Faceit Rating 3.0, swing, детальный ELO (через расширение).",
            "parameters": {
                "type": "object",
                "properties": {"nickname": {"type": "string", "description": "Никнейм Faceit или 'self'"}},
                "required": ["nickname"]
            }
        }
    },
]

# Имена функций для удобства
_TOOL_NAMES = {t["function"]["name"] for t in TOOLS}


def _build_system_prompt() -> str:
    return (
        "Ты — ИИ-ассистент по Counter-Strike 2, платформе Faceit и этому боту. "
        "Помогаешь с тактикой, тренировками, анализом статистики, вопросами по Faceit "
        "(ELO, уровни, матчмейкинг) и подсказываешь команды бота.\n\n"
        "Отказывай на всё остальное одной фразой: "
        "«Я отвечаю только по CS2/Faceit и этому боту.». "
        "Не веди светские беседы, не пиши тексты, не помогай с другим софтом.\n\n"
        "Ты можешь: составлять планы тренировок, разобрать статистику, помочь с командами бота, "
        "ответить на вопросы про CS2/Faceit. Ответы конкретные и полезные, до 200 слов.\n\n"
        "Используй инструменты ВСЕГДА, когда пользователь просит показать/посмотреть "
        "статистику, матч, ELO или расширенные данные. Если никнейм не указан — 'self'.\n"
        "После получения данных кратко прокомментируй (1-2 предложения), выдели главное через <b>...</b>.\n\n"
        "Команды бота (подсказывай их когда уместно):\n"
        f"{_COMMANDS_LIST}\n\n"
        "Формат: HTML-теги <b>...</b> для акцентов. НЕ используй markdown (#, *, **, __). "
        "Пиши на русском."
    )


async def _execute_tool(tool_name: str, tool_input: dict, user_id: int, functions_module) -> str:
    """Выполняет вызов инструмента и возвращает результат текстом."""
    nickname = tool_input.get("nickname", "self")
    if nickname == "self":
        from .db import get_user_data
        user_data = get_user_data(user_id)
        if not user_data or not user_data[0]:
            return "Ошибка: никнейм не привязан. Попроси пользователя сделать /setnick."
        nickname = user_data[0]
    try:
        if tool_name == "get_player_stats":
            return await functions_module.fetch_stats_summary(nickname) or "Не удалось загрузить статистику."
        elif tool_name == "get_last_match":
            return await functions_module.fetch_last_match_summary(nickname) or "Не удалось загрузить матч."
        elif tool_name == "get_elo_dynamics":
            return await functions_module.fetch_elo_summary(nickname, user_id) or "Не удалось загрузить ELO."
        elif tool_name == "get_advanced_stats":
            return await functions_module.fetch_advanced_stats(nickname, user_id) or "Расширенные данные недоступны."
        return f"Неизвестный инструмент: {tool_name}"
    except Exception as e:
        return f"Ошибка при выполнении {tool_name}: {str(e)}"


def _trim_history(history: list) -> list:
    total = sum(len(m.get("content", "") or "") for m in history)
    while total > HISTORY_MAX_CHARS and len(history) > 2:
        removed = history.pop(0)
        total -= len(removed.get("content", "") or "")
    return history


async def get_ai_chat_response(user_message: str, user_id: int, functions_module) -> str | None:
    """Multi-turn ответ ИИ с памятью контекста (OpenAI tool-calling loop)."""
    history = _trim_history(get_chat_history(user_id, HISTORY_LIMIT))
    system_prompt = _build_system_prompt()

    # messages для первого запроса
    messages = history + [{"role": "user", "content": user_message}]

    # Цикл tool-calling: максимум 3 итерации, чтобы не зациклиться.
    for _ in range(3):
        resp = await llm.call_llm(messages, system=system_prompt, tools=TOOLS, max_tokens=1024)
        if not resp:
            return "Ошибка ИИ: не удалось получить ответ."

        choice = resp.get("choices", [{}])[0]
        msg = choice.get("message", {})
        finish = choice.get("finish_reason", "")

        tool_calls = msg.get("tool_calls") or []
        if not tool_calls:
            final_text = msg.get("content", "") or ""
            if not final_text:
                return None
            final_text = _sanitize_for_telegram(final_text)
            save_chat_message(user_id, "user", user_message)
            save_chat_message(user_id, "assistant", final_text)
            return final_text + await get_balance_footer()

        # Есть tool_calls — выполняем и продолжаем
        messages.append(msg)
        for tc in tool_calls:
            fn = tc.get("function", {})
            name = fn.get("name", "")
            try:
                args = json.loads(fn.get("arguments", "{}") or "{}")
            except Exception:
                args = {}
            result = await _execute_tool(name, args, user_id, functions_module)
            messages.append({
                "role": "tool",
                "tool_call_id": tc.get("id", ""),
                "content": result,
            })

    # Достигли лимита итераций — берём текстовый ответ если есть
    if resp and resp.get("choices"):
        final_text = resp["choices"][0].get("message", {}).get("content", "") or ""
        if final_text:
            final_text = _sanitize_for_telegram(final_text)
            save_chat_message(user_id, "user", user_message)
            save_chat_message(user_id, "assistant", final_text)
            return final_text + await get_balance_footer()
    return None
