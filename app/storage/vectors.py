"""
vectors.py — ChromaDB 向量資料庫封裝。

功能：
- 支援 Gemini Embedding 2 Batch API 批次嵌入
- 支援 output_dimensionality=768 維度限制（大幅降低延遲與空間）
- 支援傳入既有 query_embedding 共享單次 Embedding，消除重複 API 呼叫
"""
import re
import time
import uuid
import logging
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional
import chromadb
from google import genai
from google.genai import types

from app.core.config import settings
from app.core.rate_limit import gemini_retry

logger = logging.getLogger("bestieAI.vectors")

# ==================== 可調參數與維度設定 (Tunable Constants) ====================
# 預設 Embedding 模型名稱
DEFAULT_EMBEDDING_MODEL: str = getattr(settings, "GEMINI_EMBEDDING_MODEL", "gemini-embedding-2")

# 向量輸出維度（MRL 768 維）
DEFAULT_EMBEDDING_DIMENSIONALITY: int = getattr(settings, "EMBEDDING_DIMENSIONALITY", 768)

# 向量空間度量方式（cosine / l2 / ip）
DEFAULT_DISTANCE_METRIC: str = "cosine"

# Gemini 批次 Embedding API 單次最大請求筆數上限（官方硬限制為 100）
MAX_EMBEDDING_BATCH_SIZE: int = 100


class VectorStore:
    def __init__(
        self,
        chroma_path: Optional[Path] = None,
        embedding_model: Optional[str] = None,
        collection_name: str = "chat_chunks"
    ):
        path = chroma_path or settings.CHROMA_PATH
        path.mkdir(parents=True, exist_ok=True)
        self.embedding_model = embedding_model or settings.GEMINI_EMBEDDING_MODEL
        self.collection_name = collection_name
        self.client = chromadb.PersistentClient(path=str(path))
        self.collection = self.client.get_or_create_collection(
            name=collection_name,
            metadata={"hnsw:space": "cosine"}
        )
        self._genai_client = None

    @property
    def genai_client(self) -> genai.Client:
        if self._genai_client is None:
            if not settings.GEMINI_API_KEY:
                raise ValueError("GEMINI_API_KEY is not set in environment or .env")
            self._genai_client = genai.Client(api_key=settings.GEMINI_API_KEY)
        return self._genai_client

    def get_embeddings_batch(self, texts: List[str]) -> List[List[float]]:
        """
        使用 Gemini 批次 API 向量化多筆文本，並指定 768 維度。
        若 texts 超過單次批次上限 (100 筆)，自動分段批次處理並合併回傳。
        具備 Google Free Tier 每分鐘配額 (100 requests/min) 智慧感應與自動退避等待機制。
        """
        if not texts:
            return []

        config = None
        dim = getattr(settings, "EMBEDDING_DIMENSIONALITY", DEFAULT_EMBEDDING_DIMENSIONALITY)
        if dim:
            config = types.EmbedContentConfig(output_dimensionality=dim)

        all_embeddings: List[List[float]] = []
        total_batches = (len(texts) + MAX_EMBEDDING_BATCH_SIZE - 1) // MAX_EMBEDDING_BATCH_SIZE

        for batch_idx, i in enumerate(range(0, len(texts), MAX_EMBEDDING_BATCH_SIZE)):
            batch = texts[i:i + MAX_EMBEDDING_BATCH_SIZE]
            content_items = [
                types.Content(parts=[types.Part.from_text(text=t)])
                for t in batch
            ]

            max_retries = 5
            for attempt in range(max_retries):
                try:
                    response = self.genai_client.models.embed_content(
                        model=self.embedding_model,
                        contents=content_items,
                        config=config
                    )
                    all_embeddings.extend([emb.values for emb in response.embeddings])
                    break
                except Exception as e:
                    err_msg = str(e)
                    is_rate_limit = "429" in err_msg or "RESOURCE_EXHAUSTED" in err_msg
                    if is_rate_limit and attempt < max_retries - 1:
                        wait_sec = 60.0
                        m = re.search(r"retry in ([\d\.]+)s", err_msg)
                        if not m:
                            m = re.search(r"retryDelay': '(\d+)s'", err_msg)
                        if m:
                            wait_sec = float(m.group(1)) + 2.0
                        logger.warning(
                            f"Gemini Embedding 達到每分鐘配額上限 (429)，自動等待 {wait_sec:.1f} 秒重置配額視窗 (批次 {batch_idx + 1}/{total_batches})..."
                        )
                        time.sleep(wait_sec)
                    else:
                        raise

        return all_embeddings

    def get_embedding(self, text: str) -> List[float]:
        """取得單一文本向量。"""
        embeddings = self.get_embeddings_batch([text])
        return embeddings[0]

    def add_chunks(self, contact_id: int, chunks: List[Dict[str, Any]]) -> None:
        """批次將歷史 chunks 或事件片段寫入向量庫。"""
        if not chunks:
            return

        documents = [c["text"] for c in chunks]
        metadatas = [
            {
                "contact_id": contact_id,
                "start_time": str(c.get("start_time", "")),
                "end_time": str(c.get("end_time", "")),
                "message_count": int(c.get("message_count", 1)),
                "type": str(c.get("type", "chat_chunk"))
            }
            for c in chunks
        ]
        ids = [f"contact_{contact_id}_{c['id']}" for c in chunks]
        embeddings = self.get_embeddings_batch(documents)

        self.collection.upsert(
            ids=ids,
            documents=documents,
            metadatas=metadatas,
            embeddings=embeddings
        )

    def query(
        self,
        contact_id: int,
        query_text: Optional[str] = None,
        query_embedding: Optional[List[float]] = None,
        n_results: int = 5
    ) -> List[Dict[str, Any]]:
        """
        支援共享 query_embedding 或傳入 query_text。
        若提供 query_embedding，則不再發送網路請求取得向量。
        """
        target_emb = query_embedding
        if target_emb is None:
            if not query_text:
                return []
            target_emb = self.get_embedding(query_text)

        results = self.collection.query(
            query_embeddings=[target_emb],
            where={"contact_id": contact_id},
            n_results=n_results
        )

        matches = []
        if results and results.get("documents") and results["documents"][0]:
            docs = results["documents"][0]
            metas = results.get("metadatas", [[]])[0]
            dists = results.get("distances", [[]])[0] if results.get("distances") else [None] * len(docs)
            for doc, meta, dist in zip(docs, metas, dists):
                matches.append({
                    "text": doc,
                    "metadata": meta,
                    "distance": dist
                })
        return matches

    def add_self_chunk(self, text: str, chunk_id: Optional[str] = None) -> str:
        """寫入使用者自身記憶 chunk 到向量庫。"""
        cid = chunk_id or f"self_{uuid.uuid4().hex[:12]}"
        now_str = datetime.utcnow().isoformat()
        embedding = self.get_embedding(text)
        self.collection.upsert(
            ids=[cid],
            documents=[text],
            metadatas=[{"created_at": now_str, "type": "self_memory"}],
            embeddings=[embedding]
        )
        return cid

    def query_self(
        self,
        query_text: Optional[str] = None,
        query_embedding: Optional[List[float]] = None,
        n_results: int = 3
    ) -> List[Dict[str, Any]]:
        """檢索使用者自身記憶，支援共享向量與直接文字查詢。"""
        target_emb = query_embedding
        if target_emb is None:
            if not query_text:
                return []
            target_emb = self.get_embedding(query_text)

        results = self.collection.query(
            query_embeddings=[target_emb],
            n_results=n_results
        )

        matches = []
        if results and results.get("documents") and results["documents"][0]:
            docs = results["documents"][0]
            metas = results.get("metadatas", [[]])[0]
            dists = results.get("distances", [[]])[0] if results.get("distances") else [None] * len(docs)
            for doc, meta, dist in zip(docs, metas, dists):
                matches.append({
                    "text": doc,
                    "metadata": meta,
                    "distance": dist
                })
        return matches
