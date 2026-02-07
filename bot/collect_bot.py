"""
Collect bot — MVP.
Принимает фото с подписью, сохраняет в SQLite, отвечает подтверждением.
Поддерживает отложенный постинг по расписанию.
"""

import logging
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import BotCommand
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

# Глобальный планировщик (для /postat и заготовок)
_scheduler: AsyncIOScheduler | None = None

# Режим «добавляю заготовки»: user_id в этом set — фото идут в fallback_photos
_adding_stock: set[int] = set()

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
    logger.info("DB initialized: %s", DB_PATH)


def save_entry(user_id: int, chat_id: int, message_id: int, photo_file_id: str, comment: str | None) -> int:
    """Сохраняет запись в collect_entries. Возвращает id."""
    created_at = datetime.utcnow().isoformat()
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.execute(
            """
            INSERT INTO collect_entries (user_id, chat_id, message_id, photo_file_id, photo_file_path, comment, created_at, tags, published_to_channel)
            VALUES (?, ?, ?, ?, NULL, ?, ?, NULL, 0)
            """,
            (user_id, chat_id, message_id, photo_file_id, comment or "", created_at),
        )
        rowid = cur.lastrowid
    logger.info("Saved entry: id=%s user=%s chat=%s msg=%s", rowid, user_id, chat_id, message_id)
    return rowid


def get_unpublished_entries() -> list[tuple[int, str, str | None]]:
    """Возвращает [(id, photo_file_id, comment), ...] для неопубликованных записей."""
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT id, photo_file_id, comment FROM collect_entries WHERE published_to_channel = 0 ORDER BY id"
        ).fetchall()
    return [(r["id"], r["photo_file_id"], r["comment"] or None) for r in rows]


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


def cancel_entry(entry_id: int, user_id: int) -> bool:
    """Удаляет отложенную запись. Возвращает True если удалено."""
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.execute(
            "DELETE FROM collect_entries WHERE id = ? AND user_id = ? AND published_to_channel = 0",
            (entry_id, user_id),
        )
    return cur.rowcount > 0


# --- Заготовки (fallback) ---

def add_fallback(user_id: int, photo_file_id: str) -> int:
    """Добавляет фото в заготовки. Возвращает id."""
    created_at = datetime.utcnow().isoformat()
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.execute(
            "INSERT INTO fallback_photos (user_id, photo_file_id, created_at, used_at) VALUES (?, ?, ?, NULL)",
            (user_id, photo_file_id, created_at),
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


def get_random_unused_fallback() -> tuple[int, int, str] | None:
    """Возвращает (id, user_id, photo_file_id) или None."""
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT id, user_id, photo_file_id FROM fallback_photos WHERE used_at IS NULL ORDER BY RANDOM() LIMIT 1"
        ).fetchone()
    if not row:
        return None
    return (row["id"], row["user_id"], row["photo_file_id"])


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
                    await bot.send_photo(
                        chat_id=CHANNEL_ID,
                        photo=photo_file_id,
                        caption=comment if comment else None,
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


async def cmd_start(message: Message) -> None:
    """Команда /start."""
    schedule_hint = f"\nПосты в канал: отложенно в {POST_SCHEDULE_TIME}." if POST_SCHEDULE_TIME else ""
    await message.reply(
        "Привет. Отправь фото с подписью — я сохраню его как срез дня.\n\n"
        "Один день — одна (или несколько) фоток. Буду использовать их для канала, досок и обзоров."
        f"{schedule_hint}\n\n"
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
    """Выйти из режима заготовок."""
    user_id = message.from_user.id if message.from_user else 0
    _adding_stock.discard(user_id)
    n = get_fallback_unused_count_for_user(user_id)
    await message.reply(f"Готово. Заготовок осталось: {n}.")


async def cmd_stock(message: Message) -> None:
    """Сколько заготовок осталось."""
    user_id = message.from_user.id if message.from_user else 0
    n = get_fallback_unused_count_for_user(user_id)
    await message.reply(f"Заготовок: {n}. Пополнить — /addstock.")


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
    fallback_id, owner_id, photo_file_id = row
    mark_fallback_used(fallback_id)  # Сразу помечаем — чтобы другие экземпляры не постили то же
    try:
        await bot.send_photo(chat_id=CHANNEL_ID, photo=photo_file_id, caption=None)
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
    for eid, photo_id, caption in entries:
        mark_published(eid)  # Сразу помечаем — чтобы другие экземпляры бота не постили то же
        try:
            await bot.send_photo(
                chat_id=CHANNEL_ID,
                photo=photo_id,
                caption=caption,
            )
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
        BotCommand(command="postnow", description="Опубликовать сейчас"),
        BotCommand(command="postat", description="Опубликовать в HH:MM"),
        BotCommand(command="mylist", description="Список отложенных"),
        BotCommand(command="cancel", description="Отменить фото"),
        BotCommand(command="addstock", description="Добавить заготовки"),
        BotCommand(command="stock", description="Сколько заготовок"),
        BotCommand(command="channelid", description="ID канала для .env"),
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
    dp.message.register(cmd_cancel, Command("cancel"))
    dp.message.register(cmd_mylist, Command("mylist"))
    dp.message.register(cmd_postat, Command("postat"))
    dp.message.register(cmd_postnow, Command("postnow"))
    dp.message.register(cmd_testchannel, Command("testchannel"))
    dp.message.register(on_forwarded_from_channel, F.forward_origin)  # до on_photo!
    dp.message.register(on_photo, F.photo)

    # Планировщик: отложенный постинг + проверка заготовок в 23:00
    if CHANNEL_ID:
        async def start_scheduler(*_):
            global _scheduler
            _scheduler = AsyncIOScheduler()
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
            _scheduler.start()
        dp.startup.register(start_scheduler)

    logger.info("Collect bot starting... CHANNEL_ID=%s POST_SCHEDULE=%s", CHANNEL_ID, POST_SCHEDULE_TIME)
    dp.run_polling(bot)


if __name__ == "__main__":
    main()
