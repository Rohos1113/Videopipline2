"""PR 3 (интеграция): refresh контекста нумерации читает свежее из БД.

Проверяем связку целиком: ``db_apply.apply_ops`` записал ``shot01_id_scene``
в attrs кадра → ``_refresh_scene_numbering_ctx`` перечитывает кадры из БД и
обновляет ``frames_context``/``project_state`` в том же ctx, который уедет
в следующую пачку.
"""

from __future__ import annotations

import pytest

from app.db import session_scope
from app.models import Frame, Project, ProjectStatus
from app.services.db_frames_context import build_excel_gpt_db_context


async def _seed(frames: int = 4) -> tuple[int, list[str]]:
    """Проект с N кадрами; первые — уже пронумерованы."""
    uuids = [f"u{i:03d}" for i in range(1, frames + 1)]
    async with session_scope() as s:
        p = Project(slug=f"nctx-{frames}", topic="t", status=ProjectStatus.new, meta={})
        s.add(p)
        await s.flush()
        for i, uuid in enumerate(uuids, start=1):
            attrs = {"place": "Дом"}
            if i <= 1:
                attrs["shot01_id_scene"] = "scene_01"
                attrs["shot01_number"] = "scene_01_shot_01"
            s.add(
                Frame(
                    project_id=p.id,
                    number=i,
                    uuid=uuid,
                    voiceover_text=f"Закадр {i}",
                    attrs=attrs,
                )
            )
        await s.commit()
        return p.id, uuids


@pytest.mark.asyncio
async def test_refresh_reads_scene_ids_written_by_apply_ops() -> None:
    """После apply-ops refresh видит id_scene, записанные в БД."""
    from sqlalchemy import select

    from app.orchestrator.steps.enrich_xlsx import _refresh_scene_numbering_ctx
    from app.services import db_apply

    project_id, uuids = await _seed(frames=4)

    async with session_scope() as s:
        project = await s.get(Project, project_id)
        ctx = build_excel_gpt_db_context(
            project_id=project_id,
            slug="nctx",
            frames=list((await s.execute(select(Frame).where(Frame.project_id == project_id))).scalars().all()),
            characters=[],
            with_scene_context=True,
        )
        # До apply: пронумерован только первый кадр.
        assert ctx["project_state"]["scenes_assigned"] == 1
        assert ctx["project_state"]["scene_last"] == "scene_01"

        # Нода пишет сцены кадрам 2 и 3.
        await db_apply.apply_ops(
            s,
            project,
            [
                {"frame_uuid": uuids[1], "fields": {"id_scene": "scene_02"}},
                {"frame_uuid": uuids[2], "fields": {"id_scene": "scene_03"}},
            ],
        )
        await s.commit()

        # Refresh перечитывает кадры из БД и обновляет контекст.
        changed = await _refresh_scene_numbering_ctx(s, project, ctx)

    assert changed is True
    assert ctx["project_state"]["scenes_assigned"] == 3
    assert ctx["project_state"]["scene_last"] == "scene_03"
    numbered = {r["uuid"]: r["id_scene"] for r in ctx["frames_context"] if r.get("id_scene")}
    assert numbered[uuids[1]] == "scene_02"
    assert numbered[uuids[2]] == "scene_03"


@pytest.mark.asyncio
async def test_refresh_is_noop_without_scene_context() -> None:
    """Нода без нумерации сцен: контекста нет — refresh ничего не меняет."""
    from sqlalchemy import select

    from app.orchestrator.steps.enrich_xlsx import _refresh_scene_numbering_ctx

    project_id, _ = await _seed(frames=2)

    async with session_scope() as s:
        project = await s.get(Project, project_id)
        ctx = build_excel_gpt_db_context(
            project_id=project_id,
            slug="nctx",
            frames=list((await s.execute(select(Frame).where(Frame.project_id == project_id))).scalars().all()),
            characters=[],
        )
        assert "frames_context" not in ctx
        assert await _refresh_scene_numbering_ctx(s, project, ctx) is False
