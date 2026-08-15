# Changelog - Extension Fix

## 2026-08-15 - Исправление расширения

### Исправлено
- **Расширение не работало на всех браузерах** (Chrome, Firefox, Edge)
  - Добавлен сигнал `__faceit_bot_inject_ready` из inject.js
  - Fallback-инжект если MAIN-world не загрузился (Firefox)
  - Явный `world: "MAIN"` в manifest.json v1.2
  
- **Коды link_token всё время разные**
  - Теперь токен генерируется один раз и сохраняется в БД
  - Worker хранит обратный индекс verify:{link_token}
  
- **В расширении не отображались ник и аватар**
  - Добавлен endpoint `/api/extension-profile` в Worker
  - options.html теперь показывает:
    - Аватар с Faceit
    - Никнейм Faceit
    - Никнейм Telegram
    - Статус привязки
  - Данные кешируются в chrome.storage.local

### Добавлено
- **Worker API**:
  - `GET /api/extension-profile?link_token=...` — профиль для UI расширения
  - Worker теперь хранит `tg_nickname` в KV
  
- **Расширение UI**:
  - Карточка профиля в options.html
  - Индикатор статуса (активно / не проверен / не привязан)
  - Улучшенный дизайн настроек

### Технические изменения
- `inject.js`: сигнал ready в начале скрипта
- `content.js`: таймаут 1.5s для проверки MAIN-world inject
- `cloudflare_worker.js`: 
  - Хранение tg_nickname в verify:{link_token}
  - Новый endpoint для профиля расширения
- `faceit_bot/webapp_sync.py`: передача tg_nickname в Worker
- `faceit_bot/handlers/profile.py`: отправка username при /facelogin
- `faceit_bot/db.py`: функция has_link_token()

### Debug
Все запросы к api.faceit.com теперь логируются в консоль:
```
[FaceitBot] inject loaded (MAIN world)
[FaceitBot] REQ: https://api.faceit.com/...
```

Логи Cloudflare/Turnstile не влияют на работу расширения (это нормально).
