"""H3: отказ модели — пауза вместо платных ретраев.

Живой случай (#86, 11.11): нода «ИИ-редактор сцен» получила неполный вход,
модель отказалась работать, и шаг ушёл в длинные ПЛАТНЫЕ повторы: тот же вход
даёт тот же отказ. Повтор только жёг бюджет и прятал причину (в ноде светилась
«Неизвестная ошибка»).

Как у img_pr «нет исходных данных»: отказ детерминирован → пауза с текстом
ответа модели, дальше человек чинит вход и жмёт ▶.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.contracts import LlmContractError
from app.models import Base, Project, ProjectStatus

REFUSAL_ERR = LlmContractError(
    "apply_ops_n_excel_gpt_2: модель отказалась работать: missing_global_context: "
    "Переданы только кадры 27–56 и список UUID проекта.",
    kind="refusal",
    contract="vp_apply_ops",
)


@pytest.mark.asyncio
async def test_refusal_pauses_project_without_retry() -> None:
    from app.services.step_failure_policy import record_step_failure

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sessions() as s:
            p = Project(
                id=86,
                slug="s",
                title="s",
                topic="s",
                status=ProjectStatus.enriching_2,
                meta={},
            )
            s.add(p)
            await s.flush()
            with (
                patch(
                    "app.services.step_failure_policy._soft_retry_without_wipe",
                    new_callable=AsyncMock,
                ) as soft,
                patch("app.services.run_sync.mark_running_node_failed", new_callable=AsyncMock),
                patch("app.services.run_sync.stop_active_running_node", new_callable=AsyncMock),
            ):
                action = await record_step_failure(s, p, error=REFUSAL_ERR)
            assert soft.await_count == 0, "soft retry для отказа модели запрещён"
            assert action == "pause_infra"
            assert p.status is ProjectStatus.paused
            fs = p.meta["step_failure"]
            assert fs["last_error_code"] == "llm_model_refusal"
            assert "missing_global_context" in fs["last_error"]
    finally:
        await engine.dispose()
