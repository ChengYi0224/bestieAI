import pytest
from unittest.mock import MagicMock
from app.storage.db import init_db, get_or_create_contact
from app.bot.router import CommandRouter

@pytest.fixture
def router(tmp_path):
    db_file = tmp_path / "test.db"
    init_db(db_file)

    mock_memory = MagicMock()
    mock_llm = MagicMock()
    router = CommandRouter(memory_manager=mock_memory, llm_client=mock_llm, db_path=db_file)
    return router

def test_router_commands(router, tmp_path):
    # 改用 handle_message_structured 驗證 action_type
    res = router.handle_message_structured("track bob_123")
    assert res.action_type == "TRACK_REQUEST"
    assert res.data["target"] == "bob_123"

    res_full = router.handle_message_structured("track_full bob_123 2000")
    assert res_full.action_type == "TRACK_FULL_REQUEST"
    assert res_full.data["target"] == "bob_123"
    assert res_full.data["max_amount"] == 2000

    res = router.handle_message("select bob_123")
    assert "找不到" in res or "目前作用對象" in res

    res = router.handle_message("list")
    assert "尚未追蹤" in res or "已追蹤" in res

    res = router.handle_message("status")
    assert "尚未選定" in res or "目前對話對象狀態" in res

    res_q = router.handle_message("query")
    assert "尚未選定" in res_q or "目前對話對象狀態" in res_q

    res = router.handle_message_structured("refresh_summary bob_123")
    assert res.action_type == "REFRESH_SUMMARY_REQUEST"
    assert res.data["target"] == "bob_123"

    res = router.handle_message_structured("summarize_history bob_123")
    assert res.action_type == "SUMMARIZE_HISTORY_REQUEST"
    assert res.data["target"] == "bob_123"

    res = router.handle_message_structured("sync bob_123")
    assert res.action_type == "SYNC_REQUEST"
    assert res.data["target"] == "bob_123"

    # 測試 help 指令
    help_res = router.handle_message("help")
    assert "【IG AI 陪聊機器人 指令清單】" in help_res
    assert "track (t)" in help_res

    # 測試錯誤用法帶有 help 提示
    err_res = router.handle_message("track")
    assert "格式錯誤" in err_res
    assert "help" in err_res


def test_router_short_aliases(router):
    """驗證所有指令短 alias 正確分發。"""
    def sr(text):
        return router.handle_message_structured(text)

    assert sr("t bob_123").action_type == "TRACK_REQUEST"
    assert sr("t bob_123").data["target"] == "bob_123"

    r = sr("tf bob_123 500")
    assert r.action_type == "TRACK_FULL_REQUEST"
    assert r.data["target"] == "bob_123"
    assert r.data["max_amount"] == 500

    assert sr("sy bob_123").action_type == "SYNC_REQUEST"
    assert sr("sh bob_123").action_type == "SUMMARIZE_HISTORY_REQUEST"
    assert sr("sum bob_123").action_type == "SUMMARIZE_HISTORY_REQUEST"
    assert sr("rs bob_123").action_type == "REFRESH_SUMMARY_REQUEST"
    assert sr("ref bob_123").action_type == "REFRESH_SUMMARY_REQUEST"
    assert sr("rv bob_123").action_type == "REBUILD_VECTORS_REQUEST"
    assert sr("rb bob_123").action_type == "REBUILD_VECTORS_REQUEST"
    assert "已將 bob_123 標記為停止追蹤。" in router.handle_message("ut bob_123")
    assert "尚未選定" in router.handle_message("st") or "目前對話對象狀態" in router.handle_message("st")
    assert "尚未追蹤" in router.handle_message("ls") or "已追蹤" in router.handle_message("ls")
    assert "尚未追蹤" in router.handle_message("l") or "已追蹤" in router.handle_message("l")
    assert "【IG AI 陪聊機器人 指令清單】" in router.handle_message("h")
    assert "【IG AI 陪聊機器人 指令清單 - 全量模式】" in router.handle_message("h all")


def test_select_fuzzy_matching(tmp_path):
    db_file = tmp_path / "test_fuzzy.db"
    init_db(db_file)
    router = CommandRouter(memory_manager=MagicMock(), llm_client=MagicMock(), db_path=db_file)

    # 建立兩個聯絡人：一個包含 sample，另一個也包含 sample
    get_or_create_contact("sample_user_01", "Sample", db_path=db_file)
    get_or_create_contact("sample_friend", "Sample Friend", db_path=db_file)
    get_or_create_contact("alice_w", "Alice", db_path=db_file)

    # 1. 單一吻合模糊查詢（例如 "alice"）
    res_single = router.handle_message("select alice")
    assert "目前作用對象已切換為：alice_w" in res_single

    # 2. 完全相等的精準查詢（例如 "sample_user_01"）即便多個包含 sample 也直接切換
    res_exact = router.handle_message("select sample_user_01")
    assert "目前作用對象已切換為：sample_user_01" in res_exact

    # 3. 多重候選查詢（例如 "sample" 匹配 2 個）
    res_multi = router.handle_message("select sample")
    assert "找到 2 個符合「sample」的對象" in res_multi
    assert "1. sample" in res_multi
    assert "2. sample" in res_multi
    assert "直接回傳數字如 1" in res_multi

    # 4. 回傳數字 1 確認切換
    res_choice = router.handle_message("1")
    assert "已確認！目前作用對象切換為：" in res_choice


def test_status_and_query_worker_progress(tmp_path):
    import time
    from app.storage.db import init_db, set_worker_status

    db_file = tmp_path / "test_worker.db"
    init_db(db_file)
    router = CommandRouter(memory_manager=MagicMock(), llm_client=MagicMock(), db_path=db_file)

    # 模擬背景爬蟲正在執行
    set_worker_status({
        "running": True,
        "target": "test_target",
        "mode": "安全慢速全量抓取",
        "pages": 12,
        "count": 240,
        "start_time": time.time() - 300
    }, db_path=db_file)

    res = router.handle_message("query")
    assert "背景抓取中" in res
    assert "test_target" in res
    assert "第 12 頁" in res
    assert "240 則" in res

    # 模擬背景爬蟲已結束
    set_worker_status({
        "running": False,
        "target": "test_target"
    }, db_path=db_file)

    res_done = router.handle_message("status")
    assert "無執行中任務" in res_done


def test_chat_history_in_reply(tmp_path):
    from unittest.mock import MagicMock, call
    from app.storage.db import init_db, get_or_create_contact, add_bot_conversation, set_active_contact
    from app.bot.router import CommandRouter

    db_file = tmp_path / "chat_history_test.db"
    init_db(db_file)

    contact_id = get_or_create_contact("test_user", db_path=db_file)
    set_active_contact("test_user", db_path=db_file)

    # 預先寫入兩輪舊對話
    add_bot_conversation(role="user", content="他說今天不想聊", contact_id=contact_id, db_path=db_file)
    add_bot_conversation(role="assistant", content="可能他只是累了，不一定是針對你", contact_id=contact_id, db_path=db_file)

    mock_memory = MagicMock()
    mock_memory.get_full_context.return_value = (
        {"id": contact_id, "display_name": "test", "ig_account_id": "test_user"},
        "摘要卡內容",
        "RAG chunks",
        "近期訊息",
        "你: 他說今天不想聊\nAI: 可能他只是累了，不一定是針對你",
        "我最近換了新工作"
    )
    mock_llm = MagicMock()
    mock_llm.generate_reply.return_value = "好，那你現在怎麼想？"

    router = CommandRouter(memory_manager=mock_memory, llm_client=mock_llm, db_path=db_file)
    reply = router.handle_message("那我應該繼續追嗎")

    # 確認 generate_reply 有收到 chat_history
    call_kwargs = mock_llm.generate_reply.call_args.kwargs
    assert "chat_history" in call_kwargs
    assert "他說今天不想聊" in call_kwargs["chat_history"]
    assert reply == "好，那你現在怎麼想？"


def test_card_command(tmp_path):
    from app.storage.db import init_db, get_or_create_contact, set_active_contact, update_contact_summary, set_contact_nickname
    from app.bot.router import CommandRouter

    db_file = tmp_path / "card_test.db"
    init_db(db_file)

    c_id = get_or_create_contact("amy_lee", "Amy", db_path=db_file)
    set_contact_nickname(c_id, "愛咪", db_path=db_file)
    update_contact_summary(c_id, "這是 Amy 的關係深度復盤摘要內容", db_path=db_file)

    router = CommandRouter(memory_manager=MagicMock(), llm_client=MagicMock(), db_path=db_file)

    # 1. 未 select 時直接指定帳號或暱稱查詢
    res_direct = router.handle_message("card amy_lee")
    assert "amy_lee" in res_direct
    assert "愛咪" in res_direct
    assert "這是 Amy 的關係深度復盤摘要內容" in res_direct

    res_by_nick = router.handle_message("摘要 愛咪")
    assert "amy_lee" in res_by_nick
    assert "這是 Amy 的關係深度復盤摘要內容" in res_by_nick

    # 2. select 作用對象後不帶參數直接輸入 card
    set_active_contact("amy_lee", db_path=db_file)
    res_active = router.handle_message("card")
    assert "這是 Amy 的關係深度復盤摘要內容" in res_active

    # 3. 查無對象或尚未建立摘要卡
    get_or_create_contact("no_summary_user", "NoSummary", db_path=db_file)
    res_empty = router.handle_message("card no_summary_user")
    assert "目前尚未建立摘要卡" in res_empty

