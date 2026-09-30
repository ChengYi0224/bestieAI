"""多用戶 Bot：身分解析、指令隔離、狀態分離、每用戶 IG 連線。"""
import json
from unittest.mock import MagicMock

import pytest
from cryptography.fernet import Fernet

from app.bot.dispatcher import ActionDispatcher
from app.bot.identity import SenderResolver
from app.bot.router import CommandRouter
from app.bot.task_worker import Task, TrackWorker
from app.commands.base import CommandResult
from app.services.ig_pool import IGClientPool, IGSessionUnavailable
from app.services.memory_service import MemoryManagerPool
from app.storage.db import init_db, get_or_create_contact, save_messages
from app.storage.repositories import BotStateRepository, ContactRepository
from app.storage.repositories.users import UserRepository

pytestmark = pytest.mark.no_default_tenant


@pytest.fixture
def env(tmp_path):
    db = tmp_path / "multi.db"
    init_db(db_path=db)
    users = UserRepository(db_path=db)
    friend_id = users.create_user("friend")
    assert friend_id == 2
    owner_c = get_or_create_contact("owner_buddy", "Owner Buddy", db_path=db, user_id=1)
    friend_c = get_or_create_contact("friend_buddy", "Friend Buddy", db_path=db, user_id=2)
    save_messages(owner_c, [{"ig_item_id": "o1", "sender": "them", "content": "OWNER-SECRET", "sent_at": "2026-01-01T00:00:00"}], db_path=db)
    router = CommandRouter(memory_manager=MagicMock(), llm_client=MagicMock(), db_path=db)
    return {
        "db": db, "users": users, "router": router,
        "contacts": ContactRepository(db_path=db), "state": BotStateRepository(db_path=db),
        "owner_c": owner_c, "friend_c": friend_c,
    }


# ---------- 未綁定身分 ----------

def test_unbound_sender_can_only_use_help_and_login(env):
    router = env["router"]
    res = router.handle_message_structured("list", sender_pk="stranger", user_id=None)
    assert res.success is False and "login" in res.message
    assert router.handle_message_structured("help", user_id=None).success is True


# ---------- 指令隔離 ----------

def test_list_only_shows_own_contacts(env):
    router = env["router"]
    owner_list = router.handle_message("list", user_id=1)
    friend_list = router.handle_message("list", user_id=2)
    assert "owner_buddy" in owner_list and "friend_buddy" not in owner_list
    assert "friend_buddy" in friend_list and "owner_buddy" not in friend_list


def test_export_cannot_read_other_users_contact(env):
    res = env["router"].handle_message_structured("exp 5 owner_buddy -i", user_id=2)
    assert res.success is False
    assert "OWNER-SECRET" not in res.message


def test_select_cannot_switch_to_other_users_contact(env):
    router, contacts = env["router"], env["contacts"]
    res = router.handle_message_structured("select owner_buddy", user_id=2)
    assert res.success is False
    assert contacts.get_active(user_id=2) is None
    # 直接以 id 也不能啟用他人的聯絡人
    assert contacts.set_active_by_id(env["owner_c"], user_id=2) is False


# ---------- 狀態分離 ----------

def test_active_contact_pending_selection_and_worker_status_are_per_user(env):
    contacts, state, router = env["contacts"], env["state"], env["router"]
    router.handle_message("select owner_buddy", user_id=1)
    router.handle_message("select friend_buddy", user_id=2)
    assert contacts.get_active(user_id=1)["ig_account_id"] == "owner_buddy"
    assert contacts.get_active(user_id=2)["ig_account_id"] == "friend_buddy"

    state.set_pending_selection([1, 2], user_id=1)
    assert state.get_pending_selection(user_id=2) is None

    state.set_worker_status({"running": True, "target": "owner_buddy"}, user_id=1)
    assert state.get_worker_status(user_id=2) is None
    status_for_friend = router.handle_message("status", user_id=2)
    assert "owner_buddy" not in status_for_friend


def test_conversations_are_isolated_per_user(env):
    state = env["state"]
    state.add_conversation("user", "owner question", None, user_id=1)
    state.add_conversation("user", "friend question", None, user_id=2)
    assert [r["content"] for r in state.get_conversations(None, 10, user_id=1)] == ["owner question"]
    assert [r["content"] for r in state.get_conversations(None, 10, user_id=2)] == ["friend question"]


def test_parsers_resolve_active_contact_for_the_sender(env):
    router = env["router"]
    router.handle_message("select owner_buddy", user_id=1)
    router.handle_message("select friend_buddy", user_id=2)
    assert router.parse_text_to_command("exp 5", user_id=1).target == "owner_buddy"
    assert router.parse_text_to_command("exp 5", user_id=2).target == "friend_buddy"
    assert router.parse_text_to_command("exp 5", user_id=None).target == ""


# ---------- 身分解析 ----------

def test_sender_resolver(env):
    users = env["users"]
    users.bind_ig_account(user_id=2, ig_pk="555", ig_username="friend_ig")
    resolver = SenderResolver(lambda: "111", users, owner_user_id=1)
    assert resolver.resolve("111") == 1
    assert resolver.resolve("555") == 2
    assert resolver.resolve("999") is None
    assert resolver.resolve("") is None


# ---------- 每用戶 IG 連線 ----------

def _encrypted_session(cipher_key: bytes, settings_dict: dict) -> str:
    return Fernet(cipher_key).encrypt(json.dumps(settings_dict).encode()).decode()


def test_ig_pool_uses_owner_session_for_owner_and_own_session_for_friend(env):
    key = Fernet.generate_key()
    session_manager = MagicMock()
    session_manager.cipher = Fernet(key)
    session_manager.login.return_value = "MAIN_CLIENT"
    env["users"].bind_ig_account(
        user_id=2, ig_pk="555", ig_username="friend_ig",
        encrypted_session=_encrypted_session(key, {"uuids": {}}),
    )
    pool = IGClientPool(session_manager, env["users"], owner_user_id=1,
                        client_factory=lambda c: ("wrapped", c), validate_sessions=False)

    assert pool.get(1) == ("wrapped", "MAIN_CLIENT")
    session_manager.login.assert_called_once_with("main")

    friend_client = pool.get(2)
    assert friend_client[0] == "wrapped" and friend_client[1] != "MAIN_CLIENT"
    assert pool.get(2) is friend_client  # 快取
    pool.invalidate(2)
    assert pool.get(2) is not friend_client


def test_ig_pool_never_falls_back_to_owner_session_for_unbound_user(env):
    session_manager = MagicMock()
    session_manager.cipher = Fernet(Fernet.generate_key())
    pool = IGClientPool(session_manager, env["users"], owner_user_id=1, validate_sessions=False)
    with pytest.raises(IGSessionUnavailable):
        pool.get(2)
    session_manager.login.assert_not_called()


def test_ig_pool_reports_corrupt_session(env):
    session_manager = MagicMock()
    session_manager.cipher = Fernet(Fernet.generate_key())
    env["users"].bind_ig_account(user_id=2, ig_pk="555", ig_username="f", encrypted_session="not-a-valid-token")
    pool = IGClientPool(session_manager, env["users"], owner_user_id=1, validate_sessions=False)
    with pytest.raises(IGSessionUnavailable):
        pool.get(2)


# ---------- 背景 Worker / 派發 ----------

def test_worker_queue_does_not_leak_other_users_targets():
    worker = TrackWorker(MagicMock(), MagicMock(), MagicMock())
    worker.start = MagicMock()
    worker._current = Task(1, "owner_running", 100, "t")
    assert worker.enqueue(Task(1, "owner_next", 100, "t")).kind == "queued"
    res = worker.enqueue(Task(2, "friend_target", 100, "t2"))
    assert res.kind == "queued" and res.other_user_busy is True
    assert worker.queued_targets(2) == ["friend_target"]
    assert worker.queued_targets(1) == ["owner_next"]
    # 朋友不能因為同名目標就被當成「同一個任務」
    assert worker.enqueue(Task(2, "owner_running", 100, "t2")).kind == "queued"


def test_login_completed_invalidates_that_users_ig_connection():
    pool, send = MagicMock(), MagicMock()
    dispatcher = ActionDispatcher(ig_pool=pool, ingestion_for=MagicMock(), worker=MagicMock(),
                                  activity=MagicMock(), send=send)
    result = CommandResult(success=True, message="✅ ok", action_type="LOGIN_COMPLETED", data={"user_id": 2})
    dispatcher.dispatch(result, None, "thread")
    pool.invalidate.assert_called_once_with(2)
    send.assert_called_once_with("thread", "✅ ok")


def test_dispatcher_rejects_async_actions_for_unbound_sender():
    send = MagicMock()
    dispatcher = ActionDispatcher(ig_pool=MagicMock(), ingestion_for=MagicMock(), worker=MagicMock(),
                                  activity=MagicMock(), send=send)
    dispatcher.dispatch(CommandResult(action_type="SYNC_REQUEST", data={"target": "x"}), None, "thread")
    assert "login" in send.call_args[0][1]


# ---------- 向量庫 / 記憶 ----------

def test_memory_pool_gives_each_user_its_own_manager():
    pool = MemoryManagerPool()
    from unittest.mock import patch
    with patch("app.services.memory_service.MemoryManager") as mm_cls:
        mm_cls.side_effect = lambda **kw: MagicMock(user_id=kw["user_id"])
        a, b = pool.for_user(1), pool.for_user(2)
        assert a is not b and a is pool.for_user(1)
        assert (a.user_id, b.user_id) == (1, 2)


def test_vector_tenant_keeps_owner_collection_compatible():
    from app.storage.scope import vector_tenant
    assert vector_tenant(1) is None      # 擁有者沿用舊集合（無 user_id metadata）
    assert vector_tenant(None) is None
    assert vector_tenant(2) == 2         # 其他使用者獨立集合
