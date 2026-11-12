"""img_pr: архивные кадры не входят в шаг (живой прогон #86, 12.11).

``replace_all_frames`` при переразбивке сцены не удаляет старые кадры, а
архивирует их: номер ≥ 1 000 000 + ``attrs.archived``. Промты архивным
кадрам не нужны — их не просит модель и не ждёт шаг картинок.

Шаг img_pr архивные кадры НЕ отфильтровывал: модель заполнила 72 живых
кадра, а проверка готовности требовала ещё 32 архивных → шаг вечно падал
«после apply-ops промты не заполнены» (3 попытки → пауза на 30 мин).

Все прочие шаги (картинки, видео, разбивка, enrich) архивные кадры
отсекают через ``db_v2.frame_is_archived`` — img_pr был единственным,
кто этого не делал.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models import Base, Frame, Project, ProjectStatus
from app.services.db_v2 import ARCHIVE_NUMBER_FROM

REAL = (
    "Фон: подземная камера муравьиного гнезда, стенки с влажными слоями почвы. "
    "Действие: рабочий муравей несёт личинку."
) + " STYLE: dark watercolor wash, distressed printmaking, halftone dots." * 4


async def test_reload_frames_skips_archived() -> None:
    """_reload_frames отдаёт живые кадры; архивные — нет."""
    from app.orchestrator.steps.generate_image_prompts import _reload_frames

    dir_ = Path(tempfile.mkdtemp())
    engine = create_async_engine("sqlite+aiosqlite:///" + str(dir_ / "project.db"))
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with sessions() as s:
        s.add(Project(id=2, slug="s", topic="s", status=ProjectStatus.generating_image_prompts, meta={}))
        s.add(
            Frame(
                project_id=2,
                number=1,
                uuid="a" * 24,
                sort_key=1,
                voiceover_text="vo 1",
                attrs={},
            )
        )
        s.add(
            Frame(
                project_id=2,
                number=ARCHIVE_NUMBER_FROM,
                uuid="b" * 24,
                sort_key=float(ARCHIVE_NUMBER_FROM),
                voiceover_text="vo old",
                attrs={"archived": True},
            )
        )
        await s.commit()

        frames = await _reload_frames(s, 2)
        assert [fr.number for fr in frames] == [1]
    await engine.dispose()


async def test_img_pr_succeeds_with_archived_frames_present() -> None:
    """Архивные кадры в проекте не мешают шагу завершиться успешно."""
    from app.orchestrator.steps import generate_image_prompts
    from app.services import xlsx_step_runners

    dir_ = Path(tempfile.mkdtemp())
    engine = create_async_engine("sqlite+aiosqlite:///" + str(dir_ / "project.db"))
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with sessions() as s:
        s.add(Project(id=2, slug="s", topic="s", status=ProjectStatus.generating_image_prompts, meta={}))
        s.add(
            Frame(
                project_id=2,
                number=1,
                uuid="a" * 24,
                sort_key=1,
                voiceover_text="vo 1",
                meaning="смысл 1",
                attrs={"place": "лаборатория", "accent": "свет"},
            )
        )
        # Архивный кадр от прошлой разбивки: промт у него пустой.
        s.add(
            Frame(
                project_id=2,
                number=ARCHIVE_NUMBER_FROM,
                uuid="b" * 24,
                sort_key=float(ARCHIVE_NUMBER_FROM),
                voiceover_text="vo old",
                meaning="смысл old",
                attrs={"archived": True, "place": "старое место", "accent": "старый свет"},
            )
        )
        await s.commit()

    async def runner(*_a, **_k):
        """Модель заполнила единственный живой кадр."""
        async with sessions() as writer:
            for fr in (await writer.scalars(select(Frame))).all():
                if fr.number == 1:
                    fr.image_prompt = REAL
            await writer.commit()
        return SimpleNamespace(apply_ops=[], ops_applied_inline=True)

    async with sessions() as session:
        project = await session.get(Project, 2)
        with (
            patch.object(Project, "data_dir", property(lambda _: dir_)),
            patch.object(xlsx_step_runners, "run_img_pr_xlsx", side_effect=runner),
        ):
            await generate_image_prompts.run(session, project, SimpleNamespace())
        await session.refresh(project)

        frames = (await session.scalars(select(Frame).where(Frame.project_id == 2))).all()
        live = [fr for fr in frames if fr.number == 1]
        assert live and live[0].image_prompt == REAL
    await engine.dispose()
