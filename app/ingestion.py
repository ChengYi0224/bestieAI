import time
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
from app.db import (
    get_or_create_contact,
    save_messages,
    get_connection,
    get_contact_by_id,
    get_contact_by_username,
    get_latest_message_time,
    update_contact_summary,
    should_update_summary,
    get_recent_messages
)
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

    def check_and_update_summary(
        self,
        contact_id: int,
        force: bool = False,
        threshold: int = 50,
        days_limit: int = 14,
        db_path: Optional[Any] = None
    ) -> Optional[str]:
        contact_row = get_contact_by_id(contact_id, db_path=db_path)
        if not contact_row:
            return None

        contact = dict(contact_row)
        if not force and not should_update_summary(contact, threshold=threshold, days_limit=days_limit):
            return None

        recent_msgs = get_recent_messages(contact_id=contact_id, limit=50, db_path=db_path)
        if not recent_msgs:
            return None

        formatted_lines = []
        for m in recent_msgs:
            sender_label = "我" if m["sender"] == "me" else "對方"
            formatted_lines.append(f"[{m['sent_at']}] {sender_label}: {m['content']}")
        conv_text = "\n".join(formatted_lines)

        old_summary = contact.get("summary_card")
        display_name = contact.get("display_name") or contact.get("ig_account_id") or "對方"

        if old_summary:
            new_summary = self.llm_client.update_summary(
                display_name=display_name,
                old_summary=old_summary,
                new_conversations_text=conv_text
            )
        else:
            new_summary = self.llm_client.generate_summary(conv_text)

        update_contact_summary(contact_id, new_summary, db_path=db_path)
        return new_summary

    def sync_messages(
        self,
        ig_client: IGClient,
        target_username: str,
        db_path: Optional[Any] = None
    ) -> Dict[str, Any]:
        contact_row = get_contact_by_username(target_username, db_path=db_path)
        if not contact_row:
            raise ValueError(f"尚未追蹤 {target_username}，請先使用 track 指令初次匯入。")

        contact_id = contact_row["id"]
        latest_time_str = get_latest_message_time(contact_id, db_path=db_path)

        thread = ig_client.get_thread_by_username(target_username)
        if not thread:
            raise ValueError(f"找不到與 {target_username} 的私訊對話串")

        raw_messages = ig_client.get_thread_messages(thread_id=str(thread.id), amount=100)
        me_pk = str(ig_client.client.user_id)

        processed_msgs = []
        for m in raw_messages:
            sent_dt = m.timestamp
            if latest_time_str:
                try:
                    latest_dt = datetime.fromisoformat(latest_time_str)
                    if sent_dt <= latest_dt:
                        continue
                except Exception:
                    pass

            sender = "me" if str(m.user_id) == me_pk else "them"
            processed_msgs.append({
                "ig_item_id": str(m.id),
                "sender": sender,
                "content": self.clean_text(m.text),
                "sent_at": sent_dt.isoformat()
            })

        inserted_count = save_messages(contact_id=contact_id, messages=processed_msgs, db_path=db_path)

        chunks = self.chunk_messages(processed_msgs)
        if chunks:
            self.vector_store.add_chunks(contact_id=contact_id, chunks=chunks)

        updated_summary = self.check_and_update_summary(contact_id=contact_id, db_path=db_path)

        return {
            "contact_id": contact_id,
            "target_username": target_username,
            "new_messages_count": inserted_count,
            "chunks_added": len(chunks),
            "summary_updated": updated_summary is not None
        }

    def run_ingestion(
        self,
        ig_client: IGClient,
        target_username: str,
        days_back: int = 30,
        db_path: Optional[Any] = None
    ) -> Dict[str, Any]:
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

        contact_id = get_or_create_contact(ig_account_id=target_username, display_name=target_username, db_path=db_path)
        inserted_count = save_messages(contact_id=contact_id, messages=processed_msgs, db_path=db_path)

        chunks = self.chunk_messages(processed_msgs)
        if chunks:
            self.vector_store.add_chunks(contact_id=contact_id, chunks=chunks)

        all_text = "\n".join([f"{'我' if m['sender']=='me' else '對方'}: {m['content']}" for m in processed_msgs])
        summary_card = self.llm_client.generate_summary(all_text[:4000])

        update_contact_summary(contact_id, summary_card, db_path=db_path)

        return {
            "contact_id": contact_id,
            "target_username": target_username,
            "total_messages": len(processed_msgs),
            "inserted_messages": inserted_count,
            "chunk_count": len(chunks),
            "summary_card": summary_card
        }

