"""test_api_status.py — 系統與 Bot 狀態端點單元測試。"""
import pytest
from fastapi.testclient import TestClient
from app.api.app import create_app
from app.api.dependencies import get_bot_state_repo, get_contact_repo
from app.storage.db import init_db
from app.storage.repositories.bot_state import BotStateRepository
from app.storage.repositories.contacts import ContactRepository


@pytest.fixture
def test_app(tmp_path):
    db_path = tmp_path / "test_status.db"
    init_db(db_path)

    bot_repo = BotStateRepository(db_path=db_path)
    contact_repo = ContactRepository(db_path=db_path)

    app = create_app()
    app.dependency_overrides[get_bot_state_repo] = lambda: bot_repo
    app.dependency_overrides[get_contact_repo] = lambda: contact_repo

    return app, bot_repo, contact_repo


def test_status_endpoint(test_app):
    """驗證 /status 能正確回傳系統狀態與 worker 資訊。"""
    app, bot_repo, contact_repo = test_app
    client = TestClient(app)

    # 設定 worker 狀態與活躍聯絡人
    bot_repo.set_worker_status({"state": "running", "current_task": "polling"})
    c_id = contact_repo.get_or_create("alice_ig", "Alice")
    contact_repo.set_active_by_id(c_id)

    response = client.get("/status")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["worker_status"] == {"state": "running", "current_task": "polling"}
    assert data["active_contact_id"] == c_id
    assert "timestamp" in data
