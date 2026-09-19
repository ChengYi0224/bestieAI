"""
contacts.py — 聯絡人與人物設定資料存取庫。
"""
import sqlite3
from datetime import datetime, timezone
from typing import Optional, List, Any

from app.storage.repositories.base import BaseRepository, with_connection


class ContactRepository(BaseRepository):
    """聯絡人與人物設定資料存取庫。"""

    @with_connection(readonly=True)
    def get_by_id(self, conn: sqlite3.Connection, contact_id: int, user_id: Optional[int] = None) -> Optional[sqlite3.Row]:
        cursor = conn.cursor()
        if user_id is not None:
            cursor.execute("SELECT * FROM contacts WHERE id = ? AND user_id = ?", (contact_id, user_id))
        else:
            cursor.execute("SELECT * FROM contacts WHERE id = ?", (contact_id,))
        return cursor.fetchone()

    @with_connection(readonly=True)
    def get_by_username(self, conn: sqlite3.Connection, ig_account_id: str, user_id: Optional[int] = None) -> Optional[sqlite3.Row]:
        cursor = conn.cursor()
        if user_id is not None:
            cursor.execute("SELECT * FROM contacts WHERE ig_account_id = ? AND user_id = ?", (ig_account_id, user_id))
        else:
            cursor.execute("SELECT * FROM contacts WHERE ig_account_id = ?", (ig_account_id,))
        return cursor.fetchone()

    @with_connection(readonly=True)
    def find_by_identifier(self, conn: sqlite3.Connection, identifier: str, user_id: Optional[int] = None) -> Optional[sqlite3.Row]:
        """依 IG 帳號、顯示名稱或暱稱不分大小寫精確匹配單一聯絡人。"""
        if not identifier or not identifier.strip():
            return None
        clean_id = identifier.strip()
        cursor = conn.cursor()
        if user_id is not None:
            cursor.execute("""
                SELECT * FROM contacts
                WHERE (LOWER(ig_account_id) = LOWER(?)
                   OR LOWER(display_name) = LOWER(?)
                   OR LOWER(nickname) = LOWER(?))
                   AND user_id = ?
                LIMIT 1
            """, (clean_id, clean_id, clean_id, user_id))
        else:
            cursor.execute("""
                SELECT * FROM contacts
                WHERE LOWER(ig_account_id) = LOWER(?)
                   OR LOWER(display_name) = LOWER(?)
                   OR LOWER(nickname) = LOWER(?)
                LIMIT 1
            """, (clean_id, clean_id, clean_id))
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
            """, (contact["id"], datetime.now(timezone.utc).isoformat()))
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
            """, (contact["id"], datetime.now(timezone.utc).isoformat()))
            return True
        return False

    @with_connection(readonly=False)
    def get_or_create(self, conn: sqlite3.Connection, ig_account_id: str, display_name: Optional[str] = None, user_id: int = 1) -> int:
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM contacts WHERE ig_account_id = ? AND user_id = ?", (ig_account_id, user_id))
        row = cursor.fetchone()
        if row:
            return row["id"]
        name = display_name or ig_account_id
        cursor.execute("""
            INSERT INTO contacts (user_id, ig_account_id, display_name, status)
            VALUES (?, ?, ?, 'tracked')
        """, (user_id, ig_account_id, name))
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
        """, (summary_str, datetime.now(timezone.utc).isoformat(), contact_id))

    @with_connection(readonly=False)
    def update_full_history(self, conn: sqlite3.Connection, contact_id: int, full_summary: Any) -> None:
        full_str = str(full_summary) if full_summary is not None else ""
        conn.execute("""
            UPDATE contacts
            SET full_history_summary = ?,
                full_history_updated_at = ?
            WHERE id = ?
        """, (full_str, datetime.now(timezone.utc).isoformat(), contact_id))

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
    def list_all(
        self,
        conn: sqlite3.Connection,
        status: Optional[str] = None,
        user_id: Optional[int] = None,
    ) -> List[sqlite3.Row]:
        cursor = conn.cursor()
        conditions = []
        params = []
        if user_id is not None:
            conditions.append("user_id = ?")
            params.append(user_id)
        if status:
            conditions.append("status = ?")
            params.append(status)
        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        cursor.execute(f"SELECT * FROM contacts {where_clause} ORDER BY id DESC", tuple(params))
        return cursor.fetchall()

    @with_connection(readonly=False)
    def update_details(
        self,
        conn: sqlite3.Connection,
        contact_id: int,
        nickname: Optional[str] = None,
        relationship_note: Optional[str] = None,
        update_nickname: bool = False,
        update_note: bool = False,
        user_id: Optional[int] = None,
    ) -> Optional[sqlite3.Row]:
        """更新指定聯絡人之暱稱與關係備註，並回傳更新後的資料。"""
        updates = []
        params = []
        if update_nickname:
            clean_nick = nickname.strip() if (nickname and nickname.strip()) else None
            updates.append("nickname = ?")
            params.append(clean_nick)
        if update_note:
            clean_note = relationship_note.strip() if (relationship_note and relationship_note.strip()) else None
            updates.append("relationship_note = ?")
            params.append(clean_note)

        where_clauses = ["id = ?"]
        where_params = [contact_id]
        if user_id is not None:
            where_clauses.append("user_id = ?")
            where_params.append(user_id)

        if updates:
            query = f"UPDATE contacts SET {', '.join(updates)} WHERE {' AND '.join(where_clauses)}"
            cursor = conn.cursor()
            cursor.execute(query, tuple(params + where_params))
            if cursor.rowcount == 0:
                return None

        cursor = conn.cursor()
        cursor.execute(f"SELECT * FROM contacts WHERE {' AND '.join(where_clauses)}", tuple(where_params))
        return cursor.fetchone()

    @with_connection(readonly=True)
    def get_tracked_contacts(self, conn: sqlite3.Connection, user_id: Optional[int] = None) -> List[sqlite3.Row]:
        """取得所有追蹤中（status = 'tracked'）的聯絡人。"""
        cursor = conn.cursor()
        if user_id is not None:
            cursor.execute("SELECT id, ig_account_id, display_name FROM contacts WHERE status = 'tracked' AND user_id = ?", (user_id,))
        else:
            cursor.execute("SELECT id, ig_account_id, display_name FROM contacts WHERE status = 'tracked'")
        return cursor.fetchall()

    @with_connection(readonly=False)
    def untrack(self, conn: sqlite3.Connection, ig_account_id: str, user_id: Optional[int] = None) -> bool:
        cursor = conn.cursor()
        if user_id is not None:
            cursor.execute("UPDATE contacts SET status = 'untracked' WHERE ig_account_id = ? AND user_id = ?", (ig_account_id, user_id))
        else:
            cursor.execute("UPDATE contacts SET status = 'untracked' WHERE ig_account_id = ?", (ig_account_id,))
        return cursor.rowcount > 0
