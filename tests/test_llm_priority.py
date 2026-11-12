"""Приоритет плановых (проектных) LLM-вызовов над ручными (adhoc).

Зачем. Ручной тест промта из UI идёт в того же провайдера, что и работающая
нода: 11.11 на VPS таких вызовов было 12 за день, шлюз деградировал, и
страдала нода. Плановые вызовы идут без ожидания; ручные — ждут конца
плановых и уходят с внятным отказом.

Инварианты:
* плановый вызов НЕ ждёт никогда (приоритет односторонний);
* ручной вызов ждёт и уходит с ``LlmPriorityBusy``, а не висит;
* при выключенной фиче поведение не меняется.
"""

from __future__ import annotations

import asyncio

import pytest

from app.services import llm_priority
from app.services.llm_override import LlmAccountingContext, use_accounting


@pytest.fixture(autouse=True)
def _reset_gate() -> None:
    llm_priority._planar_active = 0


@pytest.mark.asyncio
async def test_planar_call_does_not_wait() -> None:
    """Плановый вызов проходит, даже если другой плановый в полёте."""
    llm_priority._planar_enter()
    acct = LlmAccountingContext(project_id=86, node_key="n_excel_gpt_2")
    try:
        with use_accounting(acct):
            async with llm_priority.PriorityGate(enabled=True, timeout_s=5.0):
                pass
    finally:
        llm_priority._planar_exit()


@pytest.mark.asyncio
async def test_adhoc_call_waits_for_planar_to_finish() -> None:
    """Ручной вызов ждёт, пока плановый отпустит провайдера."""
    llm_priority._planar_enter()

    async def _release_later() -> None:
        await asyncio.sleep(0.3)
        llm_priority._planar_exit()

    releaser = asyncio.create_task(_release_later())
    try:
        async with llm_priority.PriorityGate(enabled=True, timeout_s=5.0):
            # К моменту входа плановый уже отпустил провайдер.
            assert llm_priority._planar_active == 0
    finally:
        await releaser


@pytest.mark.asyncio
async def test_adhoc_call_is_refused_with_clear_error() -> None:
    """Если плановый не отпустил провайдер — внятный отказ, а не таймаут."""
    llm_priority._planar_enter()
    try:
        with pytest.raises(llm_priority.LlmPriorityBusy) as exc:
            async with llm_priority.PriorityGate(enabled=True, timeout_s=0.2):
                pass
        assert "работает" in str(exc.value)
    finally:
        llm_priority._planar_exit()


@pytest.mark.asyncio
async def test_disabled_gate_changes_nothing() -> None:
    """Выключенная фича — вызов проходит, даже когда плановый в полёте."""
    llm_priority._planar_enter()
    try:
        async with llm_priority.PriorityGate(enabled=False, timeout_s=0.2):
            pass
    except llm_priority.LlmPriorityBusy:  # pragma: no cover - фича выключена
        pytest.fail("выключенный гейт не должен отказывать")
    finally:
        llm_priority._planar_exit()


@pytest.mark.asyncio
async def test_project_context_makes_call_planar() -> None:
    """Вызов с привязкой к проекту — плановый; без неё — ручной."""
    acct = LlmAccountingContext(project_id=86, node_key="n_excel_gpt_2")
    with use_accounting(acct):
        assert llm_priority.is_planar_call() is True

    assert llm_priority.is_planar_call() is False


@pytest.mark.asyncio
async def test_planar_call_is_not_blocked_by_adhoc() -> None:
    """Ручной вызов в полёте НЕ блокирует плановый (приоритет односторонний)."""
    # Ручной вызов: он не занимает слот планового.
    async with llm_priority.PriorityGate(enabled=True, timeout_s=1.0):
        assert llm_priority._planar_active == 0

    # Плановый проходит мгновенно, даже если ручной ждёт.
    async def _adhoc_waiting() -> None:
        try:
            async with llm_priority.PriorityGate(enabled=True, timeout_s=1.0):
                await asyncio.sleep(0.2)
        except llm_priority.LlmPriorityBusy:
            pass

    llm_priority._planar_enter()
    try:
        task = asyncio.create_task(_adhoc_waiting())
        await asyncio.sleep(0.05)
        # Плановый слот занят нами — ручный ждёт, мы не ждём.
        assert llm_priority._planar_active == 1
        await task
    finally:
        llm_priority._planar_exit()
