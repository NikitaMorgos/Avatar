# AGENTS.md — Avatar Project

> Этот файл читается AI-агентами (Cursor, Perplexity, Claude и др.) для понимания контекста проекта перед любой работой с кодом.

---

## Что такое Avatar

**Avatar** — личная операционная система человека (Personal ERP / Second Brain), powered by AI.
Система помогает управлять жизнью, проектами и знаниями в едином контексте.

Стек: Python · aiogram 3 · Flask · SQLite · APScheduler · OpenAI · Evernote SDK · FPDF2

Роли в системе:
- **Perplexity** — проджект-менеджер, архитектор, ставит ТЗ
- **Cursor** — реализует код по ТЗ
- **Telegram-бот** — основной интерфейс пользователя

---

## Архитектура проекта

```
Avatar/
├── bot/             # Telegram-бот (aiogram 3)
│   ├── collect_bot.py   # Главный бот: Collect + Raw Inbox + RAPA
│   └── rapa.py          # RAPA-движок (Raw→Assign→Project→Archive)
├── api/             # Flask REST API
│   ├── collect_api.py       # API для Collect
│   ├── evernote_diary.py    # Интеграция с Evernote
│   └── sprint_perplexity.py # Отчёты по спринтам через Perplexity
├── web/             # Web-интерфейс (статика)
├── db/              # SQLite БД + SQL-схемы
│   └── collect.db   # Основная БД
├── deploy/          # Скрипты деплоя (systemd, PowerShell, bat)
├── docs/            # Спеки и документация по модулям
├── tasks/           # Задачи (task management, см. ниже)
├── scripts/         # Утилиты
├── .env             # Секреты (BOT_TOKEN, CHANNEL_ID, PROXY, …)
└── requirements.txt
```

---

## Модули (Skills)

### ✅ Collect (MVP ready)
- Приём фото/видео/видеокружков через Telegram-бот
- Сохранение в SQLite (`collect_entries`)
- Пост в TG-канал (мгновенный или по расписанию)
- Заготовки (`fallback_photos`) — пост при отсутствии фото за день
- **Файл:** `bot/collect_bot.py`

### ✅ Raw Inbox
- Приём любого сырья (текст, фото, ссылки) через Telegram
- Теги: `#diary`, `#работа`, `#идея` и др.
- Команды: `/raw`, `/diary`, `/rawphoto`
- **Файл:** `bot/collect_bot.py` (handler `on_text_to_raw`, `cmd_raw`)

### ✅ RAPA
- Фреймворк: **Raw → Assign → Project → Archive**
- Автоклассификация входящих по областям жизни (Superhero Areas)
- Области: Business, Family, WCS, Ironman, Coach, Doctor, Trainer, CEO
- Обзоры: `/review daily|weekly|monthly`
- **Файл:** `bot/rapa.py`

### 🔄 Evernote Integration
- Дневник из Evernote
- **Файл:** `api/evernote_diary.py`

### 🔄 Sprint + Perplexity
- Отчёты по спринтам, анализ через Perplexity AI
- Напоминания через бот (`SPRINT_REMINDER_START`, `CURRENT_SPRINT_ID`)
- **Файл:** `api/sprint_perplexity.py`

### 🔄 Web UI
- Статичный веб-интерфейс для просмотра записей
- **Файлы:** `web/index.html`, `web/collect.html`

### ✅ Спорт (Avatar → раздел «Спорт»)
- Тренировочный дневник с программами, трекингом и AI-тренером
- Пилотная программа: **Стойка на руках без опоры** (16 недель, 4 фазы)
- **Файл:** `index.html` — функции `loadSportContent`, `bindSport`, `sendSportAI`, константа `HANDSTAND_PROGRAM`
- **Данные программы:** `db/sport_handstand_program.json`
- **Хранилище:** localStorage (`avatar_sport_data`) — сессии, чекпоинты, история чата с AI
- **Claude API key:** константа `SPORT_CLAUDE_KEY` в `index.html` (строка ~584). Получить на console.anthropic.com/settings/keys

#### Вкладки раздела Спорт:
| Вкладка | Назначение |
|---|---|
| **Программа** | Текущая фаза + упражнения с описаниями. Кнопка «Выполнено» открывает форму записи |
| **Дневник** | История сессий: дата, упражнения, hold у стены / без опоры, запястья, заметки |
| **AI-тренер** | Чат с Claude. Контекст: последние 10 тренировок + текущая фаза. Модель: claude-haiku-4-5-20251001 |
| **Добавить запись** | Ручная форма для записи сессии без упражнений |

#### Структура данных сессии (localStorage):
```json
{
  "sessions": [{
    "id": "timestamp",
    "date": "2026-04-14",
    "programId": "handstand_freestanding_2026",
    "exercises": [{"exerciseId": "hollow_body_hold", "sets": "3×45с", "rpe": 6, "notes": ""}],
    "bestWallHold": 45,
    "bestFreeHold": 0,
    "wristComfort": 5,
    "notes": "общая заметка"
  }],
  "checkpoints": {"4": "2026-05-12", "8": null},
  "aiKey": "sk-ant-...",
  "aiMessages": [{"role": "user", "content": "..."}, {"role": "assistant", "content": "..."}]
}
```

#### Программа «Стойка на руках»:
- **Фаза 1** (нед. 1–4): Фундамент — запястья, hollow body, стойка грудью к стене
- **Фаза 2** (нед. 5–8): Контроль — стойка спиной к стене, выходы (пируэт / колесо)
- **Фаза 3** (нед. 9–12): Подъём — kick-up, tuck handstand, finger pressure
- **Фаза 4** (нед. 13–16): Свободная стойка — попытки без опоры
- Старт: 2026-04-14, финиш: 2026-08-04

#### Как продолжить работу над разделом Спорт:
1. Читать `db/sport_handstand_program.json` — полная схема программы с описаниями упражнений
2. Функции в `index.html`: `loadSportContent()` → HTML, `bindSport()` → события, `sendSportAI()` → AI
3. Следующие задачи (backlog):
   - Импорт исторических данных из `Dropbox/Ironman/Ironman.xlsx` (лист `daily`)
   - Добавить Chart.js график прогресса (wall hold и freestanding hold по датам)
   - Поддержка нескольких программ (Run, Swim, GPP — из goals_2026.json)
   - Telegram-бот: команды `/s run 45min 8km`, `/d 73.5 7h good` для ввода без браузера

### 📋 Planned
- Voice inbox (Plaud integration) — `docs/plaud-integration.md`
- Google Docs/Sheets integration
- Health PDF extractor — `scripts/extract_health_pdfs.py`

---

## Окружение (.env)

| Переменная | Назначение |
|---|---|
| `BOT_TOKEN` | Telegram Bot API токен (@CollectMyDay_bot) |
| `CHANNEL_ID` | ID TG-канала для постинга (-100…) |
| `DB_PATH` | Путь к SQLite БД (default: `db/collect.db`) |
| `POST_SCHEDULE_TIME` | Время постинга (HH:MM). Пусто = мгновенно |
| `FALLBACK_TIME` | Время проверки заготовок (default: 23:00) |
| `MENU_BUTTON_URL` | URL для кнопки «Open» в боте |
| `PROXY` | Прокси для api.telegram.org (socks5/http) |
| `RAW_OWNER_USER_ID` | Telegram user_id владельца |
| `REVIEW_DAILY_TIME` | Время RAPA-обзора (HH:MM) |
| `SPRINT_REMINDER_START` | Дата начала напоминаний по спринту |
| `SPRINT_REMINDER_TIME` | Время напоминания по спринту |
| `CURRENT_SPRINT_ID` | ID текущего спринта |
| `PERPLEXITY_API_KEY` | Ключ Perplexity API |

---

## Запуск

```powershell
# Collect bot (основной)
Set-Location "c:\Users\user\Dropbox\Public\Cursor\Avatar"
python bot/collect_bot.py

# Collect API (Flask)
python api/collect_api.py

# Бот с автоперезапуском (Windows)
.\deploy\run-collect-bot-24-7.ps1
```

---

## База данных

SQLite, файл `db/collect.db`. Основные таблицы:

| Таблица | Назначение |
|---|---|
| `collect_entries` | Записи дня (фото/видео + комментарий) |
| `fallback_photos` | Заготовки для постинга |
| `raw` | Raw Inbox (сырьё, Inbox) |
| `rapa_areas` | RAPA-области жизни |
| `sprint_reports` | Сданные отчёты по спринтам |

Схема: `db/init.sql` + `db/rapa_schema.sql`

---

## Флоу управления жизнью

```
Цель → Спринт → Задачи → Лог → Рефлексия
```

Области жизни (Superhero Areas):
`Business · Family · WCS · Ironman · Coach · Doctor · Trainer · CEO`

---

## Task Management Protocol

Каждая задача — отдельная папка в `tasks/`:

```
tasks/
  task-001-vpn-proxy/
    tasks/        # подзадачи, чек-листы
    jobs/         # скрипты и команды
    breadcrumbs/  # заметки, диагностика, история
    docs/         # ссылки и документы
    plan.md       # план работ
    status.md     # текущий статус и прогресс
```

**Правила:**
- Имя: `task-NNN-short-name` (NNN — трёхзначный номер)
- Все папки создаются сразу при создании задачи
- `status.md` обновляется при каждом изменении статуса
- `breadcrumbs/` — хронологические заметки, не удалять

**Статусы задачи:** `🟡 planning` → `🔵 in-progress` → `🟣 review` → `✅ done` | `❌ cancelled`

---

## Мультиагентная работа

В проекте одновременно работают два AI-агента:

| Агент | Инструмент | Роль |
|---|---|---|
| **Cursor** | IDE (этот агент) | Реализация фич, рефакторинг, дебаг |
| **Claude Code** | CLI (`claude`) | Параллельные задачи, эксперименты |

### Правила для Claude Code

Claude Code работает через **git worktrees** в `.claude/worktrees/<name>/`.

**Обязательно:**
- Каждая задача — отдельный worktree на ветке `claude/<name>`
- Ветку называть по сути задачи (не рандомные имена)
- После мержа в `main` — сразу удалить worktree: `git worktree remove .claude/worktrees/<name>`
- Удалить ветку: `git branch -d claude/<name>`
- Не держать больше 2 активных worktrees одновременно

**Запрещено:**
- Коммитить напрямую в `main`
- Оставлять мёртвые ветки `claude/*` после мержа
- Создавать файлы в корне проекта без согласования

### Правила для Cursor

- Работает напрямую в `main` (мелкие правки) или через обычные ветки
- Не трогает `.claude/` — это рабочая зона Claude Code
- При конфликте веток — приоритет у `main`

---

## Coding Conventions

- Python 3.11+, type hints обязательны для публичных функций
- Async-first: aiogram 3, asyncio
- Логирование через `logging` (не `print`)
- Секреты только через `.env` + `python-dotenv`
- Новые фичи бота: handler → register в `main()` → задокументировать в `/start`
- БД: миграции через `ALTER TABLE` с `try/except OperationalError`
- Прокси: все запросы к TG API через `AiohttpSession(proxy=PROXY)` если `PROXY` задан

---

## Ключевые документы

| Файл | Содержание |
|---|---|
| `docs/avatar-project.md` | Концепт, модульная карта, roadmap |
| `docs/collect-spec.md` | Спека модуля Collect |
| `docs/raw-inbox-spec.md` | Спека Raw Inbox |
| `docs/rapa.md` | RAPA фреймворк |
| `docs/vps-deploy.md` | Деплой на VPS |
| `docs/project-flow.md` | Флоу Perplexity → Cursor |
| `tasks/` | Активные и завершённые задачи |
