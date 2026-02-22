import logging
import os
from datetime import datetime

import psycopg2
import psycopg2.errors
from dotenv import load_dotenv  # type: ignore

# ─────────────────────────────────────────────
#  ENV
# ─────────────────────────────────────────────

load_dotenv()
TOKEN        = os.getenv("TELEGRAM_BOT_TOKEN")
ADMIN_ID     = int(os.getenv("ADMIN_ID", "0"))
DATABASE_URL = os.getenv("DATABASE_URL")

if not TOKEN:
    raise ValueError("TELEGRAM_BOT_TOKEN not found in environment")
if ADMIN_ID == 0:
    raise ValueError("ADMIN_ID not found in environment")
if not DATABASE_URL:
    raise ValueError("DATABASE_URL not found in environment")

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

conn   = psycopg2.connect(DATABASE_URL)
conn.autocommit = False
cursor = conn.cursor()

# ─────────────────────────────────────────────
#  SCHEMA
# ─────────────────────────────────────────────

cursor.execute("""
CREATE TABLE IF NOT EXISTS folders (
    id                  SERIAL PRIMARY KEY,
    name                TEXT UNIQUE,
    created_at          TEXT,
    forwardable         INTEGER DEFAULT 1,
    auto_delete_minutes INTEGER,
    password            TEXT,
    note                TEXT,
    pinned              INTEGER DEFAULT 0,
    is_secret           INTEGER DEFAULT 0,
    secret_code         TEXT
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS files (
    id           SERIAL PRIMARY KEY,
    folder_id    INTEGER,
    file_id      TEXT,
    file_type    TEXT,
    file_size    INTEGER,
    uploaded_at  TEXT,
    text_content TEXT
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS links (
    id           SERIAL PRIMARY KEY,
    folder_id    INTEGER,
    token        TEXT UNIQUE,
    expiry       TEXT,
    revoked      INTEGER DEFAULT 0,
    created_at   TEXT,
    access_count INTEGER DEFAULT 0,
    single_use   INTEGER DEFAULT 0,
    used_by      INTEGER,
    used_at      TEXT
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS logs (
    id          SERIAL PRIMARY KEY,
    user_id     INTEGER,
    username    TEXT,
    folder_id   INTEGER,
    accessed_at TEXT
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS admins (
    id             SERIAL PRIMARY KEY,
    user_id        INTEGER UNIQUE,
    username       TEXT,
    added_by       INTEGER,
    added_at       TEXT,
    is_super_admin INTEGER DEFAULT 0
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS subscribers (
    id            SERIAL PRIMARY KEY,
    user_id       INTEGER UNIQUE,
    username      TEXT,
    first_name    TEXT,
    subscribed_at TEXT,
    last_active   TEXT,
    banned        INTEGER DEFAULT 0,
    ban_reason    TEXT
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS broadcasts (
    id             SERIAL PRIMARY KEY,
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
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS broadcast_files (
    id           SERIAL PRIMARY KEY,
    broadcast_id INTEGER,
    file_id      TEXT,
    file_type    TEXT,
    text_content TEXT
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS user_messages (
    id                 SERIAL PRIMARY KEY,
    user_id            INTEGER,
    username           TEXT,
    first_name         TEXT,
    message_id         TEXT UNIQUE,
    sent_at            TEXT,
    status             TEXT DEFAULT 'unread',
    viewed_at          TEXT,
    recipient_admin_id INTEGER,
    recipient_is_super INTEGER DEFAULT 0
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS user_message_files (
    id           SERIAL PRIMARY KEY,
    message_id   TEXT,
    file_id      TEXT,
    file_type    TEXT,
    text_content TEXT
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS banned_users (
    id        SERIAL PRIMARY KEY,
    user_id   INTEGER UNIQUE,
    username  TEXT,
    reason    TEXT,
    banned_at TEXT,
    banned_by INTEGER
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS polls (
    id          SERIAL PRIMARY KEY,
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
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS poll_votes (
    id       SERIAL PRIMARY KEY,
    poll_id  INTEGER,
    user_id  INTEGER,
    choice   TEXT,
    voted_at TEXT,
    UNIQUE(poll_id, user_id)
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS quotes (
    id        SERIAL PRIMARY KEY,
    text      TEXT,
    author    TEXT,
    added_by  INTEGER,
    added_at  TEXT,
    last_sent TEXT
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS trending (
    id         SERIAL PRIMARY KEY,
    folder_id  INTEGER,
    label      TEXT,
    added_by   INTEGER,
    added_at   TEXT,
    expires_at TEXT,
    sort_order INTEGER DEFAULT 0
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS bot_settings (
    key   TEXT PRIMARY KEY,
    value TEXT
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS link_access_log (
    id          SERIAL PRIMARY KEY,
    link_id     INTEGER,
    folder_id   INTEGER,
    user_id     INTEGER,
    username    TEXT,
    accessed_at TEXT
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS message_replies (
    id            SERIAL PRIMARY KEY,
    reply_id      TEXT UNIQUE,
    message_id    TEXT,
    from_admin_id INTEGER,
    to_user_id    INTEGER,
    content       TEXT,
    sent_at       TEXT,
    status        TEXT DEFAULT 'unread'
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS message_reply_files (
    id           SERIAL PRIMARY KEY,
    reply_id     TEXT,
    file_id      TEXT,
    file_type    TEXT,
    text_content TEXT
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS shortened_links (
    id           SERIAL PRIMARY KEY,
    short_code   TEXT UNIQUE,
    original_url TEXT,
    created_by   INTEGER,
    created_at   TEXT,
    clicks       INTEGER DEFAULT 0
)
""")

# Indexes
for idx_sql in [
    "CREATE INDEX IF NOT EXISTS idx_folder_name     ON folders(name)",
    "CREATE INDEX IF NOT EXISTS idx_link_token      ON links(token)",
    "CREATE INDEX IF NOT EXISTS idx_admin_user      ON admins(user_id)",
    "CREATE INDEX IF NOT EXISTS idx_logs_folder     ON logs(folder_id)",
    "CREATE INDEX IF NOT EXISTS idx_subscriber_user ON subscribers(user_id)",
    "CREATE INDEX IF NOT EXISTS idx_broadcast_code  ON broadcasts(broadcast_code)",
    "CREATE INDEX IF NOT EXISTS idx_user_message_id ON user_messages(message_id)",
    "CREATE INDEX IF NOT EXISTS idx_msg_recipient   ON user_messages(recipient_admin_id)",
    "CREATE INDEX IF NOT EXISTS idx_banned_user     ON banned_users(user_id)",
    "CREATE INDEX IF NOT EXISTS idx_poll_votes      ON poll_votes(poll_id, user_id)",
    "CREATE INDEX IF NOT EXISTS idx_trending        ON trending(folder_id)",
    "CREATE INDEX IF NOT EXISTS idx_link_access     ON link_access_log(link_id)",
    "CREATE INDEX IF NOT EXISTS idx_quotes          ON quotes(last_sent)",
    "CREATE INDEX IF NOT EXISTS idx_reply_msg       ON message_replies(message_id)",
    "CREATE INDEX IF NOT EXISTS idx_reply_user      ON message_replies(to_user_id)",
    "CREATE INDEX IF NOT EXISTS idx_reply_files     ON message_reply_files(reply_id)",
    "CREATE INDEX IF NOT EXISTS idx_short_code      ON shortened_links(short_code)",
]:
    try:
        cursor.execute(idx_sql)
    except Exception:
        pass

# Seed super admin
cursor.execute("""
    INSERT INTO admins (user_id, username, added_by, added_at, is_super_admin)
    VALUES (%s, 'Super Admin', %s, %s, 1)
    ON CONFLICT (user_id) DO NOTHING
""", (ADMIN_ID, ADMIN_ID, datetime.now().isoformat()))

conn.commit()
