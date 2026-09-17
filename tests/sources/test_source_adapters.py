"""
test_source_adapters.py — 資料來源適配器與工廠模式單元測試。
"""
import json
import pytest
from datetime import datetime, timezone
from unittest.mock import MagicMock
from app.sources.base import BaseSourceAdapter, NormalizedMessage
from app.sources.factory import SourceAdapterFactory
from app.sources.instagram import InstagramAdapter
from app.sources.file_import import FileImportAdapter
from app.services.ingestion_service import IngestionPipeline
from app.storage.db import init_db


def test_normalized_message_validation():
    # 正確建立
    msg = NormalizedMessage(
        external_id="msg_001",
        sender="me",
        content="哈囉",
        sent_at="2026-09-17T03:00:00+08:00",
        source_type="test",
        extras={"custom_tag": "test"}
    )
    assert msg.external_id == "msg_001"
    assert msg.sender == "me"
    assert msg.extras["custom_tag"] == "test"
    assert msg.to_dict()["source_type"] == "test"

    # 空 external_id 應拋出 ValueError
    with pytest.raises(ValueError, match="external_id"):
        NormalizedMessage(
            external_id="",
            sender="me",
            content="哈囉",
            sent_at="2026-09-17T03:00:00",
            source_type="test"
        )

    # 無效 sender 應拋出 ValueError
    with pytest.raises(ValueError, match="sender"):
        NormalizedMessage(
            external_id="msg_002",
            sender="someone_else",
            content="哈囉",
            sent_at="2026-09-17T03:00:00",
            source_type="test"
        )

    # 無效時間格式應拋出 ValueError
    with pytest.raises(ValueError, match="sent_at"):
        NormalizedMessage(
            external_id="msg_003",
            sender="them",
            content="哈囉",
            sent_at="not-a-timestamp",
            source_type="test"
        )


def test_instagram_adapter_fetch():
    mock_ig = MagicMock()
    mock_ig.client.user_id = 12345

    mock_thread = MagicMock()
    mock_thread.id = 999888
    mock_ig.get_thread_by_username.return_value = mock_thread

    msg_me = MagicMock()
    msg_me.id = 101
    msg_me.user_id = 12345
    msg_me.text = "這是我傳的"
    msg_me.timestamp = datetime(2026, 9, 17, 3, 0, 0, tzinfo=timezone.utc)

    msg_them = MagicMock()
    msg_them.id = 102
    msg_them.user_id = 67890
    msg_them.text = "這是對方傳的"
    msg_them.timestamp = datetime(2026, 9, 17, 3, 1, 0, tzinfo=timezone.utc)

    mock_ig.get_thread_messages.return_value = [msg_me, msg_them]

    adapter = InstagramAdapter(ig_client=mock_ig)
    assert adapter.get_self_id() == "12345"

    result = adapter.fetch_messages("test_target", amount=10)
    assert len(result) == 2

    assert result[0].external_id == "101"
    assert result[0].sender == "me"
    assert result[0].content == "這是我傳的"
    assert result[0].source_type == "instagram"
    assert result[0].extras["thread_id"] == "999888"

    assert result[1].external_id == "102"
    assert result[1].sender == "them"
    assert result[1].content == "這是對方傳的"


def test_file_import_adapter_json(tmp_path):
    json_file = tmp_path / "chat.json"
    data = {
        "self_id": "user_me",
        "messages": [
            {
                "id": "j_1",
                "sender": "user_me",
                "content": "JSON 我說的話",
                "sent_at": "2026-09-17T03:10:00+00:00"
            },
            {
                "id": "j_2",
                "sender": "user_them",
                "content": "JSON 對方說的話",
                "sent_at": "2026-09-17T03:11:00+00:00"
            }
        ]
    }
    json_file.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    adapter = FileImportAdapter(self_id="user_me", format="json")
    messages = adapter.fetch_messages(str(json_file))

    assert len(messages) == 2
    assert messages[0].sender == "me"
    assert messages[0].content == "JSON 我說的話"
    assert messages[1].sender == "them"
    assert messages[1].content == "JSON 對方說的話"
    assert messages[0].source_type == "file_import"


def test_file_import_adapter_csv(tmp_path):
    csv_file = tmp_path / "chat.csv"
    content = "id,sender,content,sent_at\nc_1,me,CSV測試1,2026-09-17T03:20:00+00:00\nc_2,them,CSV測試2,2026-09-17T03:21:00+00:00\n"
    csv_file.write_text(content, encoding="utf-8")

    adapter = FileImportAdapter(self_id="me", format="csv")
    messages = adapter.fetch_messages(str(csv_file))

    assert len(messages) == 2
    assert messages[0].external_id == "c_1"
    assert messages[0].sender == "me"
    assert messages[1].sender == "them"


def test_file_import_adapter_line_txt(tmp_path):
    txt_file = tmp_path / "line_chat.txt"
    content = (
        "[LINE] 2026/09/17 與「小明」的聊天記錄\n\n"
        "2026/09/17 星期四\n"
        "12:30\t小明\t吃飯了嗎？\n"
        "12:31\t我\t還沒耶，一起吃？\n"
    )
    txt_file.write_text(content, encoding="utf-8")

    adapter = FileImportAdapter(self_id="我", format="line_txt")
    messages = adapter.fetch_messages(str(txt_file))

    assert len(messages) == 2
    assert messages[0].sender == "them"
    assert messages[0].content == "吃飯了嗎？"
    assert messages[1].sender == "me"
    assert messages[1].content == "還沒耶，一起吃？"

def test_source_adapter_factory():
    mock_ig = MagicMock()
    ig_adapter = SourceAdapterFactory.create("instagram", ig_client=mock_ig)
    assert isinstance(ig_adapter, InstagramAdapter)

    file_adapter = SourceAdapterFactory.create("file_import", self_id="me")
    assert isinstance(file_adapter, FileImportAdapter)

    # 別名也應該可以建立
    file_adapter2 = SourceAdapterFactory.create("file", self_id="me")
    assert isinstance(file_adapter2, FileImportAdapter)

    # 未知來源應報錯，且列出已知清單
    with pytest.raises(ValueError, match="不支援"):
        SourceAdapterFactory.create("unknown_app")

    # 已註冊清單應包含 instagram 與 file_import
    registered = SourceAdapterFactory.registered_types()
    assert "instagram" in registered
    assert "file_import" in registered



def test_ingestion_pipeline_with_custom_adapter(tmp_path):
    db_file = tmp_path / "test_ingestion_adapter.db"
    init_db(db_file)

    mock_llm = MagicMock()
    mock_llm.generate_summary.return_value = "測試摘要卡"

    mock_vector = MagicMock()
    mock_vector.get_embeddings_batch.return_value = [[0.1, 0.2]]

    pipeline = IngestionPipeline(
        vector_store=mock_vector,
        llm_client=mock_llm,
    )
    # mock extract_event_chunks
    pipeline.extract_event_chunks = MagicMock(return_value=[])

    # 自訂 mock adapter
    mock_adapter = MagicMock(spec=BaseSourceAdapter)
    mock_adapter.fetch_messages.return_value = [
        NormalizedMessage(
            external_id="custom_1",
            sender="them",
            content="你好呀",
            sent_at="2026-09-17T03:30:00+00:00",
            source_type="custom"
        )
    ]

    res = pipeline.run_full_ingestion(
        source=mock_adapter,
        target_username="friend_custom",
        db_path=db_file
    )

    assert res["downloaded_messages"] == 1
    assert res["new_inserted_messages"] == 1
    mock_adapter.fetch_messages.assert_called_once_with(
        target="friend_custom",
        amount=5000,
        progress_callback=None
    )
