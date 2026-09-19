"""
events.py — 事件記憶快取存取庫。
"""
import sqlite3
from typing import Optional, List, Dict, Any

from app.storage.repositories.base import BaseRepository, with_connection


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
