from unittest.mock import MagicMock, patch
from datetime import datetime
import pytest

from app.core.config import settings
from app.storage.db import (
    init_db,
    get_or_create_contact,
    save_messages,
    get_contact_by_id,
    set_active_contact,
    update_contact_full_history,
)
from app.storage.repositories import ContactRepository, MessageRepository, BotStateRepository
from app.storage.vectors import VectorStore
from app.services.llm_service import LLMClient
from app.services.memory_service import MemoryManager
from app.services.ingestion_service import IngestionPipeline
from app.bot.router import CommandRouter


def test_batch_embedding_and_dimensionality(monkeypatch):
    """驗證 VectorStore 支援批次 API 與 768 維度設定。"""
    mock_genai_client = MagicMock()
    mock_emb_1 = MagicMock()
    mock_emb_1.values = [0.1] * 768
    mock_emb_2 = MagicMock()
    mock_emb_2.values = [0.2] * 768

    mock_resp = MagicMock()
    mock_resp.embeddings = [mock_emb_1, mock_emb_2]
    mock_genai_client.models.embed_content.return_value = mock_resp

    vs = VectorStore()
    vs._genai_client = mock_genai_client

    texts = ["第一條事件記憶", "第二條事件記憶"]
    embs = vs.get_embeddings_batch(texts)

    assert len(embs) == 2
    assert len(embs[0]) == 768
    assert len(embs[1]) == 768

    mock_genai_client.models.embed_content.assert_called_once()
    call_kwargs = mock_genai_client.models.embed_content.call_args.kwargs
    assert len(call_kwargs["contents"]) == len(texts)
    assert call_kwargs["contents"][0].parts[0].text == texts[0]
    assert call_kwargs["config"].output_dimensionality == 768


def test_shared_query_embedding_in_memory_service(tmp_path):
    """驗證 MemoryManager 在查詢多個庫時只計算 1 次 Embedding 向量。"""
    db_file = tmp_path / "shared_emb.db"
    init_db(db_file)
    cid = get_or_create_contact("eva_user", "Eva", db_path=db_file)
    set_active_contact("eva_user", db_path=db_file)

    mock_vector = MagicMock()
    fake_embedding = [0.5] * 768
    mock_vector.get_embedding.return_value = fake_embedding
    mock_vector.query.return_value = [{"text": "相關事件記憶條目"}]

    mock_self_vector = MagicMock()
    mock_self_vector.query_self.return_value = [{"text": "使用者記憶"}]

    mem = MemoryManager(vector_store=mock_vector, self_vector_store=mock_self_vector, db_path=db_file)
    contact, summary, rag, recent, chat_hist, self_ctx = mem.get_full_context("明天要不要去夜市")

    # 驗證 get_embedding 只被呼叫 1 次！
    assert mock_vector.get_embedding.call_count == 1
    # 驗證 query 接收到了共享向量
    mock_vector.query.assert_called_once_with(
        contact_id=cid,
        query_text="明天要不要去夜市",
        query_embedding=fake_embedding,
        n_results=settings.CONTACT_RAG_RESULTS
    )
    # 驗證 query_self 同樣接收到了共享向量
    mock_self_vector.query_self.assert_called_once_with(
        query_text="明天要不要去夜市",
        query_embedding=fake_embedding,
        n_results=settings.SELF_RAG_RESULTS
    )


def test_event_extraction_pipeline():
    """驗證 IngestionPipeline.extract_event_chunks 成功呼叫 LLM 提煉事實條目。"""
    mock_llm = MagicMock()
    mock_llm.extract_events.return_value = [
        "[2026-08-18] 兩人相約台北橋三和夜市吃德克士，氣氛熱絡",
        "[2026-08-25] 對方透露近期正在找新租屋處，預算一萬二"
    ]
    pipeline = IngestionPipeline(llm_client=mock_llm)

    msgs = [
        {"sent_at": "2026-08-18T18:00:00", "sender": "them", "content": "要吃夜市嗎？"},
        {"sent_at": "2026-08-18T18:02:00", "sender": "me", "content": "好啊，三和夜市"},
    ]
    chunks = pipeline.extract_event_chunks(msgs)

    assert len(chunks) == 2
    assert chunks[0]["type"] == "event_memory"
    assert "德克士" in chunks[0]["text"]
    assert chunks[1]["type"] == "event_memory"
    assert "租屋處" in chunks[1]["text"]
    mock_llm.extract_events.assert_called_once()


def test_card_and_card_full_commands(tmp_path):
    """驗證 card 回傳日常輕量摘要卡，card full 回傳全景深度長文。"""
    db_file = tmp_path / "card_test.db"
    init_db(db_file)
    cid = get_or_create_contact("frank", "Frank", db_path=db_file)
    set_active_contact("frank", db_path=db_file)

    contact_repo = ContactRepository(db_path=db_file)
    contact_repo.update_summary(cid, "這是日常輕量摘要卡（300字）")
    contact_repo.update_full_history(cid, "這是 7 大章節全景長篇復盤報告（3000字）")

    router = CommandRouter(db_path=db_file)

    # 1. 查詢日常卡
    card_res = router.handle_message("card")
    assert "人物關係日常摘要卡" in card_res
    assert "這是日常輕量摘要卡（300字）" in card_res
    assert "這是 7 大章節全景長篇復盤報告" not in card_res

    # 2. 查詢全景長文
    card_full_res = router.handle_message("card full")
    assert "全景深度復盤長文" in card_full_res
    assert "這是 7 大章節全景長篇復盤報告（3000字）" in card_full_res


def test_help_and_help_all_grouping():
    """驗證 help 輸出精簡核心指令，help all 輸出包含進階維護的完整指令。"""
    router = CommandRouter()

    # 精簡核心指令
    help_brief = router.handle_message("help")
    assert "【IG AI 陪聊機器人 指令清單】" in help_brief
    assert "help all" in help_brief
    assert "rebuild_vectors" not in help_brief

    # 全量指令
    help_all = router.handle_message("help all")
    assert "全量模式" in help_all
    assert "rebuild_vectors" in help_all
    assert "track_full" in help_all


def test_repositories_crud(tmp_path):
    """驗證 Repository Pattern 封裝的 CRUD 操作。"""
    db_file = tmp_path / "repo_test.db"
    init_db(db_file)

    c_repo = ContactRepository(db_path=db_file)
    m_repo = MessageRepository(db_path=db_file)
    b_repo = BotStateRepository(db_path=db_file)

    # ContactRepository
    cid = c_repo.get_or_create("user_test", "Test User")
    assert cid > 0
    c_repo.set_active("user_test")
    active = c_repo.get_active()
    assert active["ig_account_id"] == "user_test"

    # MessageRepository
    inserted = m_repo.save_messages(cid, [
        {"ig_item_id": "item1", "sender": "me", "content": "你好", "sent_at": "2026-09-15T12:00:00"}
    ])
    assert inserted == 1
    recent = m_repo.get_recent(cid, limit=10)
    assert len(recent) == 1
    assert recent[0]["content"] == "你好"

    # BotStateRepository
    b_repo.set_worker_status({"running": True, "target": "user_test"})
    status = b_repo.get_worker_status()
    assert status["running"] is True
    assert status["target"] == "user_test"


def test_temporal_vector_clustering():
    """驗證時序向量分群：時間差 <= 36h 且相似度 >= 0.80 聚為同一 Cluster，否則獨立。"""
    pipeline = IngestionPipeline()
    mock_vector = MagicMock()
    # 建立 4 個事件的向量：
    # ev0 & ev1: 同一天，高相似度 (sim ~ 0.999) -> 應同一 Cluster
    # ev2: 同一天，低相似度 (sim ~ 0.0) -> 應獨立
    # ev3: 與 ev0 高相似度，但相隔 100 小時 (> 36h) -> 應獨立
    mock_vector.get_embeddings_batch.return_value = [
        [1.0, 0.0],       # ev0
        [0.99, 0.05],     # ev1 (與 ev0 sim ~ 0.998)
        [0.0, 1.0],       # ev2 (與 ev0 sim = 0.0)
        [1.0, 0.0],       # ev3 (與 ev0 相同向量，但時間相隔數天)
    ]
    pipeline.vector_store = mock_vector

    chunks = [
        {"id": "ev0", "text": "[2026-08-15] 兩人討論去沖繩玩", "start_time": "2026-08-15T10:00:00"},
        {"id": "ev1", "text": "[2026-08-15] 兩人規劃去沖繩吃石垣牛", "start_time": "2026-08-15T14:00:00"},
        {"id": "ev2", "text": "[2026-08-15] 對方機車在路上拋錨", "start_time": "2026-08-15T18:00:00"},
        {"id": "ev3", "text": "[2026-08-20] 兩人再度提議去沖繩海邊", "start_time": "2026-08-20T10:00:00"},
    ]

    clusters = pipeline.cluster_similar_events(chunks, similarity_threshold=0.80, max_hours_gap=36.0)

    # 應分成 3 個 Cluster:
    # Cluster 1: [ev0, ev1]
    # Cluster 2: [ev2]
    # Cluster 3: [ev3]
    assert len(clusters) == 3

    cluster_ids = [[c["id"] for c in cl] for cl in clusters]
    assert ["ev0", "ev1"] in cluster_ids
    assert ["ev2"] in cluster_ids
    assert ["ev3"] in cluster_ids


def test_lossless_consolidation_pipeline(monkeypatch):
    """驗證同質無損融合：孤立事件跳過 LLM，候選群組觸發 Lite 模型融合。"""
    monkeypatch.setattr(settings, "GEMINI_PACING_DELAY", 0.0)

    mock_llm = MagicMock()
    mock_llm.consolidate_events.return_value = [
        "[2026-08-15] 兩人規劃沖繩自由行，討論吃石垣牛與自駕租車"
    ]

    mock_vector = MagicMock()
    # ev0 與 ev1 高相似度，ev2 獨立
    mock_vector.get_embeddings_batch.return_value = [
        [1.0, 0.0],
        [0.98, 0.1],
        [0.0, 1.0],
    ]

    pipeline = IngestionPipeline(vector_store=mock_vector, llm_client=mock_llm)

    chunks = [
        {"id": "0", "text": "[2026-08-15] 兩人討論去沖繩玩", "start_time": "2026-08-15T10:00:00", "end_time": "2026-08-15T10:30:00", "message_count": 20},
        {"id": "1", "text": "[2026-08-15] 兩人規劃去沖繩吃石垣牛", "start_time": "2026-08-15T14:00:00", "end_time": "2026-08-15T14:30:00", "message_count": 20},
        {"id": "2", "text": "[2026-08-15] 機車拋錨抱怨", "start_time": "2026-08-15T18:00:00", "end_time": "2026-08-15T18:30:00", "message_count": 10},
    ]

    final_chunks = pipeline.consolidate_event_chunks(chunks)

    # 應產出 2 條 chunks（1 條融合後沖繩事件 + 1 條原樣拋錨事件）
    assert len(final_chunks) == 2
    # consolidate_events 只被呼叫 1 次（只針對沖繩 cluster）
    mock_llm.consolidate_events.assert_called_once()
    call_args = mock_llm.consolidate_events.call_args[0][0]
    assert len(call_args) == 2
    assert "去沖繩玩" in call_args[0]
    assert "吃石垣牛" in call_args[1]

    # 驗證融合後的 chunk 含有整合後的時間與訊息數
    okinawa_chunk = next(c for c in final_chunks if "沖繩" in c["text"])
    assert okinawa_chunk["message_count"] == 40
    assert okinawa_chunk["start_time"] == "2026-08-15T10:00:00"
    assert okinawa_chunk["end_time"] == "2026-08-15T14:30:00"

    # 驗證獨立的拋錨 chunk 原樣保留
    scooter_chunk = next(c for c in final_chunks if "拋錨" in c["text"])
    assert scooter_chunk["id"] == "2"
    assert scooter_chunk["message_count"] == 10

