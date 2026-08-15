# Faceit Tracker Bot

Telegram-бот для отслеживания статистики CS2 на Faceit: матч-трекер, ИИ-анализ, Steam lifetime-статистика, ELO-графики, мини-приложение.

## Возможности

- `/stats [ник]` — расширенная статистика Faceit + Steam (картинка)
- `/elo` — динамика ELO (график)
- `/last [ник]` — последний матч со скорбордом
- `/history [ник]` — история матчей
- `/prematch` — ИИ-анализ состава команд перед матчем
- `/compare ник1 ник2` — сравнение игроков
- `/map [карта]` — статистика по картам
- `/session` — текущая игровая сессия
- `/top` — рейтинги пользователей бота
- `/activity` — активность за 30 дней
- `/facelogin` — привязка Faceit-аккаунта (для текущих матчей)
- `/aimode` — режим ИИ-консультанта по CS2

## Установка

1. `pip install aiogram aiohttp anthropic matplotlib`
2. Скопируй `faceit_bot/config.example.py` → `faceit_bot/config.py`, впиши свои токены
3. Задеплой `cloudflare_worker.js` на Cloudflare Workers (для мини-приложения)
4. `python bot.py`

## Браузерное расширение (токен Faceit)

Для `/facelogin` — расширение в папке `extension/`. Перехватывает Bearer-токен из заголовков запросов к api.faceit.com, копирует в буфер и открывает чат бота.

- Chrome/Edge: `chrome://extensions` → Режим разработчика → Загрузить распакованное → папка `extension/`
- Firefox: `about:debugging` → Load Temporary Add-on → `extension/manifest.json`

Перед использованием замени `BOT_USERNAME` в `extension/background.js` и `extension/prompt.js` на username твоего бота.
