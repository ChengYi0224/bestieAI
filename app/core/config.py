from pathlib import Path
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """應用程式整體設定與調優參數配置。"""
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # ==================== 帳號、憑證與金鑰（由 .env 載入） ====================
    # 主帳號（使用者本人）Instagram 帳號與密碼
    MAIN_ACCOUNT_USERNAME: str = ""
    MAIN_ACCOUNT_PASSWORD: str = ""

    # 主帳號 Instagram User ID (PK)，用於白名單鑑權；若未設定則啟動時自動透過 API 解析
    MAIN_ACCOUNT_USER_ID: str = ""

    # Bot 帳號（負責陪聊與接收指令的專用 IG 帳號）
    BOT_ACCOUNT_USERNAME: str = ""
    BOT_ACCOUNT_PASSWORD: str = ""

    # Session 對稱加密金鑰 (Fernet 32-byte base64)；若未設定則自動保存於 data/.session_key
    SESSION_ENCRYPTION_KEY: str = ""

    # Google Gemini API Key（支援單一金鑰或多組金鑰逗號分隔）
    GEMINI_API_KEY: str = ""
    GEMINI_API_KEYS: str = ""

    @property
    def api_keys_list(self) -> list[str]:
        """健全解析 GEMINI_API_KEYS 或 GEMINI_API_KEY（支援單一、多組逗號分隔、去除引號與空白）。"""
        keys: list[str] = []
        raw_sources = [self.GEMINI_API_KEYS, self.GEMINI_API_KEY]
        for src in raw_sources:
            if not src:
                continue
            clean_src = str(src).strip().strip("'\"")
            for item in clean_src.split(","):
                cleaned = item.strip().strip("'\"").strip()
                if cleaned and cleaned not in keys:
                    keys.append(cleaned)
        return keys

    # ==================== 檔案與目錄路徑 ====================
    # SQLite 資料庫檔案路徑
    DB_PATH: Path = Field(default=Path("./data/app.db"))

    # ChromaDB 向量資料庫儲存目錄
    CHROMA_PATH: Path = Field(default=Path("./data/chroma"))

    # IG Session 檔案儲存目錄
    SESSION_DIR: Path = Field(default=Path("./data/sessions"))

    # 系統日誌目錄
    LOG_DIR: Path = Field(default=Path("./logs"))

    # LLM 調用輸入與輸出明文日誌路徑
    LLM_LOG_PATH: Path = Field(default=Path("./logs/llm.log"))

    # 錯誤日誌路徑（Rotating，5MB × 3 份）
    ERROR_LOG_PATH: Path = Field(default=Path("./logs/error.log"))

    # 是否啟用 LLM 呼叫明文記錄（預設開啟，方便個人 debug 追蹤）
    ENABLE_LLM_LOG: bool = Field(default=True)

    # Bot 私訊輪詢間隔（秒）
    POLL_INTERVAL_SECONDS: int = Field(default=15)

    # ==================== LLM 與 Embedding 模型設定 ====================
    # 向量嵌入模型名稱
    GEMINI_EMBEDDING_MODEL: str = Field(default="gemini-embedding-2")

    # 向量維度設定（gemini-embedding-2 支援指定 768 維度，提升速度並降低空間）
    EMBEDDING_DIMENSIONALITY: int = Field(default=768)

    # 文字生成候選模型順序清單（逗號分隔，遇到 503 / 404 / 限速時自動依序降級切換）
    GEMINI_CANDIDATE_MODELS: str = Field(
        default="gemini-3.8-flash,gemini-3.7-flash,gemini-3.6-flash"
    )

    # 候選模型輪換時，每個 Candidate Model 的最大 Retry 次數
    GEMINI_MODEL_MAX_RETRIES: int = Field(default=2)

    # 呼叫 Gemini API 的單次 Request Timeout 秒數
    GEMINI_REQUEST_TIMEOUT: float = Field(default=30.0)

    # 全量歷史復盤卡 (summarize_history) 專用模型
    GEMINI_FULL_SUMMARY_MODEL: str = Field(default="gemini-3.8-flash")

    # 記憶條目萃取 (extract_events) 專用候選模型清單（優先使用 500 RPD 之輕量模型，依序降級）
    GEMINI_EVENT_EXTRACTION_MODELS: str = Field(
        default="gemini-3.5-flash-lite,gemini-3.1-flash-lite"
    )

    # 自身記憶萃取 (extract_self_info) 專用預設模型
    GEMINI_SELF_EXTRACT_MODEL: str = Field(default="gemini-3.8-flash")

    # ==================== 記憶組裝與 RAG 檢索參數 ====================
    # 組裝提示詞時，載入與目前對象在 IG 上的近期原始對話則數
    RECENT_MESSAGES_LIMIT: int = Field(default=30)

    # 與 AI 討論時，納入提示詞的本輪對話歷史輪數（每輪含使用者問與 AI 回）
    CHAT_HISTORY_TURNS: int = Field(default=10)

    # 對象歷史事件向量庫的語意檢索筆數
    CONTACT_RAG_RESULTS: int = Field(default=5)

    # 使用者自身記憶向量庫 (user_self) 的語意檢索筆數
    SELF_RAG_RESULTS: int = Field(default=3)

    # 對話中提及其他聯絡人暱稱時，跨對象向量檢索的筆數
    CROSS_RAG_RESULTS: int = Field(default=3)

    # ==================== 抓取、切塊與摘要更新門檻 ====================
    # track 首次追蹤快速匯入時的預設訊息則數（至少 1000 則）
    TRACK_DEFAULT_LIMIT: int = Field(default=1000)

    # track_full 安全慢速全量抓取時的預設最大歷史訊息則數
    TRACK_FULL_DEFAULT_LIMIT: int = Field(default=5000)


    # 事件萃取時，單一批次提煉的訊息筆數（每批提煉為 2~4 條關鍵事件摘要）
    EVENT_EXTRACTION_BATCH_SIZE: int = Field(default=800)
    EVENT_EXTRACTION_MAX_SIZE: int = Field(default=1000)

    # 歷史對話切塊（Chunking）時，單一 Chunk 容納的最多訊息筆數（保留向後相容）
    CHUNK_MAX_SIZE: int = Field(default=20)

    # 累積新訊息達此數量時，觸發自動更新人物關係摘要卡
    SUMMARY_MESSAGE_THRESHOLD: int = Field(default=50)

    # 摘要卡超過此天數未更新且有新訊息時，觸發自動更新
    SUMMARY_DAYS_LIMIT: int = Field(default=14)

    # ==================== 速率節流與向量分群門檻 ====================
    # 批次 LLM 呼叫間隔節流（秒，避開免費層 15 RPM 上限，測試環境可設為 0）
    GEMINI_PACING_DELAY: float = Field(default=4.5)

    # 事件時序向量分群餘弦相似度門檻（>= 0.90 進入同質無損融合候選群）
    EVENT_CLUSTER_SIMILARITY_THRESHOLD: float = Field(default=0.90)

    # 事件時序向量分群最大時間差（小時，預設 24 小時以控制同主題跨度）
    EVENT_CLUSTER_MAX_HOURS_GAP: float = Field(default=24.0)

    # 單一分群最大條目數（避免群組過大混雜）
    EVENT_MAX_CLUSTER_SIZE: int = Field(default=4)

    @property
    def candidate_models_list(self) -> list[str]:
        return [m.strip() for m in self.GEMINI_CANDIDATE_MODELS.split(",") if m.strip()]

    @property
    def event_extraction_models_list(self) -> list[str]:
        return [m.strip() for m in self.GEMINI_EVENT_EXTRACTION_MODELS.split(",") if m.strip()]


settings = Settings()
