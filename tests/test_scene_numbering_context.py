"""Контекст глобальной нумерации сцен для ноды excel_gpt.

Нода «ИИ-редактор сцен 2» (промт 05_XLSX_agent_v8_DB) назначает кадрам
сквозные идентификаторы сцен (scene_NN / scene_NN_shot_01). Нумерация
сквозная по всему проекту, поэтому модель должна видеть уже присвоенные ID
и границы проекта. Без этого модель отвечает «missing_global_context» и
отказывается работать с фрагментом (живой случай 11.11, проект #86).
"""

from __future__ import annotations

from types import SimpleNamespace

from app.services.db_frames_context import (
    build_excel_gpt_db_context,
    build_scene_numbering_context,
)


def _frame(number: int, *, scene: str = "", shot: str = "", vo: str = "текст") -> SimpleNamespace:
    attrs: dict[str, str] = {"place": "цех", "scene_sense": "смысл"}
    if scene:
        attrs["shot01_id_scene"] = scene
        attrs["shot01_number"] = f"{scene}_shot_01"
        attrs["shot01_id_shot"] = shot or "shot_01"
    return SimpleNamespace(
        number=number,
        uuid=f"uuid-{number:03d}",
        voiceover_text=vo,
        meaning="",
        animation_prompt="",
        image_prompt="",
        attrs=attrs,
    )


def test_scene_context_carries_existing_ids_and_project_state() -> None:
    """Контекст отдаёт ID соседей и сводку по проекту."""
    frames = [
        _frame(1, scene="scene_01"),
        _frame(2, scene="scene_02"),
        _frame(3),
        _frame(4),
    ]
    ctx = build_scene_numbering_context(frames)

    rows = ctx["frames_context"]
    assert [r["number"] for r in rows] == [1, 2, 3, 4]
    # Уже пронумерованные кадры несут свои ID.
    assert rows[0]["id_scene"] == "scene_01"
    assert rows[0]["number_scene"] == "scene_01_shot_01"
    assert rows[0]["id_shot"] == "shot_01"
    # Непронумерованные — без ID (ключей нет вовсе, а не пустые строки).
    assert "id_scene" not in rows[2]
    assert "id_scene" not in rows[3]

    state = ctx["project_state"]
    assert state["frames_total"] == 4
    assert state["frames_with_voiceover"] == 4
    assert state["scenes_assigned"] == 2
    assert state["scene_last"] == "scene_02"


def test_scene_last_compares_by_number_not_string() -> None:
    """scene_9 не должен «обогнать» scene_10 при сравнении строк."""
    frames = [_frame(9, scene="scene_09"), _frame(10, scene="scene_10")]
    state = build_scene_numbering_context(frames)["project_state"]
    assert state["scene_last"] == "scene_10"


def test_db_context_includes_scene_context_when_requested() -> None:
    """with_scene_context=True → в снимке есть frames_context и project_state."""
    frames = [_frame(1, scene="scene_01"), _frame(2)]

    without = build_excel_gpt_db_context(
        project_id=86,
        slug="kodak",
        frames=frames,
        characters=[],
    )
    assert "frames_context" not in without
    assert "project_state" not in without

    with_ctx = build_excel_gpt_db_context(
        project_id=86,
        slug="kodak",
        frames=frames,
        characters=[],
        with_scene_context=True,
    )
    assert len(with_ctx["frames_context"]) == 2
    assert with_ctx["project_state"]["scene_last"] == "scene_01"


def test_strip_prompts_keeps_scene_numbering() -> None:
    """Ручной ▶ (strip_prompts) не должен вычищать нумерацию сцен.

    Нумерация — состояние постановки, а не «старый промт»: без неё модель
    не видит уже присвоенные scene_NN и отказывается работать.
    """
    fr = _frame(1, scene="scene_01")
    fr.attrs["image_prompt"] = "старый промт картинки, его копировать нельзя"

    ctx = build_excel_gpt_db_context(
        project_id=86,
        slug="kodak",
        frames=[fr],
        characters=[],
        strip_prompts=True,
        with_scene_context=True,
    )
    row = ctx["frames"][0]
    # Нумерация выжила.
    assert row["shot01_id_scene"] == "scene_01"
    assert row["shot01_number"] == "scene_01_shot_01"
    # А «старый промт картинки» вычищен — как и задумано для ручного ▶.
    assert "image_prompt" not in row


def test_scene_context_has_no_voiceover_bloat() -> None:
    """Контекст — только карта проекта, без закадра (он и так в frames[])."""
    frames = [_frame(1, vo="длинный закадр " * 50)]
    ctx = build_scene_numbering_context(frames)
    assert "voiceover_text" not in ctx["frames_context"][0]
