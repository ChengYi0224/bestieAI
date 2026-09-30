"""contact_api_service.py — 聯絡人管理與主動操作業務邏輯服務。"""
import logging
import sqlite3
from typing import Callable, Optional, Dict, Any

from app.storage.repositories.contacts import ContactRepository
from app.services.ig_pool import IGClientPool, IGSessionUnavailable
from app.services.ingestion_service import IngestionPipeline
from app.sources.factory import SourceAdapterFactory

logger = logging.getLogger("bestieAI.api.contact_service")


class ContactApiService:
    """提供聯絡人查詢、更新、追蹤與記憶提煉業務邏輯服務。"""

    def __init__(
        self,
        contact_repo: ContactRepository,
        ingestion: Optional[IngestionPipeline] = None,
        ig_pool: Optional[IGClientPool] = None,
        ingestion_for: Optional[Callable[[int], IngestionPipeline]] = None,
    ):
        """
        ingestion_for: 依 user_id 取得該使用者專屬的 IngestionPipeline（建議）；
        ingestion: 所有使用者共用同一個 Pipeline（僅測試用）。
        ig_pool: 依 user_id 取得該使用者自己的 IG 連線，不會借用其他使用者（含擁有者）的帳號。
        """
        self.contact_repo = contact_repo
        self.ig_pool = ig_pool
        self._ingestion_for = ingestion_for or ((lambda _uid: ingestion) if ingestion else None)
        self.ingestion = ingestion  # 向後相容屬性

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
        queued_reason = "待排程匯入"
        if self._ingestion_for and self.ig_pool:
            try:
                ig = self.ig_pool.get(user_id)  # 該使用者自己的 IG 連線
                adapter = SourceAdapterFactory.create("instagram", ig_client=ig)
                info = self._ingestion_for(user_id).run_ingestion(adapter, clean_target, amount=limit)
                inserted_count = info.get("inserted_messages", 0)
                return {
                    "status": "success",
                    "message": f"成功追蹤 @{clean_target}，匯入 {inserted_count} 則訊息",
                    "contact_id": contact_id,
                    "inserted_messages": inserted_count,
                }
            except IGSessionUnavailable as e:
                queued_reason = str(e)
            except Exception as e:
                logger.warning(f"追蹤即時抓取私訊失敗，轉為佇列等待: {e}")

        return {
            "status": "queued",
            "message": f"已建立追蹤對象 @{clean_target}，{queued_reason}",
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

        if self._ingestion_for:
            try:
                new_summary = self._ingestion_for(user_id).check_and_update_summary(contact_id, force=True)
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
