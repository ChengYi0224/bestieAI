"""dependencies.py — FastAPI 依賴注入工廠函式與安全認證相依性。"""
from typing import Dict, Any
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from app.services.auth_api_service import AuthApiService
from app.services.contact_api_service import ContactApiService
from app.services.message_api_service import MessageApiService
from app.services.status_api_service import StatusApiService
from app.services.chat_api_service import ChatApiService
from app.storage.repositories.bot_state import BotStateRepository
from app.storage.repositories.contacts import ContactRepository
from app.storage.repositories.events import EventRepository
from app.storage.repositories.messages import MessageRepository
from app.storage.repositories.users import UserRepository

# HTTP Bearer 認證機制
bearer_scheme = HTTPBearer(auto_error=True)


# ==================== Repositories 工廠 ====================

def get_user_repo() -> UserRepository:
    return UserRepository()


def get_contact_repo() -> ContactRepository:
    return ContactRepository()


def get_message_repo() -> MessageRepository:
    return MessageRepository()


def get_event_repo() -> EventRepository:
    return EventRepository()


def get_bot_state_repo() -> BotStateRepository:
    return BotStateRepository()


# ==================== Services 工廠 ====================

def get_auth_service(
    user_repo: UserRepository = Depends(get_user_repo),
) -> AuthApiService:
    return AuthApiService(user_repo=user_repo)


def get_status_service(
    bot_state_repo: BotStateRepository = Depends(get_bot_state_repo),
    contact_repo: ContactRepository = Depends(get_contact_repo),
) -> StatusApiService:
    return StatusApiService(bot_state_repo=bot_state_repo, contact_repo=contact_repo)


def get_contact_service(
    contact_repo: ContactRepository = Depends(get_contact_repo),
) -> ContactApiService:
    return ContactApiService(contact_repo=contact_repo)


def get_message_service(
    message_repo: MessageRepository = Depends(get_message_repo),
    event_repo: EventRepository = Depends(get_event_repo),
    contact_repo: ContactRepository = Depends(get_contact_repo),
) -> MessageApiService:
    return MessageApiService(
        message_repo=message_repo,
        event_repo=event_repo,
        contact_repo=contact_repo,
    )


def get_chat_service(
    contact_repo: ContactRepository = Depends(get_contact_repo),
    bot_state_repo: BotStateRepository = Depends(get_bot_state_repo),
) -> ChatApiService:
    return ChatApiService(contact_repo=contact_repo, bot_state_repo=bot_state_repo)


# ==================== 認證相依性 ====================

def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    auth_service: AuthApiService = Depends(get_auth_service),
    user_repo: UserRepository = Depends(get_user_repo),
) -> Dict[str, Any]:
    """驗證 Bearer Token，成功回傳目前登入之使用者資料字典，失敗拋出 401 Unauthorized。"""
    token = credentials.credentials
    token_data = auth_service.verify_token(token)
    if not token_data:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user_id, _ = token_data
    user = user_repo.get_by_id(user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return dict(user)
