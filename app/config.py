from pathlib import Path
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    MAIN_ACCOUNT_USERNAME: str = ""
    MAIN_ACCOUNT_PASSWORD: str = ""
    BOT_ACCOUNT_USERNAME: str = ""
    BOT_ACCOUNT_PASSWORD: str = ""
    SESSION_ENCRYPTION_KEY: str = ""
    GEMINI_API_KEY: str = ""

    DB_PATH: Path = Field(default=Path("./data/app.db"))
    CHROMA_PATH: Path = Field(default=Path("./data/chroma"))
    SESSION_DIR: Path = Field(default=Path("./data/sessions"))
    LOG_DIR: Path = Field(default=Path("./logs"))
    LLM_LOG_PATH: Path = Field(default=Path("./logs/llm.log"))
    POLL_INTERVAL_SECONDS: int = Field(default=15)

    # 模型設定（可透過 .env 覆寫）
    GEMINI_EMBEDDING_MODEL: str = Field(default="gemini-embedding-2")
    GEMINI_CANDIDATE_MODELS: str = Field(
        default="gemini-3.8-flash,gemini-3.7-flash,gemini-3.6-flash,gemini-3.5-flash-lite"
    )
    CHAT_HISTORY_TURNS: int = Field(default=10)

    @property
    def candidate_models_list(self) -> list[str]:
        return [m.strip() for m in self.GEMINI_CANDIDATE_MODELS.split(",") if m.strip()]


settings = Settings()
