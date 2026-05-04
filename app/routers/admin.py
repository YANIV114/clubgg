from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.deps import require_user
from app.models.user import User
from app.schemas.admin import (
    AdminCourseIn,
    AdminCourseOut,
    AdminCourseUpdate,
    AdminLessonIn,
    AdminLessonOut,
    AdminLessonUpdate,
    AdminOverviewOut,
    AdminSetPlanRequest,
    AdminSetRoleRequest,
    AdminUserOut,
)
from app.services import admin_service, billing_service

router = APIRouter()

_VALID_ROLES = {"player", "admin"}


async def _require_admin(
    current_user: User = Depends(require_user),
) -> User:
    if current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required.",
        )
    return current_user


# ── Overview ──────────────────────────────────────────────────────────────────


@router.get("/admin/overview", response_model=AdminOverviewOut)
async def admin_overview(
    session: AsyncSession = Depends(get_db),
    _admin: User = Depends(_require_admin),
) -> AdminOverviewOut:
    return await admin_service.get_overview(session)


# ── Users ─────────────────────────────────────────────────────────────────────


@router.get("/admin/users", response_model=list[AdminUserOut])
async def admin_list_users(
    session: AsyncSession = Depends(get_db),
    _admin: User = Depends(_require_admin),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
) -> list[AdminUserOut]:
    pairs = await admin_service.list_users(session, skip=skip, limit=limit)
    return [
        AdminUserOut(
            id=u.id,
            email=u.email,
            username=u.username,
            role=u.role,
            is_active=u.is_active,
            plan_slug=slug,
            created_at=u.created_at,
        )
        for u, slug in pairs
    ]


@router.get("/admin/users/{user_id}", response_model=AdminUserOut)
async def admin_get_user(
    user_id: uuid.UUID,
    session: AsyncSession = Depends(get_db),
    _admin: User = Depends(_require_admin),
) -> AdminUserOut:
    user = await admin_service.get_user(session, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    slug = await billing_service.get_user_plan_slug(session, user_id)
    return AdminUserOut(
        id=user.id,
        email=user.email,
        username=user.username,
        role=user.role,
        is_active=user.is_active,
        plan_slug=slug,
        created_at=user.created_at,
    )


@router.post("/admin/users/{user_id}/set-plan", response_model=AdminUserOut)
async def admin_set_user_plan(
    user_id: uuid.UUID,
    body: AdminSetPlanRequest,
    session: AsyncSession = Depends(get_db),
    _admin: User = Depends(_require_admin),
) -> AdminUserOut:
    user = await admin_service.get_user(session, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    try:
        await billing_service.set_user_plan(session, user_id, body.plan_slug)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    await session.commit()
    slug = await billing_service.get_user_plan_slug(session, user_id)
    return AdminUserOut(
        id=user.id,
        email=user.email,
        username=user.username,
        role=user.role,
        is_active=user.is_active,
        plan_slug=slug,
        created_at=user.created_at,
    )


@router.post("/admin/users/{user_id}/set-role", response_model=AdminUserOut)
async def admin_set_user_role(
    user_id: uuid.UUID,
    body: AdminSetRoleRequest,
    session: AsyncSession = Depends(get_db),
    _admin: User = Depends(_require_admin),
) -> AdminUserOut:
    if body.role not in _VALID_ROLES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Role must be one of: {sorted(_VALID_ROLES)}",
        )
    try:
        user = await admin_service.set_user_role(session, user_id, body.role)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    await session.commit()
    slug = await billing_service.get_user_plan_slug(session, user_id)
    return AdminUserOut(
        id=user.id,
        email=user.email,
        username=user.username,
        role=user.role,
        is_active=user.is_active,
        plan_slug=slug,
        created_at=user.created_at,
    )


# ── Courses ───────────────────────────────────────────────────────────────────


@router.get("/admin/courses", response_model=list[AdminCourseOut])
async def admin_list_courses(
    session: AsyncSession = Depends(get_db),
    _admin: User = Depends(_require_admin),
) -> list[AdminCourseOut]:
    courses = await admin_service.list_courses(session)
    return [
        AdminCourseOut(
            id=c.id,
            slug=c.slug,
            title=c.title,
            description=c.description,
            level=c.level,
            estimated_minutes=c.estimated_minutes,
            is_published=c.is_published,
            created_at=c.created_at,
        )
        for c in courses
    ]


@router.post("/admin/courses", response_model=AdminCourseOut, status_code=status.HTTP_201_CREATED)
async def admin_create_course(
    body: AdminCourseIn,
    session: AsyncSession = Depends(get_db),
    _admin: User = Depends(_require_admin),
) -> AdminCourseOut:
    try:
        course = await admin_service.create_course(
            session,
            slug=body.slug,
            title=body.title,
            description=body.description,
            level=body.level,
            estimated_minutes=body.estimated_minutes,
            is_published=body.is_published,
        )
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    await session.commit()
    return AdminCourseOut(
        id=course.id,
        slug=course.slug,
        title=course.title,
        description=course.description,
        level=course.level,
        estimated_minutes=course.estimated_minutes,
        is_published=course.is_published,
        created_at=course.created_at,
    )


@router.put("/admin/courses/{course_id}", response_model=AdminCourseOut)
async def admin_update_course(
    course_id: uuid.UUID,
    body: AdminCourseUpdate,
    session: AsyncSession = Depends(get_db),
    _admin: User = Depends(_require_admin),
) -> AdminCourseOut:
    try:
        course = await admin_service.update_course(
            session,
            course_id,
            **{k: v for k, v in body.model_dump().items() if v is not None},
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    await session.commit()
    return AdminCourseOut(
        id=course.id,
        slug=course.slug,
        title=course.title,
        description=course.description,
        level=course.level,
        estimated_minutes=course.estimated_minutes,
        is_published=course.is_published,
        created_at=course.created_at,
    )


@router.delete("/admin/courses/{course_id}", status_code=status.HTTP_204_NO_CONTENT)
async def admin_delete_course(
    course_id: uuid.UUID,
    session: AsyncSession = Depends(get_db),
    _admin: User = Depends(_require_admin),
) -> None:
    try:
        await admin_service.delete_course(session, course_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    await session.commit()


@router.post("/admin/courses/{course_id}/publish", response_model=AdminCourseOut)
async def admin_publish_course(
    course_id: uuid.UUID,
    publish: bool = Query(True),
    session: AsyncSession = Depends(get_db),
    _admin: User = Depends(_require_admin),
) -> AdminCourseOut:
    try:
        course = await admin_service.publish_course(session, course_id, publish)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    await session.commit()
    return AdminCourseOut(
        id=course.id,
        slug=course.slug,
        title=course.title,
        description=course.description,
        level=course.level,
        estimated_minutes=course.estimated_minutes,
        is_published=course.is_published,
        created_at=course.created_at,
    )


# ── Lessons ───────────────────────────────────────────────────────────────────


@router.post("/admin/lessons", response_model=AdminLessonOut, status_code=status.HTTP_201_CREATED)
async def admin_create_lesson(
    body: AdminLessonIn,
    session: AsyncSession = Depends(get_db),
    _admin: User = Depends(_require_admin),
) -> AdminLessonOut:
    try:
        lesson = await admin_service.create_lesson(
            session,
            module_id=body.module_id,
            slug=body.slug,
            title=body.title,
            content=body.content,
            video_url=body.video_url,
            sort_order=body.sort_order,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    await session.commit()
    return AdminLessonOut(
        id=lesson.id,
        module_id=lesson.module_id,
        slug=lesson.slug,
        title=lesson.title,
        sort_order=lesson.sort_order,
    )


@router.put("/admin/lessons/{lesson_id}", response_model=AdminLessonOut)
async def admin_update_lesson(
    lesson_id: uuid.UUID,
    body: AdminLessonUpdate,
    session: AsyncSession = Depends(get_db),
    _admin: User = Depends(_require_admin),
) -> AdminLessonOut:
    try:
        lesson = await admin_service.update_lesson(
            session,
            lesson_id,
            **{k: v for k, v in body.model_dump().items() if v is not None},
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    await session.commit()
    return AdminLessonOut(
        id=lesson.id,
        module_id=lesson.module_id,
        slug=lesson.slug,
        title=lesson.title,
        sort_order=lesson.sort_order,
    )


@router.delete("/admin/lessons/{lesson_id}", status_code=status.HTTP_204_NO_CONTENT)
async def admin_delete_lesson(
    lesson_id: uuid.UUID,
    session: AsyncSession = Depends(get_db),
    _admin: User = Depends(_require_admin),
) -> None:
    try:
        await admin_service.delete_lesson(session, lesson_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    await session.commit()
