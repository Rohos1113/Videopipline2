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


def test_assign_slot_indices_renumbers_by_position() -> None:
    """Явный слот перебивается позицией: номера слотов = порядок по X.

    Это текущее (осознанное) поведение: слоты назначаются слева направо
    при каждом сохранении графа. Зафиксировано тестом, чтобы изменение
    было явным, а не побочным.
    """
    nodes = [
        _node("n_excel_gpt_2", slot=2, x=100.0),
        _node("n_excel_gpt_1", slot=1, x=2000.0),
    ]
    after = assign_slot_indices(nodes)
    slots = {n["id"]: n["data"]["slotIndex"] for n in after}
    assert slots == {"n_excel_gpt_2": 1, "n_excel_gpt_1": 2}
