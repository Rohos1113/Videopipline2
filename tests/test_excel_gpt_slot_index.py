"""Дефект A: тихий fallback слота на 1.

``slotIndex`` может прийти строкой (JSON/форма/PATCH без типизации). Раньше
такая нода МОЛЧА получала слот 1: работала под статусом слота 1 и
конфликтовала с настоящей нодой 1 — владелец видел «нода 2 висит, а нода 1
готова» без внятной причины.

Теперь строка разбирается, а невалидное значение — loudly логируется.
"""

from __future__ import annotations

from app.services.excel_gpt_node import (
    MAX_EXCEL_GPT_SLOTS,
    assign_slot_indices,
    legacy_enrich_slot_from_type,
    slot_index_from_node,
)


def _node(nid: str = "n_excel_gpt_2", *, slot=None, x: float = 2740.0, typ: str = "excel_gpt"):
    data: dict = {"label": "ИИ-редактор сцен"}
    if slot is not None:
        data["slotIndex"] = slot
    return {"id": nid, "type": typ, "position": {"x": x, "y": 200.0}, "data": data}


def test_slot_index_string_is_parsed() -> None:
    """slotIndex строкой '2' → слот 2, а не тихий слот 1."""
    assert slot_index_from_node(_node(slot="2")) == 2
    assert slot_index_from_node(_node(slot=" 3 ")) == 3


def test_slot_index_int_still_works() -> None:
    """Обычный int-путь не изменился."""
    for slot in range(1, MAX_EXCEL_GPT_SLOTS + 1):
        assert slot_index_from_node(_node(slot=slot)) == slot


def test_slot_index_out_of_range_falls_back_to_legacy() -> None:
    """Слот вне 1..5 — не валидный: legacy-тип, иначе первый слот."""
    # Нода excel_gpt без номера и без legacy-типа → первый слот (как было).
    assert slot_index_from_node(_node(slot=99)) == 1
    # Legacy-нода enrich_3 знает свой слот даже при мусорном slotIndex.
    legacy = _node(nid="n_enrich_3", slot=99, typ="enrich_3")
    assert legacy_enrich_slot_from_type("enrich_3") == 3
    assert slot_index_from_node(legacy) == 3


def test_slot_index_bool_is_not_a_slot() -> None:
    """bool — не int-слот (True не должен значить слот 1)."""
    assert slot_index_from_node(_node(slot=True)) == 1


def test_slot_index_garbage_does_not_crash() -> None:
    """Мусор в slotIndex не роняет резолвер (лог — отдельно)."""
    for bad in ("", "abc", "2.5", None, [], {}):
        assert slot_index_from_node(_node(slot=bad)) == 1


def test_overflow_and_scene_agents_still_reserved() -> None:
    """Служебные ноды не занимают слоты — поведение не изменилось."""
    assert slot_index_from_node(_node(slot=0)) == 1  # 0 вне 1..5 → первый слот
    agent = _node(slot=2, typ="excel_gpt")
    agent["data"]["sd_agent"] = "characters"
    assert slot_index_from_node(agent) == 0
    overflow = _node(slot=2)
    overflow["data"]["slotOverflow"] = True
    assert slot_index_from_node(overflow) == 0


def test_assign_slot_indices_keeps_explicit_slots_on_move() -> None:
    """Перетаскивание ноды НЕ переназначает слоты (дефект E).

    Слот — связь ноды с шагом DAG, а не её место на холсте. Раньше нумерация
    шла только по position.x, и нода 2, перетащенная левее ноды 1, становилась
    слотом 1 — и работала под статусом чужого слота.
    """
    nodes = [
        _node("n_excel_gpt_2", slot=2, x=100.0),  # перетащили левее
        _node("n_excel_gpt_1", slot=1, x=2000.0),
    ]
    after = assign_slot_indices(nodes)
    slots = {n["id"]: n["data"]["slotIndex"] for n in after}
    assert slots == {"n_excel_gpt_2": 2, "n_excel_gpt_1": 1}


def test_assign_slot_indices_numbers_nodes_without_slot() -> None:
    """Ноды без явного слота нумеруются по X — как раньше."""
    nodes = [
        _node("n_a", slot=None, x=100.0),
        _node("n_b", slot=None, x=2000.0),
    ]
    after = assign_slot_indices(nodes)
    slots = {n["id"]: n["data"]["slotIndex"] for n in after}
    assert slots == {"n_a": 1, "n_b": 2}


def test_assign_slot_indices_uses_free_slots_for_new_nodes() -> None:
    """Новая нода без слота занимает СВОБОДНЫЙ слот, не занятый явным."""
    nodes = [
        _node("n_excel_gpt_1", slot=1, x=100.0),
        _node("n_new", slot=None, x=2000.0),
    ]
    after = assign_slot_indices(nodes)
    slots = {n["id"]: n["data"]["slotIndex"] for n in after}
    assert slots == {"n_excel_gpt_1": 1, "n_new": 2}


def test_assign_slot_indices_marks_overflow_when_slots_exhausted() -> None:
    """Слотов больше нет — нода уходит в overflow (slotIndex нет, флаг есть)."""
    nodes = [_node(f"n_{i}", slot=None, x=float(i * 100)) for i in range(7)]
    after = assign_slot_indices(nodes)
    by_id = {n["id"]: n for n in after}
    for i in range(5):
        assert by_id[f"n_{i}"]["data"]["slotIndex"] == i + 1
    for i in (5, 6):
        data = by_id[f"n_{i}"]["data"]
        assert "slotIndex" not in data
        assert data["slotOverflow"] is True


def test_assign_slot_indices_fills_gap_by_position() -> None:
    """Дырка в явных слотах (удалили среднюю ноду) → нумерация по X.

    Дырка опасна для статусов: переход ``enrich_2_ready → enriching_3``
    уводит в слот, которого на холсте нет. Поэтому при не-непрерывных
    явных слотах возвращаемся к старой нумерации по X — слоты всегда 1..N.
    """
    nodes = [
        _node("n_excel_gpt_1", slot=1, x=100.0),
        _node("n_excel_gpt_3", slot=3, x=2000.0),  # слот 2 отсутствует
    ]
    after = assign_slot_indices(nodes)
    slots = {n["id"]: n["data"]["slotIndex"] for n in after}
    # Слоты непрерывны: 1 и 2.
    assert sorted(slots.values()) == [1, 2]


def test_assign_slot_indices_duplicate_slots_fall_back_to_position() -> None:
    """Дубль явных слотов → нумерация по X, слоты уникальны."""
    nodes = [
        _node("n_a", slot=2, x=100.0),
        _node("n_b", slot=2, x=2000.0),
    ]
    after = assign_slot_indices(nodes)
    slots = [n["data"]["slotIndex"] for n in after]
    assert sorted(slots) == [1, 2]
    assert len(set(slots)) == 2
