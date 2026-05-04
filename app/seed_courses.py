"""
Seed script for course data.

Run with: uv run python -m app.seed_courses

Idempotent: upserts courses, modules, and lessons by slug.
"""

import asyncio
import re
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings
from app.models.course import Course, Lesson, Module


@dataclass
class LessonSeed:
    title: str


@dataclass
class ModuleSeed:
    title: str
    lessons: list[LessonSeed] = field(default_factory=list)


@dataclass
class CourseSeed:
    slug: str
    title: str
    level: str
    estimated_minutes: int
    description: str = ""
    modules: list[ModuleSeed] = field(default_factory=list)


def _slugify(title: str) -> str:
    """Convert a title to a URL-friendly slug."""
    title = title.lower()
    title = re.sub(r"[^\w\s-]", "", title)
    title = re.sub(r"[\s_]+", "-", title)
    title = title.strip("-")
    return title


COURSES: list[CourseSeed] = [
    CourseSeed(
        slug="tournament-fundamentals",
        title="Tournament Poker Fundamentals",
        level="beginner",
        estimated_minutes=130,
        description="Master the essential concepts that separate tournament poker from cash games — chip EV, M-ratio, stack dynamics, and payout pressure.",
        modules=[
            ModuleSeed(
                title="Tournament vs Cash Game Mindset",
                lessons=[
                    LessonSeed(title="Why Tournament Poker Is Different"),
                    LessonSeed(title="Position: The Most Important Advantage"),
                    LessonSeed(title="Starting Hands Are Context-Based"),
                ],
            ),
            ModuleSeed(
                title="Preflop Decisions",
                lessons=[
                    LessonSeed(title="Preflop Decisions: Open, Fold, or Shove"),
                    LessonSeed(title="Short Stack Play: Under 15bb"),
                ],
            ),
            ModuleSeed(
                title="Tournament Mindset",
                lessons=[
                    LessonSeed(title="Biggest Beginner Mistakes"),
                    LessonSeed(title="How to Think in a Hand"),
                    LessonSeed(title="Final Quiz and Practice Setup"),
                ],
            ),
        ],
    ),
    CourseSeed(
        slug="stack-sizes-tournament-strategy",
        title="Stack Sizes & Tournament Strategy",
        level="intermediate",
        estimated_minutes=90,
        modules=[
            ModuleSeed(
                title="Short Stack Play",
                lessons=[
                    LessonSeed(title="Push/Fold Theory"),
                    LessonSeed(title="15BB Ranges"),
                    LessonSeed(title="10BB Ranges"),
                    LessonSeed(title="Under 10BB"),
                ],
            ),
            ModuleSeed(
                title="Medium Stack Play",
                lessons=[
                    LessonSeed(title="25-40BB Strategy"),
                    LessonSeed(title="3-bet Shove Spots"),
                    LessonSeed(title="Calling 3-bets at 30BB"),
                ],
            ),
            ModuleSeed(
                title="Deep Stack Play",
                lessons=[
                    LessonSeed(title="60BB+ Strategy"),
                    LessonSeed(title="Post-flop Planning Deep"),
                    LessonSeed(title="Squeeze Plays Deep"),
                ],
            ),
        ],
    ),
    CourseSeed(
        slug="bubble-play-mastery",
        title="Bubble Play Mastery",
        level="intermediate",
        estimated_minutes=75,
        modules=[
            ModuleSeed(
                title="Bubble Fundamentals",
                lessons=[
                    LessonSeed(title="Identifying Bubble Dynamics"),
                    LessonSeed(title="ICM Pressure at the Bubble"),
                    LessonSeed(title="Stack Distribution Strategy"),
                ],
            ),
            ModuleSeed(
                title="Exploiting the Bubble",
                lessons=[
                    LessonSeed(title="Attacking Short Stacks"),
                    LessonSeed(title="Defending vs Aggression"),
                    LessonSeed(title="Chip Leader Bubble Strategy"),
                ],
            ),
        ],
    ),
    CourseSeed(
        slug="final-table-strategy",
        title="Final Table Strategy",
        level="advanced",
        estimated_minutes=100,
        modules=[
            ModuleSeed(
                title="Final Table Dynamics",
                lessons=[
                    LessonSeed(title="Pay Jump Analysis"),
                    LessonSeed(title="Stack Leverage at FT"),
                    LessonSeed(title="Short-handed Adjustments"),
                ],
            ),
            ModuleSeed(
                title="Heads Up Play",
                lessons=[
                    LessonSeed(title="HU Push/Fold"),
                    LessonSeed(title="HU Post-flop Basics"),
                    LessonSeed(title="HU Adaptation"),
                ],
            ),
        ],
    ),
]


async def seed(session: AsyncSession) -> None:
    for course_seed in COURSES:
        # Upsert course by slug
        stmt = select(Course).where(Course.slug == course_seed.slug)
        result = await session.execute(stmt)
        course = result.scalar_one_or_none()

        if course is None:
            course = Course(
                slug=course_seed.slug,
                title=course_seed.title,
                description=course_seed.description,
                level=course_seed.level,
                estimated_minutes=course_seed.estimated_minutes,
                is_published=True,
            )
            session.add(course)
            await session.flush()
            print(f"  Created course: {course.slug}")
        else:
            course.title = course_seed.title
            course.description = course_seed.description
            course.level = course_seed.level
            course.estimated_minutes = course_seed.estimated_minutes
            await session.flush()
            print(f"  Updated course: {course.slug}")

        for mod_idx, mod_seed in enumerate(course_seed.modules):
            mod_stmt = select(Module).where(
                Module.course_id == course.id,
                Module.title == mod_seed.title,
            )
            mod_result = await session.execute(mod_stmt)
            module = mod_result.scalar_one_or_none()

            if module is None:
                module = Module(
                    course_id=course.id,
                    title=mod_seed.title,
                    sort_order=mod_idx,
                )
                session.add(module)
                await session.flush()
                print(f"    Created module: {module.title}")
            else:
                module.sort_order = mod_idx
                await session.flush()
                print(f"    Updated module: {module.title}")

            for lesson_idx, lesson_seed in enumerate(mod_seed.lessons):
                lesson_slug = _slugify(lesson_seed.title)
                lesson_stmt = select(Lesson).where(
                    Lesson.module_id == module.id,
                    Lesson.slug == lesson_slug,
                )
                lesson_result = await session.execute(lesson_stmt)
                lesson = lesson_result.scalar_one_or_none()

                if lesson is None:
                    lesson = Lesson(
                        module_id=module.id,
                        slug=lesson_slug,
                        title=lesson_seed.title,
                        content="",
                        video_url=None,
                        sort_order=lesson_idx,
                    )
                    session.add(lesson)
                    await session.flush()
                    print(f"      Created lesson: {lesson.title}")
                else:
                    lesson.title = lesson_seed.title
                    lesson.sort_order = lesson_idx
                    await session.flush()
                    print(f"      Updated lesson: {lesson.title}")

    await session.commit()
    print("Seed complete.")


async def main() -> None:
    engine = create_async_engine(settings.DATABASE_URL, echo=False)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        await seed(session)
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
