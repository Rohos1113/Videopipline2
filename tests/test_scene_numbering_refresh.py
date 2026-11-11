"""PR 3: свежесть контекста нумерации между пачками.

Контекст нумерации сцен (``frames_context`` + ``project_state``) собирается
ОДИН раз до всех пачек. Без обновления пачка N+1 не видит ``scene_NN``,
присвоенные пачкой N: модель считает, что проект начинается, и нумерует
сцены заново (или отвечает «missing_global_context»).

Проверяем:
* пересборку контекста по свежим данным из БД (номер растёт, кадры те же);
* что пачка 2 в батч-файле видит нумерацию пачки 1;
* что ``cluster`` попадает в контекст (промт читает его для continuity).
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.services.db_frames_context import (
    build_excel_gpt_db_context,
    build_scene_numbering_context,
    rebuild_scene_numbering_context,
)


def _frame(number: int, *, scene: str = "", vo: str = "Закадр", cluster: str = "") -> SimpleNamespace:
    attrs: dict[str, str] = {"place": "Дом", "scene_sense": "Смысл"}
    if cluster:
        attrs["cluster"] = cluster
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


def _ctx(frames) -> dict:
    return build_excel_gpt_db_context(
        project_id=86,
        slug="kodak",
        frames=frames,
        characters=[],
        with_scene_context=True,
    )


def test_rebuild_picks_up_new_scene_ids() -> None:
    """После применённой пачки пересборка видит новые id_scene и новый scene_last."""
    frames = [_frame(i, scene=f"scene_{i:02d}" if i <= 26 else "") for i in range(1, 105)]
    ctx = _ctx(frames)

    assert ctx["project_state"]["scene_last"] == "scene_26"
    assert ctx["project_state"]["scenes_assigned"] == 26

    # Пачка 1 отработала: кадры 27–56 получили свои сцены.
    for i in range(27, 57):
        frames[i - 1].attrs["shot01_id_scene"] = f"scene_{i:02d}"
        frames[i - 1].attrs["shot01_number"] = f"scene_{i:02d}_shot_01"

    changed = rebuild_scene_numbering_context(ctx, frames)

    assert changed is True
    assert ctx["project_state"]["scene_last"] == "scene_56"
    assert ctx["project_state"]["scenes_assigned"] == 56
    # Кадры 27–56 теперь видны в контексте с номерами.
    numbered = [r for r in ctx["frames_context"] if r.get("id_scene")]
    assert len(numbered) == 56
    assert numbered[-1]["id_scene"] == "scene_56"
    # Состав кадров прежний — пересобираются значения, не состав.
    assert len(ctx["frames_context"]) == 104


def test_rebuild_keeps_order_and_uuids() -> None:
    """Порядок и состав контекста не меняются — меняются только значения."""
    frames = [_frame(i, scene=f"scene_{i:02d}" if i <= 26 else "") for i in range(1, 105)]
    ctx = _ctx(frames)
    before = [(r["number"], r["uuid"]) for r in ctx["frames_context"]]

    for i in range(27, 57):
        frames[i - 1].attrs["shot01_id_scene"] = f"scene_{i:02d}"

    rebuild_scene_numbering_context(ctx, frames)

    after = [(r["number"], r["uuid"]) for r in ctx["frames_context"]]
    assert after == before


def test_rebuild_without_scene_context_is_noop() -> None:
    """Нода без нумерации сцен: контекста нет — пересборка ничего не делает."""
    ctx = build_excel_gpt_db_context(
        project_id=86,
        slug="kodak",
        frames=[_frame(1)],
        characters=[],
    )
    assert "frames_context" not in ctx
    assert rebuild_scene_numbering_context(ctx, [_frame(1, scene="scene_01")]) is False


def test_cluster_travels_in_context() -> None:
    """Номер кластера едет в контекст — промт читает его для continuity."""
    frames = [_frame(1, scene="scene_01", cluster="7"), _frame(2, cluster="8")]
    ctx = build_scene_numbering_context(frames)

    assert ctx["frames_context"][0]["cluster"] == "7"
    assert ctx["frames_context"][1]["cluster"] == "8"


def test_rebuild_updates_cluster_too() -> None:
    """Пересборка обновляет не только id_scene, но и кластер."""
    frames = [_frame(1, scene="scene_01", cluster="1"), _frame(2)]
    ctx = _ctx(frames)
    assert ctx["frames_context"][0]["cluster"] == "1"

    frames[0].attrs["cluster"] = "3"

    rebuild_scene_numbering_context(ctx, frames)

    assert ctx["frames_context"][0]["cluster"] == "3"


@pytest.mark.asyncio
async def test_second_pack_sees_first_pack_numbering(tmp_path, monkeypatch) -> None:
    """Пачка 2 получает в батч-файле нумерацию, присвоенную пачкой 1.

    Это и есть суть бага: без refresh вторая пачка видела бы
    ``scene_last = scene_26`` (снимок от начала ноды) и начинала бы
    нумерацию заново.

    Сценарий повторяет #86: 26 кадров уже пронумерованы и заполнены
    (в pending не попадают), остальные 78 ждут — они и режутся на пачки.
    """
    import json

    from app.services.gpt_operator_client import OperatorApiResult

    seen: list[dict] = []

    async def fake_run(**kwargs):
        path = kwargs["input_paths"][0]
        payload = json.loads(path.read_text(encoding="utf-8"))
        seen.append(payload)
        frames = payload["frames"]
        # Модель продолжает сквозную нумерацию: сцена = номер кадра.
        ops = [
            {"frame_uuid": fr["uuid"], "fields": {"id_scene": f"scene_{fr['number']:02d}"}}
            for fr in frames
        ]
        return OperatorApiResult(
            reply_text='{"ops":[]}',
            output_paths=[path],
            apply_ops={"ops": ops},
        )

    monkeypatch.setattr("app.services.apply_ops_batches.run_operator_api", fake_run)

    frames = []
    for i in range(1, 105):
        fr = _frame(i, scene=f"scene_{i:02d}" if i <= 26 else "")
        if i <= 26:
            # Готовый кадр: заполненные shot-поля → в pending не попадает.
            fr.attrs["main_action"] = "Действие"
            fr.attrs["shot01_description"] = "Описание"
        frames.append(fr)
    ctx = _ctx(frames)

    from app.services.apply_ops_batches import run_apply_ops_batched

    ctx_path = tmp_path / "db_frames.json"
    ctx_path.write_text("{}", encoding="utf-8")

    async def apply_fn(payload: dict) -> None:
        """Имитация apply: пишем id_scene в attrs кадров (как db_apply)."""
        for op in payload.get("ops") or []:
            for fr in frames:
                if fr.uuid == op["frame_uuid"]:
                    scene = str((op.get("fields") or {}).get("id_scene") or "")
                    fr.attrs["shot01_id_scene"] = scene
                    fr.attrs["shot01_number"] = f"{scene}_shot_01"
                    break

    async def refresh_ctx_fn(target: dict) -> None:
        """Колбэк раннера: пересобрать контекст из «БД» (здесь — из frames)."""
        rebuild_scene_numbering_context(target, frames)

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
        apply_fn=apply_fn,
        refresh_ctx_fn=refresh_ctx_fn,
    )

    assert len(seen) >= 2, "ожидались минимум две пачки"
    # Первая пачка — снимок от начала ноды: последняя сцена scene_26.
    assert seen[0]["project_state"]["scene_last"] == "scene_26"
    assert seen[0]["project_state"]["scenes_assigned"] == 26

    # Вторая пачка обязана видеть нумерацию первой: scene_last = max из пачки 1.
    first_numbers = [fr["number"] for fr in seen[0]["frames"]]
    expected_last = f"scene_{max(first_numbers):02d}"
    assert seen[1]["project_state"]["scene_last"] == expected_last
    assert seen[1]["project_state"]["scenes_assigned"] == 26 + len(first_numbers)


@pytest.mark.asyncio
async def test_without_refresh_second_pack_sees_stale_context(tmp_path, monkeypatch) -> None:
    """Контроль: без refresh вторая пачка видит УСТАРЕВШИЙ контекст.

    Это и есть баг, который чинит PR 3. Если этот тест перестанет падать —
    значит refresh где-то подменяет (и надо разбираться, почему).
    """
    import json

    from app.services.gpt_operator_client import OperatorApiResult

    seen: list[dict] = []

    async def fake_run(**kwargs):
        path = kwargs["input_paths"][0]
        payload = json.loads(path.read_text(encoding="utf-8"))
        seen.append(payload)
        frames = payload["frames"]
        ops = [
            {"frame_uuid": fr["uuid"], "fields": {"id_scene": f"scene_{fr['number']:02d}"}}
            for fr in frames
        ]
        return OperatorApiResult(
            reply_text='{"ops":[]}',
            output_paths=[path],
            apply_ops={"ops": ops},
        )

    monkeypatch.setattr("app.services.apply_ops_batches.run_operator_api", fake_run)

    frames = []
    for i in range(1, 105):
        fr = _frame(i, scene=f"scene_{i:02d}" if i <= 26 else "")
        if i <= 26:
            fr.attrs["main_action"] = "Действие"
            fr.attrs["shot01_description"] = "Описание"
        frames.append(fr)
    ctx = _ctx(frames)

    from app.services.apply_ops_batches import run_apply_ops_batched

    ctx_path = tmp_path / "db_frames.json"
    ctx_path.write_text("{}", encoding="utf-8")

    async def apply_fn(payload: dict) -> None:
        for op in payload.get("ops") or []:
            for fr in frames:
                if fr.uuid == op["frame_uuid"]:
                    scene = str((op.get("fields") or {}).get("id_scene") or "")
                    fr.attrs["shot01_id_scene"] = scene
                    fr.attrs["shot01_number"] = f"{scene}_shot_01"
                    break

    # БЕЗ refresh_ctx_fn — контекст остаётся от начала ноды.
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
        apply_fn=apply_fn,
    )

    assert len(seen) >= 2
    # Вторая пачка видит ту же scene_26 — нумерация пачки 1 ей не видна.
    assert seen[1]["project_state"]["scene_last"] == "scene_26"
    assert seen[1]["project_state"]["scenes_assigned"] == 26
