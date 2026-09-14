import time
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional, Callable
from app.db import (
    get_or_create_contact,
    save_messages,
    get_connection,
    get_contact_by_id,
    get_contact_by_username,
    get_latest_message_time,
    update_contact_summary,
    should_update_summary,
    get_recent_messages,
    get_all_messages,
)
from app.config import settings
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
    def chunk_messages(messages: List[Dict[str, Any]], max_chunk_size: Optional[int] = None) -> List[Dict[str, Any]]:
        chunk_sz = max_chunk_size if max_chunk_size is not None else settings.CHUNK_MAX_SIZE
        if not messages:
            return []

        sorted_msgs = sorted(messages, key=lambda m: m["sent_at"])
        chunks = []
        current_chunk = []
        current_day = None

        for m in sorted_msgs:
            sent_time_str = m["sent_at"]
            day_str = sent_time_str.split("T")[0] if "T" in sent_time_str else sent_time_str.split(" ")[0]

            if current_day != day_str or len(current_chunk) >= chunk_sz:
                if current_chunk:
                    chunks.append(IngestionPipeline._build_chunk_dict(len(chunks) + 1, current_chunk))
                    current_chunk = []
                current_day = day_str

            current_chunk.append(m)

        if current_chunk:
            chunks.append(IngestionPipeline._build_chunk_dict(len(chunks) + 1, current_chunk))

        return chunks

    @staticmethod
    def _parse_time(time_str: str) -> Optional[datetime]:
        try:
            clean_str = time_str.replace("Z", "+00:00")
            return datetime.fromisoformat(clean_str)
        except Exception:
            return None

    @staticmethod
    def _build_chunk_dict(chunk_id: int, msgs: List[Dict[str, Any]]) -> Dict[str, Any]:
        text_lines = []
        prev_time: Optional[datetime] = None
        prev_sender: Optional[str] = None

        them_count = 0
        them_short_count = 0
        long_gap_detected = False

        for m in msgs:
            sender_label = "我" if m["sender"] == "me" else "對方"
            content = m["content"]
            content_len = len(content) if content != "[圖片/貼圖/非文字訊息]" else 0

            # 計算與上一則訊息之間的時間差
            interval_str = ""
            curr_time = IngestionPipeline._parse_time(m["sent_at"])
            if curr_time and prev_time:
                diff_sec = (curr_time - prev_time).total_seconds()
                if diff_sec >= 3600:
                    diff_hours = diff_sec / 3600
                    interval_str = f" (間隔 {diff_hours:.1f}小時)"
                    if m["sender"] != prev_sender and diff_hours >= 3.0:
                        long_gap_detected = True
                elif diff_sec >= 60:
                    interval_str = f" (間隔 {int(diff_sec // 60)}分鐘)"

            line = f"[{m['sent_at']}]{interval_str} {sender_label} ({content_len}字): {content}"
            text_lines.append(line)

            # 統計互動氛圍特徵
            if m["sender"] != "me":
                them_count += 1
                if content_len <= 3 or content == "[圖片/貼圖/非文字訊息]":
                    them_short_count += 1

            if curr_time:
                prev_time = curr_time
            prev_sender = m["sender"]

        # 自動生成互動特徵標註，協助向量語意檢索情感溫度
        tags = []
        if them_count >= 2 and (them_short_count / them_count) >= 0.6:
            tags.append("對方多簡短/敷衍回覆")
        if long_gap_detected:
            tags.append("出現長時間間隔/回覆延遲")

        if tags:
            tag_text = "、".join(tags)
            text_lines.append(f"【互動特徵標註：{tag_text}】")

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

    def build_full_history_summary(
        self,
        target_username: str,
        db_path: Optional[Any] = None
    ) -> Dict[str, Any]:
        """
        讀取本地 SQLite 資料庫中自始至終的「所有歷史訊息」，
        利用 Gemini 百萬 Token 上下文視窗生成完整的全景關係復盤卡。
        """
        contact_row = get_contact_by_username(target_username, db_path=db_path)
        if not contact_row:
            raise ValueError(f"尚未追蹤 {target_username}，請先使用 track 指令。")

        contact_id = contact_row["id"]
        display_name = contact_row["display_name"] or contact_row["ig_account_id"]

        all_msgs = get_all_messages(contact_id, db_path=db_path)
        if not all_msgs:
            raise ValueError(f"{target_username} 在本地資料庫尚無任何訊息紀錄。")

        # 格式化完整對話紀錄（含時間、發送者與內容）
        formatted_lines = []
        for m in all_msgs:
            sender_label = "我" if m["sender"] == "me" else "對方"
            formatted_lines.append(f"[{m['sent_at']}] {sender_label}: {m['content']}")
        full_text = "\n".join(formatted_lines)

        # 呼叫專屬全量深度分析 Prompt
        summary_card = self.llm_client.generate_full_history_summary(
            display_name=display_name,
            full_conversations_text=full_text
        )

        update_contact_summary(contact_id, summary_card, db_path=db_path)

        return {
            "contact_id": contact_id,
            "target_username": target_username,
            "total_messages": len(all_msgs),
            "summary_card": summary_card
        }

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

    def run_full_ingestion(
        self,
        ig_client: IGClient,
        target_username: str,
        max_amount: int = 5000,
        progress_callback: Optional[Callable[[int, int], None]] = None,
        db_path: Optional[Any] = None
    ) -> Dict[str, Any]:
        """
        慢速防風控全量抓取指定對象的歷史訊息。
        - 採用 3~7 秒分頁隨機延遲＋每 5 頁（約 100 則）休眠 25 秒防範被判定為 robot。
        - 抓回訊息全部經過 SQLite UNIQUE 去重，絕不重複儲存。
        - 下載完畢後，清空舊向量庫並重新按完整脈絡 chunking + embedding。
        - 以完整歷史對話更新人物關係摘要卡。
        """
        thread = ig_client.get_thread_by_username(target_username)
        if not thread:
            raise ValueError(f"找不到與 {target_username} 的私訊對話串")

        thread_id = str(thread.id)
        # 啟動擬真人慢速防風控爬取（大標準差隨機延遲，每 4~7 頁深度休眠 35~80 秒）
        raw_messages = ig_client.get_thread_messages(
            thread_id=thread_id,
            amount=max_amount,
            min_delay=3.5,
            max_delay=14.0,
            batch_rest_pages=5,
            batch_rest_seconds=35.0,
            progress_callback=progress_callback
        )

        processed_msgs = []
        me_pk = str(ig_client.client.user_id)

        for m in raw_messages:
            sender = "me" if str(m.user_id) == me_pk else "them"
            content = self.clean_text(m.text)
            processed_msgs.append({
                "ig_item_id": str(m.id),
                "sender": sender,
                "content": content,
                "sent_at": m.timestamp.isoformat()
            })

        contact_id = get_or_create_contact(ig_account_id=target_username, display_name=target_username, db_path=db_path)

        # 1. 寫入 SQLite：利用 ig_item_id UNIQUE 去重，既有舊紀錄會自動跳過 (continue)
        inserted_count = save_messages(contact_id=contact_id, messages=processed_msgs, db_path=db_path)

        # 2. 全量重構向量資料庫：使用本地所有完整訊息重新按時間軸切塊，確保向量無重複且語意段落完整
        rebuild_res = self.rebuild_vectors(target_username, db_path=db_path)

        # 3. 重新提取全局人物關係摘要卡
        all_msgs = get_all_messages(contact_id, db_path=db_path)
        all_text = "\n".join([f"{'我' if m['sender']=='me' else '對方'}: {m['content']}" for m in all_msgs])
        # 取最新 4000 字元與最初 2000 字元綜合呈現大局動態
        context_for_summary = all_text[-4000:] if len(all_text) <= 6000 else (all_text[:2000] + "\n...\n" + all_text[-4000:])
        summary_card = self.llm_client.generate_summary(context_for_summary)
        update_contact_summary(contact_id, summary_card, db_path=db_path)

        return {
            "contact_id": contact_id,
            "target_username": target_username,
            "downloaded_messages": len(processed_msgs),
            "new_inserted_messages": inserted_count,
            "total_messages_in_db": len(all_msgs),
            "chunks_rebuilt": rebuild_res["chunks_rebuilt"],
            "summary_card": summary_card
        }

    def rebuild_vectors(
        self,
        target_username: str,
        db_path: Optional[Any] = None
    ) -> Dict[str, Any]:
        """
        從 SQLite 中已儲存的訊息重建 ChromaDB 向量庫。
        不需要登入 IG，適合 embedding 失敗後的本地修復。
        """
        contact_row = get_contact_by_username(target_username, db_path=db_path)
        if not contact_row:
            raise ValueError(f"尚未追蹤 {target_username}，請先使用 track 指令。")

        contact_id = contact_row["id"]
        all_msgs = get_all_messages(contact_id, db_path=db_path)
        if not all_msgs:
            raise ValueError(f"{target_username} 在本地資料庫尚無任何訊息紀錄。")

        # 轉換為 ingestion 標準格式
        msg_dicts = [
            {
                "ig_item_id": row["ig_item_id"],
                "sender": row["sender"],
                "content": row["content"],
                "sent_at": row["sent_at"],
            }
            for row in all_msgs
        ]

        # 先清除該 contact 舊有的 ChromaDB 向量，避免重複
        try:
            self.vector_store.collection.delete(
                where={"contact_id": contact_id}
            )
        except Exception:
            pass  # 若原本就是空的，忽略

        chunks = self.chunk_messages(msg_dicts)
        self.vector_store.add_chunks(contact_id=contact_id, chunks=chunks)

        return {
            "contact_id": contact_id,
            "target_username": target_username,
            "total_messages": len(msg_dicts),
            "chunks_rebuilt": len(chunks),
        }

