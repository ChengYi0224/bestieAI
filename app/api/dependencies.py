"""dependencies.py — FastAPI 依賴注入工廠函式與安全認證相依性。"""
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from app.services.auth_api_service import AuthApiService
from app.services.contact_api_service import ContactApiService
from app.services.message_api_service import MessageApiService
from app.services.status_api_service import StatusApiService
from app.storage.repositories.bot_state import BotStateRepository
from app.storage.repositories.contacts import ContactRepository
from app.storage.repositories.events import EventRepository
from app.storage.repositories.messages import MessageRepository

# HTTP Bearer 認證機制
bearer_scheme = HTTPBearer(auto_error=True)


# ==================== Repositories 工廠 ====================

def get_contact_repo() -> ContactRepository:
    return ContactRepository()


def get_message_repo() -> MessageRepository:
    return MessageRepository()


def get_event_repo() -> EventRepository:
    return EventRepository()


def get_bot_state_repo() -> BotStateRepository:
    return BotStateRepository()


# ==================== Services 工廠 ====================

def get_auth_service() -> AuthApiService:
    return AuthApiService()


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


# ==================== 認證相依性 ====================

def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    auth_service: AuthApiService = Depends(get_auth_service),
) -> str:
    """驗證 Bearer Token，成功回傳主體身分，失敗拋出 401 Unauthorized。"""
    token = credentials.credentials
    username = auth_service.verify_token(token)
    if not username:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return username
