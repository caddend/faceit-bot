# Extension v1.2 - Готово к использованию

## ✅ Рабочее расширение загружено на GitHub

### Прямая ссылка для скачивания:
```
https://github.com/caddend/faceit-bot/raw/main/extension.zip
```

## Что исправлено в v1.2:

1. ✅ **Работает на всех браузерах** (Chrome, Firefox, Edge)
   - Явный `world: "MAIN"` для inject.js
   - Fallback-инжект если MAIN не загрузился
   - Сигнал `__faceit_bot_inject_ready`

2. ✅ **Стабильный link_token**
   - Токен генерируется один раз
   - При повторном `/facelogin` возвращается тот же токен
   - Хранится в БД навсегда

3. ✅ **UI с профилем**
   - Аватар Faceit
   - Никнейм Faceit
   - Никнейм Telegram
   - Статус привязки

4. ✅ **Debug-логи**
   - Все запросы к api.faceit.com в консоли
   - `[FaceitBot] inject loaded (MAIN world)`
   - `[FaceitBot] MATCH найден`
   - `[FaceitBot] STATS найдены`

## Установка:

### Шаг 1: Скачай расширение
Скачай `extension.zip` с GitHub:
```
https://github.com/caddend/faceit-bot/raw/main/extension.zip
```
Распакуй в любую папку.

### Шаг 2: Загрузи в браузер

**Chrome / Edge:**
1. `chrome://extensions`
2. Включи "Режим разработчика"
3. "Загрузить распакованное"
4. Выбери папку с extension

**Firefox:**
1. `about:debugging`
2. "This Firefox"
3. "Load Temporary Add-on"
4. Выбери `manifest.json`

### Шаг 3: Привяжи токен
1. В боте: `/facelogin`
2. Скопируй токен
3. Кликни иконку расширения
4. Вставь токен → "Сохранить"

### Шаг 4: Проверь
1. Открой faceit.com
2. F12 → Консоль
3. Должно быть: `[FaceitBot] inject loaded (MAIN world)`

## Версия:
- manifest.json: **1.2**
- Коммит: `01f24f9`
- Дата: 2026-08-16

## Файлы в архиве:
- manifest.json (v1.2)
- inject.js (MAIN world + сигнал ready)
- content.js (fallback inject)
- options.html (UI с профилем)
- options.js (загрузка профиля)
- icons/ (иконки 16/48/128)

## Требования:
- Бот должен быть запущен (`python bot.py`)
- Worker должен быть задеплоен на Cloudflare
- Привязанный никнейм в боте (`/setnick`)

## Если не работает:
Смотри подробную инструкцию в `RELOAD_EXTENSION.md`
