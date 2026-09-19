"""test_user_repository.py — UserRepository 單元測試。"""
import pytest
from app.storage.db import init_db
from app.storage.repositories.users import UserRepository


@pytest.fixture
def user_repo(tmp_path):
    db_path = tmp_path / "test_users.db"
    init_db(db_path)
    return UserRepository(db_path=db_path)


def test_init_db_creates_default_admin(user_repo):
    """驗證 init_db 會自動建立 user_id = 1 的預設管理者帳號。"""
    admin = user_repo.get_by_id(1)
    assert admin is not None
    assert admin["id"] == 1
    assert admin["status"] == "active"


def test_create_and_query_user(user_repo):
    """驗證新增使用者與帳號、信箱查詢。"""
    u_id = user_repo.create_user(
        username="john_doe",
        email="john@example.com",
        password_hash="hashed_pw_123",
        display_name="John Doe",
    )
    assert u_id > 1

    by_id = user_repo.get_by_id(u_id)
    assert by_id["username"] == "john_doe"
    assert by_id["email"] == "john@example.com"
    assert by_id["display_name"] == "John Doe"

    by_username = user_repo.get_by_username("JOHN_DOE")  # 大小寫不分
    assert by_username is not None
    assert by_username["id"] == u_id

    by_email = user_repo.get_by_email("John@Example.com")
    assert by_email is not None
    assert by_email["id"] == u_id


def test_google_sub_linking(user_repo):
    """驗證 Google sub 查詢與綁定機制。"""
    u_id = user_repo.create_user(
        username="alice",
        email="alice@example.com",
    )
    assert user_repo.get_by_google_sub("g_sub_999") is None

    linked = user_repo.link_google_sub(u_id, "g_sub_999", avatar_url="http://example.com/pic.jpg")
    assert linked is True

    by_sub = user_repo.get_by_google_sub("g_sub_999")
    assert by_sub is not None
    assert by_sub["id"] == u_id
    assert by_sub["avatar_url"] == "http://example.com/pic.jpg"
