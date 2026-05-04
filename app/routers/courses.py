import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.dependencies import require_tester
from app.models.course import Lesson
from app.models.user import User
from app.schemas.course import CourseListItem, CourseOut, LessonOut, ProgressOut
from app.services import course_service
from app.services.auth_service import get_current_user
from app.services.billing_service import require_feature, user_has_feature

router = APIRouter()
_bearer = HTTPBearer(auto_error=False)
_require_progress_dashboard = require_feature("progress_dashboard")

# Maps course level → required feature flag. Levels not in this map are freely accessible.
_LEVEL_FEATURE: dict[str, str] = {
    "intermediate": "intermediate_courses",
    "advanced": "advanced_courses",
    "elite": "elite_courses",
}


async def _check_course_access(session: AsyncSession, user_id: uuid.UUID, level: str) -> None:
    required = _LEVEL_FEATURE.get(level)
    if required and not await user_has_feature(session, user_id, required):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"'{level}' courses require a higher subscription plan.",
        )


async def _optional_user_id(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
    session: AsyncSession = Depends(get_db),
) -> uuid.UUID | None:
    if creds is None:
        return None
    user = await get_current_user(session, creds.credentials)
    return user.id if user else None


async def _require_user_id(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
    session: AsyncSession = Depends(get_db),
) -> uuid.UUID:
    if creds is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    user = await get_current_user(session, creds.credentials)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token"
        )
    return user.id


@router.get("/courses", response_model=list[CourseListItem])
async def list_courses(
    user_id: uuid.UUID | None = Depends(_optional_user_id),
    session: AsyncSession = Depends(get_db),
) -> list[CourseListItem]:
    return await course_service.list_courses(session, user_id)


@router.get("/courses/{slug}", response_model=CourseOut)
async def get_course(
    slug: str,
    user_id: uuid.UUID | None = Depends(_optional_user_id),
    session: AsyncSession = Depends(get_db),
) -> CourseOut:
    course = await course_service.get_course(session, slug, user_id)
    if course is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Course not found",
            headers={"X-Error-Code": "COURSE_NOT_FOUND"},
        )
    return course


@router.get("/courses/{slug}/lessons/{lslug}", response_model=LessonOut)
async def get_lesson(
    slug: str,
    lslug: str,
    user_id: uuid.UUID | None = Depends(_optional_user_id),
    session: AsyncSession = Depends(get_db),
) -> LessonOut:
    from sqlalchemy import select

    from app.models.course import Course, LessonCompletion, Module

    course_stmt = select(Course).where(Course.slug == slug, Course.is_published.is_(True))
    course_result = await session.execute(course_stmt)
    course = course_result.scalar_one_or_none()
    if course is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Course not found",
            headers={"X-Error-Code": "COURSE_NOT_FOUND"},
        )

    lesson_stmt = (
        select(Lesson)
        .join(Module, Module.id == Lesson.module_id)
        .where(Module.course_id == course.id, Lesson.slug == lslug)
    )
    lesson_result = await session.execute(lesson_stmt)
    lesson = lesson_result.scalar_one_or_none()
    if lesson is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Lesson not found",
            headers={"X-Error-Code": "LESSON_NOT_FOUND"},
        )

    is_completed = False
    if user_id is not None:
        lc_stmt = select(LessonCompletion).where(
            LessonCompletion.user_id == user_id,
            LessonCompletion.lesson_id == lesson.id,
        )
        lc_result = await session.execute(lc_stmt)
        is_completed = lc_result.scalar_one_or_none() is not None

    return LessonOut(
        id=lesson.id,
        slug=lesson.slug,
        title=lesson.title,
        sort_order=lesson.sort_order,
        is_completed=is_completed,
    )


@router.post("/courses/{slug}/enroll", response_model=CourseOut, status_code=status.HTTP_200_OK)
async def enroll_in_course(
    slug: str,
    user_id: uuid.UUID = Depends(_require_user_id),
    session: AsyncSession = Depends(get_db),
) -> CourseOut:
    try:
        await course_service.enroll_user(session, user_id, slug)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    course = await course_service.get_course(session, slug, user_id)
    if course is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Course not found")
    return course


@router.post(
    "/lessons/{lesson_id}/complete", response_model=LessonOut, status_code=status.HTTP_200_OK
)
async def complete_lesson(
    lesson_id: uuid.UUID,
    user_id: uuid.UUID = Depends(_require_user_id),
    session: AsyncSession = Depends(get_db),
) -> LessonOut:
    from sqlalchemy import select

    lesson_stmt = select(Lesson).where(Lesson.id == lesson_id)
    lesson_result = await session.execute(lesson_stmt)
    lesson = lesson_result.scalar_one_or_none()
    if lesson is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Lesson not found",
            headers={"X-Error-Code": "LESSON_NOT_FOUND"},
        )

    completion = await course_service.complete_lesson(session, user_id, lesson_id)

    return LessonOut(
        id=lesson.id,
        slug=lesson.slug,
        title=lesson.title,
        sort_order=lesson.sort_order,
        is_completed=True,
    )


@router.get("/me/progress", response_model=list[ProgressOut])
async def get_my_progress(
    session: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_tester),
) -> list[ProgressOut]:
    return await course_service.get_user_progress(session, current_user.id)
