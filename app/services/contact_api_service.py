"""contact_api_service.py — 聯絡人管理與主動操作業務邏輯服務。"""
import logging
import sqlite3
from typing import Optional, Dict, Any

from app.storage.repositories.contacts import ContactRepository
from app.services.ingestion_service import IngestionPipeline
from app.services.session_service import SessionManager
from app.services.ig_service import IGClient
from app.sources.factory import SourceAdapterFactory

logger = logging.getLogger("bestieAI.api.contact_service")


class ContactApiService:
    """提供聯絡人查詢、更新、追蹤與記憶提煉業務邏輯服務。"""

    def __init__(
        self,
        contact_repo: ContactRepository,
        ingestion: Optional[IngestionPipeline] = None,
        session_manager: Optional[SessionManager] = None,
    ):
        self.contact_repo = contact_repo
        self.ingestion = ingestion
        self.session_manager = session_manager
        self._ig_client: Optional[IGClient] = None

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

    def track_contact(
        self,
        user_id: int,
        ig_account_id: str,
        limit: int = 1000,
    ) -> Dict[str, Any]:
        """追蹤新對象並匯入私訊。"""
        clean_target = ig_account_id.strip()
        contact_id = self.contact_repo.get_or_create(
            clean_target,
            display_name=clean_target,
            user_id=user_id,
        )

        inserted_count = 0
        if self.ingestion:
            try:
                if self._ig_client is None and self.session_manager:
                    client = self.session_manager.login("main")
                    self._ig_client = IGClient(client)

                if self._ig_client:
                    adapter = SourceAdapterFactory.create("instagram", ig_client=self._ig_client)
                    info = self.ingestion.run_ingestion(adapter, clean_target, amount=limit)
                    inserted_count = info.get("inserted_messages", 0)
                    return {
                        "status": "success",
                        "message": f"成功追蹤 @{clean_target}，匯入 {inserted_count} 則訊息",
                        "contact_id": contact_id,
                        "inserted_messages": inserted_count,
                    }
            except Exception as e:
                logger.warning(f"追蹤即時抓取私訊失敗，轉為佇列等待: {e}")

        return {
            "status": "queued",
            "message": f"已建立追蹤對象 @{clean_target}，待排程匯入",
            "contact_id": contact_id,
            "inserted_messages": inserted_count,
        }

    def extract_contact_events(
        self,
        user_id: int,
        contact_id: int,
    ) -> Optional[Dict[str, Any]]:
        """手動觸發事件萃取與摘要卡更新。"""
        contact = self.contact_repo.get_by_id(contact_id, user_id=user_id)
        if not contact:
            return None

        summary_card = contact["summary_card"]
        summary_updated = False
        events_extracted = 0

        if self.ingestion:
            try:
                new_summary = self.ingestion.check_and_update_summary(contact_id, force=True)
                if new_summary:
                    summary_card = new_summary
                    summary_updated = True
                    events_extracted = 1
            except Exception as e:
                logger.warning(f"提煉事件發生異常: {e}")

        return {
            "status": "success",
            "contact_id": contact_id,
            "events_extracted": events_extracted,
            "summary_updated": summary_updated,
            "summary_card": summary_card,
        }
