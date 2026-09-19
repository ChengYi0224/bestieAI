"""test_chroma_isolation.py — ChromaDB 多用戶向量隔離測試。"""
import pytest
from app.storage.chroma_store import ChromaStore


def test_chroma_store_user_partition(tmp_path):
    """驗證不同 user_id 的向量庫 Collection 名稱與資料完全隔離。"""
    store_user1 = ChromaStore(chroma_path=tmp_path, collection_name="chat_chunks", user_id=1)
    store_user2 = ChromaStore(chroma_path=tmp_path, collection_name="chat_chunks", user_id=2)

    # 驗證 Collection 命名隔離
    assert store_user1.collection_name == "chat_chunks"
    assert store_user2.collection_name == "chat_chunks_2"

    dummy_vector = [0.1] * 768

    # 寫入 user_2 的記憶
    store_user2.add_chunks(
        contact_id=10,
        chunks=[{"id": "c_u2_1", "text": "User 2 私人對話紀錄"}],
        precomputed_embeddings=[dummy_vector],
    )

    # 寫入 user_1 的記憶
    store_user1.add_chunks(
        contact_id=10,
        chunks=[{"id": "c_u1_1", "text": "User 1 私人對話紀錄"}],
        precomputed_embeddings=[dummy_vector],
    )

    # 從 user_2 查詢，不應查到 user_1 的內容
    res_u2 = store_user2.query(query_text="", query_embedding=dummy_vector, n_results=10)
    assert len(res_u2) == 1
    assert res_u2[0]["text"] == "User 2 私人對話紀錄"
    assert res_u2[0]["id"] == "c_u2_1"

    # 從 user_1 查詢，不應查到 user_2 的內容
    res_u1 = store_user1.query(query_text="", query_embedding=dummy_vector, n_results=10)
    assert len(res_u1) == 1
    assert res_u1[0]["text"] == "User 1 私人對話紀錄"
    assert res_u1[0]["id"] == "c_u1_1"
