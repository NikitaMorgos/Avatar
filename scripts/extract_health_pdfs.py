# -*- coding: utf-8 -*-
"""Extract text from health analysis PDFs and output JSON for Avatar Health Analyses."""
import json
import re
from pathlib import Path

try:
    from pypdf import PdfReader
except ImportError:
    from PyPDF2 import PdfReader

PDF_DIR = Path(r"c:\Users\user\Dropbox\Ironman\обследование\анализы")
OUT_JSON = Path(__file__).resolve().parent.parent / "health_analyses_extracted.json"
FILES = [
    ("202508_витаминD.pdf", "Витамин D", "blood"),
    ("202508_профили.pdf", "Биохимические профили", "blood"),
    ("202508_профили2.pdf", "Биохимические профили (часть 2)", "blood"),
]

# Skip header-like keys
SKIP_KEYS = re.compile(
    r"номер\s+заказа|в\s+очереди|дата\s+рождения|дата\s+заказа|дата\s+исследования|"
    r"дата\s+принятия|дата\s+исследовани|фио\s+пациента|направление|направил|выполнил|"
    r"группа\s+исследований|параметр\s+исследования|результат\s+ед|референсные|"
    r"комментарий|анализ\s+выполнен|перейти\s+на|исходный\s+документ|карты|"
    r"order|patient|date\s+of|№\s+карты|заказ|^\s*$",
    re.I
)


def extract_text(path: Path) -> str:
    reader = PdfReader(str(path))
    parts = []
    for p in reader.pages:
        try:
            parts.append(p.extract_text() or "")
        except Exception:
            parts.append("")
    return "\n".join(parts)


def parse_lab_lines(text: str) -> list[tuple[str, str]]:
    """Find lab result lines: 'Name: value unit' or 'Name  value  unit  ref'."""
    pairs = []
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = [s.strip() for s in text.split("\n") if s.strip()]
    for line in lines:
        if len(line) > 150 or len(line) < 4:
            continue
        # "Name: value unit" or "Name: value"
        m = re.match(r"^([^:：\n]+?)\s*[:：]\s*([\d.,]+\s*[а-яa-z/%°·\s\-]*)\s*$", line, re.I)
        if m:
            name, val = m.group(1).strip(), m.group(2).strip()
            if SKIP_KEYS.search(name) or not name or not val or name.isdigit():
                continue
            if re.match(r"^[\d.,\s]+$", name):
                continue
            pairs.append((name[:80], val))
            continue
        # "Name  number  unit  ref" e.g. "Витамин D 58.9 ng/ml 30.00-100.00"
        m = re.match(
            r"^([а-яёa-z\s\-/]+?)\s+([\d.,]+)\s+([а-яa-z/%°·]+)(?:\s+[\d.,\-]+)?\s*$",
            line, re.I | re.U
        )
        if m:
            name, num, unit = m.group(1).strip(), m.group(2).strip(), (m.group(3) or "").strip()
            if len(name) < 2 or len(name) > 55:
                continue
            if SKIP_KEYS.search(name):
                continue
            val = f"{num} {unit}".strip()
            pairs.append((name[:80], val))
            continue
        # "Name  number  unit" without reference at end
        m = re.match(r"^([а-яёa-z\s\-/]+?)\s+([\d.,]+)\s*([а-яa-z/%°·]*)\s*$", line, re.I | re.U)
        if m:
            name, num, unit = m.group(1).strip(), m.group(2).strip(), (m.group(3) or "").strip()
            if len(name) < 2 or len(name) > 55 or name.isdigit():
                continue
            if SKIP_KEYS.search(name):
                continue
            val = f"{num} {unit}".strip()
            pairs.append((name[:80], val))
    return pairs


def build_description(pairs: list[tuple[str, str]], max_len: int = 500) -> str:
    if not pairs:
        return ""
    parts = [f"{n}: {v}" for n, v in pairs[:30]]
    s = "; ".join(parts)
    if len(s) > max_len:
        s = s[: max_len - 3] + "..."
    return s


def main():
    out = []
    for filename, title, atype in FILES:
        path = PDF_DIR / filename
        if not path.exists():
            out.append({
                "date": "2025-08-01",
                "type": atype,
                "description": title,
                "notes": f"(файл не найден: {filename})",
            })
            continue
        try:
            text = extract_text(path)
            # Debug: save extracted text (optional)
            # debug_txt = Path(__file__).resolve().parent.parent / f"health_debug_{filename}.txt"
            # debug_txt.write_text(text, encoding="utf-8")
        except Exception as e:
            out.append({
                "date": "2025-08-01",
                "type": atype,
                "description": title,
                "notes": f"(ошибка чтения: {e})",
            })
            continue
        pairs = parse_lab_lines(text)
        desc = build_description(pairs) if pairs else title
        out.append({
            "date": "2025-08-01",
            "type": atype,
            "description": desc,
            "notes": f"Файл: {filename}",
        })
    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print("Written:", OUT_JSON)


if __name__ == "__main__":
    main()
