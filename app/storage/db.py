"""
db.py — 資料庫連線、Schema 定義、自動遷移與平滑相容接口。
"""
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
from app.core.config import settings


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
        # 平滑遷移：為現有資料表補足新欄位
        migrations = [
            ("bot_state", "pending_selection TEXT"),
            ("bot_state", "worker_status TEXT"),
            ("contacts", "nickname TEXT"),
            ("contacts", "full_history_summary TEXT"),
            ("contacts", "full_history_updated_at DATETIME"),
        ]
        for table, col_def in migrations:
            try:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {col_def};")
            except sqlite3.OperationalError:
                pass

        conn.executescript("""
        CREATE TABLE IF NOT EXISTS contacts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ig_account_id TEXT UNIQUE NOT NULL,
            display_name TEXT,
            nickname TEXT,
            relationship_note TEXT,
            status TEXT DEFAULT 'tracked',
            summary_card TEXT,
            summary_updated_at DATETIME,
            full_history_summary TEXT,
            full_history_updated_at DATETIME,
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

        CREATE TABLE IF NOT EXISTS contact_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            contact_id INTEGER NOT NULL REFERENCES contacts(id) ON DELETE CASCADE,
            event_id TEXT,
            content TEXT NOT NULL,
            start_time TEXT,
            end_time TEXT,
            message_count INTEGER DEFAULT 1,
            status TEXT DEFAULT 'raw',
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );

        INSERT OR IGNORE INTO bot_state (id, active_contact_id, pending_selection, worker_status, updated_at)
        VALUES (1, NULL, NULL, NULL, CURRENT_TIMESTAMP);
        """)
    conn.close()


# ==================== 模組層相容輔助函式（底層轉接 Repositories） ====================

def get_active_contact(db_path: Optional[Path] = None) -> Optional[sqlite3.Row]:
    from app.storage.repositories import ContactRepository
    return ContactRepository(db_path).get_active()


def set_active_contact_by_id(contact_id: int, db_path: Optional[Path] = None) -> bool:
    from app.storage.repositories import ContactRepository
    return ContactRepository(db_path).set_active_by_id(contact_id)


def set_active_contact(ig_account_id: str, db_path: Optional[Path] = None) -> bool:
    from app.storage.repositories import ContactRepository
    return ContactRepository(db_path).set_active(ig_account_id)


def search_contacts_fuzzy(query: str, db_path: Optional[Path] = None) -> List[sqlite3.Row]:
    from app.storage.repositories import ContactRepository
    return ContactRepository(db_path).search_fuzzy(query)


def set_pending_selection(candidate_ids: List[int], db_path: Optional[Path] = None) -> None:
    from app.storage.repositories import BotStateRepository
    BotStateRepository(db_path).set_pending_selection(candidate_ids)


def get_pending_selection(db_path: Optional[Path] = None) -> Optional[List[int]]:
    from app.storage.repositories import BotStateRepository
    return BotStateRepository(db_path).get_pending_selection()


def set_worker_status(status_info: Optional[Dict[str, Any]], db_path: Optional[Path] = None) -> None:
    from app.storage.repositories import BotStateRepository
    BotStateRepository(db_path).set_worker_status(status_info)


def get_worker_status(db_path: Optional[Path] = None) -> Optional[Dict[str, Any]]:
    from app.storage.repositories import BotStateRepository
    return BotStateRepository(db_path).get_worker_status()


def get_or_create_contact(
    ig_account_id: str,
    display_name: Optional[str] = None,
    db_path: Optional[Path] = None
) -> int:
    from app.storage.repositories import ContactRepository
    return ContactRepository(db_path).get_or_create(ig_account_id, display_name)


def save_messages(contact_id: int, messages: List[Dict[str, Any]], db_path: Optional[Path] = None) -> int:
    from app.storage.repositories import MessageRepository
    return MessageRepository(db_path).save_messages(contact_id, messages)


def get_recent_messages(contact_id: int, limit: int = 30, db_path: Optional[Path] = None) -> List[sqlite3.Row]:
    from app.storage.repositories import MessageRepository
    return MessageRepository(db_path).get_recent(contact_id, limit)


def add_bot_conversation(role: str, content: str, contact_id: Optional[int] = None, db_path: Optional[Path] = None) -> None:
    from app.storage.repositories import BotStateRepository
    BotStateRepository(db_path).add_conversation(role, content, contact_id)


def get_bot_conversations(contact_id: Optional[int], limit: int = 20, db_path: Optional[Path] = None) -> List[sqlite3.Row]:
    from app.storage.repositories import BotStateRepository
    return BotStateRepository(db_path).get_conversations(contact_id, limit)


def get_contact_by_id(contact_id: int, db_path: Optional[Path] = None) -> Optional[sqlite3.Row]:
    from app.storage.repositories import ContactRepository
    return ContactRepository(db_path).get_by_id(contact_id)


def get_contact_by_username(ig_account_id: str, db_path: Optional[Path] = None) -> Optional[sqlite3.Row]:
    from app.storage.repositories import ContactRepository
    return ContactRepository(db_path).get_by_username(ig_account_id)


def get_latest_message_time(contact_id: int, db_path: Optional[Path] = None) -> Optional[str]:
    from app.storage.repositories import MessageRepository
    return MessageRepository(db_path).get_latest_time(contact_id)


def update_contact_summary(contact_id: int, new_summary: str, db_path: Optional[Path] = None) -> None:
    from app.storage.repositories import ContactRepository
    ContactRepository(db_path).update_summary(contact_id, new_summary)


def update_contact_full_history(contact_id: int, full_summary: str, db_path: Optional[Path] = None) -> None:
    from app.storage.repositories import ContactRepository
    ContactRepository(db_path).update_full_history(contact_id, full_summary)


def should_update_summary(
    contact: Dict[str, Any],
    threshold: Optional[int] = None,
    days_limit: Optional[int] = None
) -> bool:
    thresh = threshold if threshold is not None else settings.SUMMARY_MESSAGE_THRESHOLD
    days_lim = days_limit if days_limit is not None else settings.SUMMARY_DAYS_LIMIT

    new_msgs = contact.get("new_messages_since_summary") or 0
    if new_msgs >= thresh:
        return True

    updated_at_str = contact.get("summary_updated_at")
    if not updated_at_str:
        return False

    try:
        updated_at = datetime.fromisoformat(updated_at_str)
        if (datetime.utcnow() - updated_at).days >= days_lim and new_msgs > 0:
            return True
    except Exception:
        pass

    return False


def get_all_messages(contact_id: int, db_path: Optional[Path] = None) -> List[sqlite3.Row]:
    from app.storage.repositories import MessageRepository
    return MessageRepository(db_path).get_all(contact_id)


def set_contact_nickname(contact_id: int, nickname: Optional[str], db_path: Optional[Path] = None) -> bool:
    from app.storage.repositories import ContactRepository
    return ContactRepository(db_path).set_nickname(contact_id, nickname)


def get_contacts_with_nickname(db_path: Optional[Path] = None) -> List[sqlite3.Row]:
    from app.storage.repositories import ContactRepository
    return ContactRepository(db_path).get_with_nickname()


def save_contact_events(
    contact_id: int,
    events: List[Dict[str, Any]],
    status: str = "raw",
    db_path: Optional[Path] = None
) -> int:
    from app.storage.repositories import EventRepository
    return EventRepository(db_path).save_events(contact_id, events, status=status)


def get_contact_events(
    contact_id: int,
    status: Optional[str] = None,
    db_path: Optional[Path] = None
) -> List[sqlite3.Row]:
    from app.storage.repositories import EventRepository
    return EventRepository(db_path).get_events(contact_id, status=status)


def clear_contact_events(
    contact_id: int,
    status: Optional[str] = None,
    db_path: Optional[Path] = None
) -> None:
    from app.storage.repositories import EventRepository
    EventRepository(db_path).clear_events(contact_id, status=status)

