"""
Анализ спринта через Perplexity API.
Промпт из Анализ спринта_Perplexity.pdf — выдаёт структурированный разбор.
"""

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """Ты — Perplexity, личный помощник и коуч пользователя.
Роли: личный PA, проджект/продакт, коуч, спец по личному развитию.
У пользователя есть три уровня данных: Goals 2026, Goals 1Q2026, и таблица спринта.
Курсор может собрать эти данные и передать тебе в виде JSON (поле sprint, items, insights).
Если каких‑то полей нет, они могут быть null. Главное — сохраняется общая структура.

Что ты должен выдать в ответ (компактно, но содержательно):
1. Сильные стороны спринта (2–5 пунктов)
2. Зоны внимания / риски (2–5 пунктов)
3. Выводы по системе планирования (1–3 пункта)
4. Рекомендации на следующий спринт (3–7 пунктов)
5. Один коучинговый вопрос в конце

Стиль: кратко, без пересказа таблиц; списки и короткие абзацы; тон уважительный партнёрский.
Не ссылайся на JSON/колонки в явном виде; говори человеческим языком."""


def call_perplexity(sprint_json: dict, api_key: str | None = None) -> str:
    """Вызывает Perplexity API и возвращает текст анализа."""
    import os
    key = api_key or os.getenv("PERPLEXITY_API_KEY", "").strip()
    if not key:
        raise ValueError("PERPLEXITY_API_KEY не задан в .env")
    try:
        from openai import OpenAI
        client = OpenAI(api_key=key, base_url="https://api.perplexity.ai")
    except ImportError:
        from perplexity import Perplexity
        client = Perplexity(api_key=key)
    payload = json.dumps(sprint_json, ensure_ascii=False, indent=2)
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"Проанализируй отчёт по спринту. Данные:\n\n{payload}"},
    ]
    resp = client.chat.completions.create(
        model="sonar",
        messages=messages,
    )
    return resp.choices[0].message.content


def _find_cyrillic_font() -> Path | None:
    """Ищет шрифт с поддержкой кириллицы."""
    base = Path(__file__).resolve().parent.parent
    candidates = [
        base / "fonts" / "DejaVuSansCondensed.ttf",
        base / "fonts" / "DejaVuSans.ttf",
        Path("C:/Windows/Fonts/arial.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
    ]
    for p in candidates:
        if p.exists():
            return p
    return None


def _wrap_line(line: str, max_chars: int = 65) -> list[str]:
    """Разбивает длинную строку на части, чтобы не было ошибки 'Not enough horizontal space' в PDF."""
    line = "".join(c for c in line if c.isprintable() or c in "\n\t ")
    if len(line) <= max_chars:
        return [line] if line.strip() else []
    parts = []
    while line:
        if len(line) <= max_chars:
            parts.append(line)
            break
        chunk = line[:max_chars]
        last_space = chunk.rfind(" ")
        if last_space > max_chars // 2:
            chunk, line = chunk[: last_space + 1], line[last_space + 1 :].lstrip()
        else:
            chunk, line = chunk, line[max_chars:]
        parts.append(chunk)
    return parts


def text_to_pdf(text: str, out_path: Path) -> None:
    """Сохраняет текст в PDF (fpdf2) с поддержкой кириллицы."""
    from fpdf import FPDF
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.set_margins(15, 15, 15)
    pdf.add_page()
    font_path = _find_cyrillic_font()
    if font_path:
        pdf.add_font("Cyrillic", "", str(font_path), uni=True)
        pdf.set_font("Cyrillic", "", 10)
    else:
        pdf.set_font("Helvetica", size=10)
    # Явная ширина ячейки (мм), чтобы не было "Not enough horizontal space"
    cell_w = pdf.w - pdf.l_margin - pdf.r_margin
    for raw_line in text.replace("\r", "").split("\n"):
        line = raw_line.strip()
        if not line:
            pdf.ln(3)
            continue
        if not font_path:
            line = line.encode("latin-1", "replace").decode("latin-1")
        for part in _wrap_line(line):
            if part:
                pdf.multi_cell(cell_w, 6, part)
    pdf.output(str(out_path))
