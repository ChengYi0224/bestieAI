import time
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
from app.db import get_or_create_contact, save_messages, get_connection
from app.vectors import VectorStore
from app.llm import LLMClient
from app.ig import IGClient


class IngestionPipeline:
    def __init__(self, vector_store: Optional[VectorStore] = None, llm_client: Optional[LLMClient] = None):
        self.vector_store = vector_store or VectorStore()
        self.llm_client = llm_client or LLMClient()

    @staticmethod
    def clean_text(raw_text: Optional[str]) -> str:
        if not raw_text:
            return "[圖片/貼圖/非文字訊息]"
        cleaned = raw_text.strip()
        return cleaned if cleaned else "[圖片/貼圖/非文字訊息]"

    @staticmethod
    def chunk_messages(messages: List[Dict[str, Any]], max_chunk_size: int = 20) -> List[Dict[str, Any]]:
        if not messages:
            return []

        sorted_msgs = sorted(messages, key=lambda m: m["sent_at"])
        chunks = []
        current_chunk = []
        current_day = None

        for m in sorted_msgs:
            sent_time_str = m["sent_at"]
            day_str = sent_time_str.split("T")[0] if "T" in sent_time_str else sent_time_str.split(" ")[0]

            if current_day != day_str or len(current_chunk) >= max_chunk_size:
                if current_chunk:
                    chunks.append(IngestionPipeline._build_chunk_dict(len(chunks) + 1, current_chunk))
                    current_chunk = []
                current_day = day_str

            current_chunk.append(m)

        if current_chunk:
            chunks.append(IngestionPipeline._build_chunk_dict(len(chunks) + 1, current_chunk))

        return chunks

    @staticmethod
    def _build_chunk_dict(chunk_id: int, msgs: List[Dict[str, Any]]) -> Dict[str, Any]:
        text_lines = []
        for m in msgs:
            sender = "我" if m["sender"] == "me" else "對方"
            text_lines.append(f"[{m['sent_at']}] {sender}: {m['content']}")

        return {
            "id": str(chunk_id),
            "text": "\n".join(text_lines),
            "start_time": msgs[0]["sent_at"],
            "end_time": msgs[-1]["sent_at"],
            "message_count": len(msgs)
        }

    def run_ingestion(self, ig_client: IGClient, target_username: str, days_back: int = 30) -> Dict[str, Any]:
        thread = ig_client.get_thread_by_username(target_username)
        if not thread:
            raise ValueError(f"找不到與 {target_username} 的私訊對話串")

        thread_id = str(thread.id)
        raw_messages = ig_client.get_thread_messages(thread_id=thread_id, amount=300)

        cutoff_date = datetime.utcnow() - timedelta(days=days_back)
        processed_msgs = []
        me_pk = str(ig_client.client.user_id)

        for m in raw_messages:
            sent_dt = m.timestamp
            if sent_dt < cutoff_date:
                continue

            sender = "me" if str(m.user_id) == me_pk else "them"
            content = self.clean_text(m.text)

            processed_msgs.append({
                "ig_item_id": str(m.id),
                "sender": sender,
                "content": content,
                "sent_at": sent_dt.isoformat()
            })

        contact_id = get_or_create_contact(ig_account_id=target_username, display_name=target_username)
        inserted_count = save_messages(contact_id=contact_id, messages=processed_msgs)

        chunks = self.chunk_messages(processed_msgs)
        if chunks:
            self.vector_store.add_chunks(contact_id=contact_id, chunks=chunks)

        all_text = "\n".join([f"{'我' if m['sender']=='me' else '對方'}: {m['content']}" for m in processed_msgs])
        summary_card = self.llm_client.generate_summary(all_text[:4000])

        conn = get_connection()
        with conn:
            conn.execute("""
                UPDATE contacts
                SET summary_card = ?, summary_updated_at = ?, new_messages_since_summary = 0
                WHERE id = ?
            """, (summary_card, datetime.utcnow().isoformat(), contact_id))
        conn.close()

        return {
            "contact_id": contact_id,
            "target_username": target_username,
            "total_messages": len(processed_msgs),
            "inserted_messages": inserted_count,
            "chunk_count": len(chunks),
            "summary_card": summary_card
        }
