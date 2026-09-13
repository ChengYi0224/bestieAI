import pytest
from unittest.mock import MagicMock
from app.db import init_db, get_or_create_contact
from app.router import CommandRouter

@pytest.fixture
def router(tmp_path):
    db_file = tmp_path / "test.db"
    init_db(db_file)

    mock_memory = MagicMock()
    mock_llm = MagicMock()
    router = CommandRouter(memory_manager=mock_memory, llm_client=mock_llm, db_path=db_file)
    return router

def test_router_commands(router, tmp_path):
    res = router.handle_message("track bob_123")
    assert res == "TRACK_REQUEST:bob_123"

    res = router.handle_message("select bob_123")
    assert "找不到" in res or "目前作用對象" in res

    res = router.handle_message("list")
    assert "尚未追蹤" in res or "已追蹤" in res

    res = router.handle_message("status")
    assert "尚未選定" in res or "目前對話對象狀態" in res

    res = router.handle_message("refresh_summary bob_123")
    assert res == "REFRESH_SUMMARY_REQUEST:bob_123"

    res = router.handle_message("sync bob_123")
    assert res == "SYNC_REQUEST:bob_123"

    # 測試 help 指令
    help_res = router.handle_message("help")
    assert "【IG AI 陪聊機器人 指令清單】" in help_res
    assert "track" in help_res

    # 測試錯誤用法帶有 help 提示
    err_res = router.handle_message("track")
    assert "格式錯誤" in err_res
    assert "help" in err_res
