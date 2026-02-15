-- RAPA: 5 баз — Projects, Areas, Resources, Raw, Daily Log
-- Archive = статус внутри баз

-- Areas = зоны ответственности
CREATE TABLE IF NOT EXISTS rapa_areas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    slug TEXT NOT NULL,
    type TEXT,
    goal TEXT,
    role TEXT,
    UNIQUE(user_id, slug)
);
CREATE INDEX IF NOT EXISTS idx_rapa_areas_user ON rapa_areas(user_id);

-- Projects = результат + срок
CREATE TABLE IF NOT EXISTS rapa_projects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    area_id INTEGER REFERENCES rapa_areas(id),
    name TEXT NOT NULL,
    outcome TEXT,
    status TEXT DEFAULT 'active',
    horizon TEXT,
    impact TEXT,
    effort TEXT,
    start_date TEXT,
    deadline TEXT,
    next_review TEXT,
    daily_focus_count INTEGER DEFAULT 0,
    created_at TEXT NOT NULL,
    archived_at TEXT,
    metadata TEXT
);
CREATE INDEX IF NOT EXISTS idx_rapa_projects_user ON rapa_projects(user_id);
CREATE INDEX IF NOT EXISTS idx_rapa_projects_status ON rapa_projects(status);

-- Ресурсы (Resources) = материалы, ссылки
CREATE TABLE IF NOT EXISTS rapa_resources (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    title TEXT,
    content TEXT,
    url TEXT,
    tags TEXT,
    created_at TEXT NOT NULL,
    metadata TEXT
);
CREATE INDEX IF NOT EXISTS idx_rapa_resources_user ON rapa_resources(user_id);

-- Задачи (Next Actions) — из Raw или в рамках проекта
CREATE TABLE IF NOT EXISTS rapa_tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    raw_id INTEGER REFERENCES raw(id),
    project_id INTEGER REFERENCES rapa_projects(id),
    area_id INTEGER REFERENCES rapa_areas(id),
    title TEXT NOT NULL,
    context TEXT,
    status TEXT DEFAULT 'pending',
    due_date TEXT,
    created_at TEXT NOT NULL,
    completed_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_rapa_tasks_user ON rapa_tasks(user_id);
CREATE INDEX IF NOT EXISTS idx_rapa_tasks_project ON rapa_tasks(project_id);
CREATE INDEX IF NOT EXISTS idx_rapa_tasks_status ON rapa_tasks(status);

-- Goals = годовые цели (Area + описание)
CREATE TABLE IF NOT EXISTS rapa_goals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    area_id INTEGER REFERENCES rapa_areas(id),
    year INTEGER NOT NULL,
    name TEXT NOT NULL,
    description TEXT,
    status TEXT DEFAULT 'active',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_rapa_goals_user_year ON rapa_goals(user_id, year);
