import pytest
from pathlib import Path
from app.storage.db import (
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

def test_should_update_summary():
    from app.storage.db import should_update_summary
    from datetime import datetime, timedelta, timezone

    # 1. 達 50 則門檻
    assert should_update_summary({"new_messages_since_summary": 50}) is True
    assert should_update_summary({"new_messages_since_summary": 49, "summary_updated_at": datetime.now(timezone.utc).isoformat()}) is False

    # 2. 超過 14 天保底門檻 (UTC aware)
    old_time_aware = (datetime.now(timezone.utc) - timedelta(days=15)).isoformat()
    assert should_update_summary({"new_messages_since_summary": 5, "summary_updated_at": old_time_aware}) is True
    # 超過 14 天但無新訊息
    assert should_update_summary({"new_messages_since_summary": 0, "summary_updated_at": old_time_aware}) is False

    # 3. 超過 14 天保底門檻 (Naive string 相容)
    old_time_naive = (datetime.now() - timedelta(days=15)).strftime("%Y-%m-%dT%H:%M:%S")
    assert should_update_summary({"new_messages_since_summary": 3, "summary_updated_at": old_time_naive}) is True

def test_update_contact_summary(temp_db):
    from app.storage.db import update_contact_summary, get_contact_by_id
    cid = get_or_create_contact("alex_test", "Alex", db_path=temp_db)
    update_contact_summary(cid, "這是新的摘要卡內容", db_path=temp_db)
    contact = get_contact_by_id(cid, db_path=temp_db)
    assert contact["summary_card"] == "這是新的摘要卡內容"
    assert contact["new_messages_since_summary"] == 0
    assert contact["summary_updated_at"] is not None


def test_get_latest_item_ids(temp_db):
    from app.storage.db import get_latest_item_ids
    cid = get_or_create_contact("stop_test", "Stop Test", db_path=temp_db)
    save_messages(cid, [
        {"ig_item_id": "item_101", "sender": "me", "content": "m1", "sent_at": "2026-09-19T01:00:00Z"},
        {"ig_item_id": "item_102", "sender": "them", "content": "m2", "sent_at": "2026-09-19T02:00:00Z"},
        {"ig_item_id": "item_103", "sender": "them", "content": "m3", "sent_at": "2026-09-19T03:00:00Z"},
    ], db_path=temp_db)

    ids = get_latest_item_ids(cid, limit=2, db_path=temp_db)
    assert len(ids) == 2
    assert "item_103" in ids
    assert "item_102" in ids
    assert "item_101" not in ids

