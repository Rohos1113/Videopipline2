"""H3: явная проверка входов ноды «ИИ-редактор сцен» ДО вызова модели.

Живой случай (#86, 11.11): нода собрала неполный payload и позвала модель —
модель честно отказалась («missing_global_context»), контракт отклонил ответ,
и шаг ушёл в длинные ПЛАТНЫЕ ретраи вместо внятной причины.

Проверка обязана ловить пустой/неполный вход до платного вызова и говорить,
что делать.
"""

from __future__ import annotations

import pytest

from app.orchestrator.steps.enrich_xlsx import require_excel_gpt_inputs
from app.services.error_catalog import describe_error

VO_FRAME = {"number": 1, "uuid": "u1", "voiceover_text": "Он вошёл в комнату."}
SCENE_CTX = [{"number": 1, "uuid": "u1", "id_scene": "scene_01"}]


def _ctx(frames: list[dict] | None, **extra: object) -> dict:
    ctx: dict = {"frames": frames if frames is not None else []}
    ctx.update(extra)
    return ctx


def test_empty_payload_fails_before_model() -> None:
    with pytest.raises(RuntimeError) as ei:
        require_excel_gpt_inputs(project_id=86, node_key="n_excel_gpt_2", db_ctx=_ctx([]))
    msg = str(ei.value)
    assert "excel_gpt: нет входа" in msg
    assert "кадра" in msg


def test_frames_without_voiceover_fail() -> None:
    """Кадры есть, но описывать нечего — модель ответит пустым ops."""
    with pytest.raises(RuntimeError) as ei:
        require_excel_gpt_inputs(
            project_id=86,
            node_key="n_excel_gpt_2",
            db_ctx=_ctx([{"number": 1, "uuid": "u1", "voiceover_text": ""}]),
        )
    assert "excel_gpt: нет входа" in str(ei.value)
    assert "закадр" in str(ei.value)


def test_meaning_is_enough_content() -> None:
    """Смысл кадра — тоже исходный материал для сцены."""
    require_excel_gpt_inputs(
        project_id=86,
        node_key="n_excel_gpt_2",
        db_ctx=_ctx([{"number": 1, "uuid": "u1", "voiceover_text": "", "meaning": "герой"}]),
    )


def test_qc_node_may_have_no_voiceover() -> None:
    """QC-нода проверяет готовую сцену — закадр ей не требуется."""
    require_excel_gpt_inputs(
        project_id=86,
        node_key="n_excel_gpt_2_qc",
        db_ctx=_ctx([{"number": 1, "uuid": "u1", "voiceover_text": ""}]),
        needs_voiceover=False,
    )


def test_missing_scene_context_fails() -> None:
    """Без контекста проекта модель отвечает «missing_global_context»."""
    with pytest.raises(RuntimeError) as ei:
        require_excel_gpt_inputs(
            project_id=86,
            node_key="n_excel_gpt_2",
            db_ctx=_ctx([VO_FRAME]),
            needs_scene_context=True,
        )
    msg = str(ei.value)
    assert "excel_gpt: нет входа" in msg
    assert "frames_context" in msg


def test_scene_context_present_passes() -> None:
    require_excel_gpt_inputs(
        project_id=86,
        node_key="n_excel_gpt_2",
        db_ctx=_ctx([VO_FRAME], frames_context=SCENE_CTX),
        needs_scene_context=True,
    )


def test_valid_payload_passes() -> None:
    require_excel_gpt_inputs(
        project_id=86,
        node_key="n_excel_gpt_2",
        db_ctx=_ctx([VO_FRAME], frames_context=SCENE_CTX),
    )


def test_error_has_own_code() -> None:
    """Причина видна в ноде, а не «Неизвестная ошибка»."""
    with pytest.raises(RuntimeError) as ei:
        require_excel_gpt_inputs(project_id=86, node_key="n_excel_gpt_2", db_ctx=_ctx([]))
    code, message = describe_error(ei.value)
    assert code == "excel_gpt_no_input"
    assert "excel_gpt: нет входа" in message
