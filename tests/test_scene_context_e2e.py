"""E2E: что реально уходит в батч-файл для ноды с глобальной нумерацией.

Проверяем цепочку: build_excel_gpt_db_context(with_scene_context=True)
→ run_apply_ops_batched → файл db_frames_batch_*.json на диске.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.services.db_frames_context import build_excel_gpt_db_context


def _frame(number: int, *, scene: str = "", vo: str = "текст") -> SimpleNamespace:
    attrs: dict[str, str] = {"place": "цех", "scene_sense": "смысл"}
    if scene:
        attrs["shot01_id_scene"] = scene
        attrs["shot01_number"] = f"{scene}_shot_01"
        attrs["shot01_id_shot"] = "shot_01"
    return SimpleNamespace(
        number=number,
        uuid=f"uuid-{number:03d}",
        voiceover_text=vo,
        meaning="",
        animation_prompt="",
        image_prompt="",
        attrs=attrs,
    )


@pytest.mark.asyncio
async def test_batch_file_carries_scene_context(tmp_path, monkeypatch) -> None:
    """В батч-файле есть frames_context + project_state, и модель их видит."""
    from app.services.gpt_operator_client import OperatorApiResult

    seen: dict = {}

    async def fake_run(**kwargs):
        path = kwargs["input_paths"][0]
        payload = json.loads(path.read_text(encoding="utf-8"))
        seen.update(payload)
        seen["_accompanying"] = kwargs["accompanying"]
        frames = payload["frames"]
        ops = [{"frame_uuid": fr["uuid"], "fields": {"id_scene": "scene_27"}} for fr in frames]
        return OperatorApiResult(
            reply_text='{"ops":[]}',
            output_paths=[path],
            apply_ops={"ops": ops},
        )

    monkeypatch.setattr("app.services.apply_ops_batches.run_operator_api", fake_run)

    frames = [_frame(i, scene=f"scene_{i:02d}" if i <= 26 else "") for i in range(1, 105)]
    ctx = build_excel_gpt_db_context(
        project_id=86,
        slug="kodak",
        frames=frames,
        characters=[],
        with_scene_context=True,
    )

    from app.services.apply_ops_batches import run_apply_ops_batched

    ctx_path = tmp_path / "db_frames.json"
    ctx_path.write_text("{}", encoding="utf-8")
    await run_apply_ops_batched(
        project_dir=tmp_path,
        node_key="n_excel_gpt_2",
        role="excel_gpt",
        output_mode="project_file",
        prompt="p",
        accompanying="",
        db_ctx=ctx,
        ctx_path=ctx_path,
        project_id=86,
        dense=True,
    )

    # Контекст проекта в батч-файле есть.
    assert "frames_context" in seen
    assert "project_state" in seen
    # Модель видит ID соседей: первые 26 кадров пронумерованы.
    numbered = [r for r in seen["frames_context"] if r.get("id_scene")]
    assert len(numbered) == 26
    assert numbered[0]["id_scene"] == "scene_01"
    assert numbered[-1]["id_scene"] == "scene_26"
    # Сводка по проекту — для границ нумерации.
    assert seen["project_state"]["frames_total"] == 104
    assert seen["project_state"]["scene_last"] == "scene_26"
    # Футер объясняет модели, что frames_context — только чтение.
    assert "frames_context" in seen["_accompanying"]
    assert "ТОЛЬКО ДЛЯ ЧТЕНИЯ" in seen["_accompanying"]


def test_batch_file_size_stays_reasonable() -> None:
    """Контекст не раздувает вход: карта проекта — без закадра."""
    frames = [_frame(i, scene=f"scene_{i:02d}" if i <= 26 else "") for i in range(1, 105)]
    ctx = build_excel_gpt_db_context(
        project_id=86,
        slug="kodak",
        frames=frames,
        characters=[],
        with_scene_context=True,
    )
    ctx_bytes = len(json.dumps(ctx, ensure_ascii=False).encode("utf-8"))
    ctx_no = build_excel_gpt_db_context(
        project_id=86,
        slug="kodak",
        frames=frames,
        characters=[],
    )
    base_bytes = len(json.dumps(ctx_no, ensure_ascii=False).encode("utf-8"))
    # Контекст — процент от входа, а не удвоение.
    assert ctx_bytes < base_bytes * 1.6, (ctx_bytes, base_bytes)


def test_batch_file_written_to_disk(tmp_path) -> None:
    """Файлы батчей на диске содержат контекст (для отладки вручную)."""
    frames = [_frame(1, scene="scene_01")]
    ctx = build_excel_gpt_db_context(
        project_id=86,
        slug="kodak",
        frames=frames,
        characters=[],
        with_scene_context=True,
    )
    p = tmp_path / "db_frames.json"
    p.write_text(json.dumps(ctx, ensure_ascii=False, indent=2), encoding="utf-8")
    data = json.loads(Path(p).read_text(encoding="utf-8"))
    assert data["frames_context"][0]["id_scene"] == "scene_01"
