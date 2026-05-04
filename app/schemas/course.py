import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class LessonOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    slug: str
    title: str
    sort_order: int
    is_completed: bool = False


class ModuleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    sort_order: int
    lessons: list[LessonOut]


class CourseOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    slug: str
    title: str
    level: str
    estimated_minutes: int
    modules: list[ModuleOut]
    enrolled: bool = False
    progress_pct: float = 0.0


class CourseListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    slug: str
    title: str
    level: str
    estimated_minutes: int
    enrolled: bool = False
    progress_pct: float = 0.0
    lesson_count: int


class ProgressOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    course_slug: str
    course_title: str
    enrolled_at: datetime
    completed_at: datetime | None
    lessons_completed: int
    lessons_total: int
    progress_pct: float
