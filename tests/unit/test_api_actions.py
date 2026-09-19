"""test_api_actions.py — REST API 主動操作端點（track, extract, chat）單元測試。"""
from unittest.mock import MagicMock
import pytest
from fastapi.testclient import TestClient

from app.api.app import create_app
from app.api.dependencies import (
    get_chat_service,
    get_contact_repo,
    get_contact_service,
    get_current_user,
)
from app.services.chat_api_service import ChatApiService
from app.services.contact_api_service import ContactApiService
from app.storage.db import init_db
from app.storage.repositories.contacts import ContactRepository


@pytest.fixture
def action_setup(tmp_path):
    db_path = tmp_path / "test_api_actions.db"
    init_db(db_path)
    contact_repo = ContactRepository(db_path=db_path)
    contact_service = ContactApiService(contact_repo=contact_repo)

    # 建立 mock chat service
    mock_chat_service = MagicMock(spec=ChatApiService)
    mock_chat_service.chat.return_value = ("嗨！今天有什麼新八卦？", 1)

    app = create_app()
    app.dependency_overrides[get_contact_repo] = lambda: contact_repo
    app.dependency_overrides[get_contact_service] = lambda: contact_service
    app.dependency_overrides[get_chat_service] = lambda: mock_chat_service
    app.dependency_overrides[get_current_user] = lambda: {"id": 1, "username": "admin_user"}

    client = TestClient(app)
    return client, contact_repo, mock_chat_service


def test_post_track_contact(action_setup):
    """驗證 POST /contacts/track 成功新增聯絡人並排入追蹤。"""
    client, contact_repo, _ = action_setup

    resp = client.post(
        "/contacts/track",
        json={"ig_account_id": "new_friend_target", "limit": 500},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] in ("success", "queued")
    assert "new_friend_target" in data["message"]
    assert data["contact_id"] is not None

    # 驗證資料庫存在該聯絡人且 user_id = 1
    contact = contact_repo.get_by_id(data["contact_id"], user_id=1)
    assert contact is not None
    assert contact["ig_account_id"] == "new_friend_target"


def test_post_extract_contact(action_setup):
    """驗證 POST /contacts/{id}/extract 觸發記憶提煉與 404 處理。"""
    client, contact_repo, _ = action_setup

    # 建立聯絡人
    cid = contact_repo.get_or_create("extract_target", user_id=1)

    resp = client.post(f"/contacts/{cid}/extract")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "success"
    assert data["contact_id"] == cid

    # 不存在的聯絡人應回傳 404
    resp_404 = client.post("/contacts/99999/extract")
    assert resp_404.status_code == 404


def test_post_chat(action_setup):
    """驗證 POST /chat 成功產生 AI 回覆。"""
    client, _, mock_chat_service = action_setup

    resp = client.post(
        "/chat",
        json={"message": "我想問他最近動態", "contact_id": 1},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["reply"] == "嗨！今天有什麼新八卦？"
    assert data["contact_id"] == 1
    mock_chat_service.chat.assert_called_once_with(
        user_id=1,
        message="我想問他最近動態",
        contact_id=1,
    )


def test_post_chat_empty_message(action_setup):
    """驗證空訊息回傳 422 Unprocessable Entity。"""
    client, _, _ = action_setup
    resp = client.post("/chat", json={"message": ""})
    assert resp.status_code == 422
