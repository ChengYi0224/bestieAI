"""
repositories.py — 資料存取庫模式 (Repository Pattern) 封裝。

提供乾淨的高階物件導向 CRUD 與語法糖，封裝 SQLite 交易生命週期。
"""
import json
import sqlite3
import functools
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any, Callable

from app.storage.db import get_connection


def with_connection(readonly: bool = False):
    """
    Decorator 語法糖：自動為 Repository 方法注入 connection 與 cursor，並在寫入時自動 commit。
    """
    def decorator(func: Callable):
        @functools.wraps(func)
        def wrapper(self, *args, **kwargs):
            conn = self.get_conn()
            try:
                if readonly:
                    return func(self, conn, *args, **kwargs)
                else:
                    with conn:
                        return func(self, conn, *args, **kwargs)
            finally:
                conn.close()
        return wrapper
    return decorator


class BaseRepository:
    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path

    def get_conn(self) -> sqlite3.Connection:
        return get_connection(self.db_path)


class ContactRepository(BaseRepository):
    """聯絡人與人物設定資料存取庫。"""

    @with_connection(readonly=True)
    def get_by_id(self, conn: sqlite3.Connection, contact_id: int) -> Optional[sqlite3.Row]:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM contacts WHERE id = ?", (contact_id,))
        return cursor.fetchone()

    @with_connection(readonly=True)
    def get_by_username(self, conn: sqlite3.Connection, ig_account_id: str) -> Optional[sqlite3.Row]:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM contacts WHERE ig_account_id = ?", (ig_account_id,))
        return cursor.fetchone()

    @with_connection(readonly=True)
    def get_active(self, conn: sqlite3.Connection) -> Optional[sqlite3.Row]:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT c.* FROM contacts c
            INNER JOIN bot_state s ON c.id = s.active_contact_id
            WHERE s.id = 1
        """)
        return cursor.fetchone()

    @with_connection(readonly=False)
    def set_active(self, conn: sqlite3.Connection, ig_account_id: str) -> bool:
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM contacts WHERE ig_account_id = ?", (ig_account_id,))
        contact = cursor.fetchone()
        if contact:
            cursor.execute("""
                UPDATE bot_state
                SET active_contact_id = ?, pending_selection = NULL, updated_at = ?
                WHERE id = 1
            """, (contact["id"], datetime.utcnow().isoformat()))
            return True
        return False

    @with_connection(readonly=False)
    def set_active_by_id(self, conn: sqlite3.Connection, contact_id: int) -> bool:
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM contacts WHERE id = ?", (contact_id,))
        contact = cursor.fetchone()
        if contact:
            cursor.execute("""
                UPDATE bot_state
                SET active_contact_id = ?, pending_selection = NULL, updated_at = ?
                WHERE id = 1
            """, (contact["id"], datetime.utcnow().isoformat()))
            return True
        return False

    @with_connection(readonly=False)
    def get_or_create(self, conn: sqlite3.Connection, ig_account_id: str, display_name: Optional[str] = None) -> int:
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM contacts WHERE ig_account_id = ?", (ig_account_id,))
        row = cursor.fetchone()
        if row:
            return row["id"]
        name = display_name or ig_account_id
        cursor.execute("""
            INSERT INTO contacts (ig_account_id, display_name, status)
            VALUES (?, ?, 'tracked')
        """, (ig_account_id, name))
        return cursor.lastrowid

    @with_connection(readonly=True)
    def search_fuzzy(self, conn: sqlite3.Connection, query: str) -> List[sqlite3.Row]:
        clean_q = query.strip()
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
        return cursor.fetchall()

    @with_connection(readonly=False)
    def update_summary(self, conn: sqlite3.Connection, contact_id: int, new_summary: Any) -> None:
        summary_str = str(new_summary) if new_summary is not None else ""
        conn.execute("""
            UPDATE contacts
            SET summary_card = ?,
                summary_updated_at = ?,
                new_messages_since_summary = 0
            WHERE id = ?
        """, (summary_str, datetime.utcnow().isoformat(), contact_id))

    @with_connection(readonly=False)
    def update_full_history(self, conn: sqlite3.Connection, contact_id: int, full_summary: Any) -> None:
        full_str = str(full_summary) if full_summary is not None else ""
        conn.execute("""
            UPDATE contacts
            SET full_history_summary = ?,
                full_history_updated_at = ?
            WHERE id = ?
        """, (full_str, datetime.utcnow().isoformat(), contact_id))

    @with_connection(readonly=False)
    def set_nickname(self, conn: sqlite3.Connection, contact_id: int, nickname: Optional[str]) -> bool:
        clean_nick = nickname.strip() if nickname and nickname.strip() else None
        cursor = conn.cursor()
        cursor.execute("UPDATE contacts SET nickname = ? WHERE id = ?", (clean_nick, contact_id))
        return cursor.rowcount > 0

    @with_connection(readonly=True)
    def get_with_nickname(self, conn: sqlite3.Connection) -> List[sqlite3.Row]:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, ig_account_id, display_name, nickname
            FROM contacts
            WHERE nickname IS NOT NULL AND TRIM(nickname) != ''
        """)
        return cursor.fetchall()

    @with_connection(readonly=True)
    def list_all(self, conn: sqlite3.Connection) -> List[sqlite3.Row]:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM contacts ORDER BY id DESC")
        return cursor.fetchall()

    @with_connection(readonly=False)
    def untrack(self, conn: sqlite3.Connection, ig_account_id: str) -> bool:
        cursor = conn.cursor()
        cursor.execute("UPDATE contacts SET status = 'untracked' WHERE ig_account_id = ?", (ig_account_id,))
        return cursor.rowcount > 0


class MessageRepository(BaseRepository):
    """歷史私訊紀錄存取庫。"""

    @with_connection(readonly=False)
    def save_messages(self, conn: sqlite3.Connection, contact_id: int, messages: List[Dict[str, Any]]) -> int:
        cursor = conn.cursor()
        inserted = 0
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
        return inserted

    @with_connection(readonly=True)
    def get_recent(self, conn: sqlite3.Connection, contact_id: int, limit: int = 30) -> List[sqlite3.Row]:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT * FROM (
                SELECT * FROM messages
                WHERE contact_id = ?
                ORDER BY sent_at DESC
                LIMIT ?
            ) ORDER BY sent_at ASC
        """, (contact_id, limit))
        return cursor.fetchall()

    @with_connection(readonly=True)
    def get_all(self, conn: sqlite3.Connection, contact_id: int) -> List[sqlite3.Row]:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM messages WHERE contact_id = ? ORDER BY sent_at ASC",
            (contact_id,)
        )
        return cursor.fetchall()

    @with_connection(readonly=True)
    def get_latest_time(self, conn: sqlite3.Connection, contact_id: int) -> Optional[str]:
        cursor = conn.cursor()
        cursor.execute("SELECT sent_at FROM messages WHERE contact_id = ? ORDER BY sent_at DESC LIMIT 1", (contact_id,))
        row = cursor.fetchone()
        return row["sent_at"] if row else None


class BotStateRepository(BaseRepository):
    """Bot 狀態、背景任務進度與聊天對話紀錄存取庫。"""

    @with_connection(readonly=False)
    def set_pending_selection(self, conn: sqlite3.Connection, candidate_ids: List[int]) -> None:
        val = json.dumps(candidate_ids) if candidate_ids else None
        conn.execute("UPDATE bot_state SET pending_selection = ? WHERE id = 1", (val,))

    @with_connection(readonly=True)
    def get_pending_selection(self, conn: sqlite3.Connection) -> Optional[List[int]]:
        cursor = conn.cursor()
        cursor.execute("SELECT pending_selection FROM bot_state WHERE id = 1")
        row = cursor.fetchone()
        if row and row["pending_selection"]:
            try:
                return json.loads(row["pending_selection"])
            except Exception:
                return None
        return None

    @with_connection(readonly=False)
    def set_worker_status(self, conn: sqlite3.Connection, status_info: Optional[Dict[str, Any]]) -> None:
        val = json.dumps(status_info, ensure_ascii=False) if status_info else None
        conn.execute("UPDATE bot_state SET worker_status = ?, updated_at = ? WHERE id = 1", (val, datetime.utcnow().isoformat()))

    @with_connection(readonly=True)
    def get_worker_status(self, conn: sqlite3.Connection) -> Optional[Dict[str, Any]]:
        cursor = conn.cursor()
        cursor.execute("SELECT worker_status FROM bot_state WHERE id = 1")
        row = cursor.fetchone()
        if row and row["worker_status"]:
            try:
                return json.loads(row["worker_status"])
            except Exception:
                return None
        return None

    @with_connection(readonly=False)
    def add_conversation(self, conn: sqlite3.Connection, role: str, content: str, contact_id: Optional[int] = None) -> None:
        conn.execute("""
            INSERT INTO bot_conversations (contact_id, role, content)
            VALUES (?, ?, ?)
        """, (contact_id, role, content))

    @with_connection(readonly=True)
    def get_conversations(self, conn: sqlite3.Connection, contact_id: Optional[int], limit: int = 20) -> List[sqlite3.Row]:
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
        return cursor.fetchall()


class EventRepository(BaseRepository):
    """事件記憶快取存取庫（儲存 LLM 提煉後的事件條目，避免重複消耗額度）。"""

    @with_connection(readonly=False)
    def save_events(
        self,
        conn: sqlite3.Connection,
        contact_id: int,
        events: List[Dict[str, Any]],
        status: str = "raw"
    ) -> int:
        if not events:
            return 0
        rows = []
        for e in events:
            rows.append((
                contact_id,
                e.get("id"),
                e.get("text") or e.get("content", ""),
                e.get("start_time"),
                e.get("end_time"),
                e.get("message_count", 1),
                status
            ))
        conn.executemany("""
            INSERT INTO contact_events (contact_id, event_id, content, start_time, end_time, message_count, status)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, rows)
        return len(rows)

    @with_connection(readonly=True)
    def get_events(
        self,
        conn: sqlite3.Connection,
        contact_id: int,
        status: Optional[str] = None
    ) -> List[sqlite3.Row]:
        cursor = conn.cursor()
        if status:
            cursor.execute("""
                SELECT * FROM contact_events
                WHERE contact_id = ? AND status = ?
                ORDER BY start_time ASC, id ASC
            """, (contact_id, status))
        else:
            cursor.execute("""
                SELECT * FROM contact_events
                WHERE contact_id = ?
                ORDER BY start_time ASC, id ASC
            """, (contact_id,))
        return cursor.fetchall()

    @with_connection(readonly=False)
    def clear_events(
        self,
        conn: sqlite3.Connection,
        contact_id: int,
        status: Optional[str] = None
    ) -> None:
        if status:
            conn.execute("DELETE FROM contact_events WHERE contact_id = ? AND status = ?", (contact_id, status))
        else:
            conn.execute("DELETE FROM contact_events WHERE contact_id = ?", (contact_id,))

