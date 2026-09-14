"""
gemini.py — Google Gemini 外部客戶端封裝。
職責：
1. 支援 GEMINI_API_KEYS 多組 API Key 動態輪換（Round-Robin）。
2. 429 / 配額超限（ResourceExhausted）自動感知與個別 Key 冷卻跳過。
3. 純粹的遠端呼叫傳輸（文字生成與向量 Embedding），絕不包含任何具體業務 Prompt。
"""
import time
import logging
from typing import List, Optional, Dict, Any
from google import genai
from google.genai.errors import APIError

from app.core.config import settings

logger = logging.getLogger("bestieAI.clients.gemini")


class GeminiKeyRing:
    """管理多組 Gemini API Key 的輪換池與冷卻狀態。"""

    def __init__(self, keys: Optional[List[str]] = None):
        if keys:
            self.keys = [k.strip() for k in keys if k.strip()]
        else:
            # 從設定讀取 GEMINI_API_KEYS 或 GEMINI_API_KEY
            raw_keys = getattr(settings, "GEMINI_API_KEYS", None)
            if raw_keys:
                self.keys = [k.strip() for k in raw_keys.split(",") if k.strip()]
            else:
                single_key = getattr(settings, "GEMINI_API_KEY", "")
                self.keys = [single_key] if single_key else []

        if not self.keys:
            logger.warning("未配置任何 GEMINI_API_KEY！")

        self.current_idx = 0
        self.cooldowns: Dict[str, float] = {k: 0.0 for k in self.keys}
        self.client_cache: Dict[str, genai.Client] = {}

    def mark_cooldown(self, key: str, cooldown_seconds: float = 60.0):
        """將特定 Key 標記為冷卻狀態。"""
        self.cooldowns[key] = time.time() + cooldown_seconds
        logger.warning(f"Gemini API Key (***{key[-4:] if len(key) >= 4 else '***'}) 進入冷卻 {cooldown_seconds} 秒")

    def get_available_key(self) -> Optional[str]:
        """以 Round-Robin 尋找未在冷卻中的有效 API Key。"""
        if not self.keys:
            return None

        now = time.time()
        n = len(self.keys)
        for i in range(n):
            idx = (self.current_idx + i) % n
            key = self.keys[idx]
            if now >= self.cooldowns.get(key, 0.0):
                self.current_idx = (idx + 1) % n
                return key

        # 若全部都在冷卻中，取冷卻時間最短的
        earliest_key = min(self.keys, key=lambda k: self.cooldowns.get(k, 0.0))
        wait_seconds = max(0.0, self.cooldowns[earliest_key] - now)
        logger.warning(f"所有 API Key 均在冷卻中，最快解鎖需等待 {wait_seconds:.1f} 秒")
        return earliest_key

    def get_client(self, key: Optional[str] = None) -> genai.Client:
        """取得對應 Key 的 Client 實例（快取複用）。"""
        k = key or self.get_available_key()
        if not k:
            return genai.Client()
        if k not in self.client_cache:
            self.client_cache[k] = genai.Client(api_key=k)
        return self.client_cache[k]


class GeminiClient:
    """封裝 Gemini 遠端呼叫（支援多 Key 輪換、自適應重試、純傳輸）。"""

    def __init__(self, key_ring: Optional[GeminiKeyRing] = None):
        self.key_ring = key_ring or GeminiKeyRing()

    def generate_text(
        self,
        prompt: str,
        preferred_model: Optional[str] = None,
        candidate_models: Optional[List[str]] = None,
        max_retries: int = 3
    ) -> str:
        """呼叫文字生成 API（遇到 429 自動輪換 Key 與退避重試）。"""
        models = []
        if preferred_model:
            models.append(preferred_model)
        models.extend(candidate_models or getattr(settings, "candidate_models_list", ["gemini-3.8-flash", "gemini-3.5-flash-lite"]))
        # 去重維持順序
        seen = set()
        dedup_models = [m for m in models if not (m in seen or seen.add(m))]

        for model in dedup_models:
            for attempt in range(max_retries):
                key = self.key_ring.get_available_key()
                client = self.key_ring.get_client(key)
                try:
                    res = client.models.generate_content(model=model, contents=prompt)
                    return res.text or ""
                except Exception as e:
                    err_str = str(e)
                    is_rate_limit = "429" in err_str or "RESOURCE_EXHAUSTED" in err_str
                    if is_rate_limit and key:
                        self.key_ring.mark_cooldown(key, cooldown_seconds=65.0)
                        # 還有重試機會，換下一個 Key 繼續試
                        if attempt < max_retries - 1:
                            continue
                    logger.warning(f"模型 {model} 呼叫失敗 (嘗試 {attempt + 1}/{max_retries}): {e}")
                    if attempt < max_retries - 1:
                        time.sleep(2.0)

        raise RuntimeError(f"所有候選模型及 API Key 均呼叫失敗: {dedup_models}")

    def get_embeddings_batch(
        self,
        texts: List[str],
        model: Optional[str] = None,
        max_batch_size: int = 100,
        max_retries: int = 5
    ) -> List[List[float]]:
        """批次取得文字 Embedding 向量（內建 100 筆上限切割與多 Key 輪換）。"""
        if not texts:
            return []

        emb_model = model or getattr(settings, "GEMINI_EMBEDDING_MODEL", "gemini-embedding-2")
        dim = getattr(settings, "EMBEDDING_DIMENSIONALITY", 768)
        config = None
        try:
            from google.genai import types
            if dim:
                config = types.EmbedContentConfig(output_dimensionality=dim)
        except Exception:
            pass

        all_embeddings: List[List[float]] = []

        for start_idx in range(0, len(texts), max_batch_size):
            batch = texts[start_idx:start_idx + max_batch_size]
            batch_success = False

            for attempt in range(max_retries):
                key = self.key_ring.get_available_key()
                client = getattr(self, "_genai_client", None) or self.key_ring.get_client(key)
                try:
                    from google.genai import types
                    content_items = [types.Content(parts=[types.Part.from_text(text=t)]) for t in batch]
                    res = client.models.embed_content(
                        model=emb_model,
                        contents=content_items,
                        config=config
                    )
                    all_embeddings.extend([e.values for e in res.embeddings])
                    batch_success = True
                    break
                except Exception as e:
                    err_str = str(e)
                    is_rate_limit = "429" in err_str or "RESOURCE_EXHAUSTED" in err_str
                    if is_rate_limit and key:
                        self.key_ring.mark_cooldown(key, cooldown_seconds=65.0)
                        if attempt < max_retries - 1:
                            continue
                    logger.warning(f"Embedding 批次 {start_idx // max_batch_size + 1} 失敗 (嘗試 {attempt + 1}/{max_retries}): {e}")
                    if attempt < max_retries - 1:
                        time.sleep(3.0)

            if not batch_success:
                raise RuntimeError(f"Embedding 批次 {start_idx // max_batch_size + 1} 取得失敗！")

        return all_embeddings
