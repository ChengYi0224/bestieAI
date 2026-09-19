"""test_api_messages.py — 訊息端點單元測試。"""
import pytest
from fastapi.testclient import TestClient
from app.api.app import create_app
from app.api.dependencies import (
    get_contact_repo,
    get_current_user,
    get_message_repo,
)
from app.storage.db import init_db
from app.storage.repositories.contacts import ContactRepository
from app.storage.repositories.messages import MessageRepository


@pytest.fixture
def test_setup(tmp_path):
    db_path = tmp_path / "test_messages.db"
    init_db(db_path)

    contact_repo = ContactRepository(db_path=db_path)
    message_repo = MessageRepository(db_path=db_path)

    app = create_app()
    app.dependency_overrides[get_contact_repo] = lambda: contact_repo
    app.dependency_overrides[get_message_repo] = lambda: message_repo
    app.dependency_overrides[get_current_user] = lambda: "authorized_user"

    client = TestClient(app)
    return client, contact_repo, message_repo


def test_get_messages_pagination_and_headers(test_setup):
    """驗證訊息分頁查詢與 X-Total-Count 標頭。"""
    client, contact_repo, message_repo = test_setup

    c_id = contact_repo.get_or_create("diana", "Diana")

    messages = [
        {"ig_item_id": f"msg_{i}", "sender": "diana" if i % 2 == 0 else "me", "content": f"Hello {i}", "sent_at": f"2026-03-01T10:0{i}:00Z"}
        for i in range(10)
    ]
    message_repo.save_messages(c_id, messages)

    # 查詢第 1 頁，limit=3, offset=0
    res = client.get(f"/contacts/{c_id}/messages?limit=3&offset=0")
    assert res.status_code == 200
    assert res.headers.get("x-total-count") == "10"
    data = res.json()
    assert len(data) == 3
    assert data[0]["content"] == "Hello 0"
    assert data[2]["content"] == "Hello 2"

    # 查詢第 2 頁，limit=3, offset=3
    res2 = client.get(f"/contacts/{c_id}/messages?limit=3&offset=3")
    assert res2.status_code == 200
    data2 = res2.json()
    assert len(data2) == 3
    assert data2[0]["content"] == "Hello 3"

    # 查詢不存在的聯絡人
    res_404 = client.get("/contacts/99999/messages")
    assert res_404.status_code == 404


def test_get_messages_unauthorized(tmp_path):
    """驗證未經授權請求時被拒絕。"""
    db_path = tmp_path / "test_unauth.db"
    init_db(db_path)
    app = create_app()
    client = TestClient(app)

    res = client.get("/contacts/1/messages")
    assert res.status_code in (401, 403)
