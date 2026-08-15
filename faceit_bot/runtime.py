"""Модульные синглтоны: bot, dp, кэши.

Импортируется всеми handler-модулями. НЕ импортирует db, чтобы избежать
циклических зависимостей (см. план: Risks and checks).
"""
from aiogram import Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage

from .config import create_bot

bot = create_bot()
dp = Dispatcher(storage=MemoryStorage())

# in-memory кэш матч-истории (per-user, переживает только процесс)
match_cache = {}

# in-memory кэш API-ответов с TTL, чтобы не долбить Faceit API
_api_cache = {}
