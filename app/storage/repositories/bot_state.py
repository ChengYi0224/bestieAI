"""
bot_state.py — Bot 狀態、背景任務進度與聊天對話紀錄存取庫。
"""
import json
import sqlite3
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any

from app.storage.repositories.base import BaseRepository, with_connection


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
        conn.execute("UPDATE bot_state SET worker_status = ?, updated_at = ? WHERE id = 1", (val, datetime.now(timezone.utc).isoformat()))

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
