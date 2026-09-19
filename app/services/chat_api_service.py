"""chat_api_service.py — REST API 專用 AI 陪聊業務邏輯服務。"""
import logging
from typing import Optional, Tuple

from app.storage.repositories.contacts import ContactRepository
from app.storage.repositories.bot_state import BotStateRepository
from app.services.memory_service import MemoryManager
from app.services.llm_service import LLMClient

logger = logging.getLogger("bestieAI.api.chat_service")


class ChatApiService:
    """提供 REST API 與 AI 陪聊（依聯絡人 RAG 記憶體提煉上下文）業務邏輯。"""

    def __init__(
        self,
        contact_repo: ContactRepository,
        bot_state_repo: Optional[BotStateRepository] = None,
        memory_manager: Optional[MemoryManager] = None,
        llm_client: Optional[LLMClient] = None,
    ):
        self.contact_repo = contact_repo
        self.bot_state_repo = bot_state_repo or BotStateRepository()
        self._custom_memory_manager = memory_manager
        self.llm_client = llm_client or LLMClient()

    def chat(
        self,
        user_id: int,
        message: str,
        contact_id: Optional[int] = None,
    ) -> Tuple[str, Optional[int]]:
        """
        與 AI 陪聊討論指定或目前活躍聯絡人。
        回傳 (reply_text, resolved_contact_id)。
        """
        clean_msg = message.strip()
        if not clean_msg:
            raise ValueError("對話內容不可為空。")

        # 1. 決定目標聯絡人（需符合 user_id 租戶隔離）
        contact = None
        if contact_id is not None:
            contact = self.contact_repo.get_by_id(contact_id, user_id=user_id)
            if not contact:
                raise ValueError(f"找不到 ID 為 {contact_id} 的聯絡人。")
        else:
            # 優先使用該使用者的活躍聯絡人或第一筆追蹤中聯絡人
            tracked = self.contact_repo.list_all(status="tracked", user_id=user_id)
            if tracked:
                contact = tracked[0]

        if not contact:
            raise ValueError("尚無可討論的聯絡人，請先建立或追蹤聯絡人。")

        resolved_cid = contact["id"]
        display_name = contact["nickname"] or contact["display_name"] or contact["ig_account_id"]
        summary_card = contact["summary_card"] or "尚未生成關係摘要卡。"

        # 2. 獲取 RAG 上下文與對話歷史（鎖定使用者向量庫分區）
        rag_chunks = ""
        recent_context = ""
        self_context = ""
        chat_history = ""
        try:
            mem_mgr = self._custom_memory_manager or MemoryManager(user_id=user_id)
            ctx = mem_mgr.get_full_context(clean_msg, contact_id=resolved_cid)
            if ctx and len(ctx) >= 6:
                rag_chunks = ctx[2] or ""
                recent_context = ctx[3] or ""
                chat_history = ctx[4] or ""
                self_context = ctx[5] or ""
        except Exception as e:
            logger.warning(f"擷取記憶上下文失敗，將以無記憶模式回覆: {e}")

        # 若未自記憶服務取得對話歷史，自資料庫補足
        if not chat_history:
            try:
                history_rows = self.bot_state_repo.get_conversations(contact_id=resolved_cid, limit=10)
                chat_history = "\n".join([f"{r['role']}: {r['content']}" for r in history_rows])
            except Exception:
                pass

        # 4. 調用 LLM 產生回覆
        reply = self.llm_client.generate_reply(
            display_name=display_name,
            summary_card=summary_card,
            rag_chunks=rag_chunks,
            recent_context=recent_context,
            user_query=clean_msg,
            chat_history=chat_history,
            self_context=self_context,
        )

        # 5. 儲存本次對話紀錄
        try:
            self.bot_state_repo.add_conversation(role="user", content=clean_msg, contact_id=resolved_cid)
            self.bot_state_repo.add_conversation(role="assistant", content=reply, contact_id=resolved_cid)
        except Exception as e:
            logger.warning(f"儲存對話紀錄失敗: {e}")

        return reply, resolved_cid
