LINE = "-" * 32


def section(title: str) -> str:
    return f"<b>{title}</b>\n{LINE}"


def kv(label: str, value) -> str:
    return f"{label}: <b>{value}</b>"


def table(rows, headers=None) -> str:
    all_rows = ([headers] if headers else []) + list(rows)
    if not all_rows:
        return ""
    cols = len(all_rows[0])
    widths = [0] * cols
    for row in all_rows:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(str(cell)))

    def fmt_row(row):
        parts = []
        for i, cell in enumerate(row):
            cell_str = str(cell)
            parts.append(cell_str.ljust(widths[i]) if i == 0 else cell_str.rjust(widths[i]))
        return "  ".join(parts)

    lines = []
    if headers:
        lines.append(fmt_row(headers))
        lines.append("-" * (sum(widths) + 2 * (cols - 1)))
    lines.extend(fmt_row(row) for row in rows)
    return "\n".join(lines)


def trend_arrow(delta) -> str:
    try:
        value = float(delta)
    except (TypeError, ValueError):
        return ""
    if value > 0:
        return "+"
    if value < 0:
        return ""
    return " "
