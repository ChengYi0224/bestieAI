from unittest.mock import MagicMock
from app.services.ingestion_service import IngestionPipeline

def test_clean_text():
    assert IngestionPipeline.clean_text(None) == "[圖片/貼圖/非文字訊息]"
    assert IngestionPipeline.clean_text("") == "[圖片/貼圖/非文字訊息]"
    assert IngestionPipeline.clean_text("  早安  ") == "早安"

def test_chunk_messages():
    messages = [
        {"id": "1", "sender": "me", "content": "你今天怎麼都不理我？", "sent_at": "2026-09-14T08:00:00"},
        {"id": "2", "sender": "them", "content": "沒", "sent_at": "2026-09-14T14:30:00"},
        {"id": "3", "sender": "them", "content": "嗯", "sent_at": "2026-09-14T14:31:00"},
        {"id": "4", "sender": "them", "content": "嗨", "sent_at": "2026-09-15T09:00:00"}
    ]
    chunks = IngestionPipeline.chunk_messages(messages, max_chunk_size=5)
    assert len(chunks) == 2
    assert "間隔 6.5小時" in chunks[0]["text"]
    assert "【互動特徵標註：對方多簡短/敷衍回覆、出現長時間間隔/回覆延遲】" in chunks[0]["text"]
    assert "嗨" in chunks[1]["text"]

def test_check_and_update_summary(tmp_path):
    from unittest.mock import MagicMock
    from app.storage.db import init_db, get_or_create_contact, save_messages, get_contact_by_id, get_all_messages

    db_file = tmp_path / "test.db"
    init_db(db_file)

    mock_llm = MagicMock()
    mock_llm.update_summary.return_value = "更新版摘要卡"
    mock_llm.generate_summary.return_value = "初始摘要卡"
    mock_vector = MagicMock()

    pipeline = IngestionPipeline(vector_store=mock_vector, llm_client=mock_llm)
    cid = get_or_create_contact("alex_test", "Alex", db_path=db_file)

    # 1. 訊息少且未達門檻，不強制更新
    save_messages(cid, [{"ig_item_id": "1", "sender": "them", "content": "hi", "sent_at": "2026-09-14T00:00:00"}], db_path=db_file)
    res = pipeline.check_and_update_summary(cid, force=False, db_path=db_file)
    assert res is None

    # 2. 強制更新
    res = pipeline.check_and_update_summary(cid, force=True, db_path=db_file)
    assert res == "初始摘要卡"
    contact = get_contact_by_id(cid, db_path=db_file)
    assert contact["summary_card"] == "初始摘要卡"
    assert contact["new_messages_since_summary"] == 0

    # 3. 有既有摘要卡且強制更新 -> 呼叫 update_summary 進行增量更新
    save_messages(cid, [{"ig_item_id": "2", "sender": "me", "content": "hello", "sent_at": "2026-09-14T01:00:00"}], db_path=db_file)
    res2 = pipeline.check_and_update_summary(cid, force=True, db_path=db_file)
    assert res2 == "更新版摘要卡"
    contact2 = get_contact_by_id(cid, db_path=db_file)
    assert contact2["summary_card"] == "更新版摘要卡"
    mock_llm.update_summary.assert_called_once()


def test_summarizer_check_and_update_summary(tmp_path):
    from unittest.mock import MagicMock
    from app.storage.db import init_db, get_or_create_contact, save_messages, get_contact_by_id
    from app.pipelines.summarization import Summarizer

    db_file = tmp_path / "test_summarizer.db"
    init_db(db_file)
    cid = get_or_create_contact("bob_test", "Bob", db_path=db_file)

    save_messages(cid, [{"ig_item_id": "m1", "sender": "them", "content": "hello there", "sent_at": "2026-09-19T12:00:00"}], db_path=db_file)

    mock_gemini = MagicMock()
    mock_gemini.generate_text.return_value = "- 關係良好\n- 喜歡旅行"

    summarizer = Summarizer(gemini_client=mock_gemini)

    # 1. 訊息未達門檻且 force=False -> 不觸發更新
    res = summarizer.check_and_update_summary(cid, force=False, message_threshold=50, db_path=db_file)
    assert res is False

    # 2. force=True -> 成功更新且不引發 TypeError 或 AttributeError
    res = summarizer.check_and_update_summary(cid, force=True, db_path=db_file)
    assert res is True

    contact = get_contact_by_id(cid, db_path=db_file)
    assert contact["summary_card"] == "- 關係良好\n- 喜歡旅行"
    assert contact["new_messages_since_summary"] == 0

def test_rebuild_vectors(tmp_path):
    """驗證 rebuild_vectors 從 SQLite 重建 ChromaDB，不需碰 IG API。"""
    from app.storage.db import init_db, get_or_create_contact, save_messages
    import chromadb

    db_file = tmp_path / "test.db"
    init_db(db_file)

    # 建立真實 ChromaDB
    chroma_path = tmp_path / "chroma"
    vs_real = __import__("app.storage.vectors", fromlist=["VectorStore"])
    chroma_client = chromadb.PersistentClient(path=str(chroma_path))
    collection = chroma_client.get_or_create_collection(
        name="chat_chunks",
        metadata={"hnsw:space": "cosine"}
    )

    # mock VectorStore
    mock_vector = MagicMock()
    mock_llm = MagicMock()
    pipeline = IngestionPipeline(vector_store=mock_vector, llm_client=mock_llm)

    cid = get_or_create_contact("bob_rebuild", "Bob", db_path=db_file)
    save_messages(cid, [
        {"ig_item_id": "r1", "sender": "them", "content": "你好", "sent_at": "2026-09-13T10:00:00"},
        {"ig_item_id": "r2", "sender": "me",   "content": "嗨",   "sent_at": "2026-09-13T10:01:00"},
        {"ig_item_id": "r3", "sender": "them", "content": "在嗎", "sent_at": "2026-09-14T09:00:00"},
    ], db_path=db_file)

    result = pipeline.rebuild_vectors("bob_rebuild", db_path=db_file)

    assert result["contact_id"] == cid
    assert result["total_messages"] == 3
    assert result["chunks_rebuilt"] >= 1  # 兩天 → 至少 2 個 chunks
    mock_vector.add_chunks.assert_called_once()
    # 確認 delete 被呼叫（清除舊向量）
    mock_vector.collection.delete.assert_called_once_with(where={"contact_id": cid})


def test_run_full_ingestion_deduplication(tmp_path):
    """驗證 run_full_ingestion 面對已存在訊息時自動去重、不重複儲存。"""
    from datetime import datetime
    from app.storage.db import init_db, get_or_create_contact, save_messages, get_all_messages

    db_file = tmp_path / "test_full.db"
    init_db(db_file)

    mock_vector = MagicMock()
    mock_llm = MagicMock()
    mock_llm.generate_summary.return_value = "全局摘要卡"
    pipeline = IngestionPipeline(vector_store=mock_vector, llm_client=mock_llm)

    cid = get_or_create_contact("charlie_full", "Charlie", db_path=db_file)
    # 先在本地存有 2 則訊息 (item_id: "m1", "m2")
    save_messages(cid, [
        {"ig_item_id": "m1", "sender": "them", "content": "舊訊息1", "sent_at": "2026-09-01T10:00:00"},
        {"ig_item_id": "m2", "sender": "me",   "content": "舊訊息2", "sent_at": "2026-09-01T10:01:00"},
    ], db_path=db_file)

    # 模擬 IG 抓回 3 則訊息：包含重複的 m1, m2，以及新的 m3
    mock_ig = MagicMock()
    mock_ig.client.user_id = 999
    mock_thread = MagicMock()
    mock_thread.id = 12345
    mock_ig.get_thread_by_username.return_value = mock_thread

    m1 = MagicMock(id="m1", user_id=111, text="舊訊息1", timestamp=datetime(2026, 9, 1, 10, 0, 0))
    m2 = MagicMock(id="m2", user_id=999, text="舊訊息2", timestamp=datetime(2026, 9, 1, 10, 1, 0))
    m3 = MagicMock(id="m3", user_id=111, text="全新歷史訊息3", timestamp=datetime(2026, 8, 20, 9, 0, 0))
    mock_ig.get_thread_messages.return_value = [m1, m2, m3]

    res = pipeline.run_full_ingestion(
        ig_client=mock_ig,
        target_username="charlie_full",
        max_amount=1000,
        db_path=db_file
    )

    # 驗證：本次抓回 3 則，但新增插入只有 1 則 (m3)，m1 與 m2 自動被 SQLite 去重跳過
    assert res["downloaded_messages"] == 3
    assert res["new_inserted_messages"] == 1
    assert res["total_messages_in_db"] == 3
    assert res["summary_card"] == "全局摘要卡"


def test_build_full_history_summary(tmp_path):
    """驗證 build_full_history_summary 完整讀取所有歷史對話並生成全景關係卡片。"""
    from app.storage.db import init_db, get_or_create_contact, save_messages, get_contact_by_id

    db_file = tmp_path / "test_full_sum.db"
    init_db(db_file)

    mock_llm = MagicMock()
    mock_llm.generate_full_history_summary.return_value = "深度全景復盤卡內容"
    pipeline = IngestionPipeline(llm_client=mock_llm)

    cid = get_or_create_contact("diana_test", "Diana", db_path=db_file)
    save_messages(cid, [
        {"ig_item_id": "d1", "sender": "them", "content": "第一天相識", "sent_at": "2026-07-01T10:00:00"},
        {"ig_item_id": "d2", "sender": "me",   "content": "好巧喔",   "sent_at": "2026-07-01T10:05:00"},
        {"ig_item_id": "d3", "sender": "them", "content": "結束了",   "sent_at": "2026-08-30T12:00:00"},
    ], db_path=db_file)

    res = pipeline.build_full_history_summary("diana_test", db_path=db_file)

    assert res["contact_id"] == cid
    assert res["total_messages"] == 3
    assert res["summary_card"] == "深度全景復盤卡內容"
    mock_llm.generate_full_history_summary.assert_called_once()
    # 驗證資料庫中的摘要卡已更新
    c_updated = get_contact_by_id(cid, db_path=db_file)
    assert c_updated["summary_card"] == "深度全景復盤卡內容"
