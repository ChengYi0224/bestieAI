"""
test_command_bus.py — Command Bus 架構與結構化結果單元測試。
"""
import pytest
from unittest.mock import MagicMock
from app.commands.base import BaseCommand, CommandResult
from app.commands.bus import CommandBus
from app.commands.handlers import (
    CommandService,
    create_default_command_bus,
    HelpCommand,
    TrackCommand,
    TrackFullCommand,
    SelectCommand,
    NicknameCommand,
    MeCommand,
    StatusCommand,
    ListContactsCommand,
    CardCommand,
    SyncCommand,
    FollowerSnapshotCommand,
    CheckUnfollowersCommand,
    ExportCommand,
)
from app.bot.router import CommandRouter
from app.storage.db import init_db, get_or_create_contact, set_active_contact


@pytest.fixture
def test_env(tmp_path):
    db_file = tmp_path / "test_bus.db"
    init_db(db_file)
    mock_memory = MagicMock()
    mock_llm = MagicMock()
    service = CommandService(memory_manager=mock_memory, llm_client=mock_llm, db_path=db_file)
    bus = create_default_command_bus(service)
    router = CommandRouter(memory_manager=mock_memory, llm_client=mock_llm, db_path=db_file, command_bus=bus)
    return {
        "db_file": db_file,
        "service": service,
        "bus": bus,
        "router": router,
        "mock_memory": mock_memory,
        "mock_llm": mock_llm,
    }


def test_command_bus_dispatch_track(test_env):
    bus = test_env["bus"]
    result = bus.dispatch(TrackCommand(target="test_account"))
    assert isinstance(result, CommandResult)
    assert result.success is True
    assert result.action_type == "TRACK_REQUEST"
    assert result.data == {"target": "test_account"}
    # message 應為人類可讀文字，不再包含魔法前綴
    assert "test_account" in result.message


def test_command_bus_dispatch_select(test_env):
    bus = test_env["bus"]
    db_file = test_env["db_file"]
    get_or_create_contact("alice_dev", "Alice", db_path=db_file)

    # 查無對象
    res_not_found = bus.dispatch(SelectCommand(query="non_existent"))
    assert res_not_found.success is False
    assert "找不到" in res_not_found.message

    # 成功切換對象，回傳結構化 contact 資料
    res_found = bus.dispatch(SelectCommand(query="alice_dev"))
    assert res_found.success is True
    assert res_found.data["status"] == "selected"
    assert res_found.data["contact"]["ig_account_id"] == "alice_dev"


def test_command_bus_dispatch_list_and_status(test_env):
    bus = test_env["bus"]
    db_file = test_env["db_file"]
    get_or_create_contact("bob_smith", "Bob", db_path=db_file)
    set_active_contact("bob_smith", db_path=db_file)

    res_list = bus.dispatch(ListContactsCommand())
    assert res_list.success is True
    assert len(res_list.data["contacts"]) >= 1

    res_status = bus.dispatch(StatusCommand())
    assert res_status.success is True
    assert res_status.data["active_contact"]["ig_account_id"] == "bob_smith"


def test_command_bus_unregistered_command():
    bus = CommandBus()

    class UnknownCommand(BaseCommand):
        pass

    result = bus.dispatch(UnknownCommand())
    assert result.success is False
    assert "未找到指令" in result.message


def test_router_parse_text_to_command(test_env):
    router = test_env["router"]

    cmd_track = router.parse_text_to_command("track alice_123")
    assert isinstance(cmd_track, TrackCommand)
    assert cmd_track.target == "alice_123"

    cmd_tf = router.parse_text_to_command("tf alice_123 500")
    assert isinstance(cmd_tf, TrackFullCommand)
    assert cmd_tf.target == "alice_123"
    assert cmd_tf.max_amount == 500

    cmd_card = router.parse_text_to_command("card full bob")
    assert isinstance(cmd_card, CardCommand)
    assert cmd_card.is_full is True
    assert cmd_card.target == "bob"

    cmd_sync = router.parse_text_to_command("sync charlie")
    assert isinstance(cmd_sync, SyncCommand)
    assert cmd_sync.target == "charlie"


def test_router_structured_message(test_env):
    router = test_env["router"]
    res = router.handle_message_structured("t david_456")
    assert isinstance(res, CommandResult)
    assert res.success is True
    assert res.data == {"target": "david_456"}
    assert res.to_dict()["action_type"] == "TRACK_REQUEST"


def test_future_follower_commands(test_env):
    bus = test_env["bus"]

    res_snapshot = bus.dispatch(FollowerSnapshotCommand())
    assert res_snapshot.success is True
    assert "Follower" in res_snapshot.message

    res_unfollowers = bus.dispatch(CheckUnfollowersCommand())
    assert res_unfollowers.success is True
    assert "退追" in res_unfollowers.message


def test_export_command_parsing(test_env):
    router = test_env["router"]

    cmd1 = router.parse_text_to_command("exp 10")
    assert isinstance(cmd1, ExportCommand)
    assert cmd1.limit == 10
    assert cmd1.immediate is False

    cmd2 = router.parse_text_to_command("exp 50 -I")
    assert isinstance(cmd2, ExportCommand)
    assert cmd2.limit == 50
    assert cmd2.immediate is True

    cmd3 = router.parse_text_to_command("exp -I 30")
    assert isinstance(cmd3, ExportCommand)
    assert cmd3.limit == 30
    assert cmd3.immediate is True

    cmd4 = router.parse_text_to_command("export 15 user_bob -i")
    assert isinstance(cmd4, ExportCommand)
    assert cmd4.limit == 15
    assert cmd4.immediate is True
    assert cmd4.target == "user_bob"


def test_export_command_handling(test_env):
    from app.storage.db import get_or_create_contact, set_active_contact, save_messages
    bus = test_env["bus"]
    db_file = test_env["db_file"]

    # 1. 無作用中對象
    res_no_contact = bus.dispatch(ExportCommand(limit=10))
    assert res_no_contact.success is False
    assert "尚未選定作用對象" in res_no_contact.message

    # 2. 建立聯絡人並寫入訊息
    cid = get_or_create_contact("target_user", "Target", db_path=db_file)
    set_active_contact("target_user", db_path=db_file)

    save_messages(cid, [
        {"ig_item_id": "m1", "sender": "them", "content": "哈囉！", "sent_at": "2026-09-19T10:00:00"},
        {"ig_item_id": "m2", "sender": "me", "content": "你好呀！", "sent_at": "2026-09-19T10:01:00"},
        {"ig_item_id": "m3", "sender": "them", "content": "今天天氣真好", "sent_at": "2026-09-19T10:02:00"},
    ], db_path=db_file)

    # 3. 測試 ExportCommand (immediate=True, 不呼叫 sync)
    mock_sync = MagicMock()
    test_env["service"]._export.sync_callback = mock_sync

    res_imm = bus.dispatch(ExportCommand(limit=2, immediate=True))
    assert res_imm.success is True
    assert res_imm.data["count"] == 2
    assert "--- 2026-09-19 ---" in res_imm.message
    assert "[10:01:00] 我: 你好呀！" in res_imm.message
    assert "[10:02:00] Target: 今天天氣真好" in res_imm.message
    mock_sync.assert_not_called()

    # 4. 測試 ExportCommand (immediate=False, 預設先呼叫 sync)
    res_sync = bus.dispatch(ExportCommand(limit=5, immediate=False))
    assert res_sync.success is True
    assert res_sync.data["count"] == 3
    mock_sync.assert_called_once_with("target_user")
    assert "--- 2026-09-19 ---" in res_sync.message
    assert "[10:00:00] Target: 哈囉！" in res_sync.message



def test_help_command_categorization(test_env):
    bus = test_env["bus"]

    # 1. 簡短說明
    res_short = bus.dispatch(HelpCommand(show_all=False))
    assert res_short.success is True
    assert "指令清單" in res_short.message
    assert "help all" in res_short.message

    # 2. 全量說明（需搭配 select vs 獨立指令）
    res_all = bus.dispatch(HelpCommand(show_all=True))
    assert res_all.success is True
    assert "需搭配 select" in res_all.message
    assert "獨立指令" in res_all.message
    assert "exp [數量] [-I]" in res_all.message
