"""
memory_service.py — 記憶組裝與高效檢索服務。

特色：
- 共享單次 Query Embedding：單次對話只發送 1 次 Embedding API 請求，
  同時提供 Contact Events、Self Memories 與 Cross RAG 檢索使用，徹底消除重複延遲與額度浪費。
- 分層記憶提取（日常精簡卡、近期脈絡、近期問答輪數、事實事件記憶）。
- self_context 距離過濾：只回傳 distance < SELF_CONTEXT_MAX_DISTANCE 的結果，
  避免低相關記憶被帶入 prompt。
"""
import logging
from typing import Optional, Dict, Any, Tuple, List

from app.core.config import settings
from app.core.error_logger import log_error
from app.storage.db import (
    get_active_contact,
    get_recent_messages,
    get_bot_conversations,
    get_contacts_with_nickname,
)
from app.storage.vectors import VectorStore

logger = logging.getLogger("bestieAI.memory_service")

# ==================== 可調參數與檢索筆數設定 (Tunable Constants) ====================
# 目標對象事件向量檢索筆數
CONTACT_RAG_RESULTS: int = getattr(settings, "CONTACT_RAG_RESULTS", 5)

# 使用者自我事實向量檢索筆數
SELF_RAG_RESULTS: int = getattr(settings, "SELF_RAG_RESULTS", 3)

# 跨對象暱稱關聯檢索筆數
CROSS_RAG_RESULTS: int = getattr(settings, "CROSS_RAG_RESULTS", 3)

# 提示詞載入之近期原始私訊則數
RECENT_MESSAGES_LIMIT: int = getattr(settings, "RECENT_MESSAGES_LIMIT", 30)

# 提示詞載入之最近對話歷史輪數
CHAT_HISTORY_TURNS: int = getattr(settings, "CHAT_HISTORY_TURNS", 10)

# self_context 最大 cosine distance 門檻（超過此值表示相關性不足，不納入 prompt）
# cosine distance = 1 - cosine_similarity，故 0.5 ≈ 相似度 50%
SELF_CONTEXT_MAX_DISTANCE: float = 0.5


class MemoryManager:
    def __init__(
        self,
        vector_store: Optional[VectorStore] = None,
        self_vector_store: Optional[VectorStore] = None,
        db_path: Optional[Any] = None
    ):
        self.vector_store = vector_store or VectorStore()
        self.self_vector_store = self_vector_store or VectorStore(collection_name="user_self")
        self.db_path = db_path
        self.last_query_embedding: Optional[List[float]] = None

    def add_self_memory(self, text: str) -> str:
        """將使用者自身相關事實寫入 user_self 向量庫。"""
        return self.self_vector_store.add_self_chunk(text)

    def is_duplicate_self_memory(
        self,
        text: str,
        embedding: Optional[List[float]] = None,
        distance_threshold: float = 0.15,
    ) -> bool:
        """
        檢查 user_self 向量庫中是否已存在語意高度相似的記憶。

        Args:
            text: 欲寫入的記憶文字。
            embedding: 預先計算的向量（避免重複 API 呼叫）。
            distance_threshold: cosine distance 低於此值視為重複（預設 0.15 ≈ 相似度 85%）。

        Returns:
            True 表示已有近似記憶，應跳過寫入。
        """
        try:
            results = self.self_vector_store.query_self(
                query_text=text,
                query_embedding=embedding,
                n_results=1,
            )
            if results and results[0].get("distance", 1.0) < distance_threshold:
                logger.debug(
                    f"self_memory 去重跳過（distance={results[0]['distance']:.3f} < {distance_threshold}）: {text[:50]}"
                )
                return True
        except Exception as e:
            log_error(e, context="MemoryManager.is_duplicate_self_memory", logger_name="bestieAI.memory_service")
        return False

    def query_cross_rag(
        self,
        user_query: str,
        current_contact_id: int,
        query_embedding: Optional[List[float]] = None
    ) -> str:
        """
        掃描提問中是否提及其他已標記暱稱的好友。
        若提及，使用共享向量直接進行跨對象檢索，不再重複計算 Embedding。
        """
        cross_rag_list = []
        try:
            contacts_with_nick = get_contacts_with_nickname(db_path=self.db_path)
            for c in contacts_with_nick:
                nick = c["nickname"]
                if nick and (nick.lower() in user_query.lower()) and c["id"] != current_contact_id:
                    nick_results = self.vector_store.query(
                        contact_id=c["id"],
                        query_text=user_query,
                        query_embedding=query_embedding,
                        n_results=settings.CROSS_RAG_RESULTS
                    )
                    if nick_results:
                        snippets = "\n".join([r["text"] for r in nick_results])
                        cross_rag_list.append(f"【關於 {nick} ({c['ig_account_id']}) 的紀錄】\n{snippets}")
        except Exception as e:
            log_error(e, context="MemoryManager.query_cross_rag", logger_name="bestieAI.memory_service")

        return "\n\n---\n\n".join(cross_rag_list) if cross_rag_list else ""

    def get_full_context(
        self,
        user_query: str
    ) -> Tuple[Optional[Dict[str, Any]], str, str, str, str, str]:
        """
        組裝完整對話脈絡。
        回傳: (contact_dict, summary_card, rag_chunks_str, recent_context_str, chat_history_str, self_context_str)
        """
        contact = get_active_contact(db_path=self.db_path)
        if not contact:
            return None, "", "", "", "", ""

        contact_dict = dict(contact)
        contact_id = contact_dict["id"]
        summary_card = contact_dict.get("summary_card") or "尚未建立摘要卡"

        # 1. 取得近期原始訊息
        recent_msgs = get_recent_messages(
            contact_id=contact_id,
            limit=settings.RECENT_MESSAGES_LIMIT,
            db_path=self.db_path,
        )
        formatted_recent = []
        for msg in recent_msgs:
            sender_label = "我" if msg["sender"] == "me" else "對方"
            time_prefix = f"[{msg['sent_at']}] " if "sent_at" in msg.keys() and msg["sent_at"] else ""
            formatted_recent.append(f"{time_prefix}{sender_label}: {msg['content']}")
        recent_context_str = "\n".join(formatted_recent)

        # 2. 共享單次 Query Embedding
        query_embedding: Optional[List[float]] = None
        try:
            embeddings = self.vector_store.get_embeddings_batch([user_query])
            query_embedding = embeddings[0] if embeddings else None
        except Exception as e:
            log_error(e, context="MemoryManager.get_full_context — Query Embedding", logger_name="bestieAI.memory_service")

        # 3. 檢索 Contact 事件記憶向量庫（使用 contact_id 過濾）
        rag_chunks_str = ""
        try:
            rag_results = self.vector_store.query(
                contact_id=contact_id,
                query_text=user_query,
                query_embedding=query_embedding,
                n_results=settings.CONTACT_RAG_RESULTS,
            )
            rag_chunks_str = "\n---\n".join([r["text"] for r in rag_results])
        except Exception as e:
            log_error(e, context="MemoryManager.get_full_context — Contact RAG", logger_name="bestieAI.memory_service")
            rag_chunks_str = ""

        # 4. 檢索使用者自身記憶 (user_self RAG)
        #    - 複用同一份向量
        #    - 距離 >= SELF_CONTEXT_MAX_DISTANCE 的結果過濾掉（相關性太低）
        self_context_str = ""
        try:
            self_results = self.self_vector_store.query_self(
                query_text=user_query,
                query_embedding=query_embedding,
                n_results=settings.SELF_RAG_RESULTS,
            )
            relevant = [
                r for r in self_results
                if "distance" not in r or r["distance"] < SELF_CONTEXT_MAX_DISTANCE
            ]
            if relevant:
                self_context_str = "\n---\n".join([r["text"] for r in relevant])
        except Exception as e:
            log_error(e, context="MemoryManager.get_full_context — Self RAG", logger_name="bestieAI.memory_service")

        # 5. 讀取最近 N 輪 bot 對話歷史
        turns = settings.CHAT_HISTORY_TURNS
        bot_convs = get_bot_conversations(
            contact_id=contact_id,
            limit=turns * 2,
            db_path=self.db_path,
        )
        if bot_convs:
            chat_history_str = "\n".join(
                f"{'你' if row['role'] == 'user' else 'AI'}: {row['content']}"
                for row in bot_convs
            )
        else:
            chat_history_str = ""

        self.last_query_embedding = query_embedding

        return (
            contact_dict,
            summary_card,
            rag_chunks_str,
            recent_context_str,
            chat_history_str,
            self_context_str,
        )
