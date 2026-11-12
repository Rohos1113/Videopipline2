"""Дефект D: ранний return на «stale GPT» убивает ноду.

Ситуация: юзер нажал ▶ на другой шаг (или ⏹) пока GPT enrich ещё отвечал.
Когда ответ пришёл, статус проекта уже не ``enriching_N`` — и код в
``enrich_xlsx`` делал РАННИЙ RETURN, недожидаясь двух вещей:

* ``_after_excel_gpt_done`` — синк storage-нод вниз по графу, запуск
  vision-check и авто-цепочка ``excel_gpt → excel_gpt`` по стрелкам;
* ``_maybe_auto_chain_excel_gpt`` — прыжок на следующий слот группы.

Итог прежде был: GPT отработал, ``completed_keys`` записан, NodeRun закрыт,
а цепочка не продолжилась — нода «висела» (как на скриншоте владельца).

Фикс: разделяем «работа сделана» и «статус двигаем».

* Статус/ready двигаем ТОЛЬКО если он всё ещё наш (``enriching_N``).
* Цепочка (``_after_excel_gpt_done``) выполняется ВСЕГДА: работа-то сделана,
  и storage-синк с авто-цепочкой по стрелкам нужны независимо от того,
  куда юзер ушёл статусом.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.orchestrator.steps import enrich_xlsx


class _FakeSession:
    """Сессия-заглушка: flush/commit ничего не делают."""

    async def flush(self) -> None:
        return None

    async def commit(self) -> None:
        return None

    async def refresh(self, _obj: object) -> None:
        return None


def _project(status) -> object:
    """Настоящий ORM-объект Project: flag_modified требует _sa_instance_state."""
    from app.models import Project

    return Project(
        id=86,
        slug="nctx-86",
        topic="t",
        status=status,
        meta={},
        auto_mode=False,
    )


@pytest.mark.asyncio
async def test_stale_status_still_runs_after_done(monkeypatch) -> None:
    """Статус ушёл (юзер нажал ▶) — но цепочка всё равно должна отработать."""
    from app.models import ProjectStatus

    calls: list[str] = []

    async def _fake_after_done(session, project, *, node_key, slot_idx, ready_status):
        calls.append("after_done")
        return None

    async def _fake_harness(session, project, *, check_mode):
        calls.append("harness")
        return None

    async def _fake_complete_noderun(session, project, node_key, slot_idx):
        calls.append("complete_noderun")
        return None

    monkeypatch.setattr(enrich_xlsx, "_after_excel_gpt_done", _fake_after_done)
    monkeypatch.setattr(enrich_xlsx, "_harness_before_enrich_ready", _fake_harness)
    monkeypatch.setattr(enrich_xlsx, "_complete_excel_gpt_noderun", _fake_complete_noderun)

    project = _project(ProjectStatus.splitting)  # юзер ушёл на другой шаг
    session = _FakeSession()

    await enrich_xlsx._finalize_excel_gpt_api_path(
        session,  # type: ignore[arg-type]
        project,  # type: ignore[arg-type]
        node_key="n_excel_gpt_2",
        slot_idx=2,
        running_status=ProjectStatus.enriching_2,
        ready_status=ProjectStatus.enrich_2_ready,
        check_mode=False,
        output_mode="project_file",
        api_res=SimpleNamespace(
            gate_status="pass",
            analysis=None,
            output_paths=[],
            reply_text="{}",
        ),
    )

    # Цепочка выполнена — это главное (раньше был ранний return).
    assert "after_done" in calls, calls
    # NodeRun закрыт — работа сделана.
    assert "complete_noderun" in calls, calls
    # Статус НЕ трогаем: юзер ушёл на другой шаг.
    assert project.status is ProjectStatus.splitting
    # Слот и нода отмечены выполненными.
    assert project.meta["enrich_completed_slots"] == [2]
    assert project.meta["excel_gpt_completed_keys"] == ["n_excel_gpt_2"]


@pytest.mark.asyncio
async def test_own_status_gets_ready_and_chain(monkeypatch) -> None:
    """Статус наш — пишем ready и двигаем цепочку (штатный путь)."""
    from app.models import ProjectStatus

    calls: list[str] = []

    async def _fake_after_done(session, project, *, node_key, slot_idx, ready_status):
        calls.append("after_done")
        return None

    async def _fake_harness(session, project, *, check_mode):
        calls.append("harness")
        return None

    async def _fake_complete_noderun(session, project, node_key, slot_idx):
        calls.append("complete_noderun")
        return None

    monkeypatch.setattr(enrich_xlsx, "_after_excel_gpt_done", _fake_after_done)
    monkeypatch.setattr(enrich_xlsx, "_harness_before_enrich_ready", _fake_harness)
    monkeypatch.setattr(enrich_xlsx, "_complete_excel_gpt_noderun", _fake_complete_noderun)

    project = _project(ProjectStatus.enriching_2)
    session = _FakeSession()

    await enrich_xlsx._finalize_excel_gpt_api_path(
        session,  # type: ignore[arg-type]
        project,  # type: ignore[arg-type]
        node_key="n_excel_gpt_2",
        slot_idx=2,
        running_status=ProjectStatus.enriching_2,
        ready_status=ProjectStatus.enrich_2_ready,
        check_mode=False,
        output_mode="project_file",
        api_res=SimpleNamespace(
            gate_status="pass",
            analysis=None,
            output_paths=[],
            reply_text="{}",
        ),
    )

    assert project.status is ProjectStatus.enrich_2_ready
    assert "after_done" in calls, calls
    assert "harness" in calls, calls


@pytest.mark.asyncio
async def test_active_key_is_cleared_either_way(monkeypatch) -> None:
    """``active_excel_gpt_node_key`` снимается в обоих случаях.

    Ключ указывает на ТЕКУЩУЮ активную ноду excel_gpt: оставить его после
    завершения ноды — значит следующая нода группы подхватит не ту.
    """
    from app.models import ProjectStatus

    async def _fake_after_done(session, project, *, node_key, slot_idx, ready_status):
        return None

    async def _fake_harness(session, project, *, check_mode):
        return None

    async def _fake_complete_noderun(session, project, node_key, slot_idx):
        return None

    monkeypatch.setattr(enrich_xlsx, "_after_excel_gpt_done", _fake_after_done)
    monkeypatch.setattr(enrich_xlsx, "_harness_before_enrich_ready", _fake_harness)
    monkeypatch.setattr(enrich_xlsx, "_complete_excel_gpt_noderun", _fake_complete_noderun)

    for status in (ProjectStatus.enriching_2, ProjectStatus.splitting):
        project = _project(status)
        project.meta = {"active_excel_gpt_node_key": "n_excel_gpt_2"}
        await enrich_xlsx._finalize_excel_gpt_api_path(
            _FakeSession(),  # type: ignore[arg-type]
            project,  # type: ignore[arg-type]
            node_key="n_excel_gpt_2",
            slot_idx=2,
            running_status=ProjectStatus.enriching_2,
            ready_status=ProjectStatus.enrich_2_ready,
            check_mode=False,
            output_mode="project_file",
            api_res=SimpleNamespace(
                gate_status="pass",
                analysis=None,
                output_paths=[],
                reply_text="{}",
            ),
        )
        assert "active_excel_gpt_node_key" not in project.meta
