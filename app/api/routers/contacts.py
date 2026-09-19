from typing import Optional, Dict, Any
from fastapi import APIRouter, Depends, HTTPException
from fastapi import status as http_status
from app.api.dependencies import (
    get_contact_service,
    get_current_user,
    get_message_service,
)
from app.api.schemas.action import (
    ExtractContactResponse,
    TrackContactRequest,
    TrackContactResponse,
)
from app.api.schemas.common import ErrorResponse
from app.api.schemas.contact import ContactResponse, ContactUpdateRequest
from app.api.schemas.message import EventResponse
from app.services.contact_api_service import ContactApiService
from app.services.message_api_service import MessageApiService

router = APIRouter(prefix="/contacts", tags=["Contacts"])


@router.get(
    "",
    response_model=list[ContactResponse],
    summary="取得聯絡人清單",
)
async def list_contacts(
    status: Optional[str] = None,
    current_user: Dict[str, Any] = Depends(get_current_user),
    contact_service: ContactApiService = Depends(get_contact_service),
) -> list[ContactResponse]:
    """取得聯絡人清單，支援狀態篩選（如 tracked/untracked）與使用者資料隔離。"""
    rows = contact_service.list_contacts(status=status, user_id=current_user["id"])
    return [ContactResponse.model_validate(dict(row)) for row in rows]


@router.get(
    "/{contact_id}",
    response_model=ContactResponse,
    responses={404: {"model": ErrorResponse, "description": "聯絡人不存在"}},
    summary="取得單一聯絡人詳情",
)
async def get_contact(
    contact_id: int,
    current_user: Dict[str, Any] = Depends(get_current_user),
    contact_service: ContactApiService = Depends(get_contact_service),
) -> ContactResponse:
    """依 ID 取得單一聯絡人詳細資訊。"""
    row = contact_service.get_contact(contact_id, user_id=current_user["id"])
    if not row:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail=f"Contact {contact_id} not found",
        )
    return ContactResponse.model_validate(dict(row))


@router.patch(
    "/{contact_id}",
    response_model=ContactResponse,
    responses={404: {"model": ErrorResponse, "description": "聯絡人不存在"}},
    summary="更新聯絡人資訊",
)
async def update_contact(
    contact_id: int,
    payload: ContactUpdateRequest,
    current_user: Dict[str, Any] = Depends(get_current_user),
    contact_service: ContactApiService = Depends(get_contact_service),
) -> ContactResponse:
    """更新指定聯絡人之暱稱或關係備註。"""
    update_nickname = "nickname" in payload.model_fields_set
    update_note = "relationship_note" in payload.model_fields_set

    updated = contact_service.update_contact(
        contact_id=contact_id,
        nickname=payload.nickname,
        relationship_note=payload.relationship_note,
        update_nickname=update_nickname,
        update_note=update_note,
        user_id=current_user["id"],
    )
    if not updated:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail=f"Contact {contact_id} not found",
        )
    return ContactResponse.model_validate(dict(updated))


@router.get(
    "/{contact_id}/events",
    response_model=list[EventResponse],
    responses={404: {"model": ErrorResponse, "description": "聯絡人不存在"}},
    summary="取得聯絡人記憶事件清單",
)
async def get_contact_events(
    contact_id: int,
    status: Optional[str] = None,
    current_user: Dict[str, Any] = Depends(get_current_user),
    message_service: MessageApiService = Depends(get_message_service),
) -> list[EventResponse]:
    """取得指定聯絡人之記憶事件紀錄。"""
    events = message_service.get_contact_events(contact_id, status=status, user_id=current_user["id"])
    if events is None:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail=f"Contact {contact_id} not found",
        )
    return [EventResponse.model_validate(dict(e)) for e in events]


@router.post(
    "/track",
    response_model=TrackContactResponse,
    summary="追蹤新聯絡人並匯入對話",
)
async def track_contact(
    payload: TrackContactRequest,
    current_user: Dict[str, Any] = Depends(get_current_user),
    contact_service: ContactApiService = Depends(get_contact_service),
) -> TrackContactResponse:
    """建立或追蹤指定 Instagram 帳號並觸發歷史訊息匯入。"""
    res = contact_service.track_contact(
        user_id=current_user["id"],
        ig_account_id=payload.ig_account_id,
        limit=payload.limit or 1000,
    )
    return TrackContactResponse.model_validate(res)


@router.post(
    "/{contact_id}/extract",
    response_model=ExtractContactResponse,
    responses={404: {"model": ErrorResponse, "description": "聯絡人不存在"}},
    summary="手動觸發聯絡人事件萃取與摘要更新",
)
async def extract_contact(
    contact_id: int,
    current_user: Dict[str, Any] = Depends(get_current_user),
    contact_service: ContactApiService = Depends(get_contact_service),
) -> ExtractContactResponse:
    """手動觸發對指定聯絡人的記憶事件萃取與關係摘要卡刷新。"""
    res = contact_service.extract_contact_events(
        user_id=current_user["id"],
        contact_id=contact_id,
    )
    if not res:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail=f"Contact {contact_id} not found",
        )
    return ExtractContactResponse.model_validate(res)
