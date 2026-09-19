"""contact_api_service.py — 聯絡人管理業務邏輯服務。"""
import sqlite3
from typing import Optional
from app.storage.repositories.contacts import ContactRepository


class ContactApiService:
    """提供聯絡人查詢與更新業務邏輯服務。"""

    def __init__(self, contact_repo: ContactRepository):
        self.contact_repo = contact_repo

    def list_contacts(self, status: Optional[str] = None, user_id: Optional[int] = None) -> list[sqlite3.Row]:
        """取得聯絡人清單，支援狀態篩選與使用者隔離。"""
        return self.contact_repo.list_all(status=status, user_id=user_id)

    def get_contact(self, contact_id: int, user_id: Optional[int] = None) -> Optional[sqlite3.Row]:
        """依 ID 取得單一聯絡人詳細資訊。"""
        return self.contact_repo.get_by_id(contact_id, user_id=user_id)

    def update_contact(
        self,
        contact_id: int,
        nickname: Optional[str] = None,
        relationship_note: Optional[str] = None,
        update_nickname: bool = False,
        update_note: bool = False,
        user_id: Optional[int] = None,
    ) -> Optional[sqlite3.Row]:
        """更新聯絡人暱稱與關係筆記，並回傳更新後的完整紀錄。"""
        existing = self.contact_repo.get_by_id(contact_id, user_id=user_id)
        if not existing:
            return None

        return self.contact_repo.update_details(
            contact_id=contact_id,
            nickname=nickname,
            relationship_note=relationship_note,
            update_nickname=update_nickname,
            update_note=update_note,
            user_id=user_id,
        )
