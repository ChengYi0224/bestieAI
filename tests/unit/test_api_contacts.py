"""test_api_contacts.py — 聯絡人管理端點單元測試。"""
import pytest
from fastapi.testclient import TestClient
from app.api.app import create_app
from app.api.dependencies import (
    get_contact_repo,
    get_current_user,
    get_event_repo,
)
from app.storage.db import init_db
from app.storage.repositories.contacts import ContactRepository
from app.storage.repositories.events import EventRepository


@pytest.fixture
def test_setup(tmp_path):
    db_path = tmp_path / "test_contacts.db"
    init_db(db_path)

    contact_repo = ContactRepository(db_path=db_path)
    event_repo = EventRepository(db_path=db_path)

    app = create_app()
    # 覆蓋資料庫 Repository 與認證相依性
    app.dependency_overrides[get_contact_repo] = lambda: contact_repo
    app.dependency_overrides[get_event_repo] = lambda: event_repo
    app.dependency_overrides[get_current_user] = lambda: "authorized_user"

    client = TestClient(app)
    return client, contact_repo, event_repo


def test_list_contacts_empty_and_populated(test_setup):
    """驗證取得聯絡人清單。"""
    client, contact_repo, _ = test_setup

    res = client.get("/contacts")
    assert res.status_code == 200
    assert res.json() == []

    c1 = contact_repo.get_or_create("user_one", "User One")
    c2 = contact_repo.get_or_create("user_two", "User Two")

    res = client.get("/contacts")
    assert res.status_code == 200
    data = res.json()
    assert len(data) == 2
    ids = {item["id"] for item in data}
    assert ids == {c1, c2}


def test_get_contact_detail_and_not_found(test_setup):
    """驗證取得單一聯絡人詳情與 404 錯誤處理。"""
    client, contact_repo, _ = test_setup

    c_id = contact_repo.get_or_create("alice", "Alice")

    res = client.get(f"/contacts/{c_id}")
    assert res.status_code == 200
    data = res.json()
    assert data["id"] == c_id
    assert data["ig_account_id"] == "alice"
    assert data["display_name"] == "Alice"

    res_404 = client.get("/contacts/99999")
    assert res_404.status_code == 404


def test_patch_contact(test_setup):
    """驗證更新聯絡人暱稱與備註。"""
    client, contact_repo, _ = test_setup

    c_id = contact_repo.get_or_create("bob", "Bob")

    # 更新 nickname 與 relationship_note
    res = client.patch(
        f"/contacts/{c_id}",
        json={"nickname": "Bobby", "relationship_note": "高中同學"},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["nickname"] == "Bobby"
    assert data["relationship_note"] == "高中同學"

    # 單獨更新 nickname
    res2 = client.patch(f"/contacts/{c_id}", json={"nickname": "Bobster"})
    assert res2.status_code == 200
    data2 = res2.json()
    assert data2["nickname"] == "Bobster"
    assert data2["relationship_note"] == "高中同學"

    # 更新不存在的聯絡人
    res_404 = client.patch("/contacts/99999", json={"nickname": "Nobody"})
    assert res_404.status_code == 404


def test_get_contact_events(test_setup):
    """驗證取得指定聯絡人記憶事件。"""
    client, contact_repo, event_repo = test_setup

    c_id = contact_repo.get_or_create("charlie", "Charlie")
    event_repo.save_events(
        c_id,
        [
            {"id": "ev_1", "text": "討論下週旅行", "start_time": "2026-03-01"},
            {"id": "ev_2", "text": "生日聚餐", "start_time": "2026-03-02"},
        ],
    )

    res = client.get(f"/contacts/{c_id}/events")
    assert res.status_code == 200
    data = res.json()
    assert len(data) == 2
    assert data[0]["content"] == "討論下週旅行"
    assert data[1]["content"] == "生日聚餐"

    # 不存在的聯絡人
    res_404 = client.get("/contacts/99999/events")
    assert res_404.status_code == 404
