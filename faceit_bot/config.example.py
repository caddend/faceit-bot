"""Пример конфигурации. Скопируй в config.py и впиши свои значения.

config.py НЕ коммитится (в .gitignore) — там реальные токены.
"""
import aiohttp
from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.client.telegram import TelegramAPIServer

# Telegram bot token от @BotFather
TG_TOKEN = "YOUR_TELEGRAM_BOT_TOKEN"
# Свой Telegram API server (если используешь, иначе https://api.telegram.org)
CUSTOM_API_URL = "https://api.telegram.org"

# Faceit Data API v4 (open.faceit.com)
FACEIT_TOKEN = "YOUR_FACEIT_API_TOKEN"
FACEIT_API_BASE = "https://open.faceit.com/data/v4"
FACEIT_BROWSER_API_BASE = "https://api.faceit.com"
HEADERS = {"Authorization": f"Bearer {FACEIT_TOKEN}"}
ESTIMATED_ELO_STEP = 20
CACHE_TTL = 60
GAME_MESSAGE_TTL = 6 * 3600

# ИИ (Tooken Club — OpenAI-совместимый API)
TOOKEN_BASE_URL = "https://tooken.club/v1"
TOOKEN_API_KEY = "YOUR_TOOKEN_TOKEN"
TOOKEN_MODEL = "gpt-5.5"
AI_CACHE_TTL = 600

# Баланс токенов Tooken
TOOKEN_CABINET_URL = "https://tooken.club/dashboard?section=cabinet"
BALANCE_CACHE_TTL = 60

# Steam Web API
STEAM_API_KEY = "YOUR_STEAM_API_KEY"
STEAM_API_BASE = "https://api.steampowered.com"
STEAM_STATS_CACHE_TTL = 300
CS2_APP_ID = 730

# Telegram Mini App (Cloudflare Worker)
WEBAPP_URL = ""  # пусто — кнопки мини-приложения нет
WEBAPP_AUTH_SECRET = "YOUR_WORKER_AUTH_SECRET"

# Telegram user_id администраторов (могут /announce). Узнать свой: @userinfobot.
ADMIN_IDS = []

# URL скачивания расширения (raw-ссылка на zip в репозитории).
EXTENSION_DOWNLOAD_URL = "https://github.com/caddend/faceit-bot/raw/main/extension.zip"


def create_bot() -> Bot:
    session = AiohttpSession(api=TelegramAPIServer.from_base(CUSTOM_API_URL))
    return Bot(token=TG_TOKEN, session=session, default=DefaultBotProperties(parse_mode="HTML"))
