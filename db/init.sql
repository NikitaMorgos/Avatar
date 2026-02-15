-- Схема таблицы collect_entries для модуля Collect
-- См. docs/collect-spec.md

CREATE TABLE IF NOT EXISTS collect_entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    chat_id INTEGER NOT NULL,
    message_id INTEGER NOT NULL,
    photo_file_id TEXT NOT NULL,
    photo_file_path TEXT,
    comment TEXT,
    created_at TEXT NOT NULL,
    tags TEXT,
    published_to_channel INTEGER DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_collect_user_created ON collect_entries(user_id, created_at);
CREATE INDEX IF NOT EXISTS idx_collect_created ON collect_entries(created_at);

-- Заготовки: фото для поста в 23:00, если за день не было ни одного
CREATE TABLE IF NOT EXISTS fallback_photos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    photo_file_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    used_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_fallback_used ON fallback_photos(used_at);

-- Raw Inbox: сырьё из Plaud/Email/TG для Avatar (RAPA)
CREATE TABLE IF NOT EXISTS raw (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    chat_id INTEGER NOT NULL,
    title TEXT,
    content TEXT NOT NULL,
    source TEXT DEFAULT 'Telegram',
    created_at TEXT NOT NULL,
    rapa_stage TEXT DEFAULT 'Raw',
    para_type TEXT,
    project_id INTEGER,
    area_id INTEGER,
    gtd_type TEXT,
    next_action TEXT,
    ai_summary TEXT,
    metadata TEXT,
    tags TEXT
);
CREATE INDEX IF NOT EXISTS idx_raw_user_created ON raw(user_id, created_at);
CREATE INDEX IF NOT EXISTS idx_raw_rapa_stage ON raw(rapa_stage);
