"""ИИ-тренёр: анализ статистики игрока через Anthropic API.

Собирает агрегаты статистики + последние матчи, формирует промпт и
отправляет в LLM. Результат кешируется в _api_cache на AI_CACHE_TTL секунд.
"""
import asyncio
import html
import re
import time

from .config import (
    ANTHROPIC_BASE_URL,
    ANTHROPIC_AUTH_TOKEN,
    ANTHROPIC_MODEL,
    AI_CACHE_TTL,
    FACEIT_API_BASE,
)
from .runtime import _api_cache
from .balance import get_balance_footer
from .faceit_api import fetch_faceit_data, _match_result_for_player
from .steam_api import get_cs2_lifetime_stats, get_steam_id_from_faceit

# Проверяем доступность anthropic на уровне импорта (один раз).
try:
    from anthropic import Anthropic
    _ANTHROPIC_AVAILABLE = True
except ImportError:
    Anthropic = None
    _ANTHROPIC_AVAILABLE = False


# Теги, которые LLM может использовать и которые валидны в Telegram HTML.
_VALID_TAGS = re.compile(r'&lt;(/?)(b|i|u|s|code|pre|a)&gt;', re.IGNORECASE)


def _sanitize_for_telegram(text: str) -> str:
    """Превращает произвольный ответ LLM в валидный Telegram HTML.

    1. Экранирует ВСЁ через html.escape (& < >).
    2. Восстанавливает разрешённые теги, которые LLM мог использовать.
    3. Markdown-заголовки (## ...) → <b>...</b>.
    4. Markdown bold (**...** или __...__) → <b>...</b>.
    5. Markdown italic (*...*  или _..._) → <i>...</i> (осторожно: не ломать числа/слова с _).
    """
    if not text:
        return text

    # Шаг 1: экранируем всё
    safe = html.escape(text)

    # Шаг 2: восстанавливаем валидные теги
    safe = _VALID_TAGS.sub(r'<\1\2>', safe)

    # Шаг 3: markdown заголовки ## и # → <b>заголовок</b>
    def _header_repl(m):
        return f"<b>{m.group(1).strip()}</b>"

    safe = re.sub(r'^#{1,6}\s+(.+)$', _header_repl, safe, flags=re.MULTILINE)

    # Шаг 4: markdown bold **text** или __text__ → <b>text</b>
    safe = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', safe)
    safe = re.sub(r'__(.+?)__', r'<b>\1</b>', safe)

    # Шаг 5: markdown italic *text* → <i>text</i> (только одиночные *)
    # Не трогаем ** (уже обработаны выше)
    safe = re.sub(r'(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)', r'<i>\1</i>', safe)

    return safe


def _build_stats_summary(stats_data: dict, player_data: dict, nickname: str) -> str:
    """Собирает компактный текст со всеми агрегатами статистики для промпта."""
    lifetime = stats_data.get('lifetime', {})
    segments = stats_data.get('segments', [])

    def _num(value, default=0):
        try:
            return int(str(value).replace(',', '') or default)
        except (TypeError, ValueError):
            return default

    total_kills = total_deaths = total_assists = total_hs = 0
    total_rounds = total_mvps = 0
    triple = quadro = penta = 0
    c1v1_count = c1v1_wins = c1v2_count = c1v2_wins = 0
    entry_count = entry_wins = 0
    flash_count = flash_success = 0
    kr_sum = 0.0
    map_count = 0

    maps_info = []
    for seg in segments:
        if seg.get('mode') == '5v5' and seg.get('type') == 'Map':
            ms = seg.get('stats', {})
            total_kills += _num(ms.get('Kills'))
            total_deaths += _num(ms.get('Deaths'))
            total_assists += _num(ms.get('Assists'))
            total_hs += _num(ms.get('Headshots'))
            total_rounds += _num(ms.get('Rounds'))
            total_mvps += _num(ms.get('MVPs'))
            triple += _num(ms.get('Triple Kills'))
            quadro += _num(ms.get('Quadro Kills'))
            penta += _num(ms.get('Penta Kills'))
            c1v1_count += _num(ms.get('1v1Count'))
            c1v1_wins += _num(ms.get('1v1Wins'))
            c1v2_count += _num(ms.get('1v2Count'))
            c1v2_wins += _num(ms.get('1v2Wins'))
            entry_count += _num(ms.get('Entry Count'))
            entry_wins += _num(ms.get('Entry Wins'))
            flash_count += _num(ms.get('Flash Count'))
            flash_success += _num(ms.get('Flash Successes'))

            kr_val = None
            try:
                kr_val = float(str(ms.get('K/R Ratio', '')).replace(',', ''))
            except (TypeError, ValueError):
                pass
            if kr_val is not None:
                kr_sum += kr_val
                map_count += 1

            m_played = _num(ms.get('Matches'))
            if m_played > 0:
                maps_info.append({
                    'name': seg.get('label', 'Unknown'),
                    'matches': m_played,
                    'winrate': ms.get('Win Rate %', '0'),
                    'kd': ms.get('Average K/D Ratio', '0'),
                })

    maps_info.sort(key=lambda x: x['matches'], reverse=True)

    matches = _num(lifetime.get('Matches'))
    wins = _num(lifetime.get('Wins'))
    losses = matches - wins
    winrate = lifetime.get('Win Rate %', 'N/A')
    current_streak = lifetime.get('Current Win Streak', '0')
    longest_streak = lifetime.get('Longest Win Streak', '0')
    kd = lifetime.get('Average K/D Ratio', 'N/A')
    avg_hs = lifetime.get('Average Headshots %', 'N/A')

    kr_avg = f"{round(kr_sum / map_count, 2)}" if map_count else "N/A"
    flash_per_round = f"{round(flash_count / total_rounds, 2)}" if total_rounds else "N/A"

    def _pct(part, total):
        return f"{round(part / total * 100)}%" if total else "N/A"

    elo = player_data.get('games', {}).get('cs2', {}).get('faceit_elo', 'N/A')
    lvl = player_data.get('games', {}).get('cs2', {}).get('skill_level', 'N/A')
    country = player_data.get('country', 'N/A').upper()

    lines = [
        f"Игрок: {nickname}",
        f"ELO: {elo}, Уровень: {lvl}, Регион: {country}",
        f"Матчей: {matches} (W {wins} / L {losses}), Винрейт: {winrate}%",
        f"Винстрик: {current_streak} (рекорд {longest_streak})",
        f"K/D: {kd}, K/R (avg): {kr_avg}, HS%: {avg_hs}%",
        f"Убийства: {total_kills}, Смерти: {total_deaths}, Ассисты: {total_assists}",
        f"Раундов: {total_rounds}, MVP: {total_mvps}, Хедшотов: {total_hs}",
        f"Мультикиллы: 3K={triple}, 4K={quadro}, 5K={penta}",
        f"Энтри: {entry_wins}/{entry_count} ({_pct(entry_wins, entry_count)})",
        f"1v1: {c1v1_wins}/{c1v1_count} ({_pct(c1v1_wins, c1v1_count)})",
        f"1v2: {c1v2_wins}/{c1v2_count} ({_pct(c1v2_wins, c1v2_count)})",
        f"Флешки: {flash_success}/{flash_count} ({_pct(flash_success, flash_count)}), за раунд: {flash_per_round}",
    ]

    if maps_info:
        top_maps = maps_info[:5]
        map_lines = ", ".join(
            f"{m['name']}({m['matches']}m,{m['winrate']}%WR,{m['kd']}KD)"
            for m in top_maps
        )
        lines.append(f"Топ карт: {map_lines}")

    return "\n".join(lines)


def _build_steam_summary(steam_stats: dict) -> str:
    """Компактный текст Steam lifetime статистики для промпта ИИ-тренера.

    steam_stats — {name: value} dict из get_cs2_lifetime_stats.
    Возвращает пустую строку если ключевых данных нет.
    """
    if not steam_stats:
        return ""

    def _num(key, default=0):
        v = steam_stats.get(key, default)
        try:
            return int(v)
        except (TypeError, ValueError):
            return default

    total_kills = _num('total_kills')
    total_deaths = _num('total_deaths')
    total_hs = _num('total_kills_headshot')
    total_mvps = _num('total_mvps')
    total_rounds = _num('total_rounds_played')
    total_matches_won = _num('total_matches_won')
    total_matches = _num('total_matches_played')
    total_shots_fired = _num('total_shots_fired')
    total_damage = _num('total_damage_done')
    total_planted = _num('total_planted_bombs')
    total_defused = _num('total_defused_bombs')
    total_knife = _num('total_kills_knife')
    total_he = _num('total_kills_hegrenade')
    total_molotov = _num('total_kills_molotov')
    total_flash = _num('total_kills_enemy_blinded')

    # total_shots_hit в Steam API сломан (всегда ~8), суммируем total_hits_*
    total_shots_hit = sum(v for k, v in steam_stats.items() if k.startswith('total_hits_'))

    kd_ratio = round(total_kills / total_deaths, 2) if total_deaths else 0
    hs_pct = round(total_hs / total_kills * 100, 1) if total_kills else 0
    accuracy = round(total_shots_hit / total_shots_fired * 100, 1) if total_shots_fired else 0
    adr = round(total_damage / total_rounds, 1) if total_rounds else 0
    winrate = round(total_matches_won / total_matches * 100, 1) if total_matches else 0

    lines = [
        f"K/D: {kd_ratio}, HS%: {hs_pct}%, Точность: {accuracy}%, ADR: {adr}",
        f"Kills: {total_kills}, Deaths: {total_deaths}, MVP: {total_mvps}",
        f"Rounds: {total_rounds}, Матчей: {total_matches} (WR {winrate}%)",
        f"Хедшотов: {total_hs}, Выстрелов: {total_shots_hit}/{total_shots_fired}",
        f"Урон всего: {total_damage}",
        f"Бомбы: planted={total_planted}, defused={total_defused}",
        f"Убийства: нож={total_knife}, HE={total_he}, molotov={total_molotov}, flash={total_flash}",
    ]

    return "\n".join(lines)


async def _build_recent_matches_text(player_id: str, limit: int = 7) -> str:
    """Загружает историю матчей и возвращает компактную строку с результатами."""
    history_data = await fetch_faceit_data(
        f"{FACEIT_API_BASE}/players/{player_id}/history?game=cs2&offset=0&limit={limit}"
    )
    items = history_data.get('items', []) if history_data else []
    if not items:
        return "История матчей недоступна."

    lines = []
    for item in items:
        res = _match_result_for_player(item, player_id)
        outcome = "W" if res is True else ("L" if res is False else "?")
        map_name = item.get('i1', {}).get('map', 'Unknown')
        if not map_name or map_name == 'Unknown':
            map_name = item.get('game_mode', 'Unknown')
        lines.append(f"{outcome} | {map_name}")

    return "\n".join(lines) if lines else "История матчей недоступна."


def build_coach_prompt(stats_summary: str, recent_matches: str, steam_stats_text: str = "") -> tuple:
    """Формирует (system_prompt, user_prompt) для ИИ-тренера.

    steam_stats_text — компактный текст Steam lifetime статистики (может быть пустым).
    """
    system_prompt = (
        "Ты — первоклассный CS2 тренер. Проанализируй статистику игрока, "
        "определи вероятную роль (entry fragger, support, AWPer, IGL, lurker и т.д.), "
        "выдели сильные и слабые стороны, дай конкретный план тренировки "
        "и проанализируй последние матчи. Отвечай на русском, объём 300-400 слов. "
        "Используй HTML-теги <b> для акцентов. "
        "НЕ используй markdown (заголовки #, ##, *, **, __). "
        "Пиши обычный текст, выделяй важное через <b>...</b>."
    )

    steam_block = ""
    if steam_stats_text:
        steam_block = f"\nСтатистика Steam (lifetime, все режимы — MM, Premier, community):\n{steam_stats_text}\n"

    user_prompt = (
        f"Статистика Faceit:\n{stats_summary}\n"
        f"{steam_block}"
        f"\nПоследние матчи (результат | карта):\n{recent_matches}\n\n"
        "Дай полный разбор."
    )
    return system_prompt, user_prompt


async def get_coach_analysis(
    stats_data: dict,
    player_data: dict,
    nickname: str,
    player_id: str,
) -> str | None:
    """Главная функция ИИ-тренера.

    1. Проверяет кеш (_api_cache['coach:{player_id}']).
    2. Собирает промпт (агрегаты + последние матчи).
    3. Вызывает Anthropic API (синхронный вызов обернут в asyncio.to_thread).
    4. Кеширует результат на AI_CACHE_TTL секунд.
    5. Возвращает текст анализа или None при ошибке/нет пакета.
    """
    cache_key = f"coach:{player_id}"
    cached = _api_cache.get(cache_key)
    if cached and (time.time() - cached[0]) < AI_CACHE_TTL:
        return cached[1] + await get_balance_footer()

    if not _ANTHROPIC_AVAILABLE:
        return None

    stats_summary = _build_stats_summary(stats_data, player_data, nickname)
    recent_matches = await _build_recent_matches_text(player_id)

    # Steam lifetime статистика (если SteamID доступен из Faceit профиля)
    steam_stats_text = ""
    steam_id = await get_steam_id_from_faceit(player_data)
    if steam_id:
        steam_stats = await get_cs2_lifetime_stats(steam_id)
        if steam_stats:
            steam_stats_text = _build_steam_summary(steam_stats)

    system_prompt, user_prompt = build_coach_prompt(stats_summary, recent_matches, steam_stats_text)

    def _call_api():
        client = Anthropic(api_key=ANTHROPIC_AUTH_TOKEN, base_url=ANTHROPIC_BASE_URL)
        resp = client.messages.create(
            model=ANTHROPIC_MODEL,
            max_tokens=1024,
            system=system_prompt,
            messages=[
                {"role": "user", "content": user_prompt},
            ],
        )
        # Anthropic API возвращает список content blocks, берём первый text
        return resp.content[0].text

    try:
        text = await asyncio.to_thread(_call_api)
    except Exception:
        return None

    if not text:
        return None

    text = _sanitize_for_telegram(text)

    _api_cache[cache_key] = (time.time(), text)
    return text + await get_balance_footer()

