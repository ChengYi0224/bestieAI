from typing import Optional, Dict, Any, Tuple, List
from app.db import get_active_contact, get_recent_messages, get_bot_conversations
from app.vectors import VectorStore
from app.config import settings


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

    def add_self_memory(self, text: str) -> str:
        """將使用者自身相關事實寫入 user_self 向量庫。"""
        return self.self_vector_store.add_self_chunk(text)

    def get_full_context(self, user_query: str) -> Tuple[Optional[Dict[str, Any]], str, str, str, str, str]:
        contact = get_active_contact(db_path=self.db_path)
        if not contact:
            return None, "", "", "", "", ""

        contact_dict = dict(contact)
        contact_id = contact_dict["id"]
        summary_card = contact_dict.get("summary_card") or "尚未建立摘要卡"

        recent_msgs = get_recent_messages(contact_id=contact_id, limit=settings.RECENT_MESSAGES_LIMIT, db_path=self.db_path)
        formatted_recent = []
        for msg in recent_msgs:
            sender_label = "我" if msg["sender"] == "me" else "對方"
            formatted_recent.append(f"{sender_label}: {msg['content']}")
        recent_context_str = "\n".join(formatted_recent)

        try:
            rag_results = self.vector_store.query(
                contact_id=contact_id,
                query_text=user_query,
                n_results=settings.CONTACT_RAG_RESULTS
            )
            rag_chunks_str = "\n---\n".join([r["text"] for r in rag_results])
        except Exception:
            rag_chunks_str = "（向量檢索暫不可用）"

        # 讀取使用者自身記憶 (user_self RAG)
        try:
            self_results = self.self_vector_store.query_self(
                query_text=user_query,
                n_results=settings.SELF_RAG_RESULTS
            )
            if self_results:
                self_context_str = "\n---\n".join([r["text"] for r in self_results])
            else:
                self_context_str = ""
        except Exception:
            self_context_str = ""

        # 讀取最近 N 輪 bot 對話歷史（user/assistant 各一筆算一輪，取 turns*2 筆）
        turns = settings.CHAT_HISTORY_TURNS
        bot_convs = get_bot_conversations(contact_id=contact_id, limit=turns * 2, db_path=self.db_path)
        if bot_convs:
            chat_history_str = "\n".join(
                f"{'你' if row['role'] == 'user' else 'AI'}: {row['content']}"
                for row in bot_convs
            )
        else:
            chat_history_str = ""

        return contact_dict, summary_card, rag_chunks_str, recent_context_str, chat_history_str, self_context_str

