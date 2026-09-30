"""
contacts.py — 聯絡人與人物設定資料存取庫。
"""
import sqlite3
from datetime import datetime, timezone
from typing import Optional, List, Any

from app.storage.repositories.base import BaseRepository, with_connection
from app.storage.scope import ALL_USERS, UserScope, scope_clause as _scope  # noqa: F401


class ContactRepository(BaseRepository):
    """聯絡人與人物設定資料存取庫。"""

    @with_connection(readonly=True)
    def get_by_id(self, conn: sqlite3.Connection, contact_id: int, *, user_id: UserScope) -> Optional[sqlite3.Row]:
        cond, params = _scope(user_id)
        cursor = conn.cursor()
        cursor.execute(f"SELECT * FROM contacts WHERE id = ? AND {cond}", (contact_id, *params))
        return cursor.fetchone()

    @with_connection(readonly=True)
    def get_by_username(self, conn: sqlite3.Connection, ig_account_id: str, *, user_id: UserScope) -> Optional[sqlite3.Row]:
        cond, params = _scope(user_id)
        cursor = conn.cursor()
        cursor.execute(f"SELECT * FROM contacts WHERE ig_account_id = ? AND {cond}", (ig_account_id, *params))
        return cursor.fetchone()

    @with_connection(readonly=True)
    def find_by_identifier(self, conn: sqlite3.Connection, identifier: str, *, user_id: UserScope) -> Optional[sqlite3.Row]:
        """依 IG 帳號、顯示名稱或暱稱不分大小寫精確匹配單一聯絡人。"""
        if not identifier or not identifier.strip():
            return None
        clean_id = identifier.strip()
        cond, params = _scope(user_id)
        cursor = conn.cursor()
        cursor.execute(f"""
            SELECT * FROM contacts
            WHERE (LOWER(ig_account_id) = LOWER(?)
               OR LOWER(display_name) = LOWER(?)
               OR LOWER(nickname) = LOWER(?))
               AND {cond}
            LIMIT 1
        """, (clean_id, clean_id, clean_id, *params))
        return cursor.fetchone()

    @with_connection(readonly=True)
    def get_active(self, conn: sqlite3.Connection, *, user_id: int) -> Optional[sqlite3.Row]:
        """取得指定使用者目前的作用對象（僅限屬於該使用者的聯絡人）。"""
        cursor = conn.cursor()
        cursor.execute("""
            SELECT c.* FROM contacts c
            INNER JOIN bot_user_state s ON c.id = s.active_contact_id
            WHERE s.user_id = ? AND c.user_id = ?
        """, (user_id, user_id))
        return cursor.fetchone()

    def _activate(self, conn: sqlite3.Connection, contact_id: int, user_id: int) -> None:
        now = datetime.now(timezone.utc).isoformat()
        conn.execute("INSERT OR IGNORE INTO bot_user_state (user_id, updated_at) VALUES (?, ?)", (user_id, now))
        conn.execute("""
            UPDATE bot_user_state
            SET active_contact_id = ?, pending_selection = NULL, updated_at = ?
            WHERE user_id = ?
        """, (contact_id, now, user_id))

    @with_connection(readonly=False)
    def set_active(self, conn: sqlite3.Connection, ig_account_id: str, *, user_id: int) -> bool:
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM contacts WHERE ig_account_id = ? AND user_id = ?", (ig_account_id, user_id))
        contact = cursor.fetchone()
        if not contact:
            return False
        self._activate(conn, contact["id"], user_id)
        return True

    @with_connection(readonly=False)
    def set_active_by_id(self, conn: sqlite3.Connection, contact_id: int, *, user_id: int) -> bool:
        """僅能將屬於該使用者的聯絡人設為作用對象，避免切換到他人的聯絡人。"""
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM contacts WHERE id = ? AND user_id = ?", (contact_id, user_id))
        contact = cursor.fetchone()
        if not contact:
            return False
        self._activate(conn, contact["id"], user_id)
        return True

    @with_connection(readonly=False)
    def get_or_create(self, conn: sqlite3.Connection, ig_account_id: str, display_name: Optional[str] = None, *, user_id: int) -> int:
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
    def search_fuzzy(self, conn: sqlite3.Connection, query: str, *, user_id: UserScope) -> List[sqlite3.Row]:
        clean_q = query.strip()
        cond, params = _scope(user_id)
        cursor = conn.cursor()
        cursor.execute(f"""
            SELECT * FROM contacts
            WHERE (ig_account_id LIKE ? OR display_name LIKE ?) AND {cond}
            ORDER BY
                CASE WHEN LOWER(ig_account_id) = LOWER(?) THEN 0
                     WHEN LOWER(display_name) = LOWER(?) THEN 1
                     ELSE 2 END,
                id DESC
        """, (f"%{clean_q}%", f"%{clean_q}%", *params, clean_q, clean_q))
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
    def get_with_nickname(self, conn: sqlite3.Connection, *, user_id: UserScope) -> List[sqlite3.Row]:
        cond, params = _scope(user_id)
        cursor = conn.cursor()
        cursor.execute(f"""
            SELECT id, ig_account_id, display_name, nickname
            FROM contacts
            WHERE nickname IS NOT NULL AND TRIM(nickname) != '' AND {cond}
        """, params)
        return cursor.fetchall()

    @with_connection(readonly=True)
    def list_all(
        self,
        conn: sqlite3.Connection,
        status: Optional[str] = None,
        *,
        user_id: UserScope,
    ) -> List[sqlite3.Row]:
        cond, params = _scope(user_id)
        conditions = [cond]
        params = list(params)
        if status:
            conditions.append("status = ?")
            params.append(status)
        cursor = conn.cursor()
        cursor.execute(f"SELECT * FROM contacts WHERE {' AND '.join(conditions)} ORDER BY id DESC", tuple(params))
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
        *,
        user_id: UserScope,
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

        scope_cond, scope_params = _scope(user_id)
        where_clauses = ["id = ?", scope_cond]
        where_params = [contact_id, *scope_params]

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
    def get_tracked_contacts(self, conn: sqlite3.Connection, *, user_id: UserScope) -> List[sqlite3.Row]:
        """取得所有追蹤中（status = 'tracked'）的聯絡人。"""
        cond, params = _scope(user_id)
        cursor = conn.cursor()
        cursor.execute(f"SELECT id, user_id, ig_account_id, display_name FROM contacts WHERE status = 'tracked' AND {cond}", params)
        return cursor.fetchall()

    @with_connection(readonly=False)
    def untrack(self, conn: sqlite3.Connection, ig_account_id: str, *, user_id: UserScope) -> bool:
        cond, params = _scope(user_id)
        cursor = conn.cursor()
        cursor.execute(f"UPDATE contacts SET status = 'untracked' WHERE ig_account_id = ? AND {cond}", (ig_account_id, *params))
        return cursor.rowcount > 0
