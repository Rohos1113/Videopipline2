"""Дефект F: коллизия слотов excel_gpt — ошибка графа, а не эвристика.

Две ноды «ИИ-редактор сцен» с одинаковым ``slotIndex`` означают, что одна
из них работает под статусом чужого слота (enrich_2 vs enrich_1). Раньше
это молча «чинилось» перенумерацией по позиции на холсте — нода 2 тихо
становилась нодой 1. Теперь такой граф отвергается при сохранении:
``validate_workflow_graph`` → ошибка → HTTP 400 «перенумеруйте ноды».
"""

from __future__ import annotations

from app.orchestrator.graph.validate import validate_workflow_graph
from app.services.excel_gpt_node import (
    MAX_EXCEL_GPT_SLOTS,
    assign_slot_indices,
    declared_slot_index,
    slot_collisions,
)


def _node(nid: str, *, slot=None, x: float = 100.0, typ: str = "excel_gpt"):
    data: dict = {"label": "ИИ-редактор сцен"}
    if slot is not None:
        data["slotIndex"] = slot
    return {"id": nid, "type": typ, "position": {"x": x, "y": 200.0}, "data": data}


# ── declared_slot_index: только ЯВНЫЙ слот ───────────────────────────────


def test_declared_slot_reads_explicit_slot_only() -> None:
    """Явный слот — из data.slotIndex (в т.ч. строкой) или legacy-типа."""
    assert declared_slot_index(_node("a", slot=2)) == 2
    assert declared_slot_index(_node("a", slot="3")) == 3
    assert declared_slot_index(_node("a", typ="enrich_4")) == 4
    # Без слота — None (не тихий «слот 1»).
    assert declared_slot_index(_node("a")) is None
    # Мусор и вне 1..5 — None.
    assert declared_slot_index(_node("a", slot="abc")) is None
    assert declared_slot_index(_node("a", slot=0)) is None
    assert declared_slot_index(_node("a", slot=99)) is None


# ── slot_collisions: детектор ────────────────────────────────────────────


def test_collisions_detected_for_same_slot() -> None:
    nodes = [
        _node("n_a", slot=2, x=100.0),
        _node("n_b", slot=2, x=2000.0),
    ]
    assert slot_collisions(nodes) == [(2, ["n_a", "n_b"])]


def test_no_collisions_for_distinct_slots() -> None:
    nodes = [
        _node("n_a", slot=1, x=100.0),
        _node("n_b", slot=2, x=2000.0),
    ]
    assert slot_collisions(nodes) == []


def test_scene_agents_and_overflow_do_not_collide() -> None:
    """Агенты веера и закреплённые overflow-ноды слоты не занимают."""
    agent = _node("n_agent", slot=2, x=100.0)
    agent["data"]["sd_agent"] = "characters"
    overflow = _node("n_over", slot=2, x=2000.0)
    overflow["data"]["slotOverflow"] = True
    assert slot_collisions([agent, overflow]) == []


def test_more_nodes_than_slots_is_overflow_not_collision() -> None:
    """6+ нод — переполнение (слотов всего 5), а не ошибка графа."""
    nodes = [_node(f"n_{i}", slot=5, x=float(i * 100)) for i in range(6)]
    assert slot_collisions(nodes) == []


# ── assign_slot_indices: дубль НЕ чинится молча ───────────────────────


def test_assign_keeps_duplicate_slots_instead_of_silent_renumber() -> None:
    """Дубль слотов сохраняется как есть — валидатор его увидит.

    Раньше ноды молча перенумеровывались по X: нода 2 тихо становилась
    нодой 1 (дефект E в наследство).
    """
    nodes = [
        _node("n_a", slot=2, x=100.0),
        _node("n_b", slot=2, x=2000.0),
    ]
    after = assign_slot_indices(nodes)
    slots = {n["id"]: n["data"]["slotIndex"] for n in after}
    assert slots == {"n_a": 2, "n_b": 2}


def test_assign_still_numbers_gap_by_position() -> None:
    """Дырка в слотах (удалили среднюю ноду) — по-прежнему чинится по X.

    Это не коллизия: слот остаётся непрерывным 1..N, и переход
    enrich_2_ready → enriching_3 не уводит в несуществующий слот.
    """
    nodes = [
        _node("n_excel_gpt_1", slot=1, x=100.0),
        _node("n_excel_gpt_3", slot=3, x=2000.0),
    ]
    after = assign_slot_indices(nodes)
    slots = sorted(n["data"]["slotIndex"] for n in after)
    assert slots == [1, 2]


def test_assign_renumbers_overflow_when_more_nodes_than_slots() -> None:
    """Больше 5 нод — лишние уходят в overflow, слоты остаются 1..5."""
    nodes = [_node(f"n_{i}", slot=5, x=float(i * 100)) for i in range(7)]
    after = assign_slot_indices(nodes)
    by_id = {n["id"]: n["data"] for n in after}
    assert len([d for d in by_id.values() if d.get("slotOverflow")]) == 2
    assert sorted(d["slotIndex"] for d in by_id.values() if "slotIndex" in d) == [1, 2, 3, 4, 5]


# ── validate_workflow_graph: дубль → ошибка графа ───────────────────────


def test_validate_rejects_duplicate_slots() -> None:
    nodes = [
        _node("n_a", slot=2, x=100.0),
        _node("n_b", slot=2, x=2000.0),
    ]
    r = validate_workflow_graph(nodes, [])
    assert r["valid"] is False
    assert any("слот 2" in e and "перенумеруйте" in e for e in r["errors"])


def test_validate_accepts_distinct_slots() -> None:
    nodes = [
        _node("n_a", slot=1, x=100.0),
        _node("n_b", slot=2, x=2000.0),
    ]
    r = validate_workflow_graph(nodes, [])
    assert r["valid"] is True
    assert r["errors"] == []


def test_validate_rejects_duplicate_slots_written_as_strings() -> None:
    """Дубль, записанный строками («2»), — та же ошибка, что и числами."""
    nodes = [
        _node("n_a", slot="2", x=100.0),
        _node("n_b", slot="2", x=2000.0),
    ]
    r = validate_workflow_graph(nodes, [])
    assert r["valid"] is False
    assert any("перенумеруйте" in e for e in r["errors"])


def test_validate_allows_overflow_duplicates() -> None:
    """6+ нод с одинаковым слотом — переполнение, граф валиден."""
    nodes = [_node(f"n_{i}", slot=5, x=float(i * 100)) for i in range(6)]
    r = validate_workflow_graph(nodes, [])
    assert r["valid"] is True
    assert r["errors"] == []


def test_max_slots_boundary_is_still_collision() -> None:
    """Ровно 5 нод — ещё не переполнение: дубль слота 4 — ошибка графа."""
    nodes = [
        _node("n_1", slot=1, x=100.0),
        _node("n_2", slot=2, x=200.0),
        _node("n_3", slot=3, x=300.0),
        _node("n_4", slot=4, x=400.0),
        _node("n_5", slot=4, x=500.0),
    ]
    assert len(nodes) == MAX_EXCEL_GPT_SLOTS
    r = validate_workflow_graph(nodes, [])
    assert r["valid"] is False
    assert any("перенумеруйте" in e for e in r["errors"])
