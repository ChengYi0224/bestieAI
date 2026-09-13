from app.ingestion import IngestionPipeline

def test_clean_text():
    assert IngestionPipeline.clean_text(None) == "[圖片/貼圖/非文字訊息]"
    assert IngestionPipeline.clean_text("") == "[圖片/貼圖/非文字訊息]"
    assert IngestionPipeline.clean_text("  早安  ") == "早安"

def test_chunk_messages():
    messages = [
        {"id": "1", "sender": "them", "content": "早安", "sent_at": "2026-09-14T08:00:00"},
        {"id": "2", "sender": "me", "content": "早", "sent_at": "2026-09-14T08:01:00"},
        {"id": "3", "sender": "them", "content": "嗨", "sent_at": "2026-09-15T09:00:00"}
    ]
    chunks = IngestionPipeline.chunk_messages(messages, max_chunk_size=5)
    assert len(chunks) == 2
    assert "早安" in chunks[0]["text"]
    assert "嗨" in chunks[1]["text"]

def test_check_and_update_summary(tmp_path):
    from unittest.mock import MagicMock
    from app.db import init_db, get_or_create_contact, save_messages, get_contact_by_id

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
