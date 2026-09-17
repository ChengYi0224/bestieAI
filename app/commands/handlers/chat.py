"""
chat.py — AI 陪聊 Command Handler。

PIPELINE (L2):
  ChatHandler.handle_chat(cmd)
       │
       ▼
  MemoryManager.get_full_context(user_text)
       │
       ├─ (無 active contact) ──► 提示使用 select
       │
       ▼
  LLMClient.generate_reply(display_name, summary_card, ...)
       │
       ▼
  add_bot_conversation (記錄對話到 SQLite)
       │
       ▼
  threading.Thread → _async_extract (非同步萃取使用者自身記憶)
       │
       ▼
  CommandResult(success=True, message=reply)
"""
import time
import threading
from datetime import datetime, timezone
from typing import Any, Optional

from app.commands.base import CommandResult
from app.commands.commands import ChatCommand
from app.core.config import settings
from app.core.error_logger import log_error
from app.storage.db import (
    add_bot_conversation,
    get_contacts_with_nickname,
    get_worker_status,
    set_worker_status,
)
from app.services.memory_service import MemoryManager
from app.services.llm_service import LLMClient


class ChatHandler:
    """AI 聊天 Handler。依賴 MemoryManager 與 LLMClient。"""

    def __init__(
        self,
        memory_manager: MemoryManager,
        llm_client: LLMClient,
        db_path: Optional[Any] = None,
    ):
        self.memory_manager = memory_manager
        self.llm_client = llm_client
        self.db_path = db_path

    def handle_chat(self, cmd: ChatCommand) -> CommandResult:
        user_text = cmd.text
        ctx = self.memory_manager.get_full_context(user_text)
        if not ctx or not ctx[0]:
            return CommandResult(
                success=False,
                message="目前尚未選擇討論對象！請先傳送指令：select <IG_ID> 切換對象。"
            )

        contact, summary_card, rag_chunks, recent_context, chat_history, self_context = ctx
        contact_id = contact["id"]
        add_bot_conversation(role="user", content=user_text, contact_id=contact_id)

        # 暱稱掃描：跨對象 RAG
        cross_rag_list = []
        try:
            query_emb = getattr(self.memory_manager, "last_query_embedding", None)
            contacts_with_nick = get_contacts_with_nickname(db_path=self.db_path)
            for c in contacts_with_nick:
                nick = c["nickname"]
                if nick and (nick.lower() in user_text.lower()) and c["id"] != contact_id:
                    nick_results = self.memory_manager.vector_store.query(
                        contact_id=c["id"],
                        query_text=user_text,
                        query_embedding=query_emb,
                        n_results=settings.CROSS_RAG_RESULTS
                    )
                    if nick_results:
                        snippets = "\n".join([r["text"] for r in nick_results])
                        cross_rag_list.append(f"【關於 {nick} ({c['ig_account_id']}) 的紀錄】\n{snippets}")
        except Exception:
            pass

        cross_rag_str = "\n\n---\n\n".join(cross_rag_list) if cross_rag_list else ""

        reply = self.llm_client.generate_reply(
            display_name=contact["display_name"] or contact["ig_account_id"],
            summary_card=summary_card,
            rag_chunks=rag_chunks,
            recent_context=recent_context,
            chat_history=chat_history,
            self_context=self_context,
            cross_rag=cross_rag_str,
            user_query=user_text
        )

        add_bot_conversation(role="assistant", content=reply, contact_id=contact_id)

        # 背景非同步萃取使用者自身相關資訊
        def _async_extract():
            w_status = get_worker_status(db_path=self.db_path)
            is_idle = not (w_status and w_status.get("running"))
            if is_idle:
                set_worker_status({
                    "running": True,
                    "target": "user_self",
                    "mode": "自身偏好記憶萃取",
                    "detail": "正在非同步分析並萃取對話中的個人偏好事實...",
                    "start_time": time.time(),
                    "last_update": datetime.now(timezone.utc).isoformat()
                }, db_path=self.db_path)

            try:
                extracted = self.llm_client.extract_self_info(user_text)
                if extracted:
                    # 去重：若向量庫已有高度相似記憶（distance < 0.15），跳過寫入
                    if not self.memory_manager.is_duplicate_self_memory(extracted):
                        self.memory_manager.add_self_memory(extracted)
            except Exception as e:
                log_error(e, context="ChatHandler._async_extract", logger_name="bestieAI.chat_handler")
            finally:
                if is_idle:
                    set_worker_status({
                        "running": False,
                        "target": "user_self",
                        "completed_at": datetime.now(timezone.utc).isoformat(),
                        "detail": "自身記憶萃取完成"
                    }, db_path=self.db_path)

        threading.Thread(target=_async_extract, daemon=True).start()

        return CommandResult(
            success=True,
            message=reply,
            data={"reply": reply, "contact_id": contact_id}
        )
