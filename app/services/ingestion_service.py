"""
ingestion_service.py — 對話資料匯入與管線調度服務（Ingestion Orchestration Service）。
職責：
- 作為高階調度器，協調整合四大專責管線：
  1. app.pipelines.extraction.EventExtractor（時間感知對話切塊與提煉）
  2. app.pipelines.clustering.EventClusterer（Complete Linkage 向量分群）
  3. app.pipelines.consolidation.EventConsolidator（20 群批次無損融合）
  4. app.pipelines.summarization.Summarizer（人物摘要卡與全景復盤）
- 負責對話重建與向量庫同步（rebuild_vectors）。
"""
import time
import logging
from datetime import datetime
from typing import List, Dict, Any, Optional

from app.core.config import settings
from app.clients.gemini import GeminiClient
from app.storage.chroma_store import ChromaStore, VectorStore
from app.storage.db import (
    get_active_contact,
    get_messages,
    get_recent_messages,
    update_contact_summary,
    save_contact_events,
    get_contact_events,
    clear_contact_events,
)
from app.pipelines.clustering import EventClusterer, cosine_similarity
from app.pipelines.consolidation import EventConsolidator
from app.pipelines.extraction import EventExtractor
from app.pipelines.summarization import Summarizer

logger = logging.getLogger("bestieAI.ingestion_service")

# ==================== 可調參數與門檻設定 (Tunable Constants) ====================
SIMILARITY_THRESHOLD: float = getattr(settings, "EVENT_CLUSTER_SIMILARITY_THRESHOLD", 0.90)
MAX_HOURS_GAP: float = getattr(settings, "EVENT_CLUSTER_MAX_HOURS_GAP", 24.0)
MAX_CLUSTER_SIZE: int = getattr(settings, "EVENT_MAX_CLUSTER_SIZE", 4)
PACING_DELAY: float = getattr(settings, "GEMINI_PACING_DELAY", 4.2)
EVENT_EXTRACTION_BATCH_SIZE: int = getattr(settings, "EVENT_EXTRACTION_BATCH_SIZE", 800)
EVENT_EXTRACTION_MAX_SIZE: int = getattr(settings, "EVENT_EXTRACTION_MAX_SIZE", 1000)
EVENT_EXTRACTION_OVERLAP_SIZE: int = getattr(settings, "EVENT_EXTRACTION_OVERLAP_SIZE", 12)
EVENT_EXTRACTION_SESSION_GAP_HOURS: float = getattr(settings, "EVENT_EXTRACTION_SESSION_GAP_HOURS", 6.0)
CLUSTERS_CONSOLIDATION_BATCH_SIZE: int = getattr(settings, "CLUSTERS_CONSOLIDATION_BATCH_SIZE", 20)
CHUNK_MAX_SIZE: int = getattr(settings, "CHUNK_MAX_SIZE", 20)
SUMMARY_MESSAGE_THRESHOLD: int = getattr(settings, "SUMMARY_MESSAGE_THRESHOLD", 50)
SUMMARY_DAYS_LIMIT: int = getattr(settings, "SUMMARY_DAYS_LIMIT", 14)


class IngestionPipeline:
    """資料匯入與管線調度器。"""

    def __init__(
        self,
        vector_store: Optional[ChromaStore] = None,
        llm_client: Optional[Any] = None,
        gemini_client: Optional[GeminiClient] = None
    ):
        self.vector_store = vector_store or ChromaStore()
        self.llm_client = llm_client
        self.gemini_client = gemini_client or GeminiClient()

        # 初始化專責管線
        self.clusterer = EventClusterer(
            similarity_threshold=SIMILARITY_THRESHOLD,
            max_hours_gap=MAX_HOURS_GAP,
            max_cluster_size=MAX_CLUSTER_SIZE
        )
        self.consolidator = EventConsolidator(
            gemini_client=self.gemini_client,
            batch_size=CLUSTERS_CONSOLIDATION_BATCH_SIZE
        )
        self.extractor = EventExtractor(
            gemini_client=self.gemini_client,
            target_batch_size=EVENT_EXTRACTION_BATCH_SIZE,
            max_batch_size=EVENT_EXTRACTION_MAX_SIZE,
            overlap_size=EVENT_EXTRACTION_OVERLAP_SIZE,
            session_gap_hours=EVENT_EXTRACTION_SESSION_GAP_HOURS
        )
        self.summarizer = Summarizer(gemini_client=self.gemini_client)

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

    def _slice_dialogue_batches(self, *args, **kwargs) -> List[List[Dict[str, Any]]]:
        """向後相容轉發：呼叫 EventExtractor 的切塊方法。"""
        return self.extractor.slice_dialogue_batches(*args, **kwargs)

    def extract_event_chunks(
        self,
        messages: List[Dict[str, Any]],
        contact_id: Optional[int] = None,
        progress_callback: Optional[Any] = None,
        db_path: Optional[Any] = None
    ) -> List[Dict[str, Any]]:
        """向後相容轉發：呼叫 EventExtractor 提煉事件。若提供 mock llm_client 則優先相容。"""
        if self.llm_client and hasattr(self.llm_client, "extract_events"):
            # 相容單元測試 mock
            sorted_msgs = sorted(messages, key=lambda m: m["sent_at"])
            batches = self.extractor.slice_dialogue_batches(sorted_msgs)
            chunks = []
            for b_idx, batch in enumerate(batches):
                lines = [f"[{m['sent_at']}] {'我' if m['sender'] == 'me' else '對方'}: {m['content']}" for m in batch]
                events = self.llm_client.extract_events("\n".join(lines))
                for e_idx, ev in enumerate(events):
                    chunks.append({
                        "id": f"event_{b_idx}_{e_idx}",
                        "text": ev,
                        "start_time": batch[0]["sent_at"],
                        "end_time": batch[-1]["sent_at"],
                        "message_count": len(batch),
                        "type": "event_memory"
                    })
            return chunks
        return self.extractor.extract_from_messages(
            messages,
            contact_id=contact_id,
            progress_callback=progress_callback,
            db_path=db_path
        )

    @staticmethod
    def _cosine_similarity(vec_a: List[float], vec_b: List[float]) -> float:
        return cosine_similarity(vec_a, vec_b)

    def _parse_time_str(self, time_str: Optional[str]) -> Optional[datetime]:
        from app.pipelines.clustering import parse_time_str
        return parse_time_str(time_str)

    def cluster_similar_events(
        self,
        chunks: List[Dict[str, Any]],
        similarity_threshold: Optional[float] = None,
        max_hours_gap: Optional[float] = None,
        max_cluster_size: Optional[int] = None,
        progress_callback: Optional[Any] = None
    ) -> List[List[Dict[str, Any]]]:
        """向後相容轉發：呼叫 EventClusterer 分群。"""
        if not chunks or len(chunks) <= 1:
            return [[c] for c in chunks]

        # 取得向量
        if progress_callback:
            try:
                progress_callback(f"計算 {len(chunks)} 條事件向量 Embeddings 中...")
            except Exception:
                pass

        try:
            texts = [c["text"] for c in chunks]
            embeddings = self.vector_store.get_embeddings_batch(texts)
        except Exception as e:
            logger.warning(f"取得分群向量失敗，跳過分群: {e}")
            return [[c] for c in chunks]

        if progress_callback:
            try:
                progress_callback(f"進行時序 Complete Linkage 向量分群中...")
            except Exception:
                pass

        clusterer = EventClusterer(
            similarity_threshold=similarity_threshold,
            max_hours_gap=max_hours_gap,
            max_cluster_size=max_cluster_size
        )
        return clusterer.cluster(chunks, embeddings)

    def consolidate_event_chunks(
        self,
        chunks: List[Dict[str, Any]],
        precomputed_clusters: Optional[List[List[Dict[str, Any]]]] = None,
        progress_callback: Optional[Any] = None
    ) -> List[Dict[str, Any]]:
        """向後相容轉發：呼叫 EventConsolidator 無損融合。相容 mock llm_client。"""
        if not chunks or len(chunks) <= 1:
            return chunks

        clusters = precomputed_clusters if precomputed_clusters is not None else self.cluster_similar_events(chunks, progress_callback=progress_callback)

        # 優先檢查相容單元測試 mock 的 llm_client
        if self.llm_client:
            final_chunks = [c[0] for c in clusters if len(c) == 1]
            multi_clusters = [c for c in clusters if len(c) > 1]
            for batch_start in range(0, len(multi_clusters), CLUSTERS_CONSOLIDATION_BATCH_SIZE):
                chunk_group = multi_clusters[batch_start:batch_start + CLUSTERS_CONSOLIDATION_BATCH_SIZE]
                group_dict = {f"group_{batch_start + g_idx}": [c["text"] for c in cluster] for g_idx, cluster in enumerate(chunk_group)}

                batch_results = None
                if hasattr(self.llm_client, "consolidate_clusters_batch"):
                    res = self.llm_client.consolidate_clusters_batch(group_dict)
                    if isinstance(res, dict):
                        batch_results = res
                if batch_results is None:
                    batch_results = {cid: self.llm_client.consolidate_events(texts) for cid, texts in group_dict.items()}

                for g_idx, cluster in enumerate(chunk_group):
                    cid = f"group_{batch_start + g_idx}"
                    texts = batch_results.get(cid, [c["text"] for c in cluster])
                    valid_starts = [c.get("start_time", "") for c in cluster if c.get("start_time")]
                    valid_ends = [c.get("end_time", "") for c in cluster if c.get("end_time")]
                    min_start = min(valid_starts) if valid_starts else ""
                    max_end = max(valid_ends) if valid_ends else ""
                    total_msgs = sum(c.get("message_count", 1) for c in cluster)
                    for k, t in enumerate(texts):
                        final_chunks.append({
                            "id": f"{cluster[0]['id']}_c{k}",
                            "text": t,
                            "start_time": min_start,
                            "end_time": max_end,
                            "message_count": total_msgs,
                            "type": "event_memory"
                        })
            return final_chunks

        return self.consolidator.consolidate(clusters, progress_callback=progress_callback)

    def check_and_update_summary(
        self,
        contact_id: Any,
        force: bool = False,
        threshold: Optional[int] = None,
        days_limit: Optional[int] = None,
        message_threshold: Optional[int] = None,
        db_path: Optional[Any] = None
    ) -> Optional[str]:
        """向後相容轉發：呼叫 Summarizer 或相容 mock llm_client。支援 username 字串或 contact_id 整數。"""
        from app.storage.db import (
            get_contact_by_username,
            get_contact_by_id,
            should_update_summary,
            get_recent_messages,
            update_contact_summary,
        )
        cid = contact_id
        if isinstance(contact_id, str):
            row = get_contact_by_username(contact_id, db_path=db_path)
            if not row:
                return None
            cid = row["id"]

        contact_row = get_contact_by_id(cid, db_path=db_path)
        if not contact_row:
            return None

        contact = dict(contact_row)
        thresh = threshold or message_threshold or settings.SUMMARY_MESSAGE_THRESHOLD
        if not force and not should_update_summary(contact, threshold=thresh, days_limit=days_limit):
            return None

        recent_msgs = get_recent_messages(cid, limit=50, db_path=db_path)
        if not recent_msgs:
            return None

        formatted_lines = []
        for m in recent_msgs:
            sender_label = "我" if m["sender"] == "me" else "對方"
            formatted_lines.append(f"[{m['sent_at']}] {sender_label}: {m['content']}")
        conv_text = "\n".join(formatted_lines)

        display_name = contact.get("display_name") or contact.get("ig_account_id") or "對方"
        old_summary = contact.get("summary_card")

        if self.llm_client and hasattr(self.llm_client, "update_summary") and old_summary:
            new_summary = self.llm_client.update_summary(
                display_name=display_name,
                old_summary=old_summary,
                new_conversations_text=conv_text
            )
        elif self.llm_client and hasattr(self.llm_client, "generate_summary"):
            new_summary = self.llm_client.generate_summary(conv_text)
        else:
            new_summary = self.summarizer.generate_concise_summary(conv_text)

        update_contact_summary(cid, new_summary, db_path=db_path)
        return str(new_summary) if new_summary else None

    def rebuild_summary_for_contact(self, contact_id: int, db_path: Optional[Any] = None) -> bool:
        """為指定聯絡人重新生成全景復盤與精簡日常卡。"""
        res = self.check_and_update_summary(contact_id, force=True, db_path=db_path)
        return res is not None

    def rebuild_vectors(
        self,
        contact_id: Any,
        progress_callback: Optional[Any] = None,
        db_path: Optional[Any] = None
    ) -> Dict[str, Any]:
        """
        為特定聯絡人重建向量資料庫：支援 username 字串或 contact_id 整數。
        """
        cid = contact_id
        target_username = str(contact_id)
        if isinstance(contact_id, str):
            from app.storage.db import get_contact_by_username
            row = get_contact_by_username(contact_id, db_path=db_path)
            if not row:
                logger.warning(f"聯絡人不存在: {contact_id}")
                return {"contact_id": 0, "target_username": contact_id, "total_messages": 0, "chunks_rebuilt": 0}
            cid = row["id"]
            target_username = row["ig_account_id"]
        else:
            from app.storage.db import get_contact_by_id
            row = get_contact_by_id(cid, db_path=db_path)
            if row:
                target_username = row["ig_account_id"]

        contact = get_active_contact(contact_id=cid, db_path=db_path)
        if not contact:
            logger.warning(f"聯絡人不存在: {cid}")
            return {"contact_id": cid, "target_username": target_username, "total_messages": 0, "chunks_rebuilt": 0}

        if progress_callback:
            try:
                progress_callback(f"正在讀取 {target_username} 本地對話紀錄...")
            except Exception:
                pass

        messages = get_messages(contact_id=cid, db_path=db_path)
        total_msgs = len(messages) if messages else 0

        if not messages:
            logger.info(f"聯絡人 {target_username} 無任何訊息。")
            if progress_callback:
                try:
                    progress_callback(f"聯絡人 {target_username} 無任何歷史對話。")
                except Exception:
                    pass
            return {"contact_id": cid, "target_username": target_username, "total_messages": 0, "chunks_rebuilt": 0}

        # 由 extract_event_chunks（EventExtractor）內部依時間區間自動判斷命中與增量補提煉
        event_chunks = self.extract_event_chunks(messages, contact_id=cid, progress_callback=progress_callback, db_path=db_path)

        if not event_chunks:
            msg_dicts = [dict(m) for m in messages]
            final_chunks = self.chunk_messages(msg_dicts)
        else:
            final_chunks = self.consolidate_event_chunks(event_chunks, progress_callback=progress_callback)

        if not final_chunks:
            return {"contact_id": cid, "target_username": target_username, "total_messages": total_msgs, "chunks_rebuilt": 0}

        # 寫入 ChromaDB
        if progress_callback:
            try:
                progress_callback(f"正在寫入 ChromaDB 向量庫 (共 {len(final_chunks)} 條記憶)...")
            except Exception:
                pass

        try:
            self.vector_store.collection.delete(where={"contact_id": cid})
        except Exception:
            try:
                self.vector_store.delete_chunks_by_contact(cid)
            except Exception:
                pass
        self.vector_store.add_chunks(contact_id=cid, chunks=final_chunks)

        # 持久化已融合的條目
        try:
            save_contact_events(cid, final_chunks, status="consolidated", db_path=db_path)
        except Exception as e:
            logger.warning(f"持久化 consolidated 事件失敗: {e}")

        logger.info(f"成功為 contact_id={cid} 重建 {len(final_chunks)} 條向量記憶。")
        if progress_callback:
            try:
                progress_callback(f"向量庫重建完成！共寫入 {len(final_chunks)} 條向量記憶")
            except Exception:
                pass

        return {
            "contact_id": cid,
            "target_username": target_username,
            "total_messages": total_msgs,
            "chunks_rebuilt": len(final_chunks),
        }

    def run_full_ingestion(
        self,
        ig_client: Any,
        target_username: str,
        max_amount: int = 5000,
        progress_callback: Optional[Any] = None,
        db_path: Optional[Any] = None
    ) -> Dict[str, Any]:
        """慢速防風控全量抓取指定對象的歷史訊息並重構向量庫。"""
        from app.storage.db import get_or_create_contact, save_messages, get_all_messages
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

        if progress_callback:
            try:
                progress_callback(f"私訊抓取完成 ({len(raw_messages)} 則)，已存入資料庫，準備重建向量記憶...")
            except Exception:
                pass

        # 重建向量資料庫
        rebuild_res = self.rebuild_vectors(contact_id, progress_callback=progress_callback, db_path=db_path)

        if progress_callback:
            try:
                progress_callback("正在生成人物關係日常摘要卡...")
            except Exception:
                pass

        # 重新生成人物關係日常摘要卡
        all_msgs = get_all_messages(contact_id, db_path=db_path)
        all_text = "\n".join([f"{'我' if m['sender']=='me' else '對方'}: {m['content']}" for m in all_msgs])
        context_for_summary = all_text[-4000:] if len(all_text) <= 6000 else (all_text[:2000] + "\n...\n" + all_text[-4000:])
        if self.llm_client and hasattr(self.llm_client, "generate_summary"):
            summary_card = self.llm_client.generate_summary(context_for_summary)
        elif self.llm_client and hasattr(self.llm_client, "generate_concise_summary"):
            summary_card = self.llm_client.generate_concise_summary(all_text)
        else:
            summary_card = self.summarizer.generate_concise_summary(all_text)

        update_contact_summary(contact_id, summary_card, db_path=db_path)

        return {
            "contact_id": contact_id,
            "target_username": target_username,
            "downloaded_messages": len(raw_messages),
            "new_inserted_messages": inserted_count,
            "total_messages_in_db": len(all_msgs),
            "chunks_rebuilt": rebuild_res["chunks_rebuilt"],
            "summary_card": summary_card,
        }

    def build_full_history_summary(
        self,
        target_username: str,
        progress_callback: Optional[Any] = None,
        db_path: Optional[Any] = None
    ) -> Dict[str, Any]:
        """生成全景關係復盤長文。"""
        from app.storage.db import get_contact_by_username, get_all_messages, update_contact_summary, get_contact_by_id
        if progress_callback:
            try:
                progress_callback(f"正在讀取 {target_username} 之完整歷史對話紀錄...")
            except Exception:
                pass

        contact_row = get_contact_by_username(target_username, db_path=db_path)
        if not contact_row:
            raise ValueError(f"尚未追蹤 {target_username}，請先使用 track 指令。")

        contact_id = contact_row["id"]
        all_msgs = get_all_messages(contact_id, db_path=db_path)
        if not all_msgs:
            raise ValueError(f"聯絡人 {target_username} 無任何對話紀錄。")

        if progress_callback:
            try:
                progress_callback(f"共 {len(all_msgs)} 則對話，正在呼叫 LLM 進行 7 大維度全景深度復盤分析...")
            except Exception:
                pass

        all_text = "\n".join([f"[{m['sent_at']}] {'我' if m['sender']=='me' else '對方'}: {m['content']}" for m in all_msgs])
        if self.llm_client and hasattr(self.llm_client, "generate_full_history_summary"):
            full_summary = self.llm_client.generate_full_history_summary(all_text)
        else:
            full_summary = self.summarizer.generate_full_summary(all_text)

        if progress_callback:
            try:
                progress_callback("全景復盤長文已生成，正在更新資料庫與摘要卡...")
            except Exception:
                pass

        from app.storage.db import update_full_history_summary, update_contact_summary
        update_full_history_summary(contact_id, full_summary, db_path=db_path)
        update_contact_summary(contact_id, full_summary, db_path=db_path)

        return {
            "contact_id": contact_id,
            "username": target_username,
            "total_messages": len(all_msgs),
            "summary_card": full_summary,
        }
