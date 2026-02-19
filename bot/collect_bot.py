"""
Collect bot — MVP.
Принимает фото с подписью, сохраняет в SQLite, отвечает подтверждением.
Поддерживает отложенный постинг по расписанию.
RAPA: Raw → Assign → Project → Archive.
"""

import json
import logging
import re
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import BotCommand
from aiogram.types import CallbackQuery
from aiogram.types import InlineKeyboardButton
from aiogram.types import InlineKeyboardMarkup
from aiogram.types import Message
from aiogram.types import MenuButtonCommands
from aiogram.types import MenuButtonWebApp
from aiogram.types import MessageOriginChannel
from aiogram.types import WebAppInfo
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from dotenv import load_dotenv
import os

# Загрузка .env: корень проекта (по пути к этому файлу)
BASE = Path(__file__).resolve().parent.parent
import sys
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))
for _p in [BASE / ".env", Path.cwd() / ".env", BASE / "config" / ".env"]:
    if _p.exists():
        load_dotenv(dotenv_path=_p, override=True)

BOT_TOKEN = (os.getenv("BOT_TOKEN") or "").strip()
DB_PATH = os.getenv("DB_PATH", str(BASE / "db" / "collect.db"))
_raw = (os.getenv("CHANNEL_ID") or "").strip()
CHANNEL_ID = None
if _raw:
    try:
        CHANNEL_ID = int(_raw)  # -100xxxxxxxxxx
    except ValueError:
        CHANNEL_ID = _raw  # @channel

# Время отложенного поста (HH:MM), например 20:00. Пусто = постить сразу.
POST_SCHEDULE_TIME = (os.getenv("POST_SCHEDULE_TIME") or "").strip() or None

# Время проверки «не было фото за день» и поста заготовки (HH:MM), например 23:00.
FALLBACK_TIME = (os.getenv("FALLBACK_TIME") or "").strip() or "23:00"

# URL для синей кнопки «Open» (Web App). HTTPS или t.me/... Пусто = меню с командами.
MENU_BUTTON_URL = (os.getenv("MENU_BUTTON_URL") or "").strip() or None

# RAPA: ежедневный обзор в TG (HH:MM), например 09:00. Пусто = не слать.
REVIEW_DAILY_TIME = (os.getenv("REVIEW_DAILY_TIME") or "").strip() or None
RAW_OWNER_USER_ID = int(os.getenv("RAW_OWNER_USER_ID", "0")) or None

# Напоминания об отчёте по спринту: с даты SPRINT_REMINDER_START, в SPRINT_REMINDER_TIME, пока не сдан.
SPRINT_REMINDER_START = (os.getenv("SPRINT_REMINDER_START") or "2026-02-26").strip()
SPRINT_REMINDER_TIME = (os.getenv("SPRINT_REMINDER_TIME") or "10:00").strip()
CURRENT_SPRINT_ID = (os.getenv("CURRENT_SPRINT_ID") or "s4_2026").strip()

# Глобальный планировщик (для /postat и заготовок)
_scheduler: AsyncIOScheduler | None = None

# Режим «добавляю заготовки»: user_id в этом set — фото идут в fallback_photos
_adding_stock: set[int] = set()
# Режим «добавляю в Raw»: user_id в этом set — фото идут в raw
_adding_raw: set[int] = set()

# Ожидающее видео для поста по команде /post: user_id -> { entry_id, file_id, caption, media_type }
_pending_post: dict[int, dict] = {}

# Теги для Raw — выбор из списка кнопками
RAW_TAGS = ["diary", "работа", "идея"]

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def init_db() -> None:
    """Создаёт таблицу collect_entries, если её нет. Миграция: published_to_channel."""
    db_file = Path(DB_PATH)
    db_file.parent.mkdir(parents=True, exist_ok=True)

    init_sql = (BASE / "db" / "init.sql").read_text(encoding="utf-8")
    with sqlite3.connect(DB_PATH) as conn:
        conn.executescript(init_sql)
        # RAPA schema
        try:
            from bot.rapa import init_rapa_schema
            init_rapa_schema(conn)
        except Exception as e:
            logger.warning("RAPA schema init: %s", e)
        # Миграция: добавить published_to_channel для существующих БД
        try:
            conn.execute("ALTER TABLE collect_entries ADD COLUMN published_to_channel INTEGER DEFAULT 0")
        except sqlite3.OperationalError:
            pass
        try:
            conn.execute("CREATE INDEX IF NOT EXISTS idx_collect_published ON collect_entries(published_to_channel)")
        except sqlite3.OperationalError:
            pass
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS fallback_photos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                photo_file_id TEXT NOT NULL,
                created_at TEXT NOT NULL,
                used_at TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_fallback_used ON fallback_photos(used_at);
        """)
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS raw (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                chat_id INTEGER NOT NULL,
                title TEXT,
                content TEXT NOT NULL,
                source TEXT DEFAULT 'Telegram',
                created_at TEXT NOT NULL,
                rapa_stage TEXT DEFAULT 'Raw',
                gtd_type TEXT,
                ai_summary TEXT,
                metadata TEXT,
                tags TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_raw_user_created ON raw(user_id, created_at);
        """)
        # Миграция: media_type для collect_entries (photo | video)
        try:
            conn.execute("ALTER TABLE collect_entries ADD COLUMN media_type TEXT DEFAULT 'photo'")
            logger.info("Added media_type column to collect_entries")
        except sqlite3.OperationalError:
            pass
        # Миграция: media_type для fallback_photos
        try:
            conn.execute("ALTER TABLE fallback_photos ADD COLUMN media_type TEXT DEFAULT 'photo'")
            logger.info("Added media_type column to fallback_photos")
        except sqlite3.OperationalError:
            pass
        # Миграция: tags для raw (если таблица уже существовала без колонки)
        try:
            conn.execute("ALTER TABLE raw ADD COLUMN tags TEXT")
            logger.info("Added tags column to raw")
        except sqlite3.OperationalError:
            pass  # колонка уже есть
        # sprint_reports: сданные отчёты по спринтам (для напоминаний + Perplexity)
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS sprint_reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sprint_id TEXT NOT NULL,
                user_id INTEGER NOT NULL,
                submitted_at TEXT NOT NULL,
                UNIQUE(sprint_id, user_id)
            );
            CREATE INDEX IF NOT EXISTS idx_sprint_reports_id ON sprint_reports(sprint_id, user_id);
        """)
    logger.info("DB initialized: %s", DB_PATH)


def save_entry(
    user_id: int, chat_id: int, message_id: int, file_id: str, comment: str | None, media_type: str = "photo"
) -> int:
    """Сохраняет запись в collect_entries. media_type: 'photo' | 'video'. Возвращает id."""
    created_at = datetime.utcnow().isoformat()
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.execute(
            """
            INSERT INTO collect_entries (user_id, chat_id, message_id, photo_file_id, photo_file_path, comment, created_at, tags, published_to_channel, media_type)
            VALUES (?, ?, ?, ?, NULL, ?, ?, NULL, 0, ?)
            """,
            (user_id, chat_id, message_id, file_id, comment or "", created_at, media_type),
        )
        rowid = cur.lastrowid
    logger.info("Saved entry: id=%s user=%s chat=%s msg=%s", rowid, user_id, chat_id, message_id)
    return rowid


def get_unpublished_entries() -> list[tuple[int, str, str | None, str]]:
    """Возвращает [(id, file_id, comment, media_type), ...] для неопубликованных записей."""
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT id, photo_file_id, comment, COALESCE(media_type, 'photo') as media_type FROM collect_entries WHERE published_to_channel = 0 ORDER BY id"
        ).fetchall()
    return [(r["id"], r["photo_file_id"], r["comment"] or None, r["media_type"] or "photo") for r in rows]


def mark_published(entry_id: int) -> None:
    """Помечает запись как опубликованную."""
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("UPDATE collect_entries SET published_to_channel = 1 WHERE id = ?", (entry_id,))


def mark_unpublished(entry_id: int) -> None:
    """Откатывает пометку (если пост не удался)."""
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("UPDATE collect_entries SET published_to_channel = 0 WHERE id = ?", (entry_id,))


def get_unpublished_for_user(user_id: int) -> list[tuple[int, str | None]]:
    """Возвращает [(id, comment), ...] неопубликованных записей пользователя (новые сверху)."""
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT id, comment FROM collect_entries WHERE published_to_channel = 0 AND user_id = ? ORDER BY id DESC",
            (user_id,),
        ).fetchall()
    return [(r["id"], (r["comment"] or "").strip() or None) for r in rows]


def extract_raw_tags(content: str) -> tuple[str, list[str]]:
    """Извлекает теги из текста (#diary, #работа и т.п.). Возвращает (очищенный текст, список тегов).
    #raw — служебный маркер, не сохраняется как тег."""
    text = content or ""
    tags: list[str] = []
    # Паттерн: # + слово (латиница, кириллица, цифры, _)
    for m in re.finditer(r"#([A-Za-zА-Яа-яЁё0-9_]+)", text):
        tag = m.group(1)
        if tag.lower() != "raw":
            tags.append(tag)
    # Убираем все #теги из текста
    cleaned = re.sub(r"#([A-Za-zА-Яа-яЁё0-9_]+)\s*", "", text).strip()
    return cleaned, tags


def save_raw(
    user_id: int,
    chat_id: int,
    content: str,
    source: str = "Telegram",
    metadata: dict | None = None,
    tags: list[str] | None = None,
) -> int:
    """Сохраняет сырьё в Raw (Inbox). Возвращает id. metadata — доп. данные (напр. photo_file_id)."""
    content = (content or "").strip() or "📷 Фото"
    title = content[:80] + "..." if len(content) > 80 else content
    created_at = datetime.utcnow().isoformat()
    meta_json = json.dumps(metadata) if metadata else None
    tags_str = ",".join(tags) if tags else None
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.execute(
            """
            INSERT INTO raw (user_id, chat_id, title, content, source, created_at, rapa_stage, metadata, tags)
            VALUES (?, ?, ?, ?, ?, ?, 'Raw', ?, ?)
            """,
            (user_id, chat_id, title, content, source, created_at, meta_json, tags_str),
        )
        rowid = cur.lastrowid
    logger.info("Saved raw: id=%s user=%s source=%s tags=%s", rowid, user_id, source, tags_str)
    # RAPA: предварительная классификация Assign
    try:
        from bot.rapa import propose_assign
        propose_assign(rowid, user_id, content)
    except Exception as e:
        logger.debug("RAPA propose_assign: %s", e)
    return rowid


def add_tag_to_raw(raw_id: int, user_id: int, tag: str) -> bool:
    """Добавляет тег к записи Raw. Возвращает True если обновлено."""
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT tags FROM raw WHERE id = ? AND user_id = ?", (raw_id, user_id)).fetchone()
        if not row:
            return False
        current = (row["tags"] or "").strip()
        tags_list = [t.strip() for t in current.split(",") if t.strip()]
        if tag in tags_list:
            return True
        tags_list.append(tag)
        new_tags = ",".join(tags_list)
        conn.execute("UPDATE raw SET tags = ? WHERE id = ? AND user_id = ?", (new_tags, raw_id, user_id))
    return True


def build_raw_tag_keyboard(raw_id: int, exclude_tags: list[str] | None = None) -> InlineKeyboardMarkup:
    """Кнопки выбора тега для записи Raw."""
    exclude = set((exclude_tags or []))
    buttons = [
        InlineKeyboardButton(text=t, callback_data=f"raw_tag:{raw_id}:{t}")
        for t in RAW_TAGS
        if t not in exclude
    ]
    if not buttons:
        return InlineKeyboardMarkup(inline_keyboard=[])
    return InlineKeyboardMarkup(inline_keyboard=[buttons])


def cancel_entry(entry_id: int, user_id: int) -> bool:
    """Удаляет отложенную запись. Возвращает True если удалено."""
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.execute(
            "DELETE FROM collect_entries WHERE id = ? AND user_id = ? AND published_to_channel = 0",
            (entry_id, user_id),
        )
    return cur.rowcount > 0


# --- Заготовки (fallback) ---

def add_fallback(user_id: int, file_id: str, media_type: str = "photo") -> int:
    """Добавляет фото/видео в заготовки. media_type: 'photo' | 'video'. Возвращает id."""
    created_at = datetime.utcnow().isoformat()
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.execute(
            "INSERT INTO fallback_photos (user_id, photo_file_id, created_at, used_at, media_type) VALUES (?, ?, ?, NULL, ?)",
            (user_id, file_id, created_at, media_type),
        )
        return cur.lastrowid


def get_fallback_unused_count() -> int:
    """Количество неиспользованных заготовок."""
    with sqlite3.connect(DB_PATH) as conn:
        return conn.execute("SELECT COUNT(*) FROM fallback_photos WHERE used_at IS NULL").fetchone()[0]


def get_fallback_unused_count_for_user(user_id: int) -> int:
    with sqlite3.connect(DB_PATH) as conn:
        return conn.execute(
            "SELECT COUNT(*) FROM fallback_photos WHERE used_at IS NULL AND user_id = ?", (user_id,)
        ).fetchone()[0]


def get_random_unused_fallback() -> tuple[int, int, str, str] | None:
    """Возвращает (id, user_id, file_id, media_type) или None."""
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT id, user_id, photo_file_id, COALESCE(media_type, 'photo') as media_type FROM fallback_photos WHERE used_at IS NULL ORDER BY RANDOM() LIMIT 1"
        ).fetchone()
    if not row:
        return None
    return (row["id"], row["user_id"], row["photo_file_id"], row["media_type"] or "photo")


def mark_fallback_used(fallback_id: int) -> None:
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("UPDATE fallback_photos SET used_at = ? WHERE id = ?", (datetime.utcnow().isoformat(), fallback_id))


def count_photos_sent_today_by_user(user_id: int) -> int:
    """Считает, сколько фото за сегодня отправил пользователь (collect_entries за сегодня)."""
    today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    with sqlite3.connect(DB_PATH) as conn:
        return conn.execute(
            "SELECT COUNT(*) FROM collect_entries WHERE user_id = ? AND created_at >= ?",
            (user_id, today_start),
        ).fetchone()[0]


async def _post_media_to_channel(
    bot: Bot, file_id: str, caption: str | None, media_type: str = "photo"
) -> None:
    """Публикует фото, видео или видеосообщение (кружок) в канал."""
    if media_type == "video":
        await bot.send_video(chat_id=CHANNEL_ID, video=file_id, caption=caption)
    elif media_type == "video_note":
        await bot.send_video_note(chat_id=CHANNEL_ID, video_note=file_id)
    else:
        await bot.send_photo(chat_id=CHANNEL_ID, photo=file_id, caption=caption)


def sprint_report_submitted(sprint_id: str, user_id: int) -> bool:
    """Проверяет, сдан ли отчёт по спринту."""
    with sqlite3.connect(DB_PATH) as conn:
        row = conn.execute(
            "SELECT 1 FROM sprint_reports WHERE sprint_id = ? AND user_id = ?",
            (sprint_id, user_id),
        ).fetchone()
    return row is not None


def get_owner_user_id() -> int | None:
    """user_id владельца (из последней записи collect или fallback)."""
    with sqlite3.connect(DB_PATH) as conn:
        row = conn.execute("SELECT user_id FROM collect_entries ORDER BY id DESC LIMIT 1").fetchone()
        if row:
            return row[0]
        row = conn.execute("SELECT user_id FROM fallback_photos ORDER BY id DESC LIMIT 1").fetchone()
        if row:
            return row[0]
    return None


async def on_photo(message: Message, bot: Bot) -> None:
    """Обработчик: фото с подписью или без."""
    user_id = message.from_user.id if message.from_user else 0
    chat_id = message.chat.id
    message_id = message.message_id
    comment = message.caption or ""

    # Выбираем самое большое фото из photo_sizes
    photo = message.photo[-1] if message.photo else None
    if not photo:
        await message.reply("Не вижу фото. Отправь фото с подписью или без.")
        return

    photo_file_id = photo.file_id

    # Режим «добавляю заготовки»
    if user_id in _adding_stock:
        add_fallback(user_id, photo_file_id)
        n = get_fallback_unused_count_for_user(user_id)
        await message.reply(f"Добавил в заготовки ✓ Осталось заготовок: {n}. Ещё фото или /done — закончить.")
        return

    # Режим «добавляю в Raw» или подпись #raw
    is_raw = user_id in _adding_raw or (comment and re.search(r"#raw\b", comment, re.I))
    if is_raw:
        content = re.sub(r"#raw\b", "", comment, flags=re.I).strip() if comment else ""
        cleaned, tags = extract_raw_tags(content)
        raw_id = save_raw(
            user_id, chat_id, cleaned or "📷 Фото", source="Telegram",
            metadata={"photo_file_id": photo_file_id}, tags=tags or None
        )
        tags_hint = f" #{','.join(tags)}" if tags else ""
        suffix = " Ещё фото или /done — закончить." if user_id in _adding_raw else ""
        text = f"✓ В Raw #%s%s%s" % (raw_id, tags_hint, suffix)
        kb = build_raw_tag_keyboard(raw_id, exclude_tags=tags) if not tags else None
        await message.reply(text, reply_markup=kb)
        return

    try:
        rowid = save_entry(user_id, chat_id, message_id, photo_file_id, comment)
        # Публикуем в канал, если задан CHANNEL_ID
        if CHANNEL_ID:
            if POST_SCHEDULE_TIME:
                # Отложенный постинг — публикуем по расписанию
                await message.reply(
                    f"Записал твой день ✓ Опубликую в канал в {POST_SCHEDULE_TIME}. "
                    "Сейчас — нажми /postnow в меню."
                )
            else:
                # Мгновенный постинг
                try:
                    await _post_media_to_channel(
                        bot, photo_file_id, comment if comment else None, media_type="photo"
                    )
                    logger.info("Posted to channel: %s", CHANNEL_ID)
                    mark_published(rowid)
                    await message.reply("Записал твой день и опубликовал в канал ✓")
                except Exception as ch_err:
                    logger.exception("Channel post failed: %s", ch_err)
                    await message.reply(
                        f"Записал в БД, но не удалось опубликовать в канал.\n"
                        f"Ошибка: {type(ch_err).__name__}: {ch_err}\n\n"
                        "Проверь: бот админ с правом «Post messages»? /testchannel — тест."
                    )
                    return
        else:
            await message.reply("Записал твой день ✓")
    except Exception as e:
        logger.exception("Error saving entry: %s", e)
        await message.reply("Не удалось сохранить. Попробуй позже.")


async def on_video(message: Message, bot: Bot) -> None:
    """Обработчик: видео с подписью или без. Постит в канал как фото."""
    user_id = message.from_user.id if message.from_user else 0
    chat_id = message.chat.id
    message_id = message.message_id
    comment = message.caption or ""

    video = message.video
    if not video:
        await message.reply("Не вижу видео. Отправь видео с подписью или без.")
        return

    video_file_id = video.file_id

    # Режим «добавляю заготовки»
    if user_id in _adding_stock:
        add_fallback(user_id, video_file_id, media_type="video")
        n = get_fallback_unused_count_for_user(user_id)
        await message.reply(f"Добавил видео в заготовки ✓ Осталось заготовок: {n}. Ещё фото/видео или /done — закончить.")
        return

    # Режим «добавляю в Raw» или подпись #raw
    is_raw = user_id in _adding_raw or (comment and re.search(r"#raw\b", comment, re.I))
    if is_raw:
        content = re.sub(r"#raw\b", "", comment, flags=re.I).strip() if comment else ""
        cleaned, tags = extract_raw_tags(content)
        raw_id = save_raw(
            user_id, chat_id, cleaned or "🎬 Видео", source="Telegram",
            metadata={"video_file_id": video_file_id}, tags=tags or None
        )
        tags_hint = f" #{','.join(tags)}" if tags else ""
        suffix = " Ещё фото/видео или /done — закончить." if user_id in _adding_raw else ""
        text = f"✓ В Raw #%s%s%s" % (raw_id, tags_hint, suffix)
        kb = build_raw_tag_keyboard(raw_id, exclude_tags=tags) if not tags else None
        await message.reply(text, reply_markup=kb)
        return

    try:
        rowid = save_entry(user_id, chat_id, message_id, video_file_id, comment, media_type="video")
        if CHANNEL_ID:
            _pending_post[user_id] = {
                "entry_id": rowid,
                "file_id": video_file_id,
                "caption": comment if comment else None,
                "media_type": "video",
            }
            await message.reply(
                "Видео получено ✓ Напиши /post чтобы опубликовать в канал."
            )
        else:
            await message.reply("Записал твой день ✓")
    except Exception as e:
        logger.exception("Error saving video entry: %s", e)
        await message.reply("Не удалось сохранить. Попробуй позже.")


async def on_video_note(message: Message, bot: Bot) -> None:
    """Обработчик: видеокружок (video note). Предлагает запостить по команде /post."""
    user_id = message.from_user.id if message.from_user else 0
    chat_id = message.chat.id
    message_id = message.message_id
    comment = message.caption or ""

    video_note = message.video_note
    if not video_note:
        await message.reply("Не вижу видеосообщение. Отправь видео или видеокружок.")
        return

    file_id = video_note.file_id

    if user_id in _adding_stock:
        add_fallback(user_id, file_id, media_type="video_note")
        n = get_fallback_unused_count_for_user(user_id)
        await message.reply(f"Добавил в заготовки ✓ Осталось: {n}. Ещё медиа или /done.")
        return

    is_raw = user_id in _adding_raw or (comment and re.search(r"#raw\b", comment, re.I))
    if is_raw:
        content = re.sub(r"#raw\b", "", comment, flags=re.I).strip() if comment else ""
        cleaned, tags = extract_raw_tags(content)
        raw_id = save_raw(
            user_id, chat_id, cleaned or "🎬 Видеокружок", source="Telegram",
            metadata={"video_note_file_id": file_id}, tags=tags or None
        )
        tags_hint = f" #{','.join(tags)}" if tags else ""
        suffix = " Ещё медиа или /done." if user_id in _adding_raw else ""
        await message.reply(f"✓ В Raw #%s%s%s" % (raw_id, tags_hint, suffix))
        return

    try:
        rowid = save_entry(user_id, chat_id, message_id, file_id, comment, media_type="video_note")
        if CHANNEL_ID:
            _pending_post[user_id] = {
                "entry_id": rowid,
                "file_id": file_id,
                "caption": comment if comment else None,
                "media_type": "video_note",
            }
            await message.reply(
                "Видео получено ✓ Напиши /post чтобы опубликовать в канал."
            )
        else:
            await message.reply("Записал ✓")
    except Exception as e:
        logger.exception("Error saving video_note: %s", e)
        await message.reply("Не удалось сохранить. Попробуй позже.")


async def cmd_diary(message: Message) -> None:
    """/diary <текст> — сохранить в Raw с тегом diary. Шорткат для /raw + #diary."""
    user_id = message.from_user.id if message.from_user else 0
    chat_id = message.chat.id
    text = (message.text or "").strip()
    parts = text.split(maxsplit=1)
    content = parts[1].strip() if len(parts) > 1 else ""
    if message.reply_to_message and not content:
        rep = message.reply_to_message
        content = (rep.text or rep.caption or "").strip()
    if not content:
        await message.reply("Напиши текст после /diary — сохраню в Raw с тегом diary.")
        return
    raw_id = save_raw(user_id, chat_id, content, source="Telegram", tags=["diary"])
    if raw_id:
        await message.reply(f"✓ В Raw #%s #diary" % raw_id)


async def cmd_rawphoto(message: Message) -> None:
    """Режим: следующие фото/видео идут в Raw. /done — выйти."""
    global _adding_raw
    user_id = message.from_user.id if message.from_user else 0
    _adding_raw.add(user_id)
    await message.reply("Режим Raw: следующие фото/видео — в Inbox. /done — закончить.")


async def cmd_raw(message: Message) -> None:
    """Команда /raw — сохранить текст в Raw (Inbox) для Avatar."""
    user_id = message.from_user.id if message.from_user else 0
    chat_id = message.chat.id

    content = ""
    # Текст после команды: /raw или /raw@botname
    text = (message.text or "").strip()
    parts = text.split(maxsplit=1)
    if len(parts) > 1:
        content = parts[1].strip()
    # Или ответ на сообщение
    if not content and message.reply_to_message:
        rep = message.reply_to_message
        content = (rep.text or rep.caption or "").strip()
        if not content and rep.entities:
            # Ссылки и пр.
            content = (rep.text or "").strip()

    if not content:
        logger.info("cmd_raw: empty content, reply_to=%s", bool(message.reply_to_message))
        await message.reply(
            "Отправь сырьё в Raw (Inbox):\n\n"
            "• /raw <текст> — сохранить текст\n"
            "• /diary <текст> — сразу с тегом diary\n"
            "• Или нажми кнопку тега после сохранения"
        )
        return

    cleaned, tags = extract_raw_tags(content)
    raw_id = save_raw(user_id, chat_id, cleaned or "…", source="Telegram", tags=tags or None)
    if raw_id:
        tags_hint = f" #{','.join(tags)}" if tags else ""
        text = f"✓ Сохранено в Raw #%s%s\n\n«%s»" % (raw_id, tags_hint, ((cleaned or content)[:100] + "…" if len(cleaned or content) > 100 else (cleaned or content)))
        kb = build_raw_tag_keyboard(raw_id, exclude_tags=tags) if not tags else None
        await message.reply(text, reply_markup=kb)
    else:
        await message.reply("Не удалось сохранить (пустой текст?).")


async def cmd_review(message: Message) -> None:
    """/review [daily|weekly|monthly] — обзор RAPA."""
    user_id = message.from_user.id if message.from_user else 0
    text = (message.text or "").strip().lower().split()
    period = text[1] if len(text) > 1 else "daily"
    try:
        from bot.rapa import build_daily_review, build_weekly_review, build_monthly_review
        if period in ("week", "weekly", "неделя"):
            out = build_weekly_review(user_id)
        elif period in ("month", "monthly", "месяц"):
            out = build_monthly_review(user_id)
        else:
            out = build_daily_review(user_id)
        await message.reply(out[:4000])
    except Exception as e:
        logger.exception("Review failed: %s", e)
        await message.reply(f"Ошибка: {e}")


async def cmd_start(message: Message) -> None:
    """Команда /start."""
    schedule_hint = f"\nПосты в канал: отложенно в {POST_SCHEDULE_TIME}." if POST_SCHEDULE_TIME else ""
    await message.reply(
        "Привет. Отправь фото с подписью — я сохраню его как срез дня.\n\n"
        "Один день — одна (или несколько) фоток. Буду использовать их для канала, досок и обзоров."
        f"{schedule_hint}\n\n"
        "Фото/видео → Collect (канал). Фото/видео с #raw или /rawphoto → Raw (Inbox).\n"
        "Теги: /diary или кнопки после сохранения в Raw.\n"
        "RAPA: Raw раскладывается по слоям (Assign). /review daily|weekly|monthly — обзоры.\n\n"
        "/postnow — опубликовать сейчас\n"
        "/postat 18:30 — опубликовать в указанное время\n"
        "/mylist — список отложенных\n"
        "/cancel — отменить последнее фото\n"
        "/addstock — добавить заготовки (если к 23:00 не было фото — постю одну)\n"
        "/stock — сколько заготовок осталось\n"
        "/channelid — ID канала для .env"
    )


async def cmd_addstock(message: Message) -> None:
    """Включить режим добавления заготовок."""
    user_id = message.from_user.id if message.from_user else 0
    _adding_stock.add(user_id)
    n = get_fallback_unused_count_for_user(user_id)
    await message.reply(
        f"Режим заготовок включён. Отправляй фото — каждое добавлю в заготовки. Закончить — /done.\n"
        f"Сейчас заготовок: {n}"
    )


async def cmd_done(message: Message) -> None:
    """Выйти из режима заготовок или Raw."""
    user_id = message.from_user.id if message.from_user else 0
    was_stock = user_id in _adding_stock
    was_raw = user_id in _adding_raw
    _adding_stock.discard(user_id)
    _adding_raw.discard(user_id)
    if was_raw:
        await message.reply("Готово. Режим Raw выключен.")
    elif was_stock:
        n = get_fallback_unused_count_for_user(user_id)
        await message.reply(f"Готово. Заготовок осталось: {n}.")
    else:
        await message.reply("Не был в режиме заготовок или Raw.")


async def cmd_stock(message: Message) -> None:
    """Сколько заготовок осталось."""
    user_id = message.from_user.id if message.from_user else 0
    n = get_fallback_unused_count_for_user(user_id)
    await message.reply(f"Заготовок: {n}. Пополнить — /addstock.")


async def run_sprint_reminder(bot: Bot) -> None:
    """Напоминание об отчёте по спринту (с SPRINT_REMINDER_START, пока не сдан)."""
    uid = RAW_OWNER_USER_ID or get_owner_user_id()
    if not uid:
        return
    try:
        from datetime import date
        today = date.today().isoformat()
        if today < SPRINT_REMINDER_START:
            return
        if sprint_report_submitted(CURRENT_SPRINT_ID, uid):
            return
        await bot.send_message(
            chat_id=uid,
            text="📋 Напоминание: пора сдать отчёт по спринту. Открой Avatar → СПРИНТЫ → нажми «Сдать отчёт» — Perplexity пришлёт анализ в PDF.",
        )
        logger.info("Sprint reminder sent to %s for %s", uid, CURRENT_SPRINT_ID)
    except Exception as e:
        logger.exception("Sprint reminder failed: %s", e)


async def run_daily_review(bot: Bot) -> None:
    """Отправляет ежедневный RAPA-обзор владельцу."""
    uid = RAW_OWNER_USER_ID or get_owner_user_id()
    if not uid:
        return
    try:
        from bot.rapa import build_daily_review
        text = build_daily_review(uid)
        await bot.send_message(chat_id=uid, text=text[:4000])
        logger.info("Daily review sent to %s", uid)
    except Exception as e:
        logger.exception("Daily review failed: %s", e)


async def run_fallback_check(bot: Bot) -> None:
    """В 23:00: если за день не было ни одного фото — постить заготовку и писать, сколько осталось."""
    if not CHANNEL_ID:
        return
    owner = get_owner_user_id()
    if not owner:
        logger.info("Fallback check: no owner")
        return
    if count_photos_sent_today_by_user(owner) > 0:
        logger.info("Fallback check: user sent photo today, skip")
        return
    row = get_random_unused_fallback()
    if not row:
        try:
            await bot.send_message(chat_id=owner, text="Сегодня не было фото, а заготовок нет. Добавь: /addstock")
        except Exception:
            pass
        return
    fallback_id, owner_id, file_id, media_type = row
    mark_fallback_used(fallback_id)  # Сразу помечаем — чтобы другие экземпляры не постили то же
    try:
        await _post_media_to_channel(bot, file_id, None, media_type)
        remaining = get_fallback_unused_count_for_user(owner_id)
        await bot.send_message(
            chat_id=owner_id,
            text=f"Сегодня не было фото — в канал ушла заготовка ✓ Осталось заготовок: {remaining}. Пополни: /addstock",
        )
        logger.info("Fallback posted: id=%s, remaining=%s", fallback_id, remaining)
    except Exception as ex:
        logger.exception("Fallback post failed: %s", ex)
        # Откат: помечаем заготовку как неиспользованную
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute("UPDATE fallback_photos SET used_at = NULL WHERE id = ?", (fallback_id,))


async def cmd_channelid(message: Message) -> None:
    """Команда /channelid — подсказка."""
    await message.reply(
        "Перешли сюда любое сообщение из своего канала — я пришлю его ID для .env"
    )


async def run_scheduled_post(bot: Bot) -> None:
    """Публикует неопубликованные записи в канал (вызывается по расписанию)."""
    if not CHANNEL_ID:
        return
    entries = get_unpublished_entries()
    if not entries:
        logger.info("Scheduled post: nothing to publish")
        return
    for eid, file_id, caption, media_type in entries:
        mark_published(eid)  # Сразу помечаем — чтобы другие экземпляры бота не постили то же
        try:
            await _post_media_to_channel(bot, file_id, caption, media_type)
            logger.info("Scheduled post: published entry id=%s", eid)
        except Exception as ex:
            logger.exception("Scheduled post failed for id=%s: %s", eid, ex)
            mark_unpublished(eid)


async def cmd_cancel(message: Message) -> None:
    """Отменить отложенную фотку: /cancel — последнюю, /cancel 3 — по номеру из списка."""
    user_id = message.from_user.id if message.from_user else 0
    text = (message.text or "").strip()
    parts = text.split()
    entries = get_unpublished_for_user(user_id)
    if not entries:
        await message.reply("Нет отложенных фото для отмены.")
        return
    if len(parts) >= 2:
        try:
            num = int(parts[1])
            if 1 <= num <= len(entries):
                entry_id = entries[num - 1][0]
                if cancel_entry(entry_id, user_id):
                    await message.reply(f"Отменил фото #{num}.")
                else:
                    await message.reply("Не удалось отменить.")
            else:
                await message.reply(f"Укажи номер от 1 до {len(entries)}.")
        except ValueError:
            await message.reply("Укажи номер: /cancel 2")
    else:
        entry_id = entries[0][0]
        if cancel_entry(entry_id, user_id):
            await message.reply("Отменил последнее фото.")
        else:
            await message.reply("Не удалось отменить.")


async def cmd_mylist(message: Message) -> None:
    """Показать список отложенных фото."""
    user_id = message.from_user.id if message.from_user else 0
    entries = get_unpublished_for_user(user_id)
    if not entries:
        await message.reply("Нет отложенных фото.")
        return
    lines = [f"{i}. id={eid}" + (f" — {c[:30]}..." if c and len(c) > 30 else f" — {c}" if c else "") for i, (eid, c) in enumerate(entries, 1)]
    await message.reply("Отложенные фото:\n\n" + "\n".join(lines) + "\n\n/cancel N — отменить #N")


async def cmd_postat(message: Message, bot: Bot) -> None:
    """Опубликовать накопленные посты в указанное время: /postat 18:30"""
    global _scheduler
    if not CHANNEL_ID:
        await message.reply("CHANNEL_ID не задан")
        return
    text = (message.text or "").strip()
    parts = text.split()
    if len(parts) < 2:
        await message.reply("Укажи время: /postat 18:30")
        return
    try:
        time_str = parts[1]
        h, m = map(int, time_str.split(":"))
        if not (0 <= h <= 23 and 0 <= m <= 59):
            raise ValueError("Invalid time")
    except (ValueError, IndexError):
        await message.reply("Формат: /postat HH:MM (например /postat 18:30)")
        return
    entries = get_unpublished_entries()
    if not entries:
        await message.reply("Нет накопленных постов.")
        return
    if not _scheduler:
        await message.reply("Планировщик не запущен. Используй /postnow для немедленной публикации.")
        return
    run_date = datetime.now().replace(hour=h, minute=m, second=0, microsecond=0)
    if run_date <= datetime.now():
        run_date += timedelta(days=1)
    _scheduler.add_job(run_scheduled_post, "date", run_date=run_date, args=[bot])
    await message.reply(f"Опубликую {len(entries)} пост(ов) в {time_str} ✓")


async def cmd_post(message: Message, bot: Bot) -> None:
    """Опубликовать в канал последнее сохранённое видео (после отправки видео напиши /post)."""
    user_id = message.from_user.id if message.from_user else 0
    if user_id not in _pending_post:
        await message.reply("Нет сохранённого видео. Отправь видео или видеокружок, затем напиши /post.")
        return
    if not CHANNEL_ID:
        await message.reply("CHANNEL_ID не задан.")
        return
    pending = _pending_post.pop(user_id)
    try:
        await _post_media_to_channel(
            bot,
            pending["file_id"],
            pending["caption"],
            pending.get("media_type", "video"),
        )
        mark_published(pending["entry_id"])
        await message.reply("Опубликовано в канал ✓")
        logger.info("Posted pending video to channel: %s", CHANNEL_ID)
    except Exception as ex:
        logger.exception("Post failed: %s", ex)
        _pending_post[user_id] = pending  # вернуть в очередь
        await message.reply(f"Не удалось опубликовать: {ex}. Попробуй ещё раз /post.")


async def cmd_postnow(message: Message, bot: Bot) -> None:
    """Опубликовать сейчас все накопленные посты (при отложенном режиме)."""
    if not CHANNEL_ID:
        await message.reply("CHANNEL_ID не задан")
        return
    entries = get_unpublished_entries()
    if not entries:
        await message.reply("Нет накопленных постов для публикации.")
        return
    await message.reply(f"Публикую {len(entries)} пост(ов)...")
    await run_scheduled_post(bot)
    await message.reply("Готово ✓")


async def cmd_testchannel(message: Message, bot: Bot) -> None:
    """Команда /testchannel — проверка поста в канал."""
    if not CHANNEL_ID:
        await message.reply("CHANNEL_ID не задан в .env")
        return
    try:
        await bot.send_message(
            chat_id=CHANNEL_ID,
            text="Test from Collect bot — если видишь это, посты в канал работают ✓",
        )
        await message.reply("Сообщение отправлено в канал. Проверь канал.")
    except Exception as e:
        logger.exception("Test channel failed: %s", e)
        await message.reply(f"Ошибка при посте в канал:\n{type(e).__name__}: {e}")


async def on_text_to_raw(message: Message) -> None:
    """Текст или ссылка без команды — сохранить в Raw. Теги: #diary, #работа и т.п."""
    if not message.text or message.text.strip().startswith("/"):
        return
    user_id = message.from_user.id if message.from_user else 0
    chat_id = message.chat.id
    content = message.text.strip()
    cleaned, tags = extract_raw_tags(content)
    raw_id = save_raw(user_id, chat_id, cleaned or "…", source="Telegram", tags=tags or None)
    if raw_id:
        tags_hint = f" #{','.join(tags)}" if tags else ""
        text = f"✓ В Raw #%s%s" % (raw_id, tags_hint)
        kb = build_raw_tag_keyboard(raw_id, exclude_tags=tags) if not tags else None
        await message.reply(text, reply_markup=kb)


async def on_raw_tag_callback(callback: CallbackQuery) -> None:
    """Клик по кнопке тега: добавляем тег к записи Raw."""
    data = callback.data or ""
    if not data.startswith("raw_tag:"):
        return
    try:
        _, raw_id_s, tag = data.split(":", 2)
        raw_id = int(raw_id_s)
    except (ValueError, TypeError):
        await callback.answer("Ошибка")
        return
    user_id = callback.from_user.id if callback.from_user else 0
    if add_tag_to_raw(raw_id, user_id, tag):
        await callback.answer(f"✓ Тег «{tag}» добавлен")
        # Убираем кнопки и обновляем текст
        try:
            new_text = (callback.message.text or "") + f" #{tag}"
            await callback.message.edit_text(new_text, reply_markup=None)
        except Exception:
            pass
    else:
        await callback.answer("Не удалось добавить тег")


async def on_forwarded_from_channel(message: Message) -> None:
    """Если переслано сообщение из канала — возвращаем ID канала."""
    origin = message.forward_origin
    if not origin or not isinstance(origin, MessageOriginChannel):
        await message.reply(
            "Не вижу данные канала. Telegram скрывает источник при пересылке из приватных каналов.\n\n"
            "Попробуй:\n"
            "1. Временно сделай канал публичным (настройки → Channel type → Public), получи @username, в .env укажи CHANNEL_ID=@имя\n"
            "2. Либо перешли сообщение боту @RawDataBot — в ответе найди forward_from_chat.id"
        )
        return
    chat = origin.chat
    channel_id = chat.id
    title = getattr(chat, "title", "") or ""
    await message.reply(
        f"ID канала «{title}»:\n\n{channel_id}\n\n"
        "Скопируй в .env:\n"
        f"CHANNEL_ID={channel_id}"
    )


async def setup_bot_ui(bot: Bot) -> None:
    """Регистрирует команды и устанавливает меню/кнопку слева внизу."""
    commands = [
        BotCommand(command="start", description="Начать"),
        BotCommand(command="post", description="Опубликовать видео в канал"),
        BotCommand(command="postnow", description="Опубликовать сейчас"),
        BotCommand(command="postat", description="Опубликовать в HH:MM"),
        BotCommand(command="mylist", description="Список отложенных"),
        BotCommand(command="cancel", description="Отменить фото"),
        BotCommand(command="addstock", description="Добавить заготовки"),
        BotCommand(command="stock", description="Сколько заготовок"),
        BotCommand(command="channelid", description="ID канала для .env"),
        BotCommand(command="raw", description="В Raw (Inbox)"),
        BotCommand(command="diary", description="В Raw с тегом diary"),
        BotCommand(command="rawphoto", description="Фото → Raw"),
        BotCommand(command="review", description="Обзор daily/weekly/monthly"),
    ]
    try:
        await bot.set_my_commands(commands=commands)
        logger.info("Commands registered")
    except Exception as e:
        logger.warning("Failed to set commands: %s", e)
    try:
        if MENU_BUTTON_URL:
            await bot.set_chat_menu_button(menu_button=MenuButtonWebApp(text="Open", web_app=WebAppInfo(url=MENU_BUTTON_URL)))
            logger.info("Menu button: Open (Web App) -> %s", MENU_BUTTON_URL)
        else:
            await bot.set_chat_menu_button(menu_button=MenuButtonCommands())
            logger.info("Menu button: Commands (слева внизу)")
    except Exception as e:
        logger.warning("Failed to set menu button: %s", e)


def main() -> None:
    if not BOT_TOKEN:
        raise SystemExit("Укажи BOT_TOKEN в .env или config/.env")

    init_db()

    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher()

    dp.startup.register(setup_bot_ui)

    dp.message.register(cmd_start, Command("start"))
    dp.message.register(cmd_addstock, Command("addstock"))
    dp.message.register(cmd_done, Command("done"))
    dp.message.register(cmd_stock, Command("stock"))
    dp.message.register(cmd_channelid, Command("channelid"))
    dp.message.register(cmd_raw, Command("raw"))
    dp.message.register(cmd_diary, Command("diary"))
    dp.message.register(cmd_rawphoto, Command("rawphoto"))
    dp.message.register(cmd_review, Command("review"))
    dp.callback_query.register(on_raw_tag_callback, F.data.startswith("raw_tag:"))
    dp.message.register(cmd_cancel, Command("cancel"))
    dp.message.register(cmd_mylist, Command("mylist"))
    dp.message.register(cmd_postat, Command("postat"))
    dp.message.register(cmd_post, Command("post"))
    dp.message.register(cmd_postnow, Command("postnow"))
    dp.message.register(cmd_testchannel, Command("testchannel"))
    dp.message.register(on_forwarded_from_channel, F.forward_origin)  # до on_photo!
    dp.message.register(on_photo, F.photo)
    dp.message.register(on_video, F.video)
    dp.message.register(on_video_note, F.video_note)
    dp.message.register(on_text_to_raw, F.text)  # текст/ссылки → Raw

    # Планировщик: постинг, fallback, RAPA-обзор, напоминания по спринту
    if CHANNEL_ID or REVIEW_DAILY_TIME or (SPRINT_REMINDER_START and CURRENT_SPRINT_ID):
        async def start_scheduler(*_):
            global _scheduler
            _scheduler = AsyncIOScheduler()
            if CHANNEL_ID:
                try:
                    if POST_SCHEDULE_TIME:
                        h, m = map(int, POST_SCHEDULE_TIME.strip().split(":"))
                        _scheduler.add_job(run_scheduled_post, "cron", hour=h, minute=m, args=[bot])
                        logger.info("Scheduled post: daily at %s", POST_SCHEDULE_TIME)
                except (ValueError, IndexError) as e:
                    logger.warning("Invalid POST_SCHEDULE_TIME: %s", e)
                try:
                    h, m = map(int, (FALLBACK_TIME or "23:00").strip().split(":"))
                    _scheduler.add_job(run_fallback_check, "cron", hour=h, minute=m, args=[bot])
                    logger.info("Fallback check: daily at %s", FALLBACK_TIME)
                except (ValueError, IndexError) as e:
                    logger.warning("Invalid FALLBACK_TIME, using 23:00: %s", e)
            if REVIEW_DAILY_TIME:
                try:
                    h, m = map(int, REVIEW_DAILY_TIME.strip().split(":"))
                    _scheduler.add_job(run_daily_review, "cron", hour=h, minute=m, args=[bot])
                    logger.info("Daily review: at %s", REVIEW_DAILY_TIME)
                except (ValueError, IndexError) as e:
                    logger.warning("Invalid REVIEW_DAILY_TIME: %s", e)
            if SPRINT_REMINDER_START and CURRENT_SPRINT_ID:
                try:
                    h, m = map(int, (SPRINT_REMINDER_TIME or "10:00").strip().split(":"))
                    _scheduler.add_job(run_sprint_reminder, "cron", hour=h, minute=m, args=[bot])
                    logger.info("Sprint reminder: daily at %s (from %s)", SPRINT_REMINDER_TIME, SPRINT_REMINDER_START)
                except (ValueError, IndexError) as e:
                    logger.warning("Invalid SPRINT_REMINDER_TIME: %s", e)
            _scheduler.start()
        dp.startup.register(start_scheduler)

    logger.info("Collect bot starting... CHANNEL_ID=%s POST_SCHEDULE=%s", CHANNEL_ID, POST_SCHEDULE_TIME)
    dp.run_polling(bot)


if __name__ == "__main__":
    main()
