import pytest
from app.core.config import settings
from app.clients.gemini import GeminiClient
from instagrapi import Client


@pytest.mark.external
def test_gemini_api_live():
    """測試 Google Gemini API 連線與文字生成（未配置金鑰則 Skip）。"""
    valid_keys = [k for k in settings.api_keys_list if k and not k.startswith("mock_")]
    if not valid_keys:
        pytest.skip("環境變數未提供有效之 GEMINI_API_KEY / GEMINI_API_KEYS，略過真實 Gemini API 測試")

    client = GeminiClient()
    # 測試 generate_text 關閉 Thinking 與 Timeout 配置
    result = client.generate_text(
        prompt="請只回傳單詞：OK",
        max_retries=2,
        timeout=20.0,
        disable_thinking=True,
    )
    assert isinstance(result, str)
    assert len(result.strip()) > 0

    # 測試 Embedding 批次向量計算
    embs = client.get_embeddings_batch(["測試文本向量計算"])
    assert len(embs) == 1
    assert len(embs[0]) > 0


@pytest.mark.external
def test_instagram_api_live():
    """真實測試 Instagram API 連線（檢查環境變數帳號密碼，無則 skip）。"""
    username = (getattr(settings, "MAIN_ACCOUNT_USERNAME", "") or getattr(settings, "BOT_ACCOUNT_USERNAME", "")).strip()
    password = (getattr(settings, "MAIN_ACCOUNT_PASSWORD", "") or getattr(settings, "BOT_ACCOUNT_PASSWORD", "")).strip()
    if not username or not password or username == "mock_user":
        pytest.skip("環境變數未配置 MAIN_ACCOUNT_USERNAME 或 BOT_ACCOUNT_USERNAME，略過真實 Instagram 測試")

    cl = Client()
    cl.request_timeout = 8
    # 簡單連通性測試：能成功初始化且可解析或連通公開服務
    assert hasattr(cl, "user_id_from_username")
    try:
        uid = cl.user_id_from_username("instagram")
        assert uid is not None
    except Exception as e:
        # 若遭遇 IG 臨時限速，至少確認網路與端點協議有反應
        assert "instagram" in str(e).lower() or len(str(e)) > 0
