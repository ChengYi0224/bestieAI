import logging
from pathlib import Path
from typing import Optional
from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_logger = logging.getLogger("bestieAI.config")

# 公開在原始碼中的預設金鑰：僅允許 dev 環境使用
INSECURE_DEFAULT_API_SECRET = "your-secure-secret-key-here"
MIN_API_SECRET_LENGTH = 32


class Settings(BaseSettings):
    """應用程式整體設定與調優參數配置。"""
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # ==================== 執行環境 ====================
    # dev：本機開發，允許預設金鑰並預設開啟 LLM 明文日誌；prod：啟動時強制檢查安全設定，LLM 日誌預設關閉
    APP_ENV: str = Field(default="dev")

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

    # 是否啟用 LLM 呼叫明文記錄；未設定時 dev 開啟、prod 關閉（日誌含私訊明文）
    ENABLE_LLM_LOG: Optional[bool] = Field(default=None)

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

    # ==================== FastAPI REST API 設定 ====================
    # JWT 簽章金鑰（僅用於簽發 / 驗證 token，不可當密碼使用；prod 至少 32 字元且不可為預設值）
    API_SECRET: str = Field(default=INSECURE_DEFAULT_API_SECRET)

    # 管理者（user_id = 1）原生密碼登入用密碼；留空表示停用密碼登入（改用 Google 登入）
    ADMIN_PASSWORD: str = Field(default="")

    # JWT Token 有效時數
    API_TOKEN_EXPIRE_HOURS: int = Field(default=24)

    # CORS 允許來源（逗號分隔字串）
    CORS_ORIGINS: str = Field(default="http://localhost,http://10.0.2.2")

    # Google OAuth 2.0 Client IDs
    GOOGLE_CLIENT_ID_WEB: str = Field(default="")
    GOOGLE_CLIENT_ID_ANDROID: str = Field(default="")
    GOOGLE_CLIENT_ID_IOS: str = Field(default="")

    # 預設管理者 Google Email（登入時自動綁定至 user_id = 1）
    ADMIN_EMAIL: str = Field(default="")

    @property
    def is_prod(self) -> bool:
        return self.APP_ENV.strip().lower() in ("prod", "production")

    @model_validator(mode="after")
    def _resolve_env_defaults(self) -> "Settings":
        if self.ENABLE_LLM_LOG is None:
            self.ENABLE_LLM_LOG = not self.is_prod
        return self

    def validate_security(self) -> None:
        """啟動時呼叫。prod 遇到不安全設定直接拒絕啟動；dev 僅警告。"""
        problems: list[str] = []
        if self.API_SECRET == INSECURE_DEFAULT_API_SECRET:
            problems.append("API_SECRET 仍為原始碼中的公開預設值，任何人都能偽造 JWT")
        elif len(self.API_SECRET) < MIN_API_SECRET_LENGTH:
            problems.append(f"API_SECRET 長度不足 {MIN_API_SECRET_LENGTH} 字元")
        if self.ADMIN_PASSWORD and self.ADMIN_PASSWORD in (self.API_SECRET, self.MAIN_ACCOUNT_PASSWORD):
            problems.append("ADMIN_PASSWORD 不可與 API_SECRET 或 IG 主帳號密碼相同")
        if not self.google_client_ids_list:
            problems.append("未設定任何 GOOGLE_CLIENT_ID_*，Google 登入將一律被拒絕")
        if self.is_prod and self.ENABLE_LLM_LOG:
            problems.append("prod 環境已開啟 ENABLE_LLM_LOG，私訊與 prompt 明文會寫入 logs/llm.log")

        if not problems:
            return
        if self.is_prod:
            raise RuntimeError("APP_ENV=prod 安全檢查未通過:\n- " + "\n- ".join(problems))
        for msg in problems:
            _logger.warning(f"[dev 安全提醒] {msg}")

    @property
    def google_client_ids_list(self) -> list[str]:
        """彙整所有設定之 Google Client ID 供 Token 驗證比對。"""
        ids = [self.GOOGLE_CLIENT_ID_WEB, self.GOOGLE_CLIENT_ID_ANDROID, self.GOOGLE_CLIENT_ID_IOS]
        return [client_id.strip() for client_id in ids if client_id and client_id.strip()]

    @property
    def cors_origins_list(self) -> list[str]:
        return [origin.strip() for origin in self.CORS_ORIGINS.split(",") if origin.strip()]


settings = Settings()
