import pytest
from unittest.mock import MagicMock
from app.pipelines.extraction import EventExtractor
from app.storage.db import init_db, get_connection, save_contact_events, get_contact_events

def test_extract_from_messages_batch_level_resume(tmp_path):
    db_file = tmp_path / "test_resume.db"
    init_db(db_file)
    conn = get_connection(db_file)
    with conn:
        conn.execute("INSERT INTO contacts (id, ig_account_id) VALUES (1, 'user_test')")
    conn.close()

    # 構造 16 則訊息，切成兩批 (每批 8 則)
    messages = []
    for i in range(16):
        messages.append({
            "sender": "me" if i % 2 == 0 else "them",
            "content": f"msg {i}",
            "sent_at": f"2026-03-01 10:{i:02d}:00"
        })

    mock_gemini = MagicMock()
    mock_gemini.generate_text.return_value = "- 批次二事件C"

    extractor = EventExtractor(
        gemini_client=mock_gemini,
        target_batch_size=8,
        max_batch_size=8,
        overlap_size=0,
        session_gap_hours=24.0
    )

    # 第一次執行：只跑批次 1 (假設中途只成功提煉第一批)
    batch_1 = messages[:8]
    save_contact_events(
        contact_id=1,
        events=[{
            "id": "event_0_0",
            "text": "批次一已快取的事件",
            "start_time": batch_1[0]["sent_at"],
            "end_time": batch_1[-1]["sent_at"],
            "message_count": len(batch_1)
        }],
        status="raw",
        db_path=db_file
    )

    # 重跑全部 16 則訊息：批次 1 應直接命中快取，Gemini 應該只被呼叫 1 次（提煉批次 2）
    res = extractor.extract_from_messages(messages, contact_id=1, db_path=db_file)

    assert len(res) == 2  # 1 條快取 + 1 條新提煉
    assert res[0]["text"] == "批次一已快取的事件"
    assert res[1]["text"] == "批次二事件C"
    assert mock_gemini.generate_text.call_count == 1  # 批次一完全沒調用 API
