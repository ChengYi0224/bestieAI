"""
vectors.py — 向後相容轉發層。核心實作已重構至 app.storage.chroma_store.ChromaStore。
"""
from app.storage.chroma_store import ChromaStore, VectorStore

__all__ = ["ChromaStore", "VectorStore"]
