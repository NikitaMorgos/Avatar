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


def _ensure_sprint_reports():
    with sqlite3.connect(DB_PATH) as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS sprint_reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sprint_id TEXT NOT NULL,
                user_id INTEGER NOT NULL,
                submitted_at TEXT NOT NULL,
                UNIQUE(sprint_id, user_id)
            );
        """)


def _sprint_report_submitted(sprint_id: str, user_id: int) -> bool:
    """Проверяет, сдан ли отчёт по спринту."""
    with sqlite3.connect(DB_PATH) as conn:
        row = conn.execute(
            "SELECT 1 FROM sprint_reports WHERE sprint_id = ? AND user_id = ?",
            (sprint_id, user_id),
        ).fetchone()
    return row is not None


def _save_sprint_report(sprint_id: str, user_id: int) -> None:
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            "INSERT OR REPLACE INTO sprint_reports (sprint_id, user_id, submitted_at) VALUES (?, ?, ?)",
            (sprint_id, user_id, datetime.utcnow().isoformat()),
        )


def _send_pdf_via_bot(file_path: Path, chat_id: int, caption: str = "") -> bool:
    """Отправляет PDF пользователю в Telegram."""
    if not BOT_TOKEN:
        return False
    with open(file_path, "rb") as f:
        r = requests.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendDocument",
            data={"chat_id": chat_id, "caption": caption or "Анализ спринта от Perplexity"},
            files={"document": (file_path.name, f, "application/pdf")},
            timeout=30,
        )
    return r.ok and r.json().get("ok")


@app.route("/api/gtd/sprint-report", methods=["POST"])
def api_sprint_report():
    """
    Приём отчёта по спринту: Perplexity-анализ → PDF → отправка в Collect бот.
    POST JSON: { sprint_id, sprint: {...}, items: [...], insights: [...], comment?: str }
    sprint_id например "s4_2026" для напоминаний.
    """
    user_id = RAW_OWNER_USER_ID
    if not user_id:
        return jsonify({"error": "RAW_OWNER_USER_ID not set"}), 400
    try:
        data = request.get_json(force=True, silent=True) or {}
    except Exception:
        data = {}
    sprint_id = (data.get("sprint_id") or "s4_2026").strip()
    sprint = data.get("sprint") or {}
    items = data.get("items") or []
    insights = data.get("insights") or []
    comment = (data.get("comment") or "").strip()
    if comment:
        sprint = {**sprint, "comment": comment}
    payload = {"sprint": sprint, "items": items, "insights": insights}
    _ensure_sprint_reports()
    _save_sprint_report(sprint_id, user_id)
    try:
        from api.sprint_perplexity import call_perplexity, text_to_pdf
        analysis = call_perplexity(payload)
    except Exception as e:
        return jsonify({"error": f"Perplexity: {e}", "submitted": True}), 500
    tmp_dir = Path(os.getenv("TEMP", "/tmp"))
    out_path = tmp_dir / f"sprint_analysis_{sprint_id}_{datetime.utcnow().strftime('%Y%m%d_%H%M')}.pdf"
    try:
        text_to_pdf(analysis, out_path)
    except Exception as e:
        return jsonify({"error": f"PDF: {e}", "submitted": True, "analysis_preview": analysis[:500]}), 500
    sent = _send_pdf_via_bot(out_path, user_id, f"Анализ спринта {sprint_id}")
    try:
        out_path.unlink(missing_ok=True)
    except Exception:
        pass
    if not sent:
        return jsonify({
            "status": "ok",
            "submitted": True,
            "warning": "PDF не отправлен в Telegram (проверь BOT_TOKEN)",
            "analysis_preview": analysis[:800],
        }), 200
    return jsonify({"status": "ok", "submitted": True, "pdf_sent": True}), 200


# ---------- Diary / Evernote ----------
@app.route("/api/diary/evernote/auth", methods=["GET"])
def api_diary_evernote_auth():
    """Старт OAuth: редирект на Evernote. После авторизации пользователь вернётся на callback."""
    user_id = RAW_OWNER_USER_ID
    if not user_id:
        return jsonify({"error": "RAW_OWNER_USER_ID not set"}), 400
    try:
        from api.evernote_diary import start_oauth, EVERNOTE_CALLBACK_BASE
        base = EVERNOTE_CALLBACK_BASE or request.url_root.rstrip("/")
        callback_url = base + "/api/diary/evernote/callback"
        auth_url = start_oauth(callback_url)
        from flask import redirect
        return redirect(auth_url)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/diary/evernote/callback", methods=["GET"])
def api_diary_evernote_callback():
    """Callback от Evernote после OAuth. Сохраняет токен и редиректит на сайт."""
    user_id = RAW_OWNER_USER_ID
    if not user_id:
        return jsonify({"error": "RAW_OWNER_USER_ID not set"}), 400
    oauth_token = request.args.get("oauth_token")
    oauth_verifier = request.args.get("oauth_verifier")
    if not oauth_verifier:
        return jsonify({"error": "Доступ не разрешён (нет oauth_verifier)"}), 400
    if not oauth_token:
        return jsonify({"error": "Нет oauth_token"}), 400
    try:
        from api.evernote_diary import finish_oauth
        finish_oauth(oauth_token, oauth_verifier, user_id)
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    # Редирект на фронт (GitHub Pages или тот же API base без пути)
    redirect_base = os.getenv("EVERNOTE_CALLBACK_BASE", "").strip()
    if not redirect_base:
        redirect_base = request.url_root.rstrip("/")
    if "github.io" in redirect_base or redirect_base.startswith("https://"):
        front = os.getenv("AVATAR_FRONT_URL", "https://nikitamorgos.github.io/Avatar/").strip()
    else:
        front = redirect_base
    from flask import redirect
    return redirect(front + "#diary-evernote-connected")


@app.route("/api/diary/evernote/notes", methods=["GET"])
def api_diary_evernote_notes():
    """Список заметок из Evernote (по сохранённому токену)."""
    user_id = RAW_OWNER_USER_ID
    if not user_id:
        return jsonify({"error": "RAW_OWNER_USER_ID not set"}), 400
    max_notes = min(int(request.args.get("max", 100)), 200)
    try:
        from api.evernote_diary import fetch_notes_from_evernote, get_evernote_token
        if not get_evernote_token(user_id):
            return jsonify({"error": "Evernote не подключён", "notes": []}), 200
        notes = fetch_notes_from_evernote(user_id, max_notes=max_notes)
        return jsonify({"notes": notes})
    except Exception as e:
        return jsonify({"error": str(e), "notes": []}), 500


@app.route("/api/diary/evernote/status", methods=["GET"])
def api_diary_evernote_status():
    """Проверка: подключён ли Evernote."""
    user_id = RAW_OWNER_USER_ID
    if not user_id:
        return jsonify({"connected": False})
    try:
        from api.evernote_diary import get_evernote_token
        tok = get_evernote_token(user_id)
        return jsonify({"connected": bool(tok and tok.get("access_token"))})
    except Exception:
        return jsonify({"connected": False})


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
