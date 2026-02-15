# Avatar — Evernote: структура RAPA

Полная схема работы с проектами. Реализация в связке Avatar + Evernote (или Notion).

---

## 1. Основные базы (5 таблиц)

| База | Назначение |
|------|------------|
| **Projects** | Проекты |
| **Areas** | Области ответственности |
| **Resources** | Шаблоны, промпты, скрипты, статьи |
| **Raw** | Inbox, сырьё из Plaud/Email/TG |
| **Daily Log** | 60-минутный протокол дня |

*Archive — статус/флаг внутри баз, не отдельная таблица.*

---

## 2. Projects

**Поля:**
- Name
- Area (Relation → Areas)
- Status (Select: Idea / Active / On Hold / Done / Archived)
- RAPA Type (Formula: Project)
- Horizon (Select: Week / Month / Quarter / Year)
- Impact (Number или Select: Low/Med/High)
- Effort (Number или Select)
- Start Date, Due Date
- Next Review (Date)
- Daily Focus Counter (Number)
- Related Resources (Relation → Resources)
- Related Raw (Relation → Raw)
- Daily Logs (Relation → Daily Log)

---

## 3. Areas

**Поля:**
- Name (Business, Family, WCS, Ironman и т.д.)
- Type (Personal / Work / Creative)
- RAPA Type (Formula: Area)
- Goal (краткое описание ответственности/стандарта)
- Projects (Relation → Projects)
- Resources (Relation → Resources)

---

## 4. Resources

**Поля:**
- Name
- Type (Template / Prompt / Script / Article / Note / Video / Course …)
- Domain (Code / Product / WCS / Music / Finance …)
- RAPA Type (Formula: Resource)
- Linked Projects (Relation → Projects)
- Linked Areas (Relation → Areas)
- Source (URL / файл / internal)
- Status (Active / Deprecated / Archived)

*Сюда кладёшь шаблоны/промпты/скрипты из блоков 25–40 и 40–50 протокола.*

---

## 5. Raw (Inbox / R-слой)

**Поля:**
- Title (авто: первые слова)
- Content (полный текст/линк)
- Source (Email / Plaud / Chat / Manual / System)
- Created At (Date)
- RAPA Stage (Raw / Assigned / Processed)
- GTD Type (Action / Idea / Reference / Trash)
- Assigned Project (Relation → Projects)
- Assigned Area (Relation → Areas)
- Converted Resource (Relation → Resources)

**Логика:**
- Всё из Plaud/Email/чатов → строка в Raw
- При Assign проставляешь Project/Area/GTD Type → RAPA Stage = Assigned

---

## 6. Daily Log (60-минутный протокол)

**Поля:**
- Date (Date, unique)
- Day Of Week (Formula)
- Domain (Select: Code/Agents, Product/Startup, Creative, Free)
- Focus Project (Relation → Projects)
- Focus Area (Rollup через Focus Project → Area)
- Focus Question (Text)
- Success Criteria (Text)
- What We Did (Text)
- New Resources Created (Relation → Resources)
- Raw Captured (Relation → Raw)
- Automation Steps (Text / Relation → Resources)
- Wins (Text)
- Fails (Text)
- Next Experiment Idea (Text)

**Шаблон страницы дня:**
- 0–5: вопросы фокуса
- 5–25: диалог с моделью (вырезки/ссылки)
- 25–40: правка + итоговый шаблон
- 40–50: автоматизация (линк на скрипт в Resources)
- 50–60: рефлексия

---

## 7. Views

### Dashboard «Today»
- Daily Log.Date = today
- Projects (Status = Active, по Impact/Effort)
- Raw (RAPA Stage = Raw)
- Resources (последние, Type = Template/Prompt/Script)

### View «RAPA Radar»
- Raw (Raw/Assigned)
- Projects (Active/On Hold)
- Resources (новые за 7 дней)
- Daily Log (последние 7 записей)

---

## 8. Связь с Evernote

**Evernote как:**
- Хранилище заметок (Resources, Raw-архив)
- Теги = Areas, Projects, GTD Type
- Notebooks = источники (Plaud, Email, TG)

**Notion** лучше подходит для Relations и views — рассмотреть Notion как главную базу, Evernote как доп. хранилище.

---

## См. также

- `docs/raw-inbox-spec.md` — первый шаг: Plaud/Email/TG → Raw → AI
