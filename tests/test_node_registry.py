"""Коды шагов и слотов excel_gpt: что обязано остаться верным.

Проверено на боевых данных (VPS, проект #86, 11.11): холд кассы ставится под
``enrich_2``, а фактические вызовы ноды лежат в ``llm_calls`` с
``node_key='n_excel_gpt_2'``, что даёт ``step_of_node_key(...) == "enrich_2"``.
Холд и факт по одному шагу — всё сходится.

Отсюда два инварианта, которые тесты фиксируют:

1. **Код шага слота N — ``enrich_N``**, а не ``"excel_gpt"``. Подмена обнулила
   бы смету (``PRIOR_TEXT_USD`` не знает ``excel_gpt``) и развела бы холд с
   фактом.
2. **Резолв ноды по типу/коду шага обязан учитывать слот.** ``spec_for_type``
   и ``spec_for_step_code`` не могут отдавать слот 1 для любого слота — иначе
   нода слота 2 получает статусы слота 1.
"""

from __future__ import annotations

import pytest

from app.models import ProjectStatus
from app.orchestrator.node_registry import (
    spec_for_step_code,
    spec_for_type,
    step_code_of_running_status,
)
from app.services.cost_attribution import step_of_node_key
from app.services.excel_gpt_node import (
    EXCEL_GPT_STEP_CODE,
    ready_status_for_slot,
    running_status_for_slot,
    slot_from_running_status,
)
from app.services.quote import PRIOR_TEXT_USD


@pytest.mark.parametrize("slot", [1, 2, 3, 4, 5])
def test_step_code_of_excel_gpt_slot_is_enrich_n(slot: int) -> None:
    """Код шага слота N = enrich_N — он есть и в DAG, и в прайсе кассы."""
    status = running_status_for_slot(slot)
    code = step_code_of_running_status(status)

    assert code == f"enrich_{slot}"
    # Смета по этому шагу живая: с пустым кодом касса резервировала бы ноль.
    assert PRIOR_TEXT_USD.get(code) is not None


@pytest.mark.parametrize("slot", [1, 2, 3, 4, 5])
def test_hold_step_matches_fact_step(slot: int) -> None:
    """Шаг холда кассы совпадает с шагом фактических вызовов ноды.

    Факт лежит в ``llm_calls`` под ``node_key='n_excel_gpt_N'``; если шаг
    холда разойдётся с шагом факта, резерв и списание попадут в разные
    корзины и ночная сверка покажет расхождение.
    """
    code = step_code_of_running_status(running_status_for_slot(slot))
    assert code == step_of_node_key(f"n_excel_gpt_{slot}")


def test_excel_gpt_step_code_is_not_a_dag_step() -> None:
    """``excel_gpt`` — код НОДЫ, не код шага DAG.

    Подставлять его в кассу нельзя: в прайсе ``PRIOR_TEXT_USD`` его нет, и
    смета обнулится (шаг встанет без резерва).
    """
    assert PRIOR_TEXT_USD.get(EXCEL_GPT_STEP_CODE) is None
    assert PRIOR_TEXT_USD.get("enrich_2") is not None


@pytest.mark.parametrize("slot", [1, 2, 3, 4, 5])
def test_slot_is_recognised_by_running_status(slot: int) -> None:
    """Running-статус слота опознаётся как слот excel_gpt."""
    assert slot_from_running_status(running_status_for_slot(slot)) == slot


@pytest.mark.parametrize("slot", [1, 2, 3, 4, 5])
def test_slot_ready_status_is_distinct(slot: int) -> None:
    """У каждого слота свой ready-статус (иначе нода 2 ждёт слот 1)."""
    assert ready_status_for_slot(slot).value == f"enrich_{slot}_ready"


def test_non_slot_statuses_keep_their_step_codes() -> None:
    """Резолв не-слотовых статусов не изменился."""
    assert step_code_of_running_status(ProjectStatus.planning) == "plan"
    assert step_code_of_running_status(ProjectStatus.scripting) == "script"
    assert step_code_of_running_status(ProjectStatus.splitting) == "split"
    assert step_code_of_running_status(ProjectStatus.scene_designing) == "scene_d"


def test_non_running_status_has_no_step_code() -> None:
    """Готовый статус — не шаг: кода шага у него нет."""
    assert step_code_of_running_status(ProjectStatus.plan_ready) is None
    assert step_code_of_running_status(ProjectStatus.enrich_2_ready) is None


def test_spec_for_type_excel_gpt_resolves_slot_one() -> None:
    """``spec_for_type('excel_gpt')`` — слот 1 (типу слот неотличим).

    Зафиксировано текущее поведение: по типу слот определить нельзя, поэтому
    резолв по типу допустим только для первого слота. Для остальных слотов
    нужен ``spec_for_node`` (по конкретной ноде).
    """
    spec = spec_for_type(EXCEL_GPT_STEP_CODE)
    assert spec is not None
    assert spec.running_status is ProjectStatus.enriching_1
    assert spec.ready_status is ProjectStatus.enrich_1_ready


def test_spec_for_step_code_enrich_n_gives_matching_statuses() -> None:
    """``spec_for_step_code('enrich_N')`` — статусы слота N."""
    spec = spec_for_step_code("enrich_2")
    assert spec is not None
    assert spec.running_status is ProjectStatus.enriching_2
    assert spec.ready_status is ProjectStatus.enrich_2_ready
