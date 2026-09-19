"""app.py — FastAPI 應用程式實例工廠、CORS 與路由註冊。"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api.routers import (
    auth_router,
    contacts_router,
    messages_router,
    status_router,
)
from app.core.config import settings


def create_app() -> FastAPI:
    """建構並配置 FastAPI 應用程式實例。"""
    application = FastAPI(
        title="bestieAI REST API",
        version="0.11.0",
        description="Sonara 產品專用 bestieAI 後端 REST API 介面。",
    )

    # 設定 CORS 中介軟體
    origins = settings.cors_origins_list
    if not origins:
        origins = ["*"]

    application.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Total-Count"],
    )

    # 掛載路由模組
    application.include_router(auth_router)
    application.include_router(status_router)
    application.include_router(contacts_router)
    application.include_router(messages_router)

    return application
