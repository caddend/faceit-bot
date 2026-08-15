"""ИИ-ассистент по CS2/Faceit/боту — с multi-turn памятью.

Отвечает ТОЛЬКО на темы: CS2 (тактика/тренировки/статистика), платформа Faceit,
команды этого бота. На всё остальное — короткий отказ. Помнит контекст последних
N сообщений (хранится в БД chat_history). /clear сбрасывает контекст.

Может вызывать инструменты бота (статистика, последний матч, ELO, расширенные
данные из расширения) по запросу пользователя.
"""
import asyncio

from .config import ANTHROPIC_BASE_URL, ANTHROPIC_AUTH_TOKEN, ANTHROPIC_MODEL
from .coach import _sanitize_for_telegram
from .balance import get_balance_footer
from .db import get_chat_history, save_chat_message

try:
    from anthropic import Anthropic
    _ANTHROPIC_AVAILABLE = True
except ImportError:
    Anthropic = None
    _ANTHROPIC_AVAILABLE = False

# Лимит истории сообщений (oldest-first). При превышении дропаем старые.
HISTORY_LIMIT = 20
# Лимит по длине истории, чтобы не разрастался контекст (символов).
HISTORY_MAX_CHARS = 8000

# Список команд бота для системного промпта (генерируется один раз при импорте).
try:
    from .menu import BOT_COMMANDS
    _COMMANDS_LIST = "\n".join(f"/{c.command} — {c.description}" for c in BOT_COMMANDS)
except Exception:
    _COMMANDS_LIST = "(список недоступен)"


# Доступные инструменты (tools) для ИИ
TOOLS = [
    {
        "name": "get_player_stats",
        "description": "Полная статистика игрока Faceit (K/D, винрейт, ELO, мультикиллы, клатчи, энтри). Используй когда пользователь просит показать/посмотреть статистику.",
        "input_schema": {
            "type": "object",
            "properties": {
                "nickname": {"type": "string", "description": "Никнейм Faceit (или 'self' для своей статистики)"}
            },
            "required": ["nickname"]
        }
    },
    {
        "name": "get_last_match",
        "description": "Детали последнего матча (карта, результат, K/D, скорборд). Используй когда пользователь просит показать последний матч/игру.",
        "input_schema": {
            "type": "object",
            "properties": {
                "nickname": {"type": "string", "description": "Никнейм Faceit (или 'self')"}
            },
            "required": ["nickname"]
        }
    },
    {
        "name": "get_elo_dynamics",
        "description": "Динамика ELO за последние матчи. Используй когда спрашивают про изменение ELO или прогресс.",
        "input_schema": {
            "type": "object",
            "properties": {
                "nickname": {"type": "string", "description": "Никнейм Faceit (или 'self')"}
            },
            "required": ["nickname"]
        }
    },
    {
        "name": "get_advanced_stats",
        "description": "Расширенные данные, которых нет в публичном API: Faceit Rating 3.0, swing, детальный ELO. Доступно только если у пользователя установлено расширение и он открывал профиль на faceit.com. Если данные устарели/отсутствуют — вернёт инструкцию для пользователя.",
        "input_schema": {
            "type": "object",
            "properties": {
                "nickname": {"type": "string", "description": "Никнейм Faceit (или 'self')"}
            },
            "required": ["nickname"]
        }
    },
]


def _build_system_prompt() -> str:
    """Системный промпт: scoped ассистент по CS2/Faceit/боту."""
    return (
        "Ты — ИИ-ассистент по Counter-Strike 2, платформе Faceit и этому боту. "
        "Помогаешь с тактикой, тренировками, анализом статистики, вопросами по Faceit "
        "(ELO, уровни, матчмейкинг) и подсказываешь команды бота.\n\n"
        "<b>Отказывай на всё остальное</b> одной фразой: "
        "«Я отвечаю только по CS2/Faceit и этому боту.». "
        "Не веди светские беседы, не пиши тексты, не помогай с другим софтом.\n\n"
        "Ты можешь: составлять планы тренировок, разбрать статистику, помочь с командами бота, "
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
    """Обрезает историю снизу, если суммарная длина превышает лимит символов."""
    total = sum(len(m["content"]) for m in history)
    while total > HISTORY_MAX_CHARS and len(history) > 2:
        removed = history.pop(0)
        total -= len(removed["content"])
    return history


async def get_ai_chat_response(user_message: str, user_id: int, functions_module) -> str | None:
    """Multi-turn ответ ИИ с памятью контекста (chat_history в БД).

    1. Грузит последние HISTORY_LIMIT сообщений.
    2. Добавляет новый user-message.
    3. Шлёт в API (с tools). При tool_use — второй запрос с результатами.
    4. Сохраняет user + assistant сообщения в историю.
    """
    if not _ANTHROPIC_AVAILABLE or not Anthropic:
        return None

    history = _trim_history(get_chat_history(user_id, HISTORY_LIMIT))
    system_prompt = _build_system_prompt()

    def _call_api(messages):
        client = Anthropic(api_key=ANTHROPIC_AUTH_TOKEN, base_url=ANTHROPIC_BASE_URL)
        return client.messages.create(
            model=ANTHROPIC_MODEL,
            max_tokens=1024,
            system=system_prompt,
            tools=TOOLS,
            messages=messages,
        )

    # messages для первого запроса: история + новое сообщение
    messages = history + [{"role": "user", "content": user_message}]

    try:
        response = await asyncio.to_thread(_call_api, messages)
    except Exception as e:
        return f"Ошибка ИИ: {str(e)}"

    final_text = ""

    if response.stop_reason == "tool_use":
        tool_results = []
        for block in response.content:
            if block.type == "tool_use":
                tool_result_text = await _execute_tool(block.name, block.input, user_id, functions_module)
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": tool_result_text,
                })

        # Второй запрос: история + user + assistant(tool_use) + tool_results
        messages2 = messages + [
            {"role": "assistant", "content": response.content},
            {"role": "user", "content": tool_results},
        ]
        try:
            response2 = await asyncio.to_thread(_call_api, messages2)
            for block in response2.content:
                if block.type == "text":
                    final_text += block.text
        except Exception as e:
            return f"Ошибка при обработке инструментов: {str(e)}"
    else:
        for block in response.content:
            if block.type == "text":
                final_text += block.text

    if not final_text:
        return None

    final_text = _sanitize_for_telegram(final_text)

    # Сохраняем контекст в историю (user-вопрос + ответ ассистента)
    save_chat_message(user_id, "user", user_message)
    save_chat_message(user_id, "assistant", final_text)

    return final_text + await get_balance_footer()
