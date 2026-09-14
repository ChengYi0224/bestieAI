import pytest
from unittest.mock import MagicMock, patch
from pathlib import Path
from app.db import (
    init_db,
    get_or_create_contact,
    set_contact_nickname,
    get_contacts_with_nickname,
    set_active_contact,
    get_contact_by_id,
)
from app.vectors import VectorStore
from app.memory import MemoryManager
from app.llm import LLMClient
from app.router import CommandRouter


def test_nickname_db_crud(tmp_path):
    db_file = tmp_path / "test_nick.db"
    init_db(db_file)

    c1 = get_or_create_contact("alice_w", "Alice", db_path=db_file)
    c2 = get_or_create_contact("bob_k", "Bob", db_path=db_file)

    # 初步查詢無暱稱
    assert len(get_contacts_with_nickname(db_path=db_file)) == 0

    # 設定暱稱
    success = set_contact_nickname(c1, "小白", db_path=db_file)
    assert success is True

    # 再次查詢
    nicks = get_contacts_with_nickname(db_path=db_file)
    assert len(nicks) == 1
    assert nicks[0]["nickname"] == "小白"
    assert nicks[0]["ig_account_id"] == "alice_w"


def test_vector_store_self_memory(tmp_path):
    chroma_dir = tmp_path / "chroma"
    mock_genai = MagicMock()
    mock_genai.models.embed_content.return_value = MagicMock(
        embeddings=[MagicMock(values=[0.1, 0.2, 0.3])]
    )

    vs = VectorStore(chroma_path=chroma_dir, collection_name="user_self")
    vs._genai_client = mock_genai

    # 寫入使用者自身記憶
    cid = vs.add_self_chunk("我最近換了新工作，在一家新創公司當工程師")
    assert cid.startswith("self_")

    # 查詢
    results = vs.query_self("新工作", n_results=2)
    assert len(results) == 1
    assert "新工作" in results[0]["text"]
    assert results[0]["metadata"]["type"] == "self_memory"


def test_memory_manager_self_rag(tmp_path):
    db_file = tmp_path / "test_mem.db"
    init_db(db_file)
    cid = get_or_create_contact("charlie", "Charlie", db_path=db_file)
    set_active_contact("charlie", db_path=db_file)

    mock_chat_vs = MagicMock()
    mock_chat_vs.query.return_value = [{"text": "chat chunk 1"}]

    mock_self_vs = MagicMock()
    mock_self_vs.query_self.return_value = [{"text": "使用者喜歡喝黑咖啡"}]

    mem = MemoryManager(vector_store=mock_chat_vs, self_vector_store=mock_self_vs, db_path=db_file)
    contact, summary, rag, recent, chat_hist, self_ctx = mem.get_full_context("要買什麼飲料")

    assert contact["ig_account_id"] == "charlie"
    assert self_ctx == "使用者喜歡喝黑咖啡"
    assert rag == "chat chunk 1"


def test_llm_extract_self_info():
    client = LLMClient(api_key="mock_key")
    
    # 測試萃取出具體資訊
    client._generate_with_fallback = MagicMock(return_value="- 使用者最近在準備托福考試")
    res = client.extract_self_info("我最近在準備托福，好累喔")
    assert res == "- 使用者最近在準備托福考試"

    # 測試無資訊輸出「無」
    client._generate_with_fallback = MagicMock(return_value="無")
    res_none = client.extract_self_info("他怎麼都不回我訊息")
    assert res_none == ""


def test_router_nickname_and_me_command(tmp_path):
    db_file = tmp_path / "test_router_nick.db"
    init_db(db_file)
    cid = get_or_create_contact("david_99", "David", db_path=db_file)
    set_active_contact("david_99", db_path=db_file)

    mock_memory = MagicMock()
    mock_llm = MagicMock()
    router = CommandRouter(memory_manager=mock_memory, llm_client=mock_llm, db_path=db_file)

    # 測試 nickname 指令為 active contact 設定暱稱
    res_nick = router.handle_message("nickname 大衛")
    assert "已為 david_99 設定暱稱為「大衛」" in res_nick

    # 測試 me 指令記錄自身記憶
    res_me = router.handle_message("me 我下週要出國出差")
    assert res_me == "好，我記下了。"
    mock_memory.add_self_memory.assert_called_once_with("我下週要出國出差")


def test_router_cross_rag_trigger(tmp_path):
    db_file = tmp_path / "test_cross_rag.db"
    init_db(db_file)

    c_active = get_or_create_contact("active_user", "Active", db_path=db_file)
    c_friend = get_or_create_contact("friend_eva", "Eva", db_path=db_file)
    set_active_contact("active_user", db_path=db_file)
    set_contact_nickname(c_friend, "小伊", db_path=db_file)

    mock_memory = MagicMock()
    mock_memory.get_full_context.return_value = (
        {"id": c_active, "display_name": "Active", "ig_account_id": "active_user"},
        "摘要卡",
        "RAG chunks",
        "近期訊息",
        "歷史對話",
        "自身記憶"
    )
    mock_memory.vector_store.query.return_value = [
        {"text": "Eva 說她喜歡看舞台劇"}
    ]

    mock_llm = MagicMock()
    mock_llm.generate_reply.return_value = "我知道了，小伊很喜歡看劇"

    router = CommandRouter(memory_manager=mock_memory, llm_client=mock_llm, db_path=db_file)
    router.handle_message("小伊之前好像說想看某個劇")

    # 驗證 generate_reply 是否有收到 cross_rag
    call_kwargs = mock_llm.generate_reply.call_args.kwargs
    assert "cross_rag" in call_kwargs
    assert "小伊" in call_kwargs["cross_rag"]
    assert "Eva 說她喜歡看舞台劇" in call_kwargs["cross_rag"]
