"""users.py — 使用者帳號資料存取庫。"""
import sqlite3
from typing import Optional, List
from app.storage.repositories.base import BaseRepository, with_connection


class UserRepository(BaseRepository):
    """使用者帳號與身分憑證資料存取庫。"""

    @with_connection(readonly=True)
    def get_by_id(self, conn: sqlite3.Connection, user_id: int) -> Optional[sqlite3.Row]:
        """依系統流水號 user_id 取得使用者。"""
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM users WHERE id = ?", (user_id,))
        return cursor.fetchone()

    @with_connection(readonly=True)
    def get_by_username(self, conn: sqlite3.Connection, username: str) -> Optional[sqlite3.Row]:
        """依使用者帳號不分大小寫查詢。"""
        if not username or not username.strip():
            return None
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM users WHERE LOWER(username) = LOWER(?)", (username.strip(),))
        return cursor.fetchone()

    @with_connection(readonly=True)
    def get_by_email(self, conn: sqlite3.Connection, email: str) -> Optional[sqlite3.Row]:
        """依電子郵件信箱不分大小寫查詢。"""
        if not email or not email.strip():
            return None
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM users WHERE LOWER(email) = LOWER(?)", (email.strip(),))
        return cursor.fetchone()

    @with_connection(readonly=True)
    def get_by_google_sub(self, conn: sqlite3.Connection, google_sub: str) -> Optional[sqlite3.Row]:
        """依 Google 唯一身分識別碼 (sub) 查詢。"""
        if not google_sub or not google_sub.strip():
            return None
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM users WHERE google_sub = ?", (google_sub.strip(),))
        return cursor.fetchone()

    @with_connection(readonly=False)
    def create_user(
        self,
        conn: sqlite3.Connection,
        username: str,
        email: Optional[str] = None,
        password_hash: Optional[str] = None,
        google_sub: Optional[str] = None,
        display_name: Optional[str] = None,
        avatar_url: Optional[str] = None,
    ) -> int:
        """新增使用者帳號並回傳自動生成的 user_id。"""
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO users (username, email, password_hash, google_sub, display_name, avatar_url, status)
            VALUES (?, ?, ?, ?, ?, ?, 'active')
        """, (
            username.strip(),
            email.strip() if email else None,
            password_hash,
            google_sub.strip() if google_sub else None,
            display_name.strip() if display_name else username.strip(),
            avatar_url.strip() if avatar_url else None,
        ))
        return cursor.lastrowid

    @with_connection(readonly=False)
    def link_google_sub(
        self,
        conn: sqlite3.Connection,
        user_id: int,
        google_sub: str,
        avatar_url: Optional[str] = None,
        email: Optional[str] = None,
    ) -> bool:
        """將 Google sub 綁定至指定使用者，並可選擇同步頭像與信箱。"""
        updates = ["google_sub = ?"]
        params = [google_sub.strip()]

        if avatar_url:
            updates.append("avatar_url = COALESCE(avatar_url, ?)")
            params.append(avatar_url.strip())
        if email:
            updates.append("email = COALESCE(email, ?)")
            params.append(email.strip())

        params.append(user_id)
        query = f"UPDATE users SET {', '.join(updates)} WHERE id = ?"
        cursor = conn.cursor()
        cursor.execute(query, tuple(params))
        return cursor.rowcount > 0

    @with_connection(readonly=False)
    def update_password(self, conn: sqlite3.Connection, user_id: int, password_hash: str) -> bool:
        """更新使用者密碼雜湊值。"""
        cursor = conn.cursor()
        cursor.execute("UPDATE users SET password_hash = ? WHERE id = ?", (password_hash, user_id))
        return cursor.rowcount > 0

    @with_connection(readonly=True)
    def list_all(self, conn: sqlite3.Connection) -> List[sqlite3.Row]:
        """列出所有使用者。"""
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM users ORDER BY id ASC")
        return cursor.fetchall()
