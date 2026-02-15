# Raw Inbox — Сбор сырья для Avatar

## Цель

**Первый шаг:** подключить источники сырья (Plaud, Email, TG-чат) → AI-ассистент обрабатывает → попадает в Raw (Inbox) для дальнейшей разборки в систему RAPA (Avatar + Evernote/Notion).

---

## Архитектура потока

```
[Plaud]  ──┐
[Email]  ──┼──► [Сборщик] ──► [AI-обработка] ──► [Raw / Inbox] ──► [Assign → Projects/Areas/Resources]
[TG-чат] ─┘
```

---

## 1. Источники сырья

### Plaud (голосовые заметки)

- **Что:** аудио → транскрипция → текст
- **Как подключать:**
  - Plaud AI имеет облако и API? (проверить документацию Plaud)
  - Альтернатива: экспорт транскриптов по email / webhook
  - Или: плагин/скрипт, который забирает новые заметки из приложения
- **Формат на выходе:** `{ title, content, source: "Plaud", created_at }`

### Email

- **Что:** письма на специальный адрес (например `inbox@avatar.xxx`) или пересылка
- **Как подключать:**
  - Gmail: OAuth + API, или IMAP-парсер
  - Создать `avatar-inbox@...` — письма на него идут в Raw
  - Сервис: Zapier/Make + Gmail trigger → webhook
- **Формат:** `{ title: subject, content: body, source: "Email", created_at, from }`

### Telegram-чат

- **Что:** сообщения из личного чата или группы
- **Как подключать:**
  - Бот Avatar, который ты добавляешь в чат: пересылаешь ему сообщения
  - Или: бот в группе, который логирует все сообщения (с согласия участников)
  - Команда `/raw <текст>` — быстрая запись в Inbox
- **Формат:** `{ title, content, source: "Telegram", created_at, chat_id }`

---

## 2. Сборщик (Collector)

Единый сервис, который:

1. Принимает сырьё из всех источников (webhook, API, бот)
2. Нормализует в общий формат **Raw**:
   - `title` (авто: первые N слов)
   - `content` (полный текст)
   - `source` (Plaud / Email / Telegram)
   - `created_at`
   - `metadata` (опционально: from, chat_id, attachment_url)
3. Кладёт в очередь на AI-обработку

---

## 3. AI-обработка

AI-ассистент получает сырой текст и:

1. **Суммаризирует** — краткое резюме
2. **Классифицирует** — предлагает GTD Type (Action / Idea / Reference / Trash)
3. **Предлагает** — Project, Area (если есть маппинг)
4. **Извлекает** — действия, даты, ссылки

Результат дополняет запись Raw перед сохранением в базу.

**Реализация AI:**
- Локально: Ollama, LM Studio
- Облако: OpenAI API, Claude, Gemini
- Через Avatar: единый эндпоинт, который вызывает выбранную модель

---

## 4. Хранение Raw

**Куда класть:**

| Вариант | Плюсы | Минусы |
|---------|-------|--------|
| **Evernote** | Уже есть, теги, поиск | API ограничен, нет Relations |
| **Notion** | Relations, DB, гибко | Нужна миграция |
| **Своя БД** | Полный контроль, Relations | Нужен UI |
| **Notion + Evernote** | Notion — структура, Evernote — заметки | Две системы |

**Рекомендация для первого шага:** своя БД (SQLite/Postgres) с таблицей `raw` + позже синк в Notion/Evernote. Так проще тестировать поток.

---

## 5. Avatar — Evernote: как связать

### Вариант A: Evernote как хранилище Raw

- Каждая запись Raw → заметка в Evernote с тегом `#raw` и тегом источника `#plaud`, `#email`, `#telegram`
- AI-обработка: создаётся заметка, в тело добавляется блок «AI summary» и «suggested GTD type»

### Вариант B: Notion как главная база, Evernote — архив

- Raw, Projects, Areas, Resources — в Notion (Relations, views)
- Evernote: экспорт туда «обработанных» заметок как reference material

### Вариант C: Avatar как оркестратор

- Avatar (веб/бот) — единая точка входа
- Сборщик кладёт в Avatar DB
- Avatar синхронизирует с Evernote (через API) и/или Notion

---

## 6. План реализации (Phase 1)

### Шаг 1.1 — TG-бот для Raw ✓

- Реализовано в Collect-боте:
- **Текст/ссылки:** `/raw <текст>` или просто отправить сообщение → Raw
- **Фото в Collect** (канал): фото без маркера → collect_entries
- **Фото в Raw:** фото с подписью `#raw` или режим `/rawphoto` → Raw (metadata: photo_file_id)

### Шаг 1.2 — Email Inbox

- Создать email `avatar-inbox@...` (или использовать существующий)
- Скрипт/сервис: IMAP polling или Gmail API → при новом письме → запись в Raw

### Шаг 1.3 — Plaud

- Исследовать API Plaud / экспорт
- Webhook или cron: забирать новые транскрипты → Raw

### Шаг 1.4 — AI-обработка

- После записи в Raw вызвать AI (локально или API)
- Обновить запись: `ai_summary`, `suggested_gtd_type`, `suggested_project`

### Шаг 1.5 — Связь с Evernote

- Evernote API: создать заметку из Raw
- Или: экспорт в ENEX-файл, импорт вручную (для MVP)

---

## 7. Схема таблицы Raw (для своей БД)

```sql
CREATE TABLE raw (
  id INTEGER PRIMARY KEY,
  title TEXT,
  content TEXT,
  source TEXT,  -- Plaud / Email / Telegram
  created_at DATETIME,
  rapa_stage TEXT DEFAULT 'Raw',  -- Raw / Assigned / Processed
  gtd_type TEXT,  -- Action / Idea / Reference / Trash
  ai_summary TEXT,
  suggested_gtd_type TEXT,
  suggested_project_id INTEGER,
  assigned_project_id INTEGER,
  assigned_area_id INTEGER,
  converted_resource_id INTEGER,
  evernote_note_id TEXT,
  metadata JSON
);
```

---

## Следующие шаги

1. Уточнить: Plaud — есть ли API / webhook / экспорт?
2. Выбрать: Evernote-first или Notion-first для структуры RAPA?
3. Начать с TG `/raw` — быстрый MVP за 1 день.
