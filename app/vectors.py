import chromadb
import uuid
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional
from google import genai
from app.config import settings
from app.rate_limit import gemini_retry

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
    def genai_client(self):
        if self._genai_client is None:
            if not settings.GEMINI_API_KEY:
                raise ValueError("GEMINI_API_KEY is not set in environment or .env")
            self._genai_client = genai.Client(api_key=settings.GEMINI_API_KEY)
        return self._genai_client

    @gemini_retry(max_short_retries=3, base_delay=10.0)
    def get_embedding(self, text: str) -> List[float]:
        response = self.genai_client.models.embed_content(
            model=self.embedding_model,
            contents=text
        )
        return response.embeddings[0].values

    def add_chunks(self, contact_id: int, chunks: List[Dict[str, Any]]) -> None:
        if not chunks:
            return

        documents = [c["text"] for c in chunks]
        metadatas = [
            {
                "contact_id": contact_id,
                "start_time": str(c.get("start_time", "")),
                "end_time": str(c.get("end_time", "")),
                "message_count": int(c.get("message_count", 1))
            }
            for c in chunks
        ]
        ids = [f"contact_{contact_id}_{c['id']}" for c in chunks]
        embeddings = [self.get_embedding(doc) for doc in documents]

        self.collection.upsert(
            ids=ids,
            documents=documents,
            metadatas=metadatas,
            embeddings=embeddings
        )

    def query(self, contact_id: int, query_text: str, n_results: int = 5) -> List[Dict[str, Any]]:
        query_embedding = self.get_embedding(query_text)
        results = self.collection.query(
            query_embeddings=[query_embedding],
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

    def query_self(self, query_text: str, n_results: int = 3) -> List[Dict[str, Any]]:
        """檢索使用者自身記憶，不加 contact_id 過濾。"""
        query_embedding = self.get_embedding(query_text)
        results = self.collection.query(
            query_embeddings=[query_embedding],
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
