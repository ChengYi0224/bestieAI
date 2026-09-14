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
        # 平滑遷移：為現有 bot_state 補足 pending_selection 與 worker_status 欄位
        try:
            conn.execute("ALTER TABLE bot_state ADD COLUMN pending_selection TEXT;")
        except sqlite3.OperationalError:
            pass
        try:
            conn.execute("ALTER TABLE bot_state ADD COLUMN worker_status TEXT;")
        except sqlite3.OperationalError:
            pass

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
            pending_selection TEXT,
            worker_status TEXT,
            updated_at DATETIME
        );

        CREATE TABLE IF NOT EXISTS bot_conversations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            contact_id INTEGER REFERENCES contacts(id) ON DELETE SET NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );

        INSERT OR IGNORE INTO bot_state (id, active_contact_id, pending_selection, worker_status, updated_at)
        VALUES (1, NULL, NULL, NULL, CURRENT_TIMESTAMP);
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


def set_active_contact_by_id(contact_id: int, db_path: Optional[Path] = None) -> bool:
    conn = get_connection(db_path)
    found = False
    try:
        with conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id FROM contacts WHERE id = ?", (contact_id,))
            contact = cursor.fetchone()
            if contact:
                found = True
                cursor.execute("""
                    UPDATE bot_state
                    SET active_contact_id = ?, pending_selection = NULL, updated_at = ?
                    WHERE id = 1
                """, (contact["id"], datetime.utcnow().isoformat()))
    finally:
        conn.close()
    return found


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
                    SET active_contact_id = ?, pending_selection = NULL, updated_at = ?
                    WHERE id = 1
                """, (contact["id"], datetime.utcnow().isoformat()))
    finally:
        conn.close()
    return found


def search_contacts_fuzzy(query: str, db_path: Optional[Path] = None) -> List[sqlite3.Row]:
    """
    支援大小寫不敏感的模糊比對（比對 ig_account_id 或 display_name）。
    若有完全相等的結果，優先排在第一位。
    """
    clean_q = query.strip()
    conn = get_connection(db_path)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT * FROM contacts
        WHERE ig_account_id LIKE ? OR display_name LIKE ?
        ORDER BY
            CASE WHEN LOWER(ig_account_id) = LOWER(?) THEN 0
                 WHEN LOWER(display_name) = LOWER(?) THEN 1
                 ELSE 2 END,
            id DESC
    """, (f"%{clean_q}%", f"%{clean_q}%", clean_q, clean_q))
    rows = cursor.fetchall()
    conn.close()
    return rows


def set_pending_selection(candidate_ids: List[int], db_path: Optional[Path] = None) -> None:
    """暫存多重搜尋結果的 contact_id 清單 (以逗號分隔)。"""
    import json
    val = json.dumps(candidate_ids) if candidate_ids else None
    conn = get_connection(db_path)
    with conn:
        conn.execute("UPDATE bot_state SET pending_selection = ? WHERE id = 1", (val,))
    conn.close()


def get_pending_selection(db_path: Optional[Path] = None) -> Optional[List[int]]:
    """讀取當前暫存的候選對象清單。"""
    import json
    conn = get_connection(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT pending_selection FROM bot_state WHERE id = 1")
    row = cursor.fetchone()
    conn.close()
    if row and row["pending_selection"]:
        try:
            return json.loads(row["pending_selection"])
        except Exception:
            return None
    return None


def set_worker_status(status_info: Optional[Dict[str, Any]], db_path: Optional[Path] = None) -> None:
    """儲存或清除背景工作（如全量爬取）的即時進度狀態。"""
    import json
    val = json.dumps(status_info, ensure_ascii=False) if status_info else None
    conn = get_connection(db_path)
    with conn:
        conn.execute("UPDATE bot_state SET worker_status = ?, updated_at = ? WHERE id = 1", (val, datetime.utcnow().isoformat()))
    conn.close()


def get_worker_status(db_path: Optional[Path] = None) -> Optional[Dict[str, Any]]:
    """讀取當前正在運行的背景工作進度狀態。"""
    import json
    conn = get_connection(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT worker_status FROM bot_state WHERE id = 1")
    row = cursor.fetchone()
    conn.close()
    if row and row["worker_status"]:
        try:
            return json.loads(row["worker_status"])
        except Exception:
            return None
    return None


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


def get_bot_conversations(contact_id: Optional[int], limit: int = 20, db_path: Optional[Path] = None) -> List[sqlite3.Row]:
    """取最近 limit 筆 bot 對話紀錄（user/assistant 各算一筆），依時間正序回傳。"""
    conn = get_connection(db_path)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT role, content FROM (
            SELECT role, content, created_at
            FROM bot_conversations
            WHERE contact_id IS ? OR (? IS NULL AND contact_id IS NULL)
            ORDER BY created_at DESC
            LIMIT ?
        ) ORDER BY created_at ASC
    """, (contact_id, contact_id, limit))
    rows = cursor.fetchall()
    conn.close()
    return rows


def get_contact_by_id(contact_id: int, db_path: Optional[Path] = None) -> Optional[sqlite3.Row]:
    conn = get_connection(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM contacts WHERE id = ?", (contact_id,))
    row = cursor.fetchone()
    conn.close()
    return row


def get_contact_by_username(ig_account_id: str, db_path: Optional[Path] = None) -> Optional[sqlite3.Row]:
    conn = get_connection(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM contacts WHERE ig_account_id = ?", (ig_account_id,))
    row = cursor.fetchone()
    conn.close()
    return row


def get_latest_message_time(contact_id: int, db_path: Optional[Path] = None) -> Optional[str]:
    conn = get_connection(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT sent_at FROM messages WHERE contact_id = ? ORDER BY sent_at DESC LIMIT 1", (contact_id,))
    row = cursor.fetchone()
    conn.close()
    return row["sent_at"] if row else None


def update_contact_summary(contact_id: int, new_summary: str, db_path: Optional[Path] = None) -> None:
    conn = get_connection(db_path)
    with conn:
        conn.execute("""
            UPDATE contacts
            SET summary_card = ?,
                summary_updated_at = ?,
                new_messages_since_summary = 0
            WHERE id = ?
        """, (new_summary, datetime.utcnow().isoformat(), contact_id))
    conn.close()


def should_update_summary(contact: Dict[str, Any], threshold: int = 50, days_limit: int = 14) -> bool:
    new_msgs = contact.get("new_messages_since_summary") or 0
    if new_msgs >= threshold:
        return True

    updated_at_str = contact.get("summary_updated_at")
    if not updated_at_str:
        return False

    try:
        updated_at = datetime.fromisoformat(updated_at_str)
        if (datetime.utcnow() - updated_at).days >= days_limit and new_msgs > 0:
            return True
    except Exception:
        pass

    return False


def get_all_messages(contact_id: int, db_path: Optional[Path] = None) -> List[sqlite3.Row]:
    """回傳該對象所有訊息（按時間升冪），供 rebuild_vectors 重建向量庫使用。"""
    conn = get_connection(db_path)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT * FROM messages WHERE contact_id = ? ORDER BY sent_at ASC",
        (contact_id,)
    )
    rows = cursor.fetchall()
    conn.close()
    return rows
