import logging
import sqlite3
import os
from datetime import datetime
from dotenv import load_dotenv  # type: ignore

# ─────────────────────────────────────────────
#  ENV
# ─────────────────────────────────────────────

load_dotenv()
TOKEN    = os.getenv("TELEGRAM_BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))

if not TOKEN:
    raise ValueError("TELEGRAM_BOT_TOKEN not found in .env")
if ADMIN_ID == 0:
    raise ValueError("ADMIN_ID not found in .env")

BOT_VERSION  = "3.0.0"
BOT_CODENAME = "Drazeforce"
START_TIME   = datetime.now()

# ─────────────────────────────────────────────
#  LOGGING
# ─────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

# ─────────────────────────────────────────────
#  DATABASE
# ─────────────────────────────────────────────

conn   = sqlite3.connect("bot.db", check_same_thread=False)

# WAL mode = much safer writes, survives crashes without data loss
conn.execute("PRAGMA journal_mode=WAL")
conn.execute("PRAGMA synchronous=NORMAL")
conn.commit()

cursor = conn.cursor()

cursor.executescript("""
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS folders (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    name                TEXT UNIQUE,
    created_at          TEXT,
    forwardable         INTEGER DEFAULT 1,
    auto_delete_minutes INTEGER,
    password            TEXT,
    note                TEXT,
    pinned              INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS files (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    folder_id    INTEGER,
    file_id      TEXT,
    file_type    TEXT,
    file_size    INTEGER,
    uploaded_at  TEXT,
    text_content TEXT
);

CREATE TABLE IF NOT EXISTS links (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    folder_id    INTEGER,
    token        TEXT,
    expiry       TEXT,
    revoked      INTEGER DEFAULT 0,
    created_at   TEXT,
    access_count INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS logs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER,
    username    TEXT,
    folder_id   INTEGER,
    accessed_at TEXT
);

CREATE TABLE IF NOT EXISTS admins (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id        INTEGER UNIQUE,
    username       TEXT,
    added_by       INTEGER,
    added_at       TEXT,
    is_super_admin INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS subscribers (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id       INTEGER UNIQUE,
    username      TEXT,
    first_name    TEXT,
    subscribed_at TEXT,
    last_active   TEXT,
    banned        INTEGER DEFAULT 0,
    ban_reason    TEXT
);

CREATE TABLE IF NOT EXISTS broadcasts (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    broadcast_code TEXT UNIQUE,
    created_by     INTEGER,
    created_at     TEXT,
    scheduled_for  TEXT,
    password       TEXT,
    expiry_minutes INTEGER,
    forwardable    INTEGER DEFAULT 1,
    total_sent     INTEGER DEFAULT 0,
    total_failed   INTEGER DEFAULT 0,
    status         TEXT DEFAULT 'sent'
);

CREATE TABLE IF NOT EXISTS broadcast_files (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    broadcast_id INTEGER,
    file_id      TEXT,
    file_type    TEXT,
    text_content TEXT
);

CREATE TABLE IF NOT EXISTS user_messages (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id            INTEGER,
    username           TEXT,
    first_name         TEXT,
    message_id         TEXT UNIQUE,
    sent_at            TEXT,
    status             TEXT DEFAULT 'unread',
    viewed_at          TEXT,
    recipient_admin_id INTEGER,
    recipient_is_super INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS user_message_files (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    message_id   TEXT,
    file_id      TEXT,
    file_type    TEXT,
    text_content TEXT
);

CREATE TABLE IF NOT EXISTS banned_users (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id   INTEGER UNIQUE,
    username  TEXT,
    reason    TEXT,
    banned_at TEXT,
    banned_by INTEGER
);

CREATE TABLE IF NOT EXISTS scheduled_broadcasts (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id       TEXT UNIQUE,
    created_by   INTEGER,
    scheduled_at TEXT,
    created_at   TEXT,
    status       TEXT DEFAULT 'pending'
);

CREATE TABLE IF NOT EXISTS pinned_messages (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    message_id TEXT UNIQUE,
    content    TEXT,
    pinned_by  INTEGER,
    pinned_at  TEXT
);

CREATE INDEX IF NOT EXISTS idx_folder_name      ON folders(name);
CREATE INDEX IF NOT EXISTS idx_link_token       ON links(token);
CREATE INDEX IF NOT EXISTS idx_admin_user       ON admins(user_id);
CREATE INDEX IF NOT EXISTS idx_logs_folder      ON logs(folder_id);
CREATE INDEX IF NOT EXISTS idx_subscriber_user  ON subscribers(user_id);
CREATE INDEX IF NOT EXISTS idx_broadcast_code   ON broadcasts(broadcast_code);
CREATE INDEX IF NOT EXISTS idx_user_message_id  ON user_messages(message_id);
CREATE INDEX IF NOT EXISTS idx_msg_recipient    ON user_messages(recipient_admin_id);
CREATE INDEX IF NOT EXISTS idx_banned_user      ON banned_users(user_id);
""")

# Seed super admin
cursor.execute("""
    INSERT OR IGNORE INTO admins (user_id, username, added_by, added_at, is_super_admin)
    VALUES (?, 'Super Admin', ?, ?, 1)
""", (ADMIN_ID, ADMIN_ID, datetime.now().isoformat()))
conn.commit()

# ── Schema migrations for existing DBs ──
_migrations = [
    ("user_messages",  "recipient_admin_id", "INTEGER", "NULL"),
    ("user_messages",  "recipient_is_super",  "INTEGER", "0"),
    ("folders",        "note",                "TEXT",    "NULL"),
    ("folders",        "pinned",              "INTEGER", "0"),
    ("subscribers",    "banned",              "INTEGER", "0"),
    ("subscribers",    "ban_reason",          "TEXT",    "NULL"),
    ("broadcasts",     "scheduled_for",       "TEXT",    "NULL"),
    ("broadcasts",     "status",              "TEXT",    "'sent'"),
]
for _tbl, _col, _type, _default in _migrations:
    try:
        cursor.execute(f"ALTER TABLE {_tbl} ADD COLUMN {_col} {_type} DEFAULT {_default}")
        conn.commit()
    except sqlite3.OperationalError:
        pass

# ── v3.0 schema additions ──
_v3_script = """
CREATE TABLE IF NOT EXISTS polls (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    question    TEXT,
    option_a    TEXT,
    option_b    TEXT,
    option_c    TEXT,
    option_d    TEXT,
    created_by  INTEGER,
    created_at  TEXT,
    closes_at   TEXT,
    status      TEXT DEFAULT 'open',
    result_sent INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS poll_votes (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    poll_id  INTEGER,
    user_id  INTEGER,
    choice   TEXT,
    voted_at TEXT,
    UNIQUE(poll_id, user_id)
);

CREATE TABLE IF NOT EXISTS quotes (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    text      TEXT,
    added_by  INTEGER,
    added_at  TEXT,
    last_sent TEXT
);

CREATE TABLE IF NOT EXISTS trending (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    folder_id  INTEGER,
    label      TEXT,
    added_by   INTEGER,
    added_at   TEXT,
    expires_at TEXT,
    sort_order INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS bot_settings (
    key   TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS link_access_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    link_id     INTEGER,
    folder_id   INTEGER,
    user_id     INTEGER,
    username    TEXT,
    accessed_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_poll_votes  ON poll_votes(poll_id, user_id);
CREATE INDEX IF NOT EXISTS idx_trending    ON trending(folder_id);
CREATE INDEX IF NOT EXISTS idx_link_access ON link_access_log(link_id);
CREATE INDEX IF NOT EXISTS idx_quotes      ON quotes(last_sent);

CREATE TABLE IF NOT EXISTS message_replies (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    reply_id      TEXT    UNIQUE,
    message_id    TEXT,
    from_admin_id INTEGER,
    to_user_id    INTEGER,
    content       TEXT,
    sent_at       TEXT,
    status        TEXT    DEFAULT 'unread'
);

CREATE INDEX IF NOT EXISTS idx_reply_msg  ON message_replies(message_id);
CREATE INDEX IF NOT EXISTS idx_reply_user ON message_replies(to_user_id);
"""
cursor.executescript(_v3_script)
conn.commit()

# ── v3.0 column migrations ──
_v3_migrations = [
    ("links",   "single_use",  "INTEGER", "0"),
    ("links",   "used_by",     "INTEGER", "NULL"),
    ("links",   "used_at",     "TEXT",    "NULL"),
    ("folders", "is_secret",   "INTEGER", "0"),
    ("folders", "secret_code", "TEXT",    "NULL"),
]
for _tbl, _col, _type, _default in _v3_migrations:
    try:
        cursor.execute(f"ALTER TABLE {_tbl} ADD COLUMN {_col} {_type} DEFAULT {_default}")
        conn.commit()
    except sqlite3.OperationalError:
        pass

# ── v3.1 column migrations ──
_v31_migrations = [
    ("quotes", "author", "TEXT", "NULL"),
]
for _tbl, _col, _type, _default in _v31_migrations:
    try:
        cursor.execute(f"ALTER TABLE {_tbl} ADD COLUMN {_col} {_type} DEFAULT {_default}")
        conn.commit()
    except sqlite3.OperationalError:
        pass