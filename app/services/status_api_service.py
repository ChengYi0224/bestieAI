"""status_api_service.py — 系統與 Bot 狀態業務邏輯服務。"""
from datetime import datetime, timezone
from typing import Any, Optional
from app.storage.repositories.bot_state import BotStateRepository
from app.storage.repositories.contacts import ContactRepository


class StatusApiService:
    """提供系統健康狀態與 Bot 運作狀態業務邏輯。"""

    def __init__(
        self,
        bot_state_repo: BotStateRepository,
        contact_repo: Optional[ContactRepository] = None,
    ):
        self.bot_state_repo = bot_state_repo
        self.contact_repo = contact_repo or ContactRepository()

    def get_system_status(self) -> dict[str, Any]:
        """彙整系統健康狀況、Worker 狀態與活躍聯絡人。"""
        worker_status = self.bot_state_repo.get_worker_status()
        active_contact = self.contact_repo.get_active()
        active_contact_id = active_contact["id"] if active_contact else None

        return {
            "status": "ok",
            "timestamp": datetime.now(timezone.utc),
            "worker_status": worker_status,
            "active_contact_id": active_contact_id,
        }
