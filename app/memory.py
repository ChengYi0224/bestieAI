from typing import Optional, Dict, Any, Tuple
from app.db import get_active_contact, get_recent_messages
from app.vectors import VectorStore


class MemoryManager:
    def __init__(self, vector_store: Optional[VectorStore] = None):
        self.vector_store = vector_store or VectorStore()

    def get_full_context(self, user_query: str) -> Tuple[Optional[Dict[str, Any]], str, str, str]:
        contact = get_active_contact()
        if not contact:
            return None, "", "", ""

        contact_dict = dict(contact)
        contact_id = contact_dict["id"]
        summary_card = contact_dict.get("summary_card") or "尚未建立摘要卡"

        recent_msgs = get_recent_messages(contact_id=contact_id, limit=30)
        formatted_recent = []
        for msg in recent_msgs:
            sender_label = "我" if msg["sender"] == "me" else "對方"
            formatted_recent.append(f"{sender_label}: {msg['content']}")
        recent_context_str = "\n".join(formatted_recent)

        try:
            rag_results = self.vector_store.query(contact_id=contact_id, query_text=user_query, n_results=5)
            rag_chunks_str = "\n---\n".join([r["text"] for r in rag_results])
        except Exception:
            rag_chunks_str = "（向量檢索暫不可用）"

        return contact_dict, summary_card, rag_chunks_str, recent_context_str
