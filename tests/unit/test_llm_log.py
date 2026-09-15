import pytest
from unittest.mock import MagicMock
from app.services.llm_service import LLMClient, log_llm_call

def test_log_llm_call_writes_structured_log(tmp_path):
    log_file = tmp_path / "test_llm.log"

    # 1. 成功紀錄（含 token）
    log_llm_call(
        model="gemini-3.8-flash",
        prompt="你好，請給出回覆建議",
        output="哈囉！以下是回覆建議：1. 好的 2. 沒問題",
        duration_sec=1.25,
        log_path=log_file,
        prompt_tokens=15,
        candidate_tokens=25,
        total_tokens=40
    )

    content = log_file.read_text(encoding="utf-8")
    assert "[MODEL: gemini-3.8-flash]" in content
    assert "[STATUS: SUCCESS]" in content
    assert "耗時: 1.25s" in content
    assert "Tokens: 40 (prompt: 15, candidate: 25)" in content
    assert "[INPUT]" in content
    assert "你好，請給出回覆建議" in content
    assert "[OUTPUT]" in content
    assert "哈囉！以下是回覆建議" in content

    # 2. 失敗紀錄
    log_llm_call(
        model="gemini-3.7-flash",
        prompt="測試錯誤",
        error=ValueError("測試拋出例外"),
        duration_sec=0.45,
        log_path=log_file
    )

    updated_content = log_file.read_text(encoding="utf-8")
    assert "[MODEL: gemini-3.7-flash]" in updated_content
    assert "[STATUS: FAILED]" in updated_content
    assert "[ERROR]" in updated_content
    assert "測試拋出例外" in updated_content

def test_llm_client_logs_during_call(tmp_path):
    log_file = tmp_path / "client_llm.log"
    client = LLMClient(api_key="fake_key", log_path=log_file)

    # Mock client.models.generate_content
    mock_models = MagicMock()
    mock_resp = MagicMock()
    mock_resp.text = "這是由 Mock 生成的回覆"
    mock_models.generate_content.return_value = mock_resp

    client._client = MagicMock()
    client._client.models = mock_models

    res = client.generate_reply(
        display_name="小美",
        summary_card="好友關係",
        rag_chunks="上週聊過聚餐",
        recent_context="晚上要吃什麼",
        user_query="他問我晚上吃什麼"
    )

    assert res == "這是由 Mock 生成的回覆"
    assert log_file.exists()
    content = log_file.read_text(encoding="utf-8")
    assert "[INPUT]" in content
    assert "他問我晚上吃什麼" in content
    assert "[OUTPUT]" in content
    assert "這是由 Mock 生成的回覆" in content


def test_llm_log_disabled(tmp_path, monkeypatch):
    from app.core.config import settings

    log_file = tmp_path / "disabled_llm.log"
    monkeypatch.setattr(settings, "ENABLE_LLM_LOG", False)

    log_llm_call(
        model="gemini-3.8-flash",
        prompt="這則日誌不應該被寫入",
        output="這則也不該寫入",
        duration_sec=0.1,
        log_path=log_file
    )

    assert not log_file.exists()
