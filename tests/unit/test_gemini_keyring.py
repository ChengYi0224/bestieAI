import pytest
import time
from unittest.mock import MagicMock, patch
from app.core.config import Settings
from app.clients.gemini import GeminiKeyRing, GeminiClient, _is_invalid_key, _is_rate_limit


def test_config_api_keys_list_parsing(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEYS", raising=False)

    s1 = Settings(GEMINI_API_KEYS="key1, key2,  key3 ", GEMINI_API_KEY="")
    assert s1.api_keys_list == ["key1", "key2", "key3"]

    s2 = Settings(GEMINI_API_KEYS='"key1, key2, key3"', GEMINI_API_KEY="")
    assert s2.api_keys_list == ["key1", "key2", "key3"]

    s3 = Settings(GEMINI_API_KEYS="'keyA, keyB'", GEMINI_API_KEY="")
    assert s3.api_keys_list == ["keyA", "keyB"]

    s4 = Settings(GEMINI_API_KEY="k1, k2, k3", GEMINI_API_KEYS="")
    assert s4.api_keys_list == ["k1", "k2", "k3"]

    s5 = Settings(GEMINI_API_KEY='"single_key"', GEMINI_API_KEYS="")
    assert s5.api_keys_list == ["single_key"]


def test_keyring_round_robin():
    ring = GeminiKeyRing(keys=["key1", "key2", "key3"])
    assert ring.get_available_key() == "key1"
    assert ring.get_available_key() == "key2"
    assert ring.get_available_key() == "key3"
    assert ring.get_available_key() == "key1"


def test_keyring_cooldown_skipping():
    ring = GeminiKeyRing(keys=["k1", "k2"])
    assert ring.get_available_key() == "k1"

    ring.mark_cooldown("k2", cooldown_seconds=60)
    ring.mark_cooldown("k1", cooldown_seconds=10)

    # 全部冷卻中時，應退回至最早冷卻結束的 k1
    assert ring.get_available_key() == "k1"


def test_is_invalid_key_detection():
    err1 = "400 INVALID_ARGUMENT. API key not valid. Please pass a valid API key."
    err2 = "{'error': {'code': 400, 'message': 'API key not valid.', 'details': [{'reason': 'API_KEY_INVALID'}]}}"
    err3 = "429 RESOURCE_EXHAUSTED. Quota exceeded."
    err4 = "500 INTERNAL_SERVER_ERROR"

    assert _is_invalid_key(err1) is True
    assert _is_invalid_key(err2) is True
    assert _is_invalid_key(err3) is False
    assert _is_invalid_key(err4) is False

    assert _is_rate_limit(err3) is True
    assert _is_rate_limit(err1) is False


def test_client_switches_on_invalid_key():
    keyring = GeminiKeyRing(keys=["invalid_key", "valid_key"])
    client = GeminiClient(key_ring=keyring)

    mock_bad_client = MagicMock()
    mock_bad_client.models.generate_content.side_effect = Exception(
        "400 INVALID_ARGUMENT. API key not valid. Please pass a valid API key."
    )

    mock_good_client = MagicMock()
    mock_good_resp = MagicMock()
    mock_good_resp.text = "Hello success"
    mock_good_client.models.generate_content.return_value = mock_good_resp

    def fake_get_client(key):
        if key == "invalid_key":
            return mock_bad_client
        return mock_good_client

    with patch.object(keyring, "get_client", side_effect=fake_get_client):
        result = client.generate_text(prompt="測試提示詞", preferred_model="gemini-3.8-flash")
        assert result == "Hello success"
        # invalid_key 應該被標記冷卻 24 小時
        assert keyring.cooldowns["invalid_key"] > time.time() + 80000


def test_client_passes_no_thinking_and_timeout_config():
    """驗證呼叫 generate_text 時，確實關閉思考 (thinking_budget=0) 並帶入超時時間。"""
    keyring = GeminiKeyRing(keys=["test_key"])
    client = GeminiClient(key_ring=keyring)

    mock_client = MagicMock()
    mock_resp = MagicMock()
    mock_resp.text = "Success with config"
    mock_client.models.generate_content.return_value = mock_resp

    with patch.object(keyring, "get_client", return_value=mock_client):
        res = client.generate_text(prompt="Test prompt", preferred_model="gemini-3.7-flash", timeout=25.0)
        assert res == "Success with config"

        mock_client.models.generate_content.assert_called_once()
        _, kwargs = mock_client.models.generate_content.call_args
        config = kwargs.get("config")
        assert config is not None
        assert config.thinking_config.thinking_budget == 0
        assert config.http_options.timeout == 25000


def test_client_model_retry_count_from_settings(monkeypatch):
    """驗證輪換模型時，每個模型呼叫次數符合 1 次初呼叫 + settings.GEMINI_MODEL_MAX_RETRIES 次重試。"""
    from app.core.config import settings

    monkeypatch.setattr(settings, "GEMINI_MODEL_MAX_RETRIES", 2)
    keyring = GeminiKeyRing(keys=["k1"])
    client = GeminiClient(key_ring=keyring)

    mock_client = MagicMock()
    # 模擬模型 1 經歷 1 次初呼叫 + 2 次 retry（共 3 次失敗）後，切換到模型 2 第 1 次成功
    mock_resp = MagicMock()
    mock_resp.text = "Model 2 success"
    mock_client.models.generate_content.side_effect = [
        Exception("503 Service Unavailable"),
        Exception("503 Service Unavailable"),
        Exception("503 Service Unavailable"),
        mock_resp,
    ]

    with patch.object(keyring, "get_client", return_value=mock_client), patch("time.sleep"):
        res = client.generate_text(
            prompt="Test",
            candidate_models=["gemini-3.8-flash", "gemini-3.7-flash"],
        )
        assert res == "Model 2 success"
        # 總共呼叫 4 次（模型 1 嘗試 1 初次 + 2 重試 = 3 次失敗，模型 2 嘗試第 1 次成功）
        assert mock_client.models.generate_content.call_count == 4


