"""
RAPA: Raw → Assign → Project → Archive
PARA: Projects / Areas / Resources / Archive
Супергерои: Coach, PA, Doctor, Trainer, CEO, Co-founder, PR
"""

import json
import logging
import re
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)

# Супергерои = роли/области
SUPERHERO_AREAS = [
    ("Business", "business", "Personal", "Бизнес, продукты, стартапы"),
    ("Family", "family", "Personal", "Семья, близкие"),
    ("WCS", "wcs", "Creative", "West Coast Swing, танцы"),
    ("Ironman", "ironman", "Personal", "Триатлон, выносливость"),
    ("Coach", "coach", "Personal", "Личное развитие, рефлексия"),
    ("Doctor", "doctor", "Personal", "Здоровье"),
    ("Trainer", "trainer", "Personal", "Спорт, тренировки"),
    ("CEO of projects", "ceo", "Work", "Проекты, стратегия"),
]

# Ключевые слова для классификации (Assign)
AREA_KEYWORDS = {
    "business": ["бизнес", "стартап", "партнёр", "сделка", "договор", "инвестор", "продукт"],
    "family": ["семья", "дети", "родители", "дома"],
    "wcs": ["wcs", "танц", "соревнован", "кадриль"],
    "ironman": ["триатлон", "ironman", "плаван", "вело", "марафон"],
    "coach": ["рефлексия", "цель", "развитие", "привычка", "медитация", "дневник", "diary"],
    "doctor": ["здоровье", "врач", "анализ", "болит", "лечение", "таблетк", "сон", "устал"],
    "trainer": ["тренировка", "спорт", "бег", "зал", "упражнен", "фитнес", "кроссфит"],
    "ceo": ["проект", "задача", "дедлайн", "спринт", "роудмап", "результат"],
}

GTD_TYPES = ["task", "idea", "reference", "someday", "trash"]


def get_db_path() -> str:
    import os
    BASE = Path(__file__).resolve().parent.parent
    return os.getenv("DB_PATH", str(BASE / "db" / "collect.db"))


def init_rapa_schema(conn: sqlite3.Connection) -> None:
    """Применяет RAPA-схему и миграции raw."""
    schema = (Path(__file__).resolve().parent.parent / "db" / "rapa_schema.sql").read_text(encoding="utf-8")
    conn.executescript(schema)

    # Миграции rapa_areas
    for col, typ in [("type", "TEXT"), ("goal", "TEXT")]:
        try:
            conn.execute(f"ALTER TABLE rapa_areas ADD COLUMN {col} {typ}")
            logger.info("Added rapa_areas.%s", col)
        except sqlite3.OperationalError:
            pass
    # Миграции rapa_projects
    for col, typ in [("horizon", "TEXT"), ("impact", "TEXT"), ("effort", "TEXT"), ("start_date", "TEXT"), ("next_review", "TEXT"), ("daily_focus_count", "INTEGER DEFAULT 0")]:
        try:
            conn.execute(f"ALTER TABLE rapa_projects ADD COLUMN {col} {typ}")
            logger.info("Added rapa_projects.%s", col)
        except sqlite3.OperationalError:
            pass
    # Миграции raw: para_type, project_id, area_id, next_action
    for col, typ in [
        ("para_type", "TEXT DEFAULT 'Raw'"),
        ("project_id", "INTEGER"),
        ("area_id", "INTEGER"),
        ("next_action", "TEXT"),
        ("assign_proposed_at", "TEXT"),
    ]:
        try:
            conn.execute(f"ALTER TABLE raw ADD COLUMN {col} {typ}")
            logger.info("Added raw.%s", col)
        except sqlite3.OperationalError:
            pass

    ensure_default_areas(conn)


def classify_raw(content: str) -> dict:
    """Правило-базовая классификация. Возвращает: gtd_type, area_slug, para_type."""
    text = (content or "").lower().strip()
    result = {"gtd_type": "idea", "area_slug": None, "para_type": "Raw"}

    # Actionable?
    actionable = any(w in text for w in ["надо", "нужно", "сделать", "проверить", "позвонить", "написать", "отправить", "купить"])
    if actionable:
        result["gtd_type"] = "task"

    # Area по ключевым словам
    for slug, keywords in AREA_KEYWORDS.items():
        if any(kw in text for kw in keywords):
            result["area_slug"] = slug
            break

    # para_type: если task + контекст проекта → Project, иначе Area/Resource
    if result["gtd_type"] == "task" and result["area_slug"]:
        result["para_type"] = "Project"
    elif result["gtd_type"] == "reference" or ("ссылка" in text or "http" in text):
        result["para_type"] = "Resource"
    elif result["gtd_type"] == "idea" and not result["area_slug"]:
        result["para_type"] = "Raw"

    return result


def assign_raw(raw_id: int, user_id: int, para_type: str, project_id: int | None, area_id: int | None) -> bool:
    """Обновляет Raw: Assign — кладёт в Project/Area/Resource."""
    conn = sqlite3.connect(get_db_path())
    try:
        conn.execute(
            """
            UPDATE raw SET rapa_stage = 'Assign', para_type = ?, project_id = ?, area_id = ?, assign_proposed_at = ?
            WHERE id = ? AND user_id = ?
            """,
            (para_type, project_id, area_id, datetime.utcnow().isoformat(), raw_id, user_id),
        )
        return conn.total_changes > 0
    finally:
        conn.close()


def get_area_id_by_slug(conn: sqlite3.Connection, user_id: int, slug: str) -> int | None:
    row = conn.execute("SELECT id FROM rapa_areas WHERE (user_id = ? OR user_id = 0) AND slug = ? ORDER BY user_id DESC LIMIT 1", (user_id, slug)).fetchone()
    return row[0] if row else None


def ensure_default_areas(conn: sqlite3.Connection) -> None:
    """Создаёт дефолтные области (user_id=0), если их нет."""
    for name, slug, area_type, goal in SUPERHERO_AREAS:
        conn.execute(
            "INSERT OR IGNORE INTO rapa_areas (user_id, name, slug, type, goal, role) VALUES (0, ?, ?, ?, ?, ?)",
            (name, slug, area_type, goal, name),
        )


def propose_assign(raw_id: int, user_id: int, content: str) -> dict:
    """Предлагает Assign для Raw. Возвращает {gtd_type, area_slug, para_type}."""
    cls = classify_raw(content)
    db = get_db_path()
    with sqlite3.connect(db) as conn:
        init_rapa_schema(conn)
        area_id = None
        if cls.get("area_slug"):
            area_id = get_area_id_by_slug(conn, user_id, cls["area_slug"])
        conn.execute(
            """
            UPDATE raw SET gtd_type = ?, rapa_stage = 'Assign', para_type = ?, area_id = ?, assign_proposed_at = ?
            WHERE id = ? AND user_id = ?
            """,
            (cls["gtd_type"], cls["para_type"], area_id, datetime.utcnow().isoformat(), raw_id, user_id),
        )
    return cls


def get_raw_for_review(user_id: int, days: int = 1) -> list[dict]:
    """Raw за последние N дней."""
    since = (datetime.utcnow() - timedelta(days=days)).isoformat()
    with sqlite3.connect(get_db_path()) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT id, title, content, source, created_at, rapa_stage, gtd_type, para_type, tags
            FROM raw WHERE user_id = ? AND created_at >= ? ORDER BY created_at DESC
            """,
            (user_id, since),
        ).fetchall()
    return [dict(r) for r in rows]


def get_all_projects(user_id: int) -> list[dict]:
    """Все проекты для GTD дашборда."""
    with sqlite3.connect(get_db_path()) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT p.id, p.name, p.outcome, p.status, p.horizon, p.impact, p.effort,
                   p.start_date, p.deadline, p.next_review, p.daily_focus_count, a.name as area_name
            FROM rapa_projects p
            LEFT JOIN rapa_areas a ON p.area_id = a.id
            WHERE p.user_id = ? ORDER BY p.status, p.deadline IS NULL, p.deadline
            """,
            (user_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def get_all_areas(user_id: int) -> list[dict]:
    """Все области для GTD дашборда."""
    with sqlite3.connect(get_db_path()) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT id, name, slug, type, goal FROM rapa_areas WHERE user_id = ? OR user_id = 0 ORDER BY name",
            (user_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def get_goals_for_year(user_id: int, year: int) -> list[dict]:
    """Цели на год."""
    with sqlite3.connect(get_db_path()) as conn:
        init_rapa_schema(conn)
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute(
                """
                SELECT g.id, g.name, g.description, g.status, a.name as area_name
                FROM rapa_goals g
                LEFT JOIN rapa_areas a ON g.area_id = a.id
                WHERE g.user_id = ? AND g.year = ? ORDER BY a.name, g.name
                """,
                (user_id, year),
            ).fetchall()
            return [dict(r) for r in rows]
        except sqlite3.OperationalError:
            return []


def get_projects_active(user_id: int) -> list[dict]:
    """Активные проекты."""
    with sqlite3.connect(get_db_path()) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT p.id, p.name, p.outcome, p.status, p.deadline, a.name as area_name
            FROM rapa_projects p
            LEFT JOIN rapa_areas a ON p.area_id = a.id
            WHERE p.user_id = ? AND p.status = 'active' ORDER BY p.deadline IS NULL, p.deadline
            """,
            (user_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def build_daily_review(user_id: int) -> str:
    """Ежедневный обзор: новые Raw + предложения Assign."""
    raw_list = get_raw_for_review(user_id, days=1)
    lines = ["📋 Ежедневный обзор (сегодня)\n"]

    if not raw_list:
        lines.append("• Нового Raw нет. Отправь сырьё в бота — разложим по слоям.")
        return "\n".join(lines)

    lines.append(f"• Новых записей Raw: {len(raw_list)}\n")
    for r in raw_list:
        content_preview = (r["content"] or "")[:80] + "…" if len(r["content"] or "") > 80 else (r["content"] or "")
        stage = r.get("rapa_stage") or "Raw"
        gtd = r.get("gtd_type") or ""
        para = r.get("para_type") or "Raw"
        lines.append(f"  #{r['id']} [{stage}] {para} {gtd}")
        lines.append(f"      «{content_preview}»")
        lines.append("")
    lines.append("— Подтверди или поправь Assign в Avatar.")
    return "\n".join(lines)


def build_weekly_review(user_id: int) -> str:
    """Еженедельный обзор: проекты + Raw за неделю."""
    raw_list = get_raw_for_review(user_id, days=7)
    projects = get_projects_active(user_id)

    lines = ["📊 Еженедельный обзор\n"]

    lines.append("Активные проекты:")
    if not projects:
        lines.append("  (нет)")
    else:
        for p in projects:
            deadline = f" до {p['deadline']}" if p.get("deadline") else ""
            area = f" [{p.get('area_name') or ''}]" if p.get("area_name") else ""
            lines.append(f"  • {p['name']}{area}{deadline}")

    lines.append("")
    lines.append(f"Raw за неделю: {len(raw_list)} записей")
    if raw_list:
        by_source = {}
        for r in raw_list:
            s = r.get("source") or "Other"
            by_source[s] = by_source.get(s, 0) + 1
        for src, cnt in by_source.items():
            lines.append(f"  — {src}: {cnt}")

    lines.append("")
    lines.append("— Что перевести в Archive? Какие проекты в фокус на неделю?")
    return "\n".join(lines)


def build_monthly_review(user_id: int) -> str:
    """Ежемесячный ревью: Areas + Resources."""
    raw_list = get_raw_for_review(user_id, days=30)
    projects = get_projects_active(user_id)

    lines = ["📆 Ежемесячный обзор\n"]
    lines.append(f"• Записей Raw за месяц: {len(raw_list)}")
    lines.append(f"• Активных проектов: {len(projects)}")
    lines.append("")
    lines.append("Области:")
    for item in SUPERHERO_AREAS:
        name = item[0]
        lines.append(f"  — {name}")
    lines.append("")
    lines.append("— Ревизия Areas. Чистка Resources/Archive.")
    return "\n".join(lines)
