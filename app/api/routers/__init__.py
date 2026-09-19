from app.api.routers.auth import router as auth_router
from app.api.routers.contacts import router as contacts_router
from app.api.routers.messages import router as messages_router
from app.api.routers.status import router as status_router
from app.api.routers.chat import router as chat_router

__all__ = [
    "auth_router",
    "contacts_router",
    "messages_router",
    "status_router",
    "chat_router",
]
