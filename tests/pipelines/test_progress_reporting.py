import time
from unittest.mock import MagicMock
from app.pipelines.extraction import EventExtractor
from app.pipelines.consolidation import EventConsolidator
from app.services.ingestion_service import IngestionPipeline
from app.bot.router import CommandRouter
from app.storage.db import (
    init_db,
    get_or_create_contact,
    save_messages,
    set_worker_status,
    get_worker_status,
)


def test_event_extractor_progress_callback():
    """驗證 EventExtractor 呼叫與快取命中時皆會觸發 progress_callback。"""
    mock_gemini = MagicMock()
    mock_gemini.generate_text.return_value = "- 討論了期末專案進度\n- 約定週六見面"
    extractor = EventExtractor(gemini_client=mock_gemini, target_batch_size=2, overlap_size=0)

    messages = [
        {"sender": "them", "content": "你好", "sent_at": "2026-09-15T10:00:00"},
        {"sender": "me", "content": "嗨", "sent_at": "2026-09-15T10:01:00"},
        {"sender": "them", "content": "專案如何", "sent_at": "2026-09-15T10:02:00"},
        {"sender": "me", "content": "快寫完了", "sent_at": "2026-09-15T10:03:00"},
    ]

    progress_log = []
    def on_progress(msg: str):
        progress_log.append(msg)

    chunks = extractor.extract_from_messages(messages, progress_callback=on_progress)
    assert len(chunks) == 4
    assert len(progress_log) >= 3
    assert any("切分為 2 個批次" in log for log in progress_log)
    assert any("批次 1/2" in log for log in progress_log)
    assert any("批次 2/2" in log for log in progress_log)


def test_event_consolidator_progress_callback():
    """驗證 EventConsolidator 批次打包融合時會觸發 progress_callback。"""
    mock_gemini = MagicMock()
    mock_gemini.generate_text.return_value = '<cluster_result id="group_0">\n- 融合後的事件摘要\n</cluster_result>'
    consolidator = EventConsolidator(gemini_client=mock_gemini, batch_size=2)

    clusters = [
        [
            {"id": "e1", "text": "事件 1", "start_time": "2026-09-15T10:00:00", "end_time": "2026-09-15T10:01:00"},
            {"id": "e2", "text": "事件 2", "start_time": "2026-09-15T10:02:00", "end_time": "2026-09-15T10:03:00"},
        ]
    ]

    progress_log = []
    consolidated = consolidator.consolidate(clusters, progress_callback=lambda m: progress_log.append(m))
    assert len(consolidated) == 1
    assert any("同質事件融合中" in m for m in progress_log)


def test_rebuild_vectors_progress_pipeline(tmp_path):
    """驗證 rebuild_vectors 依序執行各階段並透過 progress_callback 回報。"""
    db_file = tmp_path / "test_rebuild_prog.db"
    init_db(db_file)
    cid = get_or_create_contact("test_user", "Test User", db_path=db_file)

    save_messages(cid, [
        {"ig_item_id": "m1", "sender": "them", "content": "明天開會嗎", "sent_at": "2026-09-15T10:00:00"},
        {"ig_item_id": "m2", "sender": "me", "content": "對，十點", "sent_at": "2026-09-15T10:01:00"},
    ], db_path=db_file)

    mock_vector = MagicMock()
    mock_llm = MagicMock()
    mock_llm.extract_events.return_value = ["討論明天十點開會"]
    pipeline = IngestionPipeline(vector_store=mock_vector, llm_client=mock_llm)

    progress_steps = []
    res = pipeline.rebuild_vectors(
        "test_user",
        progress_callback=lambda m: progress_steps.append(m),
        db_path=db_file
    )

    assert res["total_messages"] == 2
    assert len(progress_steps) >= 3
    assert any("正在讀取 test_user 本地對話紀錄" in s for s in progress_steps)
    assert any("正在寫入 ChromaDB 向量庫" in s for s in progress_steps)
    assert any("向量庫重建完成" in s for s in progress_steps)


def test_router_q_command_shows_dynamic_progress(tmp_path):
    """驗證 q 指令能即時展示重建各階段的具體批次與進度。"""
    db_file = tmp_path / "test_q_prog.db"
    init_db(db_file)
    router = CommandRouter(memory_manager=MagicMock(), llm_client=MagicMock(), db_path=db_file)

    # 1. 模擬提煉中階段
    set_worker_status({
        "running": True,
        "target": "alex_123",
        "mode": "重建向量庫",
        "detail": "提煉事件中: 批次 3/10 完成 (累計 15 條事件)",
        "start_time": time.time() - 45
    }, db_path=db_file)

    res_q1 = router.handle_message("q")
    assert "【重建向量庫執行中】" in res_q1
    assert "alex_123" in res_q1
    assert "提煉事件中: 批次 3/10 完成 (累計 15 條事件)" in res_q1

    # 2. 模擬分群與融合階段
    set_worker_status({
        "running": True,
        "target": "alex_123",
        "mode": "重建向量庫",
        "detail": "同質事件融合中: 第 1~2/2 群...",
        "start_time": time.time() - 90
    }, db_path=db_file)

    res_q2 = router.handle_message("q")
    assert "同質事件融合中: 第 1~2/2 群..." in res_q2

    # 3. 模擬全景復盤分析階段
    set_worker_status({
        "running": True,
        "target": "alex_123",
        "mode": "全景復盤分析",
        "detail": "共 1200 則對話，正在呼叫 LLM 進行 7 大維度全景深度復盤分析...",
        "start_time": time.time() - 10
    }, db_path=db_file)

    res_q3 = router.handle_message("status")
    assert "【全景復盤分析執行中】" in res_q3
    assert "7 大維度全景深度復盤分析" in res_q3
