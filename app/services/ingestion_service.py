"""
ingestion_service.py — 對話匯入、事件提煉與雙軌記憶管道。

革新：
- 徹底廢除破碎口語切塊直接向量化，改由 LLM 提煉出客觀事件記憶條目（Event Memory Snippets）再存入 ChromaDB。
- 記憶層級分離：全景長篇復盤儲存於 full_history_summary；日常對話僅使用 300~500 字精簡 summary_card。
- 支援增量同步 (sync)、慢速全量抓取 (track_full) 與本地向量重建 (rebuild_vectors)。
"""
import time
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional, Callable

from app.core.config import settings
from app.storage.db import (
    get_or_create_contact,
    save_messages,
    get_contact_by_id,
    get_contact_by_username,
    get_latest_message_time,
    update_contact_summary,
    update_contact_full_history,
    should_update_summary,
    get_recent_messages,
    get_all_messages,
)
from app.storage.vectors import VectorStore
from app.services.llm_service import LLMClient
from app.services.ig_service import IGClient

logger = logging.getLogger("bestieAI.ingestion_service")

# ==================== 可調參數與門檻設定 (Tunable Constants) ====================
# 向量餘弦相似度門檻（>= 此數值判定為同主題候選群）
SIMILARITY_THRESHOLD: float = getattr(settings, "EVENT_CLUSTER_SIMILARITY_THRESHOLD", 0.80)

# 時序向量分群最大時間差（小時，超過此時間差即使相似度高也不合併）
MAX_HOURS_GAP: float = getattr(settings, "EVENT_CLUSTER_MAX_HOURS_GAP", 36.0)

# 批次呼叫間隔節流延遲（秒，避開 15 RPM 上限）
PACING_DELAY: float = getattr(settings, "GEMINI_PACING_DELAY", 4.2)

# 事件提煉單批對話訊息筆數
EVENT_EXTRACTION_BATCH_SIZE: int = getattr(settings, "EVENT_EXTRACTION_BATCH_SIZE", 40)

# 傳統切塊單一 chunk 最大則數
CHUNK_MAX_SIZE: int = getattr(settings, "CHUNK_MAX_SIZE", 20)

# 觸發更新摘要卡的新訊息門檻與天數上限
SUMMARY_MESSAGE_THRESHOLD: int = getattr(settings, "SUMMARY_MESSAGE_THRESHOLD", 50)
SUMMARY_DAYS_LIMIT: int = getattr(settings, "SUMMARY_DAYS_LIMIT", 14)


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
    def _parse_time(time_str: str) -> Optional[datetime]:
        try:
            clean_str = time_str.replace("Z", "+00:00")
            return datetime.fromisoformat(clean_str)
        except Exception:
            return None

    @staticmethod
    def chunk_messages(messages: List[Dict[str, Any]], max_chunk_size: Optional[int] = None) -> List[Dict[str, Any]]:
        """保留傳統基於日期的切塊邏輯（相容既有單元測試與回退備案）。"""
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

    def extract_event_chunks(self, messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        核心革新：對話批次提煉為高密度事件記憶條目。
        每批對話萃取出 1~4 條帶時間戳的事實條目，避免破碎無效對話污染向量資料庫。
        """
        if not messages:
            return []

        sorted_msgs = sorted(messages, key=lambda m: m["sent_at"])
        batch_size = getattr(settings, "EVENT_EXTRACTION_BATCH_SIZE", 40)
        event_chunks = []

        for i in range(0, len(sorted_msgs), batch_size):
            batch = sorted_msgs[i:i + batch_size]
            formatted_lines = []
            for m in batch:
                sender_label = "我" if m["sender"] == "me" else "對方"
                formatted_lines.append(f"[{m['sent_at']}] {sender_label}: {m['content']}")
            conv_text = "\n".join(formatted_lines)

            try:
                events = self.llm_client.extract_events(conv_text)
                for e_idx, ev in enumerate(events):
                    event_chunks.append({
                        "id": f"event_{i}_{e_idx}",
                        "text": ev,
                        "start_time": batch[0]["sent_at"],
                        "end_time": batch[-1]["sent_at"],
                        "message_count": len(batch),
                        "type": "event_memory"
                    })
            except Exception as ex:
                logger.warning(f"事件提煉失敗，降級為傳統 chunk 切塊: {ex}")
                fallback = self._build_chunk_dict(len(event_chunks) + 1, batch)
                event_chunks.append(fallback)

            if i + batch_size < len(sorted_msgs):
                pacing = getattr(settings, "GEMINI_PACING_DELAY", 4.2)
                if pacing > 0:
                    time.sleep(pacing)

        return event_chunks

    @staticmethod
    def _cosine_similarity(vec_a: List[float], vec_b: List[float]) -> float:
        dot = sum(a * b for a, b in zip(vec_a, vec_b))
        norm_a = sum(a * a for a in vec_a) ** 0.5
        norm_b = sum(b * b for b in vec_b) ** 0.5
        if norm_a == 0.0 or norm_b == 0.0:
            return 0.0
        return dot / (norm_a * norm_b)

    @staticmethod
    def _parse_time_str(time_str: Optional[str]) -> Optional[datetime]:
        if not time_str:
            return None
        try:
            return datetime.fromisoformat(time_str)
        except Exception:
            pass
        try:
            return datetime.strptime(time_str[:10], "%Y-%m-%d")
        except Exception:
            return None

    def cluster_similar_events(
        self,
        chunks: List[Dict[str, Any]],
        similarity_threshold: Optional[float] = None,
        max_hours_gap: Optional[float] = None
    ) -> List[List[Dict[str, Any]]]:
        """
        時序感知語意向量分群（Temporal-aware Cosine Clustering）：
        1. 批次取得所有事件的 Embedding 向量。
        2. 若兩事件在時間差 <= max_hours_gap 且 Cosine Similarity >= similarity_threshold，
           則建立連結，透過連通元件（Connected Components）劃分 Cluster。
        """
        if not chunks or len(chunks) <= 1:
            return [[c] for c in chunks]

        sim_thresh = similarity_threshold if similarity_threshold is not None else getattr(
            settings, "EVENT_CLUSTER_SIMILARITY_THRESHOLD", 0.80
        )
        max_gap = max_hours_gap if max_hours_gap is not None else getattr(
            settings, "EVENT_CLUSTER_MAX_HOURS_GAP", 36.0
        )

        # 批次取得向量
        try:
            if hasattr(self.vector_store, "get_embeddings_batch"):
                texts = [c["text"] for c in chunks]
                embeddings = self.vector_store.get_embeddings_batch(texts)
            else:
                return [[c] for c in chunks]
        except Exception as e:
            logger.warning(f"取得分群向量失敗，跳過分群: {e}")
            return [[c] for c in chunks]

        n = len(chunks)
        parsed_times = []
        for c in chunks:
            t = self._parse_time_str(c.get("start_time"))
            if not t:
                text = c.get("text", "")
                if text.startswith("[") and len(text) >= 11 and text[1:11].count("-") == 2:
                    t = self._parse_time_str(text[1:11])
            parsed_times.append(t)

        adj: Dict[int, List[int]] = {i: [] for i in range(n)}
        for i in range(n):
            for j in range(i + 1, n):
                t_i, t_j = parsed_times[i], parsed_times[j]
                if t_i and t_j:
                    hours_diff = abs((t_i - t_j).total_seconds()) / 3600.0
                    if hours_diff > max_gap:
                        continue

                sim = self._cosine_similarity(embeddings[i], embeddings[j])
                if sim >= sim_thresh:
                    adj[i].append(j)
                    adj[j].append(i)

        visited = [False] * n
        clusters: List[List[Dict[str, Any]]] = []
        for i in range(n):
            if not visited[i]:
                component_indices = []
                queue = [i]
                visited[i] = True
                while queue:
                    curr = queue.pop(0)
                    component_indices.append(curr)
                    for neighbor in adj[curr]:
                        if not visited[neighbor]:
                            visited[neighbor] = True
                            queue.append(neighbor)
                clusters.append([chunks[idx] for idx in component_indices])

        return clusters

    def consolidate_event_chunks(self, chunks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        同質無損融合管線：
        1. 執行時序向量分群。
        2. 孤立事件直接保留。
        3. Cluster >= 2 呼叫 Lite 模型無損融合去重，同主題融合細節、異主題各自保留。
        """
        if not chunks or len(chunks) <= 1:
            return chunks

        clusters = self.cluster_similar_events(chunks)
        final_chunks: List[Dict[str, Any]] = []
        pacing = getattr(settings, "GEMINI_PACING_DELAY", 4.2)

        for cluster in clusters:
            if len(cluster) == 1:
                final_chunks.append(cluster[0])
                continue

            cluster_texts = [c["text"] for c in cluster]
            try:
                consolidated_texts = self.llm_client.consolidate_events(cluster_texts)
                if pacing > 0:
                    time.sleep(pacing)

                valid_starts = [c.get("start_time", "") for c in cluster if c.get("start_time")]
                valid_ends = [c.get("end_time", "") for c in cluster if c.get("end_time")]
                min_start = min(valid_starts) if valid_starts else ""
                max_end = max(valid_ends) if valid_ends else ""
                total_msgs = sum(c.get("message_count", 1) for c in cluster)

                for k, text in enumerate(consolidated_texts):
                    final_chunks.append({
                        "id": f"{cluster[0]['id']}_c{k}",
                        "text": text,
                        "start_time": min_start,
                        "end_time": max_end,
                        "message_count": total_msgs,
                        "type": "event_memory"
                    })
            except Exception as e:
                logger.warning(f"無損融合失敗，保留原事件: {e}")
                final_chunks.extend(cluster)

        return final_chunks

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

        display_name = contact.get("display_name") or contact.get("ig_account_id") or "對方"
        old_summary = contact.get("summary_card")
        if old_summary and hasattr(self.llm_client, "update_summary"):
            new_summary = self.llm_client.update_summary(
                display_name=display_name,
                old_summary=old_summary,
                new_conversations_text=conv_text
            )
        else:
            new_summary = self.llm_client.generate_summary(conv_text)

        update_contact_summary(contact_id, new_summary, db_path=db_path)
        return str(new_summary)

    def build_full_history_summary(
        self,
        target_username: str,
        db_path: Optional[Any] = None
    ) -> Dict[str, Any]:
        """
        生成全景關係復盤長文（存入 full_history_summary），
        同時自動提煉 300~500 字日常輕量卡（更新 summary_card）。
        """
        contact_row = get_contact_by_username(target_username, db_path=db_path)
        if not contact_row:
            raise ValueError(f"尚未追蹤 {target_username}，請先使用 track 指令。")

        contact_id = contact_row["id"]
        display_name = contact_row["display_name"] or contact_row["ig_account_id"]

        all_msgs = get_all_messages(contact_id, db_path=db_path)
        if not all_msgs:
            raise ValueError(f"{target_username} 在本地資料庫尚無任何訊息紀錄。")

        formatted_lines = []
        for m in all_msgs:
            sender_label = "我" if m["sender"] == "me" else "對方"
            formatted_lines.append(f"[{m['sent_at']}] {sender_label}: {m['content']}")
        full_text = "\n".join(formatted_lines)

        # 1. 深度生成 7 大章節全景長篇復盤
        full_history_summary = self.llm_client.generate_full_history_summary(
            display_name=display_name,
            full_conversations_text=full_text
        )
        update_contact_full_history(contact_id, full_history_summary, db_path=db_path)
        update_contact_summary(contact_id, full_history_summary, db_path=db_path)

        return {
            "contact_id": contact_id,
            "target_username": target_username,
            "total_messages": len(all_msgs),
            "summary_card": full_history_summary,
            "full_history_summary": full_history_summary
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

        # 批次萃取事件條目並寫入向量庫
        chunks = self.extract_event_chunks(processed_msgs)
        if chunks:
            chunks = self.consolidate_event_chunks(chunks)
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

        # 萃取事件記憶
        chunks = self.extract_event_chunks(processed_msgs)
        if chunks:
            chunks = self.consolidate_event_chunks(chunks)
            self.vector_store.add_chunks(contact_id=contact_id, chunks=chunks)

        all_text = "\n".join([f"{'我' if m['sender']=='me' else '對方'}: {m['content']}" for m in processed_msgs])
        summary_card = self.llm_client.generate_concise_summary(all_text[:4000])
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
        """慢速防風控全量抓取指定對象的歷史訊息並重構向量庫。"""
        thread = ig_client.get_thread_by_username(target_username)
        if not thread:
            raise ValueError(f"找不到與 {target_username} 的私訊對話串")

        thread_id = str(thread.id)
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
        inserted_count = save_messages(contact_id=contact_id, messages=processed_msgs, db_path=db_path)

        # 重建向量資料庫
        rebuild_res = self.rebuild_vectors(target_username, db_path=db_path)

        # 重新生成人物關係日常摘要卡
        all_msgs = get_all_messages(contact_id, db_path=db_path)
        all_text = "\n".join([f"{'我' if m['sender']=='me' else '對方'}: {m['content']}" for m in all_msgs])
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
        """從本地 SQLite 重建向量庫（事件條目化向量化）。"""
        contact_row = get_contact_by_username(target_username, db_path=db_path)
        if not contact_row:
            raise ValueError(f"尚未追蹤 {target_username}，請先使用 track 指令。")

        contact_id = contact_row["id"]
        all_msgs = get_all_messages(contact_id, db_path=db_path)
        if not all_msgs:
            raise ValueError(f"{target_username} 在本地資料庫尚無任何訊息紀錄。")

        msg_dicts = [
            {
                "ig_item_id": row["ig_item_id"],
                "sender": row["sender"],
                "content": row["content"],
                "sent_at": row["sent_at"],
            }
            for row in all_msgs
        ]

        try:
            self.vector_store.collection.delete(
                where={"contact_id": contact_id}
            )
        except Exception:
            pass

        chunks = self.extract_event_chunks(msg_dicts)
        if chunks:
            chunks = self.consolidate_event_chunks(chunks)
        else:
            chunks = self.chunk_messages(msg_dicts)
        self.vector_store.add_chunks(contact_id=contact_id, chunks=chunks)

        return {
            "contact_id": contact_id,
            "target_username": target_username,
            "total_messages": len(msg_dicts),
            "chunks_rebuilt": len(chunks),
        }
