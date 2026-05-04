from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.billing import Subscription, SubscriptionPlan
from app.models.course import Course, Lesson, Module
from app.models.hand import Hand
from app.models.user import User
from app.schemas.admin import AdminOverviewOut
from app.services import billing_service

# ── Users ─────────────────────────────────────────────────────────────────────


async def list_users(
    session: AsyncSession, skip: int = 0, limit: int = 100
) -> list[tuple[User, str]]:
    """Return (user, plan_slug) pairs ordered by created_at desc."""
    rows = await session.execute(
        select(User).order_by(User.created_at.desc()).offset(skip).limit(limit)
    )
    users = list(rows.scalars().all())
    result = []
    for user in users:
        slug = await billing_service.get_user_plan_slug(session, user.id)
        result.append((user, slug))
    return result


async def get_user(session: AsyncSession, user_id: uuid.UUID) -> User | None:
    return await session.get(User, user_id)


async def set_user_role(session: AsyncSession, user_id: uuid.UUID, role: str) -> User:
    user = await session.get(User, user_id)
    if user is None:
        raise ValueError(f"User {user_id} not found")
    user.role = role
    await session.flush()
    return user


# ── Overview stats ────────────────────────────────────────────────────────────


async def get_overview(session: AsyncSession) -> AdminOverviewOut:
    total_users = await session.scalar(select(func.count()).select_from(User)) or 0
    active_users = (
        await session.scalar(select(func.count()).select_from(User).where(User.is_active.is_(True)))
        or 0
    )
    paying_users = (
        await session.scalar(
            select(func.count())
            .select_from(Subscription)
            .join(SubscriptionPlan, SubscriptionPlan.id == Subscription.plan_id)
            .where(
                Subscription.status == "active",
                SubscriptionPlan.price_cents > 0,
            )
        )
        or 0
    )
    total_hands = await session.scalar(select(func.count()).select_from(Hand)) or 0

    # Plan distribution: count active subscriptions grouped by plan slug
    plan_rows = await session.execute(
        select(SubscriptionPlan.slug, func.count(Subscription.id))
        .join(Subscription, Subscription.plan_id == SubscriptionPlan.id)
        .where(Subscription.status == "active")
        .group_by(SubscriptionPlan.slug)
    )
    plan_dist: dict[str, int] = dict(plan_rows.all())
    users_with_sub = sum(plan_dist.values())
    plan_dist["free"] = plan_dist.get("free", 0) + (total_users - users_with_sub)

    return AdminOverviewOut(
        total_users=total_users,
        active_users=active_users,
        paying_users=paying_users,
        total_hands=total_hands,
        plan_distribution=plan_dist,
    )


# ── Course CRUD ───────────────────────────────────────────────────────────────


async def list_courses(session: AsyncSession) -> list[Course]:
    result = await session.execute(select(Course).order_by(Course.created_at.desc()))
    return list(result.scalars().all())


async def create_course(
    session: AsyncSession,
    slug: str,
    title: str,
    description: str,
    level: str,
    estimated_minutes: int,
    is_published: bool,
) -> Course:
    course = Course(
        slug=slug,
        title=title,
        description=description,
        level=level,
        estimated_minutes=estimated_minutes,
        is_published=is_published,
    )
    session.add(course)
    await session.flush()
    # Create a default module so lessons can be added immediately
    module = Module(course_id=course.id, title="Main", sort_order=1)
    session.add(module)
    await session.flush()
    return course


async def update_course(session: AsyncSession, course_id: uuid.UUID, **fields: object) -> Course:
    course = await session.get(Course, course_id)
    if course is None:
        raise ValueError(f"Course {course_id} not found")
    for key, val in fields.items():
        if val is not None:
            setattr(course, key, val)
    await session.flush()
    return course


async def delete_course(session: AsyncSession, course_id: uuid.UUID) -> None:
    course = await session.get(Course, course_id)
    if course is None:
        raise ValueError(f"Course {course_id} not found")
    await session.delete(course)
    await session.flush()


async def publish_course(session: AsyncSession, course_id: uuid.UUID, publish: bool) -> Course:
    course = await session.get(Course, course_id)
    if course is None:
        raise ValueError(f"Course {course_id} not found")
    course.is_published = publish
    await session.flush()
    return course


# ── Lesson CRUD ───────────────────────────────────────────────────────────────


async def create_lesson(
    session: AsyncSession,
    module_id: uuid.UUID,
    slug: str,
    title: str,
    content: str,
    video_url: str | None,
    sort_order: int,
) -> Lesson:
    module = await session.get(Module, module_id)
    if module is None:
        raise ValueError(f"Module {module_id} not found")
    lesson = Lesson(
        module_id=module_id,
        slug=slug,
        title=title,
        content=content,
        video_url=video_url,
        sort_order=sort_order,
    )
    session.add(lesson)
    await session.flush()
    return lesson


async def update_lesson(session: AsyncSession, lesson_id: uuid.UUID, **fields: object) -> Lesson:
    lesson = await session.get(Lesson, lesson_id)
    if lesson is None:
        raise ValueError(f"Lesson {lesson_id} not found")
    for key, val in fields.items():
        if val is not None:
            setattr(lesson, key, val)
    await session.flush()
    return lesson


async def delete_lesson(session: AsyncSession, lesson_id: uuid.UUID) -> None:
    lesson = await session.get(Lesson, lesson_id)
    if lesson is None:
        raise ValueError(f"Lesson {lesson_id} not found")
    await session.delete(lesson)
    await session.flush()
