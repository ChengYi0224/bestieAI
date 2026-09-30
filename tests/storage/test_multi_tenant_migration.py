import sqlite3

from app.storage.db import init_db

LEGACY_SCHEMA = """
CREATE TABLE users (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE NOT NULL, email TEXT UNIQUE,
    password_hash TEXT, google_sub TEXT UNIQUE, ig_pk TEXT UNIQUE, ig_username TEXT, ig_session TEXT,
    display_name TEXT, avatar_url TEXT, status TEXT DEFAULT 'active', created_at DATETIME DEFAULT CURRENT_TIMESTAMP);
INSERT INTO users (id, username) VALUES (1, 'owner');
CREATE TABLE contacts (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER DEFAULT 1 REFERENCES users(id),
    ig_account_id TEXT UNIQUE NOT NULL, display_name TEXT, nickname TEXT, relationship_note TEXT,
    status TEXT DEFAULT 'tracked', summary_card TEXT, summary_updated_at DATETIME, full_history_summary TEXT,
    full_history_updated_at DATETIME, new_messages_since_summary INTEGER DEFAULT 0, last_synced_at DATETIME);
CREATE TABLE messages (id INTEGER PRIMARY KEY AUTOINCREMENT, contact_id INTEGER NOT NULL REFERENCES contacts(id) ON DELETE CASCADE,
    ig_item_id TEXT UNIQUE NOT NULL, sender TEXT NOT NULL, content TEXT NOT NULL, sent_at DATETIME NOT NULL,
    ingested_to_vector_store BOOLEAN DEFAULT 0, created_at DATETIME DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE bot_state (id INTEGER PRIMARY KEY CHECK (id = 1), active_contact_id INTEGER REFERENCES contacts(id) ON DELETE SET NULL,
    pending_selection TEXT, worker_status TEXT, updated_at DATETIME);
CREATE TABLE bot_conversations (id INTEGER PRIMARY KEY AUTOINCREMENT, contact_id INTEGER REFERENCES contacts(id) ON DELETE SET NULL,
    role TEXT NOT NULL, content TEXT NOT NULL, created_at DATETIME DEFAULT CURRENT_TIMESTAMP);
INSERT INTO contacts (id, user_id, ig_account_id, display_name) VALUES (7, 1, 'alice', 'Alice');
INSERT INTO messages (contact_id, ig_item_id, sender, content, sent_at) VALUES (7, 'm1', 'them', 'hi', '2026-01-01T00:00:00');
INSERT INTO bot_state (id, active_contact_id, pending_selection) VALUES (1, 7, '[7]');
INSERT INTO bot_conversations (contact_id, role, content) VALUES (7, 'user', 'q'), (NULL, 'user', 'general');
"""


def _legacy_db(tmp_path):
    db = tmp_path / "legacy.db"
    conn = sqlite3.connect(db)
    conn.executescript(LEGACY_SCHEMA)
    conn.close()
    return db


def test_legacy_db_is_migrated_without_data_loss(tmp_path):
    db = _legacy_db(tmp_path)
    init_db(db_path=db)
    init_db(db_path=db)  # 冪等

    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    assert conn.execute("SELECT id, ig_account_id FROM contacts").fetchall()[0]["id"] == 7
    assert conn.execute("SELECT COUNT(*) FROM messages WHERE contact_id = 7").fetchone()[0] == 1

    state = conn.execute("SELECT * FROM bot_user_state WHERE user_id = 1").fetchone()
    assert state["active_contact_id"] == 7 and state["pending_selection"] == "[7]"

    users = [r["user_id"] for r in conn.execute("SELECT user_id FROM bot_conversations ORDER BY id")]
    assert users == [1, 1]
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    conn.close()


def test_two_users_can_track_same_account_and_share_message_ids(tmp_path):
    db = _legacy_db(tmp_path)
    init_db(db_path=db)

    conn = sqlite3.connect(db)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("INSERT INTO users (id, username) VALUES (2, 'friend')")
    # 同一個 IG 帳號可被不同使用者各自追蹤
    conn.execute("INSERT INTO contacts (id, user_id, ig_account_id) VALUES (8, 2, 'alice')")
    # 同一串私訊的同一個 item_id 可存在於不同使用者的聯絡人之下
    conn.execute("INSERT INTO messages (contact_id, ig_item_id, sender, content, sent_at) VALUES (8, 'm1', 'them', 'hi', '2026-01-01T00:00:00')")
    conn.commit()

    # 同一使用者內仍不可重複
    import pytest
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO contacts (user_id, ig_account_id) VALUES (2, 'alice')")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO messages (contact_id, ig_item_id, sender, content, sent_at) VALUES (8, 'm1', 'them', 'x', '2026-01-01T00:00:00')")
    conn.close()


def test_fresh_db_has_tenant_aware_constraints(tmp_path):
    db = tmp_path / "fresh.db"
    init_db(db_path=db)
    conn = sqlite3.connect(db)
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "bot_user_state" in tables
    cols = {r[1] for r in conn.execute("PRAGMA table_info(bot_conversations)")}
    assert "user_id" in cols
    conn.execute("INSERT INTO users (id, username) VALUES (2, 'f')")
    conn.execute("INSERT INTO contacts (user_id, ig_account_id) VALUES (1, 'x'), (2, 'x')")
    conn.close()
