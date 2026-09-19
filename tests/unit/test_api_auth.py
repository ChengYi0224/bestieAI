"""test_api_auth.py — REST API 認證端點單元測試。"""
import pytest
from fastapi.testclient import TestClient
from app.api.app import create_app
from app.core.config import settings
from app.services.auth_api_service import AuthApiService


@pytest.fixture
def client():
    app = create_app()
    return TestClient(app)


def test_auth_token_success(client, monkeypatch):
    """驗證正確密碼可成功取得 JWT Bearer Token。"""
    monkeypatch.setattr(settings, "API_SECRET", "test-secret-key-123")
    monkeypatch.setattr(settings, "MAIN_ACCOUNT_USERNAME", "")

    response = client.post(
        "/auth/token",
        json={"username": "test_user", "password": "test-secret-key-123"},
    )
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"
    assert data["expires_in"] == 24 * 3600


def test_auth_token_failure_wrong_password(client, monkeypatch):
    """驗證錯誤密碼回傳 401 Unauthorized。"""
    monkeypatch.setattr(settings, "API_SECRET", "test-secret-key-123")

    response = client.post(
        "/auth/token",
        json={"username": "test_user", "password": "wrong-password"},
    )
    assert response.status_code == 401
    assert response.json()["detail"] == "Incorrect username or password"


def test_auth_token_mismatched_main_username(client, monkeypatch):
    """若設定了主帳號，帳號不符時應回傳 401。"""
    monkeypatch.setattr(settings, "API_SECRET", "test-secret-key-123")
    monkeypatch.setattr(settings, "MAIN_ACCOUNT_USERNAME", "my_ig_account")

    response = client.post(
        "/auth/token",
        json={"username": "wrong_user", "password": "test-secret-key-123"},
    )
    assert response.status_code == 401


def test_auth_service_token_expiry(monkeypatch):
    """驗證 AuthApiService 對已過期 Token 回傳 None。"""
    service = AuthApiService(secret_key="secret", expire_hours=-1)
    token, _ = service.create_access_token("test_user")
    assert service.verify_token(token) is None
