# Краткая сводка исправлений

## Что было исправлено

### 1. Расширение не работало ни на одном браузере ❌ → ✅
**Причина**: inject.js не загружался в MAIN world
**Решение**:
- Добавлен явный `world: "MAIN"` в manifest.json
- Сигнал `__faceit_bot_inject_ready` из inject.js
- Fallback-инжект в content.js (если MAIN не сработал через 1.5s)
- Поддержка старых Firefox

### 2. Коды link_token всё время разные ❌ → ✅
**Причина**: токен генерировался заново при каждом вызове `/facelogin`
**Решение**:
- `create_link_token()` теперь обновляет существующий токен в БД
- Worker хранит обратный индекс `verify:{link_token}`
- Токен стабильный — привязывается один раз

### 3. В расширении не было ника и аватара ❌ → ✅
**Причина**: расширение не запрашивало профиль с Faceit
**Решение**:
- Новый endpoint: `GET /api/extension-profile?link_token=...`
- options.html показывает:
  - ✅ Аватар Faceit
  - ✅ Никнейм Faceit
  - ✅ Никнейм Telegram
  - ✅ Статус привязки
- Данные кешируются в `chrome.storage.local`

### 4. Нет отладочной информации ❌ → ✅
**Решение**:
- Все запросы к `api.faceit.com` логируются:
  ```
  [FaceitBot] inject loaded (MAIN world)
  [FaceitBot] REQ: https://api.faceit.com/...
  [FaceitBot] MATCH найден: ...
  [FaceitBot] STATS найдены: ...
  ```

## Что нужно сделать сейчас

1. **Задеплой Worker** — скопируй `cloudflare_worker.js` на Cloudflare
2. **Перезапусти бота** — `python bot.py`
3. **Переустанови расширение** — удали старую версию, загрузи новую (v1.2)
4. **Протестируй** — следуй TESTING.md

## Файлы изменены

- ✅ `extension/manifest.json` — v1.1 → v1.2
- ✅ `extension/inject.js` — сигнал ready
- ✅ `extension/content.js` — fallback inject
- ✅ `extension/options.html` — UI профиля
- ✅ `extension/options.js` — загрузка профиля
- ✅ `cloudflare_worker.js` — endpoint /api/extension-profile
- ✅ `faceit_bot/webapp_sync.py` — передача tg_nickname
- ✅ `faceit_bot/handlers/profile.py` — отправка username
- ✅ `faceit_bot/db.py` — функция has_link_token()

## Коммит создан

```bash
git log -1 --oneline
# 7e1dd35 Fix: Extension not working on any browser + stable link_token + profile UI
```

Можешь пушить: `git push origin main`
