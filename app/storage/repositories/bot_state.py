"""
bot_state.py — Bot 狀態、背景任務進度與聊天對話紀錄存取庫（每位使用者各一份）。

狀態存於 bot_user_state（每位使用者一列），對話紀錄以 bot_conversations.user_id 隔離。
所有方法的 user_id 皆為 keyword-only 必填整數。
"""
import json
import logging
import sqlite3
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any

from app.storage.repositories.base import BaseRepository, with_connection

logger = logging.getLogger("bestieAI.storage.bot_state")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ensure_row(conn: sqlite3.Connection, user_id: int) -> None:
    conn.execute("INSERT OR IGNORE INTO bot_user_state (user_id, updated_at) VALUES (?, ?)", (user_id, _now()))


def _read_json(conn: sqlite3.Connection, user_id: int, column: str) -> Optional[Any]:
    # column 為呼叫端寫死的常數（pending_selection / worker_status），不接受外部輸入
    row = conn.execute(f"SELECT {column} FROM bot_user_state WHERE user_id = ?", (user_id,)).fetchone()
    if row and row[column]:
        try:
            return json.loads(row[column])
        except Exception as e:
            logger.warning(f"{column} JSON 損毀 (user_id={user_id})，視為無資料: {e}")
    return None


class BotStateRepository(BaseRepository):
    """Bot 狀態、背景任務進度與聊天對話紀錄存取庫。"""

    @with_connection(readonly=False)
    def set_pending_selection(self, conn: sqlite3.Connection, candidate_ids: List[int], *, user_id: int) -> None:
        _ensure_row(conn, user_id)
        val = json.dumps(candidate_ids) if candidate_ids else None
        conn.execute("UPDATE bot_user_state SET pending_selection = ? WHERE user_id = ?", (val, user_id))

    @with_connection(readonly=True)
    def get_pending_selection(self, conn: sqlite3.Connection, *, user_id: int) -> Optional[List[int]]:
        return _read_json(conn, user_id, "pending_selection")

    @with_connection(readonly=False)
    def set_worker_status(self, conn: sqlite3.Connection, status_info: Optional[Dict[str, Any]], *, user_id: int) -> None:
        _ensure_row(conn, user_id)
        val = json.dumps(status_info, ensure_ascii=False) if status_info else None
        conn.execute("UPDATE bot_user_state SET worker_status = ?, updated_at = ? WHERE user_id = ?", (val, _now(), user_id))

    @with_connection(readonly=True)
    def get_worker_status(self, conn: sqlite3.Connection, *, user_id: int) -> Optional[Dict[str, Any]]:
        return _read_json(conn, user_id, "worker_status")

    @with_connection(readonly=False)
    def add_conversation(
        self,
        conn: sqlite3.Connection,
        role: str,
        content: str,
        contact_id: Optional[int] = None,
        *,
        user_id: int,
    ) -> None:
        conn.execute("""
            INSERT INTO bot_conversations (user_id, contact_id, role, content)
            VALUES (?, ?, ?, ?)
        """, (user_id, contact_id, role, content))

    @with_connection(readonly=True)
    def get_conversations(
        self,
        conn: sqlite3.Connection,
        contact_id: Optional[int],
        limit: int = 20,
        *,
        user_id: int,
    ) -> List[sqlite3.Row]:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT role, content FROM (
                SELECT role, content, created_at
                FROM bot_conversations
                WHERE user_id = ? AND (contact_id IS ? OR (? IS NULL AND contact_id IS NULL))
                ORDER BY created_at DESC, id DESC
                LIMIT ?
            ) ORDER BY created_at ASC
        """, (user_id, contact_id, contact_id, limit))
        return cursor.fetchall()
