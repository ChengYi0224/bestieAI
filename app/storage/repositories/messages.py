"""
messages.py — 歷史私訊紀錄存取庫。
"""
import sqlite3
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any, Set

from app.storage.repositories.base import BaseRepository, with_connection


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
        """, (inserted, datetime.now(timezone.utc).isoformat(), contact_id))
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

    @with_connection(readonly=True)
    def get_latest_item_ids(self, conn: sqlite3.Connection, contact_id: int, limit: int = 50) -> Set[str]:
        """取得指定聯絡人最新 N 則訊息的外部 ID 集合。"""
        cursor = conn.cursor()
        cursor.execute(
            "SELECT ig_item_id FROM messages WHERE contact_id = ? AND ig_item_id IS NOT NULL ORDER BY sent_at DESC LIMIT ?",
            (contact_id, limit)
        )
        return {str(row["ig_item_id"]) for row in cursor.fetchall() if row["ig_item_id"]}

    @with_connection(readonly=True)
    def get_paginated(
        self,
        conn: sqlite3.Connection,
        contact_id: int,
        limit: int = 50,
        offset: int = 0
    ) -> List[sqlite3.Row]:
        """分頁取得指定聯絡人的歷史私訊，預設依發送時間昇冪排序。"""
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM messages WHERE contact_id = ? ORDER BY sent_at ASC LIMIT ? OFFSET ?",
            (contact_id, limit, offset)
        )
        return cursor.fetchall()

    @with_connection(readonly=True)
    def count_by_contact(self, conn: sqlite3.Connection, contact_id: int) -> int:
        """計算指定聯絡人的歷史私訊總數。"""
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM messages WHERE contact_id = ?", (contact_id,))
        row = cursor.fetchone()
        return row[0] if row else 0
