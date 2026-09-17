"""
chroma_store.py — ChromaDB 本地向量庫存取封裝。
職責：
1. 管理 PersistentClient 與 Collection（預設 cosine 空間）。
2. 提供向量 Chunk 寫入、刪除與相似度檢索（KNN）。
3. 計算 Embedding 委派給專責的 GeminiClient，本地儲存層不直接維護遠端連線邏輯。
"""
import uuid
import logging
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional
import chromadb

from app.core.config import settings
from app.clients.gemini import GeminiClient

logger = logging.getLogger("bestieAI.storage.chroma_store")


class ChromaStore:
    """本地 ChromaDB 向量庫存取封裝。"""

    def __init__(
        self,
        chroma_path: Optional[Path] = None,
        collection_name: str = "chat_chunks",
        gemini_client: Optional[GeminiClient] = None
    ):
        path = chroma_path or settings.CHROMA_PATH
        path.mkdir(parents=True, exist_ok=True)
        self.collection_name = collection_name
        self.client = chromadb.PersistentClient(path=str(path))
        self.collection = self.client.get_or_create_collection(
            name=collection_name,
            metadata={"hnsw:space": "cosine"}
        )
        self.gemini_client = gemini_client or GeminiClient()

    @property
    def _genai_client(self):
        return getattr(self.gemini_client, "_genai_client", None)

    @_genai_client.setter
    def _genai_client(self, client):
        self.gemini_client._genai_client = client

    def get_embeddings_batch(self, texts: List[str]) -> List[List[float]]:
        """委派給 GeminiClient 進行批次向量計算。"""
        return self.gemini_client.get_embeddings_batch(texts)

    def add_chunks(
        self,
        contact_id: int,
        chunks: List[Dict[str, Any]],
        precomputed_embeddings: Optional[List[List[float]]] = None
    ) -> int:
        """寫入對象的事件記憶 Chunks。"""
        if not chunks:
            return 0

        texts = [c["text"] for c in chunks]
        embeddings = precomputed_embeddings or self.get_embeddings_batch(texts)

        ids = []
        documents = []
        metadatas = []

        for i, c in enumerate(chunks):
            chunk_id = str(c.get("id") or f"chunk_{contact_id}_{uuid.uuid4().hex[:8]}")
            ids.append(chunk_id)
            documents.append(c["text"])

            meta = {
                "contact_id": int(contact_id),
                "type": c.get("type", "event_memory"),
                "message_count": int(c.get("message_count", 1)),
                "start_time": str(c.get("start_time") or ""),
                "end_time": str(c.get("end_time") or ""),
            }
            metadatas.append(meta)

        self.collection.add(
            ids=ids,
            embeddings=embeddings,
            documents=documents,
            metadatas=metadatas
        )
        return len(chunks)

    def add_self_chunk(self, text: str) -> str:
        """寫入使用者自身事實記憶。"""
        embeddings = self.get_embeddings_batch([text])
        chunk_id = f"self_{uuid.uuid4().hex[:8]}"
        self.collection.add(
            ids=[chunk_id],
            embeddings=embeddings,
            documents=[text],
            metadatas=[{"type": "self_memory", "created_at": datetime.now().isoformat()}]
        )
        return chunk_id

    def query(
        self,
        query_text: str,
        n_results: int = 5,
        where: Optional[Dict[str, Any]] = None,
        query_embedding: Optional[List[float]] = None,
        contact_id: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """執行向量相似度檢索（支援共享 query_embedding 避免重複計算）。

        Args:
            query_text: 查詢文字（當 query_embedding 未提供時用於計算向量）。
            n_results: 回傳筆數上限。
            where: ChromaDB where 過濾條件字典。
            query_embedding: 預先計算的 query 向量（共享用）。
            contact_id: 若提供，自動加入 contact_id 過濾（與 where 合併為 $and）。
        """
        # 建立完整 where 條件
        contact_filter: Optional[Dict[str, Any]] = (
            {"contact_id": int(contact_id)} if contact_id is not None else None
        )
        if contact_filter and where:
            effective_where: Optional[Dict[str, Any]] = {"$and": [contact_filter, where]}
        elif contact_filter:
            effective_where = contact_filter
        else:
            effective_where = where

        if query_embedding is None:
            embeddings = self.get_embeddings_batch([query_text])
            query_embedding = embeddings[0] if embeddings else None

        if query_embedding is None:
            return []

        kwargs: Dict[str, Any] = {
            "query_embeddings": [query_embedding],
            "n_results": n_results,
            "include": ["documents", "metadatas", "distances"]
        }
        if effective_where:
            kwargs["where"] = effective_where

        results = self.collection.query(**kwargs)
        records = []

        if results and results.get("ids") and len(results["ids"]) > 0:
            count = len(results["ids"][0])
            for i in range(count):
                doc = results["documents"][0][i]
                records.append({
                    "id": results["ids"][0][i],
                    "text": doc,
                    "document": doc,
                    "metadata": results["metadatas"][0][i] if results.get("metadatas") else {},
                    "distance": results["distances"][0][i] if results.get("distances") else 0.0,
                })
        return records


    def query_self(
        self,
        query_text: str,
        n_results: int = 3,
        query_embedding: Optional[List[float]] = None
    ) -> List[Dict[str, Any]]:
        """專門檢索使用者自身事實記憶。"""
        return self.query(
            query_text=query_text,
            n_results=n_results,
            where={"type": "self_memory"},
            query_embedding=query_embedding
        )

    def delete_chunks_by_contact(self, contact_id: int) -> None:
        """刪除特定聯絡人的所有向量資料。"""
        try:
            self.collection.delete(where={"contact_id": contact_id})
        except Exception as e:
            logger.warning(f"刪除 contact_id={contact_id} 向量資料失敗: {e}")


# 向後相容別名
VectorStore = ChromaStore
