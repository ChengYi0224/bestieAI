import pytest
from instagrapi import Client
from instagrapi.realtime import RealtimeClient
from google import genai
from google.genai.types import EmbedContentResponse, GenerateContentResponse, ContentEmbedding
import chromadb

def test_instagrapi_client_contract():
    """驗證本專案使用的 instagrapi Client 關鍵 API 介面未因版本變動而遺失"""
    client = Client()
    # 輪詢與私訊相關
    assert hasattr(client, "direct_threads")
    assert hasattr(client, "direct_messages")
    assert hasattr(client, "direct_send")
    assert hasattr(client, "user_id_from_username")

    # Realtime / MQTT 相關
    assert hasattr(client, "realtime_client")
    assert hasattr(client, "realtime_connect")
    assert hasattr(client, "realtime_disconnect")
    assert hasattr(client, "realtime_on")
    assert hasattr(client, "realtime_read_once")
    assert hasattr(client, "realtime_ping")

    # RealtimeClient 實例介面
    rt = client.realtime_client()
    assert hasattr(rt, "direct_subscribe")
    assert hasattr(rt, "iris_subscribe")
    assert hasattr(rt, "read_once")
    assert hasattr(rt, "ping")

def test_gemini_api_contract():
    """驗證本專案使用的 google.genai SDK 結構與資料屬性"""
    client = genai.Client(api_key="mock_test_key")
    assert hasattr(client.models, "generate_content")
    assert hasattr(client.models, "embed_content")

    # 驗證 EmbedContentResponse 屬性
    embedding_obj = ContentEmbedding(values=[0.1, 0.2, 0.3])
    embed_resp = EmbedContentResponse(embeddings=[embedding_obj])
    assert embed_resp.embeddings[0].values == [0.1, 0.2, 0.3]

    # 驗證 GenerateContentResponse 屬性
    assert hasattr(GenerateContentResponse, "text")

def test_chromadb_contract(tmp_path):
    """驗證 ChromaDB Client 與 Collection 寫入與查詢介面真實可用"""
    client = chromadb.PersistentClient(path=str(tmp_path))
    collection = client.get_or_create_collection(name="test_col")

    assert hasattr(collection, "upsert")
    assert hasattr(collection, "query")

    collection.upsert(
        ids=["c1"],
        documents=["測試文本"],
        embeddings=[[0.1, 0.2, 0.3]],
        metadatas=[{"contact_id": 1}]
    )

    results = collection.query(
        query_embeddings=[[0.1, 0.2, 0.3]],
        where={"contact_id": 1},
        n_results=1
    )
    assert len(results["documents"][0]) == 1
    assert results["documents"][0][0] == "測試文本"
