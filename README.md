# Avatar — личный ERP / Second Brain

Минимальный каркас системы Avatar: личная операционная система человека, powered by AI. Perplexity выступает проджект‑менеджером; Cursor — инструментом разработки.

## Структура проекта

```
avatar-system/
├── docs/              # Документация для Perplexity и человека
│   ├── avatar-project.md   # Концепт, карта проекта
│   ├── collect-spec.md     # Спецификация модуля Collect
│   └── project-flow.md     # Флоу: Perplexity → ТЗ → Cursor
├── bot/               # Telegram‑бот Collect
│   └── collect_bot.py
├── db/                # Схема и инициализация БД
│   └── init.sql
├── config/            # Конфигурация
│   └── .env.example
├── requirements.txt
└── README.md
```

## Установка

1. Клонируй или скачай проект.
2. Создай виртуальное окружение:
   ```bash
   python -m venv venv
   venv\Scripts\activate   # Windows
   ```
3. Установи зависимости:
   ```bash
   pip install -r requirements.txt
   ```
4. Создай файл `.env` в корне проекта (или скопируй `config/.env.example` в `config/.env`).
5. Укажи `BOT_TOKEN` — токен бота от [@BotFather](https://t.me/BotFather).
6. При необходимости задай `DB_PATH` (по умолчанию: `db/collect.db`).
7. **Автопост в канал:** задай `CHANNEL_ID` в `.env` (@username или -100xxxxxxxxxx), добавь бота админом в канал с правом публиковать сообщения.
8. **Синяя кнопка «Open»:** задеплой `web/index.html` на GitHub Pages или Netlify, укажи `MENU_BUTTON_URL=https://твой-сайт/` в `.env`.

## Запуск бота Collect

```bash
python -m bot.collect_bot
```

Или из корня проекта:
```bash
python bot/collect_bot.py
```

## Документация

- `docs/avatar-project.md` — общий концепт Avatar, области жизни, карта модулей
- `docs/collect-spec.md` — ТЗ модуля Collect
- `docs/project-flow.md` — как Perplexity и Cursor работают вместе

---

Для более удобной структуры можно добавить `src/` и вынести бота туда; на старте оставлена простая схема `bot/` + `db/` + `config/`.
