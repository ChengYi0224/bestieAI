"""
consolidation.py — 同質無損融合管線（Lossless Cluster Consolidation Pipeline）。
職責：
1. 自行讀取 events/consolidate_batch.txt 提示詞範本並組裝 XML Payload。
2. 支援一次打包最多 20 個獨立 Cluster 進行批次融合，大幅節省 90% 以上 RPD。
3. 孤立事件（單條）直接保留，0 外部請求。
4. 呼叫 GeminiClient 執行純文字生成，並呼叫解析工具萃取各群組結果。
"""
import time
import logging
from pathlib import Path
from typing import List, Dict, Any, Optional

from app.core.config import settings
from app.clients.gemini import GeminiClient
from app.utils.text import parse_cluster_results

logger = logging.getLogger("bestieAI.pipelines.consolidation")
PROMPT_PATH = Path(__file__).resolve().parent.parent / "prompts" / "events" / "consolidate_batch.txt"


class EventConsolidator:
    """同質無損融合器。"""

    def __init__(self, gemini_client: Optional[GeminiClient] = None, batch_size: int = 20):
        self.gemini_client = gemini_client or GeminiClient()
        self.batch_size = batch_size

    def consolidate(
        self,
        clusters: List[List[Dict[str, Any]]],
        progress_callback: Optional[Any] = None
    ) -> List[Dict[str, Any]]:
        """
        對所有分群結果進行無損融合：
        - 單條群組：直接放行保留（0 次 API 呼叫）。
        - 多條群組：以 20 群為一批次打包，組裝 XML 發送給 GeminiClient。
        """
        if not clusters:
            return []

        final_chunks: List[Dict[str, Any]] = []
        # 1. 孤立事件直接保留
        for c in clusters:
            if len(c) == 1:
                final_chunks.append(c[0])

        multi_clusters = [c for c in clusters if len(c) > 1]
        if not multi_clusters:
            return final_chunks

        total_multi = len(multi_clusters)
        pacing = getattr(settings, "GEMINI_PACING_DELAY", 4.2)
        template = PROMPT_PATH.read_text(encoding="utf-8")

        for batch_start in range(0, total_multi, self.batch_size):
            chunk_group = multi_clusters[batch_start:batch_start + self.batch_size]
            end_idx = min(batch_start + len(chunk_group), total_multi)
            if progress_callback:
                try:
                    progress_callback(f"同質事件融合中: 第 {batch_start + 1}~{end_idx}/{total_multi} 群...")
                except Exception:
                    pass

            # 2. 自己組裝多群組 XML 結構 Payload
            payload_blocks = []
            group_map = {}
            for g_idx, cluster in enumerate(chunk_group):
                cid = f"group_{batch_start + g_idx}"
                group_map[cid] = cluster
                ev_lines = "\n".join(f"- {c['text']}" for c in cluster)
                payload_blocks.append(f'<cluster id="{cid}">\n{ev_lines}\n</cluster>')

            prompt = template.format(clusters_payload="\n\n".join(payload_blocks))
            logger.info(f"批次打包融合 {len(chunk_group)} 個同主題群組 (進度 {batch_start + 1}~{end_idx}/{total_multi})...")

            try:
                raw_output = self.gemini_client.generate_text(
                    prompt,
                    preferred_model="gemini-3.5-flash-lite",
                    candidate_models=["gemini-3.5-flash-lite", "gemini-3.8-flash"]
                )

                if pacing > 0:
                    time.sleep(pacing)

                # 3. 解析結果
                results = parse_cluster_results(raw_output)

                # 4. 組裝最終 chunk，若該群組解析失敗則降級保留原事件
                for cid, cluster in group_map.items():
                    consolidated_texts = results.get(cid, [c["text"] for c in cluster])
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
                logger.warning(f"批次打包融合失敗，降級保留原事件: {e}")
                for cluster in chunk_group:
                    final_chunks.extend(cluster)

        return final_chunks
