"""
extraction.py — 事件提煉與時間滑動窗口管線（Temporal Event Extraction Pipeline）。
職責：
1. 依據自然靜默（6 小時）與目標容量（400 則 + 12 Overlap）進行對話時間感知滑動切塊。
2. 自行讀取 events/extract.txt 提示詞並組裝對話內容。
3. 呼叫 GeminiClient 執行微觀事件提煉（按客觀事實密度記錄，無條數限制）。
4. 每提煉完成一批次，立即增量寫入本地 SQLite 快取（status='raw'），阻斷中斷資料損失。
"""
import time
import logging
from pathlib import Path
from typing import List, Dict, Any, Optional

from app.core.config import settings
from app.clients.gemini import GeminiClient
from app.storage.db import save_contact_events
from app.utils import parse_time_str
from app.utils.text import parse_bullet_list, format_chat_messages


logger = logging.getLogger("bestieAI.pipelines.extraction")
PROMPT_PATH = Path(__file__).resolve().parent.parent / "prompts" / "events" / "extract.txt"


class EventExtractor:
    """事件提煉管線執行器。"""

    def __init__(
        self,
        gemini_client: Optional[GeminiClient] = None,
        target_batch_size: int = 800,
        max_batch_size: int = 1000,
        overlap_size: int = 12,
        session_gap_hours: float = 6.0
    ):
        self.gemini_client = gemini_client or GeminiClient()
        self.target_batch_size = target_batch_size
        self.max_batch_size = max_batch_size
        self.overlap_size = overlap_size
        self.session_gap_hours = session_gap_hours

    def slice_dialogue_batches(
        self,
        sorted_msgs: List[Dict[str, Any]],
        target_size: Optional[int] = None,
        max_size: Optional[int] = None,
        overlap_size: Optional[int] = None,
        gap_hours: Optional[float] = None
    ) -> List[List[Dict[str, Any]]]:
        """時間感知對話滑動窗口切塊。"""
        if not sorted_msgs:
            return []

        tgt = target_size or self.target_batch_size
        hard_max = max_size or self.max_batch_size
        ovlp = overlap_size if overlap_size is not None else self.overlap_size
        silent_gap = gap_hours if gap_hours is not None else self.session_gap_hours

        batches = []
        n = len(sorted_msgs)
        start_idx = 0

        while start_idx < n:
            curr_batch = []
            curr_idx = start_idx
            prev_time = None

            while curr_idx < n:
                msg = sorted_msgs[curr_idx]
                try:
                    t = parse_time_str(msg["sent_at"])
                except Exception:
                    t = None

                if prev_time and t and len(curr_batch) >= (tgt // 2):
                    hours_diff = abs((t - prev_time).total_seconds()) / 3600.0
                    if hours_diff >= silent_gap:
                        break

                curr_batch.append(msg)
                prev_time = t
                curr_idx += 1

                if len(curr_batch) >= tgt or len(curr_batch) >= hard_max:
                    break

            batches.append(curr_batch)
            if curr_idx >= n:
                break

            start_idx = max(start_idx + 1, curr_idx - ovlp)

        return batches

    def extract_from_messages(
        self,
        messages: List[Dict[str, Any]],
        contact_id: Optional[int] = None,
        progress_callback: Optional[Any] = None,
        db_path: Optional[Any] = None
    ) -> List[Dict[str, Any]]:
        """執行切塊與事件提煉，每批次即時增量落盤。"""
        if not messages:
            return []

        sorted_msgs = sorted(messages, key=lambda m: m["sent_at"])
        batches = self.slice_dialogue_batches(sorted_msgs)
        event_chunks = []
        pacing = getattr(settings, "GEMINI_PACING_DELAY", 4.2)
        total_batches = len(batches)
        total_messages = len(sorted_msgs)
        logger.info(
            f"對話歷史共 {total_messages} 則訊息，切分為 {total_batches} 個時間感知批次"
            f"（目標 {self.target_batch_size} 則/批，重疊 {self.overlap_size} 則）"
        )
        if progress_callback:
            try:
                progress_callback(f"對話共 {total_messages} 則，切分為 {total_batches} 個批次，開始提煉事件...")
            except Exception:
                pass

        # 載入現有 raw 快取，支援斷點續傳
        existing_raw = []
        if contact_id:
            from app.storage.db import get_contact_events
            existing_raw = get_contact_events(contact_id=contact_id, status="raw", db_path=db_path)

        # 建立已存在的時間區間快取映射: (start_time, end_time) -> [events]
        cached_batch_map: Dict[tuple, List[Dict[str, Any]]] = {}
        for r in existing_raw:
            key = (r["start_time"], r["end_time"])
            if key not in cached_batch_map:
                cached_batch_map[key] = []
            cached_batch_map[key].append({
                "id": r["event_id"] or f"ev_{r['id']}",
                "text": r["content"],
                "start_time": r["start_time"],
                "end_time": r["end_time"],
                "message_count": r["message_count"] or 1,
                "type": "event_memory"
            })

        template = PROMPT_PATH.read_text(encoding="utf-8")

        for b_idx, batch in enumerate(batches):
            b_start = batch[0]["sent_at"]
            b_end = batch[-1]["sent_at"]
            cache_key = (b_start, b_end)

            # 斷點續傳命中：跳過已提煉批次
            if cache_key in cached_batch_map:
                hits = cached_batch_map[cache_key]
                event_chunks.extend(hits)
                msg = f"提煉事件中: 批次 {b_idx + 1}/{total_batches} (快取命中，跳過 API 呼叫，累計 {len(event_chunks)} 條)"
                logger.info(f"批次 {b_idx + 1}/{total_batches} 已有本機快取 ({len(hits)} 條事件，涵蓋 {len(batch)} 則訊息)，跳過呼叫")
                if progress_callback:
                    try:
                        progress_callback(msg)
                    except Exception:
                        pass
                continue

            if progress_callback:
                try:
                    progress_callback(f"提煉事件中: 批次 {b_idx + 1}/{total_batches} (處理 {len(batch)} 則訊息，目前累計 {len(event_chunks)} 條)...")
                except Exception:
                    pass

            conv_text = format_chat_messages(batch, other_label="對方")
            prompt = template.format(conversations_text=conv_text)

            batch_events = []
            try:
                raw_output = self.gemini_client.generate_text(
                    prompt,
                    preferred_model="gemini-3.5-flash-lite",
                    candidate_models=["gemini-3.5-flash-lite", "gemini-3.8-flash"]
                ).strip()

                items = parse_bullet_list(raw_output)
                for e_idx, line in enumerate(items):
                    item = {
                        "id": f"event_{b_idx}_{e_idx}",
                        "text": line,
                        "start_time": b_start,
                        "end_time": b_end,
                        "message_count": len(batch),
                        "type": "event_memory"
                    }
                    batch_events.append(item)
                    event_chunks.append(item)

            except Exception as ex:
                logger.warning(f"批次 {b_idx + 1}/{total_batches} 提煉失敗: {ex}")

            # 即時增量落盤至本地 SQLite
            if contact_id and batch_events:
                try:
                    save_contact_events(contact_id, batch_events, status="raw", db_path=db_path)
                    logger.info(
                        f"批次 {b_idx + 1}/{total_batches} 提煉完成 ({len(batch_events)} 條事件，涵蓋 {len(batch)} 則訊息)，已即時落盤"
                    )
                except Exception as e:
                    logger.warning(f"即時落盤失敗 (非致命): {e}")

            if progress_callback:
                try:
                    progress_callback(f"提煉事件中: 批次 {b_idx + 1}/{total_batches} 完成 (累計 {len(event_chunks)} 條事件)")
                except Exception:
                    pass

            if b_idx < total_batches - 1 and pacing > 0:
                time.sleep(pacing)

        return event_chunks
