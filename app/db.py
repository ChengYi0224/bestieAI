import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
from app.config import settings


def get_connection(db_path: Optional[Path] = None) -> sqlite3.Connection:
    path = db_path or settings.DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def init_db(db_path: Optional[Path] = None) -> None:
    conn = get_connection(db_path)
    with conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS contacts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ig_account_id TEXT UNIQUE NOT NULL,
            display_name TEXT,
            relationship_note TEXT,
            status TEXT DEFAULT 'tracked',
            summary_card TEXT,
            summary_updated_at DATETIME,
            new_messages_since_summary INTEGER DEFAULT 0,
            last_synced_at DATETIME
        );

        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            contact_id INTEGER NOT NULL REFERENCES contacts(id) ON DELETE CASCADE,
            ig_item_id TEXT UNIQUE NOT NULL,
            sender TEXT NOT NULL,
            content TEXT NOT NULL,
            sent_at DATETIME NOT NULL,
            ingested_to_vector_store BOOLEAN DEFAULT 0,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS bot_state (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            active_contact_id INTEGER REFERENCES contacts(id) ON DELETE SET NULL,
            updated_at DATETIME
        );

        CREATE TABLE IF NOT EXISTS bot_conversations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            contact_id INTEGER REFERENCES contacts(id) ON DELETE SET NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );

        INSERT OR IGNORE INTO bot_state (id, active_contact_id, updated_at)
        VALUES (1, NULL, CURRENT_TIMESTAMP);
        """)
    conn.close()


def get_active_contact(db_path: Optional[Path] = None) -> Optional[sqlite3.Row]:
    conn = get_connection(db_path)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT c.* FROM contacts c
        INNER JOIN bot_state s ON c.id = s.active_contact_id
        WHERE s.id = 1
    """)
    row = cursor.fetchone()
    conn.close()
    return row


def set_active_contact(ig_account_id: str, db_path: Optional[Path] = None) -> bool:
    conn = get_connection(db_path)
    found = False
    try:
        with conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id FROM contacts WHERE ig_account_id = ?", (ig_account_id,))
            contact = cursor.fetchone()
            if contact:
                found = True
                cursor.execute("""
                    UPDATE bot_state
                    SET active_contact_id = ?, updated_at = ?
                    WHERE id = 1
                """, (contact["id"], datetime.utcnow().isoformat()))
    finally:
        conn.close()
    return found


def get_or_create_contact(
    ig_account_id: str,
    display_name: Optional[str] = None,
    db_path: Optional[Path] = None
) -> int:
    conn = get_connection(db_path)
    with conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM contacts WHERE ig_account_id = ?", (ig_account_id,))
        row = cursor.fetchone()
        if row:
            contact_id = row["id"]
        else:
            name = display_name or ig_account_id
            cursor.execute("""
                INSERT INTO contacts (ig_account_id, display_name, status)
                VALUES (?, ?, 'tracked')
            """, (ig_account_id, name))
            contact_id = cursor.lastrowid
    conn.close()
    return contact_id


def save_messages(contact_id: int, messages: List[Dict[str, Any]], db_path: Optional[Path] = None) -> int:
    conn = get_connection(db_path)
    inserted = 0
    with conn:
        cursor = conn.cursor()
        for msg in messages:
            try:
                cursor.execute("""
                    INSERT INTO messages (contact_id, ig_item_id, sender, content, sent_at, ingested_to_vector_store)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (
                    contact_id,
                    msg["ig_item_id"],
                    msg["sender"],
                    msg["content"],
                    msg["sent_at"],
                    msg.get("ingested_to_vector_store", False)
                ))
                inserted += 1
            except sqlite3.IntegrityError:
                continue
        cursor.execute("""
            UPDATE contacts
            SET new_messages_since_summary = new_messages_since_summary + ?,
                last_synced_at = ?
            WHERE id = ?
        """, (inserted, datetime.utcnow().isoformat(), contact_id))
    conn.close()
    return inserted


def get_recent_messages(contact_id: int, limit: int = 30, db_path: Optional[Path] = None) -> List[sqlite3.Row]:
    conn = get_connection(db_path)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT * FROM (
            SELECT * FROM messages
            WHERE contact_id = ?
            ORDER BY sent_at DESC
            LIMIT ?
        ) ORDER BY sent_at ASC
    """, (contact_id, limit))
    rows = cursor.fetchall()
    conn.close()
    return rows


def add_bot_conversation(role: str, content: str, contact_id: Optional[int] = None, db_path: Optional[Path] = None) -> None:
    conn = get_connection(db_path)
    with conn:
        conn.execute("""
            INSERT INTO bot_conversations (contact_id, role, content)
            VALUES (?, ?, ?)
        """, (contact_id, role, content))
    conn.close()
