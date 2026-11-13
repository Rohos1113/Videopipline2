"""Тесты наблюдаемости: лог прогресса работающей ноды в реконсайлере (задача 5а).

В фоновом цикле реконсайлера (раз в 60 с) для нод в статусе running пишется
heartbeat-лог: сколько нода выполняется, сколько минут назад был прогресс и
текущий текст прогресса:
`[#86] нода 'n_excel_gpt_2': running 12 мин, последний прогресс 3 мин назад, в работе: пачка 2/3`
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any
from unittest.mock import MagicMock

import pytest

from app.models import NodeRun, NodeRunStatus, Project, ProjectStatus, WorkflowRun
from app.services.run_sync import (
    _format_duration_ru,
    _log_running_node_progress,
    _reconcile_stale_node_runs,
)

# ── 1. Форматирование длительности ──────────────────────────────────────────


def test_format_duration_ru_seconds() -> None:
    assert _format_duration_ru(0) == "0 с"
    assert _format_duration_ru(15) == "15 с"
    assert _format_duration_ru(59) == "59 с"


def test_format_duration_ru_minutes() -> None:
    assert _format_duration_ru(60) == "1 мин"
    assert _format_duration_ru(180) == "3 мин"
    assert _format_duration_ru(720) == "12 мин"
    assert _format_duration_ru(3540) == "59 мин"


def test_format_duration_ru_hours() -> None:
    assert _format_duration_ru(3600) == "1 ч"
    assert _format_duration_ru(4500) == "1 ч 15 мин"
    assert _format_duration_ru(7200) == "2 ч"


# ── 2. Heartbeat лог ноды ───────────────────────────────────────────────────


def test_log_running_node_progress_with_progress_text() -> None:
    now = datetime(2026, 11, 13, 12, 0, 0)
    started = now - timedelta(minutes=12)
    updated = now - timedelta(minutes=3)

    nr = NodeRun(
        workflow_run_id=1,
        node_key="n_excel_gpt_2",
        node_type="excel_gpt",
        status=NodeRunStatus.running,
        progress=50,
        progress_text="в работе: пачка 2/3",
        started_at=started,
        updated_at=updated,
    )

    messages: list[str] = []
    fake_logger = MagicMock()
    fake_logger.info.side_effect = lambda msg, *args: messages.append(msg.format(*args))

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("app.services.run_sync.logger", fake_logger)
        _log_running_node_progress(86, nr, now)

    assert len(messages) == 1
    assert (
        messages[0]
        == "[#86] нода 'n_excel_gpt_2': running 12 мин, последний прогресс 3 мин назад, в работе: пачка 2/3"
    )


def test_log_running_node_progress_without_progress_text() -> None:
    now = datetime(2026, 11, 13, 12, 0, 0)
    started = now - timedelta(seconds=40)
    updated = now - timedelta(seconds=10)

    nr = NodeRun(
        workflow_run_id=1,
        node_key="n_script",
        node_type="script",
        status=NodeRunStatus.running,
        progress=0,
        progress_text=None,
        started_at=started,
        updated_at=updated,
    )

    messages: list[str] = []
    fake_logger = MagicMock()
    fake_logger.info.side_effect = lambda msg, *args: messages.append(msg.format(*args))

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("app.services.run_sync.logger", fake_logger)
        _log_running_node_progress(42, nr, now)

    assert len(messages) == 1
    assert messages[0] == "[#42] нода 'n_script': running 40 с, последний прогресс 10 с назад"


def test_log_running_node_progress_fallback_to_created_at() -> None:
    now = datetime(2026, 11, 13, 12, 0, 0)
    created = now - timedelta(minutes=5)

    nr = NodeRun(
        workflow_run_id=1,
        node_key="n_hero",
        node_type="hero",
        status=NodeRunStatus.running,
        progress=10,
        progress_text="генерация",
        started_at=None,
        created_at=created,
        updated_at=None,
    )

    messages: list[str] = []
    fake_logger = MagicMock()
    fake_logger.info.side_effect = lambda msg, *args: messages.append(msg.format(*args))

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("app.services.run_sync.logger", fake_logger)
        _log_running_node_progress(10, nr, now)

    assert len(messages) == 1
    assert messages[0] == "[#10] нода 'n_hero': running 5 мин, последний прогресс 5 мин назад, генерация"


# ── 3. Интеграция с _reconcile_stale_node_runs ─────────────────────────────


@pytest.mark.asyncio
async def test_reconcile_emits_heartbeat_for_running_live_node(monkeypatch: pytest.MonkeyPatch) -> None:
    now = datetime(2026, 11, 13, 12, 0, 0)
    started = now - timedelta(minutes=10)
    updated = now - timedelta(minutes=2)

    project = Project(
        id=86,
        slug="test-86",
        title="Test 86",
        topic="topic",
        status=ProjectStatus.enriching_2,
        meta={},
    )
    nr = NodeRun(
        id=1,
        workflow_run_id=1,
        node_key="n_excel_gpt_2",
        node_type="excel_gpt",
        status=NodeRunStatus.running,
        progress=40,
        progress_text="в работе: пачка 2/3",
        started_at=started,
        updated_at=updated,
    )
    wf_run = WorkflowRun(
        id=1,
        workflow_id=1,
        project_id=86,
        status="running",
        node_runs=[nr],
    )

    # Мокаем session_scope так, чтобы вернуть наш wf_run и project
    class FakeSession:
        async def execute(self, _query: Any) -> Any:
            mock_res = MagicMock()
            mock_res.scalars.return_value.all.return_value = [wf_run]
            return mock_res

        async def get(self, model: Any, entity_id: Any) -> Any:
            if model is Project and entity_id == 86:
                return project
            return None

        async def flush(self) -> None:
            pass

    class FakeSessionScope:
        async def __aenter__(self) -> FakeSession:
            return FakeSession()

        async def __aexit__(self, *args: Any) -> None:
            pass

    monkeypatch.setattr("app.services.run_sync.session_scope", lambda: FakeSessionScope())

    async def fake_is_work_live(*a: Any, **kw: Any) -> bool:
        return True

    monkeypatch.setattr("app.services.reconciler.is_work_live", fake_is_work_live)

    logged: list[str] = []
    fake_logger = MagicMock()
    fake_logger.info.side_effect = lambda msg, *args: logged.append(msg.format(*args))
    monkeypatch.setattr("app.services.run_sync.logger", fake_logger)

    fixed = await _reconcile_stale_node_runs(
        initiator="background_reconcile",
        require_no_live_task=True,
    )

    assert fixed == 0
    assert nr.status == NodeRunStatus.running  # Ноду не тронули
    heartbeat_logs = [m for m in logged if "running" in m and "последний прогресс" in m]
    assert len(heartbeat_logs) == 1
    assert "нода 'n_excel_gpt_2'" in heartbeat_logs[0]
    assert "в работе: пачка 2/3" in heartbeat_logs[0]
