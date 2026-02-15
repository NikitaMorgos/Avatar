"""
API для Avatar: фото-доска Collect + webhook Plaud.
- Фото из канала
- Приём транскриптов Plaud через Zapier → Raw
Запуск: python -m api.collect_api (порт 8080 по умолчанию)
"""

import json
import os
import sqlite3
from datetime import datetime
from pathlib import Path

import requests
from dotenv import load_dotenv
from flask import Flask, Response, jsonify, request
from flask_cors import CORS

BASE = Path(__file__).resolve().parent.parent
import sys
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))
for p in [BASE / ".env", Path.cwd() / ".env", BASE / "config" / ".env"]:
    if p.exists():
        load_dotenv(dotenv_path=p, override=True)
        break

BOT_TOKEN = (os.getenv("BOT_TOKEN") or "").strip()
DB_PATH = os.getenv("DB_PATH", str(BASE / "db" / "collect.db"))
RAW_OWNER_USER_ID = int(os.getenv("RAW_OWNER_USER_ID", "0"))

app = Flask(__name__)
CORS(app)


def get_published_entries() -> list[dict]:
    """Опубликованные записи: id, comment, created_at, photo_file_id."""
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT id, comment, created_at, photo_file_id
            FROM collect_entries
            WHERE published_to_channel = 1
            ORDER BY created_at DESC
            """
        ).fetchall()
    return [
        {
            "id": r["id"],
            "comment": (r["comment"] or "").strip() or None,
            "created_at": r["created_at"],
            "photo_file_id": r["photo_file_id"],
        }
        for r in rows
    ]


def get_photo_file_path(entry_id: int) -> str | None:
    """Получить file_path из Telegram по entry_id."""
    with sqlite3.connect(DB_PATH) as conn:
        row = conn.execute(
            "SELECT photo_file_id FROM collect_entries WHERE id = ? AND published_to_channel = 1",
            (entry_id,),
        ).fetchone()
    if not row:
        return None
    file_id = row[0]
    if not BOT_TOKEN:
        return None
    r = requests.get(
        f"https://api.telegram.org/bot{BOT_TOKEN}/getFile",
        params={"file_id": file_id},
        timeout=10,
    )
    if not r.ok:
        return None
    data = r.json()
    if not data.get("ok"):
        return None
    return data["result"].get("file_path")


@app.route("/api/collect/entries", methods=["GET"])
def api_entries():
    """Список опубликованных записей (хронология, новые сверху)."""
    entries = get_published_entries()
    return jsonify(entries)


@app.route("/api/plaud/webhook", methods=["POST"])
def plaud_webhook():
    """
    Webhook для Zapier: Plaud (Transcript & Summary Ready) → POST сюда.
    Ожидает JSON: transcript, summary, title (опц.), и др. поля от Plaud.
    """
    try:
        data = request.get_json(force=True, silent=True) or {}
    except Exception:
        data = {}
    transcript = (data.get("transcript") or data.get("Transcript") or "").strip()
    summary = (data.get("summary") or data.get("Summary") or "").strip()
    title = (data.get("title") or data.get("Title") or "").strip()
    content = transcript or summary or ""
    if not content:
        return jsonify({"error": "transcript or summary required"}), 400
    if summary and transcript and summary != transcript:
        content = f"{summary}\n\n---\n{transcript}"
    elif not content:
        content = str(data)[:5000]
    title = title or (content[:80] + "..." if len(content) > 80 else content)
    created_at = datetime.utcnow().isoformat()
    metadata = {k: v for k, v in data.items() if k not in ("transcript", "summary", "title", "Transcript", "Summary", "Title")}
    meta_json = json.dumps(metadata) if metadata else None
    user_id = RAW_OWNER_USER_ID
    chat_id = 0
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.execute(
            """
            INSERT INTO raw (user_id, chat_id, title, content, source, created_at, rapa_stage, metadata, tags)
            VALUES (?, ?, ?, ?, 'Plaud', ?, 'Raw', ?, 'plaud')
            """,
            (user_id, chat_id, title, content, created_at, meta_json),
        )
        rowid = cur.lastrowid
    try:
        from bot.rapa import propose_assign
        propose_assign(rowid, user_id, content)
    except Exception:
        pass
    return jsonify({"status": "ok", "raw_id": rowid}), 200


@app.route("/api/rapa/review", methods=["GET"])
def rapa_review():
    """Обзор RAPA: ?period=daily|weekly|monthly. Требует RAW_OWNER_USER_ID."""
    period = (request.args.get("period") or "daily").lower()
    user_id = RAW_OWNER_USER_ID
    if not user_id:
        return jsonify({"error": "RAW_OWNER_USER_ID not set"}), 400
    try:
        from bot.rapa import build_daily_review, build_weekly_review, build_monthly_review
        if period in ("week", "weekly"):
            text = build_weekly_review(user_id)
        elif period in ("month", "monthly"):
            text = build_monthly_review(user_id)
        else:
            text = build_daily_review(user_id)
        return jsonify({"period": period, "review": text})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/rapa/raw", methods=["GET"])
def rapa_raw():
    """Список Raw за последние N дней. ?days=7"""
    user_id = RAW_OWNER_USER_ID
    if not user_id:
        return jsonify({"error": "RAW_OWNER_USER_ID not set"}), 400
    days = int(request.args.get("days", 7))
    days = min(max(days, 1), 90)
    try:
        from bot.rapa import get_raw_for_review
        items = get_raw_for_review(user_id, days=days)
        return jsonify({"raw": items, "days": days})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


def _ensure_rapa_schema():
    try:
        from bot.rapa import init_rapa_schema
        with sqlite3.connect(DB_PATH) as conn:
            init_rapa_schema(conn)
    except Exception:
        pass


@app.route("/api/rapa/projects", methods=["GET"])
def rapa_projects():
    """Список проектов для GTD."""
    user_id = RAW_OWNER_USER_ID
    if not user_id:
        return jsonify({"error": "RAW_OWNER_USER_ID not set"}), 400
    _ensure_rapa_schema()
    try:
        from bot.rapa import get_all_projects
        items = get_all_projects(user_id)
        return jsonify({"projects": items})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/rapa/areas", methods=["GET"])
def rapa_areas():
    """Список областей для GTD."""
    user_id = RAW_OWNER_USER_ID
    if not user_id:
        return jsonify({"error": "RAW_OWNER_USER_ID not set"}), 400
    _ensure_rapa_schema()
    try:
        from bot.rapa import get_all_areas
        items = get_all_areas(user_id)
        return jsonify({"areas": items})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/rapa/goals", methods=["GET", "POST"])
def rapa_goals():
    """Цели на год. GET ?year=2026. POST: {name, area_id?, year?, description?}"""
    user_id = RAW_OWNER_USER_ID
    if not user_id:
        return jsonify({"error": "RAW_OWNER_USER_ID not set"}), 400
    if request.method == "POST":
        try:
            data = request.get_json(force=True, silent=True) or {}
            name = (data.get("name") or "").strip()
            if not name:
                return jsonify({"error": "name required"}), 400
            area_id = data.get("area_id")
            year = int(data.get("year", datetime.now().year))
            description = (data.get("description") or "").strip()
            created_at = datetime.utcnow().isoformat()
            with sqlite3.connect(DB_PATH) as conn:
                try:
                    from bot.rapa import init_rapa_schema
                    init_rapa_schema(conn)
                except Exception:
                    pass
                cur = conn.execute(
                    "INSERT INTO rapa_goals (user_id, area_id, year, name, description, status, created_at) VALUES (?, ?, ?, ?, ?, 'active', ?)",
                    (user_id, area_id, year, name, description or None, created_at),
                )
                rowid = cur.lastrowid
            return jsonify({"status": "ok", "id": rowid, "year": year}), 201
        except Exception as e:
            return jsonify({"error": str(e)}), 500
    year = int(request.args.get("year", datetime.now().year))
    _ensure_rapa_schema()
    try:
        from bot.rapa import get_goals_for_year
        items = get_goals_for_year(user_id, year)
        return jsonify({"goals": items, "year": year})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/photo/<int:entry_id>", methods=["GET"])
def api_photo(entry_id: int):
    """Прокси фото из Telegram по id записи."""
    file_path = get_photo_file_path(entry_id)
    if not file_path or not BOT_TOKEN:
        return Response("Not found", status=404)
    url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file_path}"
    r = requests.get(url, timeout=15)
    if not r.ok:
        return Response("Failed to fetch", status=502)
    ext = (file_path or "").lower().split(".")[-1]
    mime = "image/jpeg" if ext in ("jpg", "jpeg") else ("image/png" if ext == "png" else "image/jpeg")
    return Response(
        r.content,
        mimetype=mime,
        headers={"Cache-Control": "public, max-age=86400"},
    )


if __name__ == "__main__":
    port = int(os.getenv("COLLECT_API_PORT", "8080"))
    app.run(host="0.0.0.0", port=port, debug=False)
