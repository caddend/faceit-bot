"""Генерация картинок (единый монохромный стиль, как в /elo).

Содержит существующие функции render_compare_chart, render_map_chart,
render_activity_chart и НОВУЮ render_stats_image — расширенную
статистику в виде таблиц-блоков на одной картинке.
"""
import io

from .faceit_api import _to_number


def _import_mpl():
    """Возвращает (plt, None) или (None, None) если matplotlib недоступен."""
    try:
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
        return plt
    except ImportError:
        return None


# ============================================================
#  Существующие графики (перенесено из bot.py)
# ============================================================

def render_compare_chart(p1: dict, p2: dict):
    """Возвращает PNG (bytes) с гистограммами по каждой метрике сравнения,
    либо None, если matplotlib недоступен или сравнивать нечего."""
    plt = _import_mpl()
    if plt is None:
        return None

    metrics = [
        ("ELO", 'elo'), ("Матчи", 'matches'), ("Винрейт %", 'winrate'),
        ("K/D", 'kd'), ("HS %", 'hs'),
    ]
    usable = []
    for label, key in metrics:
        v1, v2 = _to_number(p1.get(key)), _to_number(p2.get(key))
        if v1 is not None and v2 is not None:
            usable.append((label, v1, v2))

    if not usable:
        return None

    fig, axes = plt.subplots(1, len(usable), figsize=(2.6 * len(usable), 3.6))
    if len(usable) == 1:
        axes = [axes]

    for ax, (label, v1, v2) in zip(axes, usable):
        ax.bar([0, 1], [v1, v2], color=['#444444', '#999999'], width=0.55)
        ax.set_xticks([0, 1])
        ax.set_xticklabels([p1['nickname'], p2['nickname']], rotation=20, ha='right', fontsize=8)
        ax.set_title(label, fontsize=10)
        for i, v in enumerate([v1, v2]):
            ax.text(i, v, f"{v:g}", ha='center', va='bottom', fontsize=8)
        ax.spines['top'].set_visible(False)
        ax.spines['right'].set_visible(False)

    fig.suptitle(f"{p1['nickname']}  vs  {p2['nickname']}", fontsize=11)
    fig.tight_layout()

    buf = io.BytesIO()
    fig.savefig(buf, format='png', dpi=140)
    plt.close(fig)
    buf.seek(0)
    return buf.read()


def render_map_chart(maps_info: list, nickname: str, limit: int = 10):
    """Горизонтальная гистограмма по картам: длина полосы — число матчей,
    подпись у полосы — винрейт. Возвращает PNG (bytes) или None."""
    plt = _import_mpl()
    if plt is None:
        return None

    data = maps_info[:limit]
    if not data:
        return None

    names = [m['name'] for m in reversed(data)]
    matches = [m['matches'] for m in reversed(data)]
    winrates = [m['winrate'] for m in reversed(data)]

    fig, ax = plt.subplots(figsize=(7, 0.5 * len(data) + 1.5))
    bars = ax.barh(names, matches, color='#444444', height=0.55)
    ax.set_xlabel("Матчей")
    ax.set_title(f"Карты: {nickname}")
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)

    for bar, wr in zip(bars, winrates):
        ax.text(bar.get_width(), bar.get_y() + bar.get_height() / 2,
                f" {wr}% WR", va='center', fontsize=8)

    fig.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format='png', dpi=140)
    plt.close(fig)
    buf.seek(0)
    return buf.read()


def render_activity_chart(days_data: list, nickname: str):
    """Столбчатый график матчей по дням за 30 дней (победы/поражения стопкой).
    days_data — список словарей {'date': 'YYYY-MM-DD', 'wins': int, 'losses': int},
    отсортированный по возрастанию даты. Возвращает PNG (bytes) или None."""
    plt = _import_mpl()
    if plt is None:
        return None

    if not days_data:
        return None

    labels = [d['date'][5:] for d in days_data]  # MM-DD
    wins = [d['wins'] for d in days_data]
    losses = [d['losses'] for d in days_data]

    fig, ax = plt.subplots(figsize=(11, 4))
    ax.bar(labels, wins, color='#444444', label='Победы', width=0.7)
    ax.bar(labels, losses, bottom=wins, color='#bbbbbb', label='Поражения', width=0.7)

    ax.set_title(f"Активность за 30 дней: {nickname}")
    ax.set_ylabel("Матчей")
    ax.legend(frameon=False, fontsize=8, loc='upper left')
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)

    step = max(1, len(labels) // 15)
    tick_positions = list(range(0, len(labels), step))
    ax.set_xticks(tick_positions)
    ax.set_xticklabels([labels[i] for i in tick_positions], rotation=45, ha='right', fontsize=7)

    fig.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format='png', dpi=140)
    plt.close(fig)
    buf.seek(0)
    return buf.read()


# ============================================================
#  НОВАЯ: render_stats_image — расширенная /stats картинкой
# ============================================================

def _num(value, default=0):
    """Безопасное преобразование строки/числа в int (для суммирования из сегментов)."""
    try:
        return int(str(value).replace(',', '') or default)
    except (TypeError, ValueError):
        return default


def _pct(part, total):
    """Процент: part/total*100, округлённый до целого. 'N/A' если total==0."""
    return f"{round(part / total * 100)}%" if total else "N/A"


def render_stats_image(stats_data: dict, player_data: dict, nickname: str):
    """Возвращает PNG (bytes) с таблицами полной статистики, либо None.

    Рисует 6 блоков подтаблиц на одной картинке (matplotlib):
    1. Общая статистика
    2. Серии убийств (мультикиллы)
    3. Энтри
    4. Клатчи (1v1, 1v2)
    5. Снаряжение (флешки)
    6. Топ-3 карты
    """
    plt = _import_mpl()
    if plt is None:
        return None

    lifetime = stats_data.get('lifetime', {})
    segments = stats_data.get('segments', [])

    # --- Суммирование из сегментов (mode=5v5, type=Map) ---
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
            map_stats = seg.get('stats', {})

            total_kills += _num(map_stats.get('Kills'))
            total_deaths += _num(map_stats.get('Deaths'))
            total_assists += _num(map_stats.get('Assists'))
            total_hs += _num(map_stats.get('Headshots'))
            total_rounds += _num(map_stats.get('Rounds'))
            total_mvps += _num(map_stats.get('MVPs'))

            triple += _num(map_stats.get('Triple Kills'))
            quadro += _num(map_stats.get('Quadro Kills'))
            penta += _num(map_stats.get('Penta Kills'))

            c1v1_count += _num(map_stats.get('1v1Count'))
            c1v1_wins += _num(map_stats.get('1v1Wins'))
            c1v2_count += _num(map_stats.get('1v2Count'))
            c1v2_wins += _num(map_stats.get('1v2Wins'))

            entry_count += _num(map_stats.get('Entry Count'))
            entry_wins += _num(map_stats.get('Entry Wins'))

            flash_count += _num(map_stats.get('Flash Count'))
            flash_success += _num(map_stats.get('Flash Successes'))

            kr_val = _to_number(map_stats.get('K/R Ratio'))
            if kr_val is not None:
                kr_sum += kr_val
                map_count += 1

            m_played = _num(map_stats.get('Matches'))
            if m_played > 0:
                maps_info.append({
                    'name': seg.get('label', 'Unknown'),
                    'matches': m_played,
                    'winrate': map_stats.get('Win Rate %', '0'),
                    'kd': map_stats.get('Average K/D Ratio', '0'),
                })

    maps_info.sort(key=lambda x: x['matches'], reverse=True)

    # --- Данные из lifetime ---
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

    # --- Блоки данных (каждый — список [param, value] строк) ---
    block_general = [
        ["Матчи", str(matches)],
        ["Победы", str(wins)],
        ["Поражения", str(losses)],
        ["Раундов", str(total_rounds)],
        ["Винрейт", f"{winrate}%"],
        ["Винстрик", str(current_streak)],
        ["Рекорд стрик", str(longest_streak)],
        ["Убийства", str(total_kills)],
        ["Смерти", str(total_deaths)],
        ["Ассисты", str(total_assists)],
        ["K/D", str(kd)],
        ["K/R (avg)", kr_avg],
        ["Хедшоты", str(total_hs)],
        ["HS%", f"{avg_hs}%"],
        ["MVP", str(total_mvps)],
    ]

    block_multikills = [
        ["Эйсы (5K)", str(penta)],
        ["4K", str(quadro)],
        ["3K", str(triple)],
    ]

    block_entry = [
        ["Попытки энтри", str(entry_count)],
        ["Успешные энтри", str(entry_wins)],
        ["Процент энтри", _pct(entry_wins, entry_count)],
    ]

    block_clutch = [
        ["1v1 победы", str(c1v1_wins)],
        ["1v1 поражения", str(c1v1_count - c1v1_wins)],
        ["1v1 процент", _pct(c1v1_wins, c1v1_count)],
        ["1v2 победы", str(c1v2_wins)],
        ["1v2 поражения", str(c1v2_count - c1v2_wins)],
        ["1v2 процент", _pct(c1v2_wins, c1v2_count)],
    ]

    block_flash = [
        ["Брошено флешек", str(flash_count)],
        ["Ослеплено", str(flash_success)],
        ["Процент попаданий", _pct(flash_success, flash_count)],
        ["Флешек за раунд", flash_per_round],
    ]

    block_maps = [
        [m['name'], str(m['matches']), f"{m['winrate']}%", str(m['kd'])]
        for m in maps_info[:3]
    ]

    # --- Рендеринг подтаблиц ---
    blocks = [
        ("Общая статистика", block_general, ["Параметр", "Значение"]),
        ("Серии убийств", block_multikills, ["Параметр", "Значение"]),
        ("Энтри", block_entry, ["Параметр", "Значение"]),
        ("Клатчи", block_clutch, ["Параметр", "Значение"]),
        ("Снаряжение (флешки)", block_flash, ["Параметр", "Значение"]),
    ]
    if block_maps:
        blocks.append(("Топ-3 карты", block_maps, ["Карта", "M", "WR", "K/D"]))

    # Расчёт размеров grid: 3 колонки x 2 ряда = до 6 блоков
    n_blocks = len(blocks)
    ncols = 3
    nrows = (n_blocks + ncols - 1) // ncols

    fig, axes = plt.subplots(nrows, ncols, figsize=(9 * ncols, 5 * nrows))
    # Нормализуем axes в плоский список
    axes_flat = []
    if n_blocks == 1:
        axes_flat = [axes]
    else:
        axes_flat = list(axes.flat)

    for idx, (title, rows, headers) in enumerate(blocks):
        ax = axes_flat[idx]
        _draw_table(ax, title, rows, headers)

    # Скрываем лишние subplot'ы
    for idx in range(n_blocks, len(axes_flat)):
        axes_flat[idx].axis('off')

    fig.suptitle(f"Статистика: {nickname}", fontsize=16, fontweight='bold')
    fig.tight_layout(rect=[0, 0, 1, 0.96])

    buf = io.BytesIO()
    fig.savefig(buf, format='png', dpi=160)
    plt.close(fig)
    buf.seek(0)
    return buf.read()


def _draw_table(ax, title: str, rows, headers):
    """Рисует одну подтаблицу на заданном ax (без осей, текстовая таблица)."""
    ax.axis('off')

    all_rows = [headers] + rows
    cols = len(headers)
    nrows = len(rows) + 2  # header + separator + data

    # Вычисляем ширины колонок
    widths = [0] * cols
    for r in all_rows:
        for i, cell in enumerate(r):
            widths[i] = max(widths[i], len(str(cell)))

    def fmt_row(r, align_right=False):
        parts = []
        for i, cell in enumerate(r):
            cell_str = str(cell)
            if align_right and i > 0:
                parts.append(cell_str.rjust(widths[i]))
            else:
                parts.append(cell_str.ljust(widths[i]))
        return "  ".join(parts)

    header_line = fmt_row(headers, align_right=True)
    sep_line = "-" * (sum(widths) + 2 * (cols - 1))

    lines = [header_line, sep_line]
    for r in rows:
        lines.append(fmt_row(r, align_right=True))

    table_text = "\n".join(lines)

    ax.text(0.02, 0.98, table_text,
            transform=ax.transAxes,
            fontsize=13,
            fontfamily='monospace',
            verticalalignment='top',
            bbox=dict(boxstyle='round,pad=0.8', facecolor='#f5f5f5', edgecolor='#cccccc'))
    ax.set_title(title, fontsize=13, fontweight='bold', loc='left', pad=10)
