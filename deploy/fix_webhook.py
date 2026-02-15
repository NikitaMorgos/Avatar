"""
Сброс webhook перед запуском Collect-бота в режиме polling.
Запусти перед main.py, если возникает ошибка Conflict (terminated by other getUpdates).

Запуск: python deploy/fix_webhook.py
Или: ./venv/bin/python deploy/fix_webhook.py
"""

import asyncio
import os
import sys
from pathlib import Path

# Добавляем корень проекта в путь
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(ROOT / ".env")
load_dotenv(ROOT / "config" / ".env")

BOT_TOKEN = (os.getenv("BOT_TOKEN") or "").strip()
if not BOT_TOKEN:
    print("Ошибка: BOT_TOKEN не найден в .env")
    sys.exit(1)


async def main():
    from aiogram import Bot
    bot = Bot(token=BOT_TOKEN)
    await bot.delete_webhook(drop_pending_updates=True)
    print("Webhook удалён, pending updates сброшены.")
    print("Подожди 5–10 сек, затем: sudo systemctl start collect-bot")
    await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
