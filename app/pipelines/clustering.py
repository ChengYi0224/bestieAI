"""
clustering.py — 時序感知全連結向量分群管線（Temporal Complete Linkage Clustering）。
職責：
1. 接收候選記憶 chunks 及其 Embedding 向量。
2. 執行 Complete Linkage（團分群）：群內成員兩兩之間必須均滿足「時間差 <= max_hours_gap」與「相似度 >= similarity_threshold」。
3. 徹底阻斷 Single Linkage 的鏈狀串聯效應（Chaining Effect）。
4. 支援單群容量上限（max_cluster_size，預設 4 條）。
5. 純演算法與矩陣運算，100% 離線本地執行，不包含外部 API 網路請求。
"""
from datetime import datetime
from typing import List, Dict, Any, Optional

from app.core.config import settings


def parse_time_str(time_str: Optional[str]) -> Optional[datetime]:
    """安全解析 ISO 或 YYYY-MM-DD 格式時間字串。"""
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


def cosine_similarity(vec_a: List[float], vec_b: List[float]) -> float:
    """計算兩向量之餘弦相似度。"""
    dot = sum(a * b for a, b in zip(vec_a, vec_b))
    norm_a = sum(a * a for a in vec_a) ** 0.5
    norm_b = sum(b * b for b in vec_b) ** 0.5
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


class EventClusterer:
    """事件時序語意向量分群器。"""

    def __init__(
        self,
        similarity_threshold: Optional[float] = None,
        max_hours_gap: Optional[float] = None,
        max_cluster_size: Optional[int] = None
    ):
        self.similarity_threshold = (
            similarity_threshold if similarity_threshold is not None
            else getattr(settings, "EVENT_CLUSTER_SIMILARITY_THRESHOLD", 0.90)
        )
        self.max_hours_gap = (
            max_hours_gap if max_hours_gap is not None
            else getattr(settings, "EVENT_CLUSTER_MAX_HOURS_GAP", 24.0)
        )
        self.max_cluster_size = (
            max_cluster_size if max_cluster_size is not None
            else getattr(settings, "EVENT_MAX_CLUSTER_SIZE", 4)
        )

    def cluster(
        self,
        chunks: List[Dict[str, Any]],
        embeddings: List[List[float]]
    ) -> List[List[Dict[str, Any]]]:
        """
        使用 Complete Linkage 演算法對事件進行團分群。
        回傳 List of Clusters，每個 Cluster 包含 >= 1 條 chunks。
        """
        if not chunks or len(chunks) <= 1:
            return [[c] for c in chunks]

        n = len(chunks)
        parsed_times = []
        for c in chunks:
            t = parse_time_str(c.get("start_time"))
            if not t:
                text = c.get("text", "")
                if text.startswith("[") and len(text) >= 11 and text[1:11].count("-") == 2:
                    t = parse_time_str(text[1:11])
            parsed_times.append(t)

        clusters: List[List[int]] = []

        for i in range(n):
            t_i = parsed_times[i]
            best_cluster_idx = -1
            best_avg_sim = -1.0

            for c_idx, cluster in enumerate(clusters):
                if len(cluster) >= self.max_cluster_size:
                    continue

                can_join = True
                sim_sum = 0.0
                for member_idx in cluster:
                    t_m = parsed_times[member_idx]
                    if t_i and t_m:
                        hours_diff = abs((t_i - t_m).total_seconds()) / 3600.0
                        if hours_diff > self.max_hours_gap:
                            can_join = False
                            break

                    sim = cosine_similarity(embeddings[i], embeddings[member_idx])
                    if sim < self.similarity_threshold:
                        can_join = False
                        break
                    sim_sum += sim

                if can_join:
                    avg_sim = sim_sum / len(cluster)
                    if avg_sim > best_avg_sim:
                        best_avg_sim = avg_sim
                        best_cluster_idx = c_idx

            if best_cluster_idx >= 0:
                clusters[best_cluster_idx].append(i)
            else:
                clusters.append([i])

        return [[chunks[idx] for idx in c] for c in clusters]
