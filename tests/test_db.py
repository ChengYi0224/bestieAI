import pytest
from pathlib import Path
from app.db import (
    init_db,
    get_connection,
    get_or_create_contact,
    save_messages,
    get_recent_messages,
    set_active_contact,
    get_active_contact,
    add_bot_conversation
)

@pytest.fixture
def temp_db(tmp_path):
    db_file = tmp_path / "test.db"
    init_db(db_file)
    return db_file

def test_init_db(temp_db):
    conn = get_connection(temp_db)
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = [row["name"] for row in cursor.fetchall()]
    conn.close()
    assert "contacts" in tables
    assert "messages" in tables
    assert "bot_state" in tables
    assert "bot_conversations" in tables

def test_contact_and_active_state(temp_db):
    cid = get_or_create_contact("alex_test", "Alex", db_path=temp_db)
    assert cid > 0

    assert set_active_contact("alex_test", db_path=temp_db) is True
    active = get_active_contact(db_path=temp_db)
    assert active is not None
    assert active["ig_account_id"] == "alex_test"

def test_save_and_get_messages(temp_db):
    cid = get_or_create_contact("alex_test", "Alex", db_path=temp_db)
    sample_msgs = [
        {"ig_item_id": "1", "sender": "them", "content": "嗨！", "sent_at": "2026-09-14T01:00:00"},
        {"ig_item_id": "2", "sender": "me", "content": "哈囉！", "sent_at": "2026-09-14T01:05:00"},
        {"ig_item_id": "1", "sender": "them", "content": "重複", "sent_at": "2026-09-14T01:00:00"}
    ]
    inserted = save_messages(cid, sample_msgs, db_path=temp_db)
    assert inserted == 2

    recent = get_recent_messages(cid, limit=10, db_path=temp_db)
    assert len(recent) == 2
    assert recent[0]["content"] == "嗨！"
    assert recent[1]["content"] == "哈囉！"
