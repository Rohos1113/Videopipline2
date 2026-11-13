"""Карта дефолтного графа: слоты → node_key → статусы → порядок шагов.

Дефекты A, D, E, F аудита 11.11 — это один класс: «нода работает под чужим
слотом/статусом». Юнит-тесты проверяли синтетические ноды, а сквозного теста
на РЕАЛЬНОМ дефолтном графе не было: путь «граф → слот → ключ ноды → статус
шага» проверялся только руками на VPS.

Здесь зафиксирован контракт, на котором держится цепочка:

* в дефолтном графе две excel-ноды со слотами 1 и 2, дублей слотов нет;
* после ноды 1 цепочка идёт «Персонажи → Предметы → нода 2» (аудит §6 п.10);
* перетаскивание ноды 2 левее ноды 1 НЕ меняет слоты и НЕ подменяет ключ
  (ровно этот баг давал «нода 2 работает под статусом ноды 1»);
* слот ↔ статус ↔ код шага согласованы в одном каноне (SLOT_MAP), и
  node_registry / enrich_xlsx читают ИМЕННО его, а не свои копии.
"""

from __future__ import annotations

from typing import Any

from app.models import Project, ProjectStatus
from app.orchestrator import node_registry
from app.orchestrator.default_graph import default_graph
from app.orchestrator.steps import enrich_xlsx
from app.services import excel_gpt_node as egn

SLOT_1 = "n_excel_gpt_1"
SLOT_2 = "n_excel_gpt_2"


def _graph() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    nodes, edges = default_graph()
    return list(nodes), list(edges)


def _project(nodes: list[dict[str, Any]], edges: list[dict[str, Any]]) -> Project:
    return Project(
        id=1,
        slug="graph-map",
        title="graph-map",
        topic="t",
        status=ProjectStatus.enriching_2,
        meta={"canvas_graph": {"nodes": nodes, "edges": edges}},
    )


def _slot_by_id(nodes: list[dict[str, Any]]) -> dict[str, int | None]:
    """Слоты только excel-нод: у остальных понятия слота нет."""
    return {str(n.get("id")): egn.slot_index_from_node(n) for n in nodes if n.get("type") == "excel_gpt"}


def _drag_node_left(nodes: list[dict[str, Any]], node_id: str) -> list[dict[str, Any]]:
    """Перетащить ноду далеко влево — как на холсте (позиция меняется)."""
    return [{**n, "position": {"x": -500.0, "y": 0.0}} if n.get("id") == node_id else n for n in nodes]


# ── 1. Форма дефолтного графа ─────────────────────────────────────────────


def test_default_graph_has_two_excel_nodes_with_slots_1_and_2() -> None:
    nodes, _ = _graph()
    excel = [n for n in nodes if n.get("type") == "excel_gpt"]

    assert [n["id"] for n in excel] == [SLOT_1, SLOT_2]
    assert [n["data"]["slotIndex"] for n in excel] == [1, 2]
    assert [n["data"]["label"] for n in excel] == [
        egn.default_excel_gpt_label(1),
        egn.default_excel_gpt_label(2),
    ]


def test_default_graph_has_no_slot_collisions() -> None:
    nodes, _ = _graph()
    assert egn.slot_collisions(nodes) == []


def test_assign_slot_indices_keeps_default_graph_unchanged() -> None:
    """Дефолтный граф уже корректен: раздача слотов его не двигает."""
    nodes, _ = _graph()
    before = _slot_by_id(nodes)
    after = _slot_by_id(egn.assign_slot_indices(nodes))

    assert before == {SLOT_1: 1, SLOT_2: 2}
    assert after == before


# ── 2. Порядок цепочки (аудит §6 п.10: «нода 1 → hero → items → нода 2») ──


def test_chain_goes_node1_hero_items_node2() -> None:
    nodes, edges = _graph()
    project = _project(nodes, edges)

    assert egn.first_work_successor_along_edges(project, SLOT_1) == ("n_hero", "hero")
    assert egn.first_work_successor_along_edges(project, "n_hero") == ("n_items", "items")
    assert egn.first_work_successor_along_edges(project, "n_items") == (SLOT_2, "excel_gpt")


# ── 3. Перетаскивание ноды не меняет слот и не подменяет ключ ─────────────


def test_dragging_node2_left_keeps_slots() -> None:
    """Дефект E: раньше слот считался по position.x — нода 2 становилась слотом 1."""
    nodes, _ = _graph()
    dragged = _drag_node_left(nodes, SLOT_2)

    assert _slot_by_id(egn.assign_slot_indices(dragged)) == {SLOT_1: 1, SLOT_2: 2}


def test_dragging_node2_left_keeps_runtime_key() -> None:
    """Слот → ключ ноды остаётся верным и после перетаскивания."""
    nodes, edges = _graph()
    project = _project(egn.assign_slot_indices(_drag_node_left(nodes, SLOT_2)), edges)

    assert egn.resolve_excel_gpt_node_key_for_slot(project, 1) == SLOT_1
    assert egn.resolve_excel_gpt_node_key_for_slot(project, 2) == SLOT_2


def test_foreign_active_key_is_rejected_for_slot() -> None:
    """Дефект D: в enriching_2 остался ключ ноды слота 1 → шаг её пропускал."""
    project = _project(*_graph())

    assert egn.active_key_belongs_to_other_slot(project, SLOT_1, 2) is True
    assert egn.active_key_belongs_to_other_slot(project, SLOT_2, 1) is True
    assert egn.active_key_belongs_to_other_slot(project, SLOT_2, 2) is False


# ── 4. Слот ↔ статус ↔ код шага: один канон ───────────────────────────────


def test_slot_map_is_continuous_1_to_5() -> None:
    assert sorted(egn.SLOT_MAP) == list(range(1, egn.MAX_EXCEL_GPT_SLOTS + 1))
    assert len({v[0] for v in egn.SLOT_MAP.values()}) == egn.MAX_EXCEL_GPT_SLOTS
    assert len({v[1] for v in egn.SLOT_MAP.values()}) == egn.MAX_EXCEL_GPT_SLOTS
    for slot, (_running, _ready, code) in egn.SLOT_MAP.items():
        assert code == f"enrich_{slot}"


def test_slot_status_roundtrip() -> None:
    for slot in range(1, egn.MAX_EXCEL_GPT_SLOTS + 1):
        assert egn.slot_from_running_status(egn.running_status_for_slot(slot)) == slot
        assert egn.slot_from_ready_status(egn.ready_status_for_slot(slot)) == slot


def test_node_registry_derives_from_slot_canon() -> None:
    """Дефект F: копии маппинга в node_registry не должны разъезжаться с каноном."""
    for slot, (running, ready, code) in egn.SLOT_MAP.items():
        spec = node_registry.WORK_NODES[f"enrich_{slot}"]
        assert (
            spec.node_type,
            spec.step_code,
            spec.running_status,
            spec.ready_status,
        ) == (f"enrich_{slot}", code, running, ready)


def test_enrich_xlsx_uses_same_slot_canon() -> None:
    """`_SLOT_MAP` в шаге — это ТОТ ЖЕ объект канона, а не копия."""
    assert enrich_xlsx._SLOT_MAP is egn.SLOT_MAP


# ── 5. Критерий приёмки аудита §7 ────────────────────────────────────────


def test_slot2_closes_into_enrich_2_ready() -> None:
    nodes, edges = _graph()
    project = _project(nodes, edges)

    assert egn.running_status_for_slot(2) is ProjectStatus.enriching_2
    assert egn.ready_status_for_slot(2) is ProjectStatus.enrich_2_ready
    assert egn.resolve_excel_gpt_node_key_for_slot(project, 2) == SLOT_2
