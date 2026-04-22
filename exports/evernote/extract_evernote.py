# -*- coding: utf-8 -*-
"""One-off: parse ENEX and extract Darina + travel mentions."""
import html
import re
from pathlib import Path


def strip_tags(s: str) -> str:
    if not s:
        return ""
    s = re.sub(r"<script[^>]*>.*?</script>", "", s, flags=re.DOTALL | re.I)
    s = re.sub(r"<style[^>]*>.*?</style>", "", s, flags=re.DOTALL | re.I)
    s = re.sub(r"<[^>]+>", " ", s)
    s = html.unescape(s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def parse_enex(path: Path) -> list[dict]:
    raw = path.read_text(encoding="utf-8", errors="replace")
    notes = []
    for m in re.finditer(
        r"<title>([^<]*)</title>.*?<content>\s*<!\[CDATA\[(.*?)\]\]>\s*</content>",
        raw,
        re.DOTALL,
    ):
        title = html.unescape(m.group(1))
        plain = strip_tags(m.group(2))
        notes.append({"title": title, "text": plain, "file": path.name})
    return notes


# Keywords for Darina (nicknames + name forms)
DARINA_RE = re.compile(
    r"(?i)(дарин[а-яё]{0,4}|дарякв|дарюшм|дарюш[а-яё]{0,3}|пузяк|дарюх|дариш|дарква|дарюн|даришк|дарюшун)",
    re.UNICODE,
)

# Travel / location heuristics
TRAVEL_RE = re.compile(
    r"(?i).{0,80}("
    r"поездк|переезд|аэропорт|самолет|границ|заграниц|отпуск|"
    r"внуково|шереметьево|домодедово|красн(ая)?\s+полян|пятигорск|"
    r"ярославл|тверь|амстердам|болгар|индия|индию|индии|"
    r"турци|испани|итали|герман|франц|польш|черногор|"
    r"грузи|армени|казахстан|беларус|украин|"
    r"на\s+море|за\s+рубеж|в\s+командировк"
    r").{0,220}",
    re.DOTALL | re.UNICODE,
)


def match_contexts(text: str, pattern: re.Pattern, before: int = 100, after: int = 220) -> list[str]:
    out = []
    for m in pattern.finditer(text):
        start = max(0, m.start() - before)
        end = min(len(text), m.end() + after)
        s = text[start:end].strip()
        if len(s) > 400:
            s = s[:397] + "..."
        out.append(s)
    return out


def travel_snippets(text: str, pattern: re.Pattern, max_len: int = 360) -> list[str]:
    out = []
    for m in pattern.finditer(text):
        s = m.group(0).strip()
        if len(s) > max_len:
            s = s[: max_len - 3] + "..."
        out.append(s)
    return out


def main() -> None:
    base = Path(__file__).resolve().parent / "Evernote_backup"
    all_notes: list[dict] = []
    for f in sorted(base.glob("*.enex")):
        all_notes.extend(parse_enex(f))

    dar_blocks: list[tuple[str, str, str]] = []
    travel_blocks: list[tuple[str, str, str]] = []

    for n in all_notes:
        t = n["text"]
        title = n["title"]
        fname = n["file"]
        if DARINA_RE.search(t):
            for sn in match_contexts(t, DARINA_RE):
                dar_blocks.append((fname, title, sn))
        if TRAVEL_RE.search(t):
            for sn in travel_snippets(t, TRAVEL_RE):
                travel_blocks.append((fname, title, sn))

    out_path = Path(__file__).resolve().parent / "darina_and_travel_extract.txt"
    lines = [
        f"Всего заметок в экспорте: {len(all_notes)}",
        "",
        "=== УПОМИНАНИЯ ДАРИНЫ / НИКНЕЙМОВ (по контексту) ===",
        "",
    ]
    for fname, title, sn in dar_blocks:
        lines.append(f"[{fname}] {title}")
        lines.append(f"  {sn}")
        lines.append("")

    lines.extend(
        [
            "",
            "=== ЛОКАЦИИ / ПОЕЗДКИ / ПЕРЕЕЗДЫ (эвристика по словам) ===",
            "",
        ]
    )
    for fname, title, sn in travel_blocks:
        lines.append(f"[{fname}] {title}")
        lines.append(f"  {sn}")
        lines.append("")

    out_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"Wrote {out_path}")
    print(f"Notes: {len(all_notes)}, darina snippets: {len(dar_blocks)}, travel: {len(travel_blocks)}")


if __name__ == "__main__":
    main()
