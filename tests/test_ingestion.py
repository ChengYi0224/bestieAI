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
