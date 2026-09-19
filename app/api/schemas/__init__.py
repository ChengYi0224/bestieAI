"""API schemas package."""
from app.api.schemas.auth import TokenRequest, TokenResponse
from app.api.schemas.common import ErrorResponse, PaginationParams, StatusResponse
from app.api.schemas.contact import ContactListResponse, ContactResponse, ContactUpdateRequest
from app.api.schemas.message import (
    EventListResponse,
    EventResponse,
    MessageListResponse,
    MessageResponse,
)

__all__ = [
    "TokenRequest",
    "TokenResponse",
    "ErrorResponse",
    "PaginationParams",
    "StatusResponse",
    "ContactResponse",
    "ContactListResponse",
    "ContactUpdateRequest",
    "MessageResponse",
    "MessageListResponse",
    "EventResponse",
    "EventListResponse",
]
