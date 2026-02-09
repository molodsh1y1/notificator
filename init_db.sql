PRAGMA journal_mode = WAL;
PRAGMA synchronous = NORMAL;
PRAGMA cache_size = -64000;
PRAGMA temp_store = MEMORY;

CREATE TABLE IF NOT EXISTS users (
    chat_id INTEGER PRIMARY KEY,
    active INTEGER DEFAULT 1,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS last_graph (
    id INTEGER PRIMARY KEY DEFAULT 1,
    graph_id TEXT NOT NULL,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS graph_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    graph_id TEXT UNIQUE NOT NULL,
    date_graph TEXT NOT NULL,
    times_data TEXT NOT NULL,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_users_active ON users(active);
CREATE INDEX IF NOT EXISTS idx_graph_history_date ON graph_history(date_graph);
