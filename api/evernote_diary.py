"""
Evernote OAuth 1.0 и получение заметок для раздела Diary.
Нужны: EVERNOTE_CONSUMER_KEY, EVERNOTE_CONSUMER_SECRET в .env.
Получить ключи: https://dev.evernote.com/doc/ → Get an API Key.
"""

import os
import re
import sqlite3
from dotenv import load_dotenv
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
for p in [BASE / ".env", Path.cwd() / ".env", BASE / "config" / ".env"]:
    if p.exists():
        load_dotenv(dotenv_path=p, override=True)
        break

EVERNOTE_CONSUMER_KEY = (os.getenv("EVERNOTE_CONSUMER_KEY") or "").strip()
EVERNOTE_CONSUMER_SECRET = (os.getenv("EVERNOTE_CONSUMER_SECRET") or "").strip()
DB_PATH = os.getenv("DB_PATH", str(BASE / "db" / "collect.db"))

# Публичный URL твоего API (для callback). Пример: https://твой-домен.ru
# Без слеша в конце. Для локальной разработки: http://localhost:8080
EVERNOTE_CALLBACK_BASE = (os.getenv("EVERNOTE_CALLBACK_BASE") or "").strip()


def _ensure_evernote_table(conn: sqlite3.Connection) -> None:
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS evernote_tokens (
            user_id INTEGER PRIMARY KEY,
            access_token TEXT NOT NULL,
            note_store_url TEXT,
            expires_at TEXT,
            updated_at TEXT NOT NULL
        );
    """)


def get_evernote_token(user_id: int) -> dict | None:
    """Возвращает {access_token, note_store_url} или None."""
    with sqlite3.connect(DB_PATH) as conn:
        _ensure_evernote_table(conn)
        row = conn.execute(
            "SELECT access_token, note_store_url FROM evernote_tokens WHERE user_id = ?",
            (user_id,),
        ).fetchone()
    if not row:
        return None
    return {"access_token": row[0], "note_store_url": row[1] or ""}


def save_evernote_token(user_id: int, access_token: str, note_store_url: str = "", expires_at: str = "") -> None:
    from datetime import datetime
    with sqlite3.connect(DB_PATH) as conn:
        _ensure_evernote_table(conn)
        conn.execute(
            """INSERT OR REPLACE INTO evernote_tokens (user_id, access_token, note_store_url, expires_at, updated_at)
               VALUES (?, ?, ?, ?, ?)""",
            (user_id, access_token, note_store_url or None, expires_at or None, datetime.utcnow().isoformat()),
        )


def _ensure_oauth_state_table(conn: sqlite3.Connection) -> None:
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS evernote_oauth_state (
            request_token TEXT PRIMARY KEY,
            request_token_secret TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
    """)


def start_oauth(callback_url: str) -> str:
    """
    Начать OAuth: сохраняет request token в БД, возвращает URL для редиректа на Evernote.
    """
    try:
        from requests_oauthlib import OAuth1Session
    except ImportError:
        raise RuntimeError("Установи requests_oauthlib: pip install requests_oauthlib")
    if not EVERNOTE_CONSUMER_KEY or not EVERNOTE_CONSUMER_SECRET:
        raise RuntimeError("Задай EVERNOTE_CONSUMER_KEY и EVERNOTE_CONSUMER_SECRET в .env")
    oauth = OAuth1Session(
        client_key=EVERNOTE_CONSUMER_KEY,
        client_secret=EVERNOTE_CONSUMER_SECRET,
        callback_uri=callback_url,
    )
    request_token_url = "https://www.evernote.com/oauth"
    oauth.fetch_request_token(request_token_url)
    auth_url = oauth.authorization_url("https://www.evernote.com/OAuth.action")
    from datetime import datetime
    with sqlite3.connect(DB_PATH) as conn:
        _ensure_oauth_state_table(conn)
        conn.execute(
            "INSERT OR REPLACE INTO evernote_oauth_state (request_token, request_token_secret, created_at) VALUES (?, ?, ?)",
            (oauth.token.get("oauth_token"), oauth.token.get("oauth_token_secret", ""), datetime.utcnow().isoformat()),
        )
    return auth_url


def finish_oauth(oauth_token: str, oauth_verifier: str, user_id: int) -> dict:
    """
    Обмен request token на access token. Сохраняет токен в БД для user_id.
    Возвращает dict с edam_noteStoreUrl и т.д. для редиректа.
    """
    try:
        from requests_oauthlib import OAuth1Session
    except ImportError:
        raise RuntimeError("Установи requests_oauthlib: pip install requests_oauthlib")
    with sqlite3.connect(DB_PATH) as conn:
        _ensure_oauth_state_table(conn)
        row = conn.execute(
            "SELECT request_token_secret FROM evernote_oauth_state WHERE request_token = ?",
            (oauth_token,),
        ).fetchone()
        if not row:
            raise RuntimeError("Не найден request token. Начни подключение заново.")
        request_token_secret = row[0]
        conn.execute("DELETE FROM evernote_oauth_state WHERE request_token = ?", (oauth_token,))
    oauth = OAuth1Session(
        client_key=EVERNOTE_CONSUMER_KEY,
        client_secret=EVERNOTE_CONSUMER_SECRET,
        resource_owner_key=oauth_token,
        resource_owner_secret=request_token_secret,
    )
    access_token_url = "https://www.evernote.com/oauth"
    # Evernote возвращает access token в body (form-urlencoded), не JSON
    oauth.verifier = oauth_verifier
    token = oauth.fetch_access_token(access_token_url)
    access_token = token.get("oauth_token") or token.get("edam_authToken") or ""
    note_store_url = token.get("edam_noteStoreUrl", "")
    expires_at = token.get("edam_expires", "")
    if access_token:
        save_evernote_token(user_id, access_token, note_store_url, str(expires_at))
    return token


def fetch_notes_from_evernote(user_id: int, max_notes: int = 100) -> list[dict]:
    """
    Скачивает заметки из Evernote по сохранённому токену.
    Возвращает список {title, plainText, created, updated}.
    """
    tok = get_evernote_token(user_id)
    if not tok or not tok.get("access_token"):
        return []
    try:
        from evernote.api.client import EvernoteClient
        from evernote.edam.notestore.ttypes import NoteFilter, NotesMetadataResultSpec
    except ImportError:
        raise RuntimeError("Установи evernote SDK: pip install evernote")
    client = EvernoteClient(token=tok["access_token"], sandbox=False)
    note_store = client.get_note_store()
    # Список заметок (метаданные)
    result_spec = NotesMetadataResultSpec(includeTitle=True, includeCreated=True, includeUpdated=True, includeContentLength=False)
    filter = NoteFilter(order=1)  # CREATED desc
    try:
        result = note_store.findNotesMetadata(filter, 0, max_notes, result_spec)
    except Exception as e:
        raise RuntimeError(f"Evernote API: {e}") from e
    notes = []
    for meta in (result.notes or []):
        created = meta.created
        updated = meta.updated
        # EDAM timestamp в миллисекундах
        created_ts = str(int(created)) if created is not None else ""
        updated_ts = str(int(updated)) if updated is not None else ""
        title = (meta.title or "").strip()
        plain_text = ""
        try:
            content = note_store.getNoteContent(meta.guid)
            if content:
                plain_text = _enml_to_plain(content)
        except Exception:
            pass
        notes.append({
            "title": title,
            "plainText": plain_text[:5000],
            "created": created_ts,
            "updated": updated_ts,
        })
    return notes


def _enml_to_plain(enml: str) -> str:
    """Упрощённое извлечение текста из ENML (Evernote markup)."""
    if not enml:
        return ""
    s = re.sub(r"<en-note[^>]*>", "", enml, flags=re.I)
    s = re.sub(r"</en-note>", "", s, flags=re.I)
    s = re.sub(r"<[^>]+>", " ", s)
    s = re.sub(r"&nbsp;", " ", s, flags=re.I)
    s = re.sub(r"&amp;", "&", s, flags=re.I)
    s = re.sub(r"&lt;", "<", s, flags=re.I)
    s = re.sub(r"&gt;", ">", s, flags=re.I)
    s = re.sub(r"&quot;", '"', s, flags=re.I)
    s = re.sub(r"\s+", " ", s).strip()
    return s[:10000]
