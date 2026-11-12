"""Архивные кадры не считаются в готовности проекта (живой прогон #86, 12.11).

``replace_all_frames`` при переразбивке сцены не удаляет старые кадры, а
архивирует их: номер ≥ 1 000 000 + ``attrs.archived``. Промты архивным кадрам
не нужны, но счётчики готовности их видели — и проект уезжал назад:

- ``_primary_image_prompt_counts``: 72 живых с промтами против 104 кадров
  (72 живых + 32 архивных) → ``img_prompts_incomplete`` → статус
  ``image_prompts_ready`` НЕ достигался;
- шаг img_pr падал «после apply-ops промты не заполнены» (починено в PR #196);
- ``recompute_status`` откатывал проект ``image_prompts_ready → items_ready``
  («статус опережал данные — откат») — то есть шаг успевал отработать и
  проект всё равно уезжал назад.

Живые кадры — единственные, чья готовность имеет значение.
"""

from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models import Base, Frame, Project, ProjectStatus
from app.services.db_v2 import ARCHIVE_NUMBER_FROM
from app.services.project_state import compute_actual_status


@pytest_asyncio.fixture
async def db_session(tmp_path):
    db_file = tmp_path / "test_state.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_file}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


def _live_frame(number: int) -> Frame:
    return Frame(
        project_id=1,
        number=number,
        voiceover_text=f"Кадр {number}",
        image_prompt=f"Промпт {number}",
        attrs={},
    )


def _archived_frame(number: int) -> Frame:
    """Кадр от прошлой разбивки: номер ≥ 1 000 000, attrs.archived."""
    return Frame(
        project_id=1,
        number=ARCHIVE_NUMBER_FROM + number,
        voiceover_text=f"Старый кадр {number}",
        image_prompt="",  # промта нет — и не нужно
        attrs={"archived": True},
    )


@pytest.mark.asyncio
async def test_archived_frames_do_not_block_image_prompts_ready(db_session) -> None:
    """Живые кадры с промтами → image_prompts_ready, даже если есть архивные."""
    project = Project(
        topic="Лаборатория",
        slug="lab",
        script_text="Закадровый текст",
        general_plan="План" * 100,
        status=ProjectStatus.image_prompts_ready,
        meta={},
    )
    db_session.add(project)
    await db_session.commit()
    await db_session.refresh(project)

    for i in range(3):
        db_session.add(_live_frame(i + 1))
    for i in range(2):
        db_session.add(_archived_frame(i))
    await db_session.commit()

    status = await compute_actual_status(db_session, project)
    assert status == ProjectStatus.image_prompts_ready


@pytest.mark.asyncio
async def test_archived_frames_not_counted_as_frames_at_all(db_session) -> None:
    """Только архивные кадры → это НЕ «кадры есть» (fr_total без них = 0)."""
    project = Project(
        topic="Лаборатория",
        slug="lab",
        script_text="Закадровый текст",
        general_plan="План" * 100,
        status=ProjectStatus.new,
        meta={},
    )
    db_session.add(project)
    await db_session.commit()
    await db_session.refresh(project)

    for i in range(2):
        db_session.add(_archived_frame(i))
    await db_session.commit()

    status = await compute_actual_status(db_session, project)
    # Архивные кадры — не данные проекта: без живых кадров шаг разбивки
    # не выполнен, и статус не должен прыгать выше скрипта (frames_ready и
    # дальше — только за реальные кадры).
    assert status == ProjectStatus.script_ready
