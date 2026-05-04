from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel


class AdminUserOut(BaseModel):
    id: uuid.UUID
    email: str
    username: str | None
    role: str
    is_active: bool
    plan_slug: str
    created_at: datetime


class AdminSetPlanRequest(BaseModel):
    plan_slug: str


class AdminSetRoleRequest(BaseModel):
    role: str


class AdminCourseIn(BaseModel):
    slug: str
    title: str
    description: str = ""
    level: str = "beginner"
    estimated_minutes: int = 30
    is_published: bool = True


class AdminCourseUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    level: str | None = None
    estimated_minutes: int | None = None
    is_published: bool | None = None


class AdminCourseOut(BaseModel):
    id: uuid.UUID
    slug: str
    title: str
    description: str
    level: str
    estimated_minutes: int
    is_published: bool
    created_at: datetime


class AdminLessonIn(BaseModel):
    module_id: uuid.UUID
    slug: str
    title: str
    content: str = ""
    video_url: str | None = None
    sort_order: int = 1


class AdminLessonUpdate(BaseModel):
    title: str | None = None
    content: str | None = None
    video_url: str | None = None
    sort_order: int | None = None


class AdminLessonOut(BaseModel):
    id: uuid.UUID
    module_id: uuid.UUID
    slug: str
    title: str
    sort_order: int


class AdminOverviewOut(BaseModel):
    total_users: int
    active_users: int
    paying_users: int
    total_hands: int
    plan_distribution: dict[str, int]
