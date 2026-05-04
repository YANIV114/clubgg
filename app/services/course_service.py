import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.course import Course, Lesson, LessonCompletion, Module, UserProgress
from app.schemas.course import CourseListItem, CourseOut, LessonOut, ModuleOut, ProgressOut


async def list_courses(
    session: AsyncSession,
    user_id: uuid.UUID | None = None,
) -> list[CourseListItem]:
    stmt = select(Course).where(Course.is_published.is_(True)).order_by(Course.created_at)
    result = await session.execute(stmt)
    courses = result.scalars().all()

    enrolled_course_ids: set[uuid.UUID] = set()
    progress_map: dict[uuid.UUID, float] = {}

    if user_id is not None:
        up_stmt = select(UserProgress).where(UserProgress.user_id == user_id)
        up_result = await session.execute(up_stmt)
        user_progresses = up_result.scalars().all()
        enrolled_course_ids = {up.course_id for up in user_progresses}

        if enrolled_course_ids:
            for up in user_progresses:
                pct = await _compute_progress_pct(session, user_id, up.course_id)
                progress_map[up.course_id] = pct

    items = []
    for course in courses:
        lesson_count = sum(len(mod.lessons) for mod in course.modules)
        enrolled = course.id in enrolled_course_ids
        progress_pct = progress_map.get(course.id, 0.0) if enrolled else 0.0
        items.append(
            CourseListItem(
                id=course.id,
                slug=course.slug,
                title=course.title,
                level=course.level,
                estimated_minutes=course.estimated_minutes,
                enrolled=enrolled,
                progress_pct=progress_pct,
                lesson_count=lesson_count,
            )
        )
    return items


async def get_course(
    session: AsyncSession,
    slug: str,
    user_id: uuid.UUID | None = None,
) -> CourseOut | None:
    stmt = select(Course).where(Course.slug == slug, Course.is_published.is_(True))
    result = await session.execute(stmt)
    course = result.scalar_one_or_none()
    if course is None:
        return None

    enrolled = False
    progress_pct = 0.0
    completed_lesson_ids: set[uuid.UUID] = set()

    if user_id is not None:
        up_stmt = select(UserProgress).where(
            UserProgress.user_id == user_id,
            UserProgress.course_id == course.id,
        )
        up_result = await session.execute(up_stmt)
        up = up_result.scalar_one_or_none()
        if up is not None:
            enrolled = True
            progress_pct = await _compute_progress_pct(session, user_id, course.id)

        lc_stmt = (
            select(LessonCompletion.lesson_id)
            .join(Lesson, Lesson.id == LessonCompletion.lesson_id)
            .join(Module, Module.id == Lesson.module_id)
            .where(
                LessonCompletion.user_id == user_id,
                Module.course_id == course.id,
            )
        )
        lc_result = await session.execute(lc_stmt)
        completed_lesson_ids = {row[0] for row in lc_result.all()}

    modules_out = []
    for mod in course.modules:
        lessons_out = []
        for lesson in mod.lessons:
            lessons_out.append(
                LessonOut(
                    id=lesson.id,
                    slug=lesson.slug,
                    title=lesson.title,
                    sort_order=lesson.sort_order,
                    is_completed=lesson.id in completed_lesson_ids,
                )
            )
        modules_out.append(
            ModuleOut(
                id=mod.id,
                title=mod.title,
                sort_order=mod.sort_order,
                lessons=lessons_out,
            )
        )

    return CourseOut(
        id=course.id,
        slug=course.slug,
        title=course.title,
        level=course.level,
        estimated_minutes=course.estimated_minutes,
        modules=modules_out,
        enrolled=enrolled,
        progress_pct=progress_pct,
    )


async def enroll_user(
    session: AsyncSession,
    user_id: uuid.UUID,
    course_slug: str,
) -> UserProgress:
    course_stmt = select(Course).where(Course.slug == course_slug)
    course_result = await session.execute(course_stmt)
    course = course_result.scalar_one_or_none()
    if course is None:
        raise ValueError(f"Course '{course_slug}' not found")

    existing_stmt = select(UserProgress).where(
        UserProgress.user_id == user_id,
        UserProgress.course_id == course.id,
    )
    existing_result = await session.execute(existing_stmt)
    existing = existing_result.scalar_one_or_none()
    if existing is not None:
        return existing

    now = datetime.now(UTC)
    progress = UserProgress(
        user_id=user_id,
        course_id=course.id,
        enrolled_at=now,
        completed_at=None,
    )
    session.add(progress)
    await session.flush()
    return progress


async def complete_lesson(
    session: AsyncSession,
    user_id: uuid.UUID,
    lesson_id: uuid.UUID,
) -> LessonCompletion:
    existing_stmt = select(LessonCompletion).where(
        LessonCompletion.user_id == user_id,
        LessonCompletion.lesson_id == lesson_id,
    )
    existing_result = await session.execute(existing_stmt)
    existing = existing_result.scalar_one_or_none()
    if existing is not None:
        return existing

    now = datetime.now(UTC)
    completion = LessonCompletion(
        user_id=user_id,
        lesson_id=lesson_id,
        completed_at=now,
    )
    session.add(completion)
    await session.flush()

    # Check if all lessons in the course are now complete; if so mark UserProgress.completed_at
    lesson_stmt = (
        select(Lesson).join(Module, Module.id == Lesson.module_id).where(Lesson.id == lesson_id)
    )
    lesson_result = await session.execute(lesson_stmt)
    lesson = lesson_result.scalar_one_or_none()
    if lesson is not None:
        module_stmt = select(Module).where(Module.id == lesson.module_id)
        module_result = await session.execute(module_stmt)
        module = module_result.scalar_one_or_none()
        if module is not None:
            course_id = module.course_id
            up_stmt = select(UserProgress).where(
                UserProgress.user_id == user_id,
                UserProgress.course_id == course_id,
            )
            up_result = await session.execute(up_stmt)
            up = up_result.scalar_one_or_none()
            if up is not None and up.completed_at is None:
                # Count total lessons in course
                total_stmt = (
                    select(func.count(Lesson.id))
                    .join(Module, Module.id == Lesson.module_id)
                    .where(Module.course_id == course_id)
                )
                total_result = await session.execute(total_stmt)
                total_lessons = total_result.scalar() or 0

                # Count completed lessons
                completed_stmt = (
                    select(func.count(LessonCompletion.id))
                    .join(Lesson, Lesson.id == LessonCompletion.lesson_id)
                    .join(Module, Module.id == Lesson.module_id)
                    .where(
                        LessonCompletion.user_id == user_id,
                        Module.course_id == course_id,
                    )
                )
                completed_result = await session.execute(completed_stmt)
                completed_lessons = completed_result.scalar() or 0

                if total_lessons > 0 and completed_lessons >= total_lessons:
                    up.completed_at = now
                    await session.flush()

    return completion


async def get_user_progress(
    session: AsyncSession,
    user_id: uuid.UUID,
) -> list[ProgressOut]:
    up_stmt = select(UserProgress).where(UserProgress.user_id == user_id)
    up_result = await session.execute(up_stmt)
    user_progresses = up_result.scalars().all()

    results = []
    for up in user_progresses:
        course_stmt = select(Course).where(Course.id == up.course_id)
        course_result = await session.execute(course_stmt)
        course = course_result.scalar_one_or_none()
        if course is None:
            continue

        total_stmt = (
            select(func.count(Lesson.id))
            .join(Module, Module.id == Lesson.module_id)
            .where(Module.course_id == course.id)
        )
        total_result = await session.execute(total_stmt)
        lessons_total = total_result.scalar() or 0

        completed_stmt = (
            select(func.count(LessonCompletion.id))
            .join(Lesson, Lesson.id == LessonCompletion.lesson_id)
            .join(Module, Module.id == Lesson.module_id)
            .where(
                LessonCompletion.user_id == user_id,
                Module.course_id == course.id,
            )
        )
        completed_result = await session.execute(completed_stmt)
        lessons_completed = completed_result.scalar() or 0

        progress_pct = (lessons_completed / lessons_total * 100.0) if lessons_total > 0 else 0.0

        results.append(
            ProgressOut(
                course_slug=course.slug,
                course_title=course.title,
                enrolled_at=up.enrolled_at,
                completed_at=up.completed_at,
                lessons_completed=lessons_completed,
                lessons_total=lessons_total,
                progress_pct=progress_pct,
            )
        )

    return results


async def _compute_progress_pct(
    session: AsyncSession,
    user_id: uuid.UUID,
    course_id: uuid.UUID,
) -> float:
    total_stmt = (
        select(func.count(Lesson.id))
        .join(Module, Module.id == Lesson.module_id)
        .where(Module.course_id == course_id)
    )
    total_result = await session.execute(total_stmt)
    lessons_total = total_result.scalar() or 0
    if lessons_total == 0:
        return 0.0

    completed_stmt = (
        select(func.count(LessonCompletion.id))
        .join(Lesson, Lesson.id == LessonCompletion.lesson_id)
        .join(Module, Module.id == Lesson.module_id)
        .where(
            LessonCompletion.user_id == user_id,
            Module.course_id == course_id,
        )
    )
    completed_result = await session.execute(completed_stmt)
    lessons_completed = completed_result.scalar() or 0

    return lessons_completed / lessons_total * 100.0
