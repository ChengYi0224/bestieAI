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
    POLL_INTERVAL_SECONDS: int = Field(default=15)


settings = Settings()
