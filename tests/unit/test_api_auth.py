"""test_api_auth.py — REST API 雙軌認證端點單元測試。"""
import pytest
from fastapi.testclient import TestClient
from google.oauth2 import id_token as google_id_token

from app.api.app import create_app
from app.api.dependencies import get_user_repo
from app.core.config import settings
from app.services.auth_api_service import AuthApiService
from app.storage.db import init_db
from app.storage.repositories.users import UserRepository


@pytest.fixture
def auth_setup(tmp_path):
    db_path = tmp_path / "test_auth.db"
    init_db(db_path)
    user_repo = UserRepository(db_path=db_path)

    app = create_app()
    app.dependency_overrides[get_user_repo] = lambda: user_repo

    client = TestClient(app)
    return client, user_repo


def test_register_and_login_success(auth_setup):
    """驗證原生帳密註冊、登入與 /auth/me 個人資訊取得。"""
    client, user_repo = auth_setup

    # 1. 註冊新用戶
    reg_resp = client.post(
        "/auth/register",
        json={
            "username": "tester_user",
            "password": "mypassword123",
            "email": "tester@example.com",
            "display_name": "Tester",
        },
    )
    assert reg_resp.status_code == 201
    user_data = reg_resp.json()
    assert user_data["username"] == "tester_user"
    assert user_data["email"] == "tester@example.com"
    assert user_data["id"] > 1

    # 2. 重複註冊應回傳 400
    dup_resp = client.post(
        "/auth/register",
        json={"username": "tester_user", "password": "mypassword123"},
    )
    assert dup_resp.status_code == 400

    # 3. 帳密登入取得 Token
    login_resp = client.post(
        "/auth/token",
        json={"username": "tester_user", "password": "mypassword123"},
    )
    assert login_resp.status_code == 200
    token_data = login_resp.json()
    assert "access_token" in token_data
    token = token_data["access_token"]

    # 4. 帶 Token 存取 /auth/me
    me_resp = client.get(
        "/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert me_resp.status_code == 200
    me_data = me_resp.json()
    assert me_data["id"] == user_data["id"]
    assert me_data["username"] == "tester_user"


def test_login_wrong_password(auth_setup):
    """驗證密碼錯誤回傳 401。"""
    client, _ = auth_setup

    client.post(
        "/auth/register",
        json={"username": "alice", "password": "correct_password"},
    )

    resp = client.post(
        "/auth/token",
        json={"username": "alice", "password": "wrong_password"},
    )
    assert resp.status_code == 401


def test_google_login_admin_auto_binding(auth_setup, monkeypatch):
    """驗證管理員 Google 登入時自動綁定為 user_id = 1。"""
    client, user_repo = auth_setup
    monkeypatch.setattr(settings, "ADMIN_EMAIL", "admin_boss@gmail.com")

    # Mock Google Token 驗證函式
    monkeypatch.setattr(
        google_id_token,
        "verify_oauth2_token",
        lambda token, request, audience: {
            "sub": "google_sub_admin_999",
            "email": "admin_boss@gmail.com",
            "name": "Boss Admin",
            "picture": "http://example.com/boss.jpg",
        },
    )

    resp = client.post("/auth/google", json={"id_token": "fake_admin_token"})
    assert resp.status_code == 200
    token = resp.json()["access_token"]

    # 驗證綁定後的管理者 ID 為 1
    me_resp = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me_resp.status_code == 200
    assert me_resp.json()["id"] == 1
    assert me_resp.json()["email"] == "admin_boss@gmail.com"


def test_google_login_new_friend_user(auth_setup, monkeypatch):
    """驗證新朋友 Google 登入時分配獨立 user_id > 1。"""
    client, user_repo = auth_setup
    monkeypatch.setattr(settings, "ADMIN_EMAIL", "admin_boss@gmail.com")

    # Mock 朋友登入 Token
    monkeypatch.setattr(
        google_id_token,
        "verify_oauth2_token",
        lambda token, request, audience: {
            "sub": "google_sub_friend_888",
            "email": "friend@gmail.com",
            "name": "Friend User",
            "picture": "http://example.com/friend.jpg",
        },
    )

    resp = client.post("/auth/google", json={"id_token": "fake_friend_token"})
    assert resp.status_code == 200
    token = resp.json()["access_token"]

    me_resp = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me_resp.status_code == 200
    assert me_resp.json()["id"] > 1
    assert me_resp.json()["email"] == "friend@gmail.com"


def test_token_expiry_validation(monkeypatch):
    """驗證過期 Token 無法通過驗證。"""
    service = AuthApiService(secret_key="secret", expire_hours=-1)
    token, _ = service.create_access_token(user_id=1, username="admin")
    assert service.verify_token(token) is None
