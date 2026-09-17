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
