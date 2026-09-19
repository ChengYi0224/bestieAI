"""message_api_service.py — 訊息與記憶事件業務邏輯服務。"""
import sqlite3
from typing import Optional
from app.storage.repositories.contacts import ContactRepository
from app.storage.repositories.events import EventRepository
from app.storage.repositories.messages import MessageRepository


class MessageApiService:
    """提供歷史私訊與記憶事件查詢業務邏輯服務。"""

    def __init__(
        self,
        message_repo: MessageRepository,
        event_repo: EventRepository,
        contact_repo: Optional[ContactRepository] = None,
    ):
        self.message_repo = message_repo
        self.event_repo = event_repo
        self.contact_repo = contact_repo or ContactRepository()

    def get_contact_messages(
        self,
        contact_id: int,
        limit: int = 50,
        offset: int = 0,
        user_id: Optional[int] = None,
    ) -> Optional[tuple[int, list[sqlite3.Row]]]:
        """
        取得指定聯絡人訊息清單（分頁）與總筆數。
        若聯絡人不存在或不屬於該使用者則回傳 None。
        """
        contact = self.contact_repo.get_by_id(contact_id, user_id=user_id)
        if not contact:
            return None

        total = self.message_repo.count_by_contact(contact_id)
        items = self.message_repo.get_paginated(contact_id, limit=limit, offset=offset)
        return total, items

    def get_contact_events(
        self,
        contact_id: int,
        status: Optional[str] = None,
        user_id: Optional[int] = None,
    ) -> Optional[list[sqlite3.Row]]:
        """
        取得指定聯絡人之記憶事件清單。
        若聯絡人不存在或不屬於該使用者則回傳 None。
        """
        contact = self.contact_repo.get_by_id(contact_id, user_id=user_id)
        if not contact:
            return None

        return self.event_repo.get_events(contact_id, status=status)
