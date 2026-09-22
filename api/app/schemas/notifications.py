"""Notification schemas."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel

from app.models.tenancy import NotificationType


class NotificationResponse(BaseModel):
    id: uuid.UUID
    type: NotificationType
    title: str
    body: str
    link: str
    read: bool
    created_at: datetime


class NotificationPage(BaseModel):
    items: list[NotificationResponse]
    total: int
    unread_count: int
    limit: int
    offset: int
