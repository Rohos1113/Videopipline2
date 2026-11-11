import pytest

from app.services.apply_ops_batches import (
    _frame_complete,
    _pending_frames,
    frames_per_batch,
    pack_call_timeout_s,
    run_apply_ops_batched,
    select_frames_for_batches,
    should_batch_apply_ops,
    split_frames,
)


def test_pack_call_timeout_uses_own_wall_not_gpt_timeout(monkeypatch) -> None:
    """Стена пачки — своя (APPLY_OPS_PACK_CALL_TIMEOUT_S), не GPT_TIMEOUT_S.

    GPT_TIMEOUT_S — потолок на весь чат с ретраями; как стена одной пачки он
    превращал одно падение в 10 минут ожидания.
    """
    from app.settings import settings

    monkeypatch.setattr(settings, "apply_ops_pack_call_timeout_s", 420.0)
    assert pack_call_timeout_s("bits") == 420.0
    assert pack_call_timeout_s("shots_coverage") == 420.0
    assert pack_call_timeout_s("prompts") == 420.0
    monkeypatch.setattr(settings, "apply_ops_pack_call_timeout_s", 30.0)
    assert pack_call_timeout_s("bits") >= 180.0


def test_pack_call_timeout_falls_back_to_gpt_timeout(monkeypatch) -> None:
    """Без своей стены — старое поведение (GPT_TIMEOUT_S, не короче 180с)."""
    from app.settings import settings

    monkeypatch.setattr(settings, "apply_ops_pack_call_timeout_s", 0.0)
    monkeypatch.setattr(settings, "gpt_timeout_s", 600.0)
    assert pack_call_timeout_s("bits") == 600.0
    monkeypatch.setattr(settings, "gpt_timeout_s", 90.0)
    assert pack_call_timeout_s("bits") >= 180.0


def test_dense_32_pending_stays_one_batch() -> None:
    n, raw = 32, 24_000
    size = frames_per_batch(n_frames=n, json_bytes=raw, dense=True, target_batches=5)
    assert size == 32
    assert not should_batch_apply_ops(n_frames=n, json_bytes=raw, dense=True, target_batches=5)


def test_dense_160_is_five_batches() -> None:
    n, raw = 160, 120_000
    size = frames_per_batch(n_frames=n, json_bytes=raw, dense=True, target_batches=5)
    assert size == 32
    assert should_batch_apply_ops(n_frames=n, json_bytes=raw, dense=True, target_batches=5)
    chunks = split_frames(list(range(n)), size)
    assert [len(c) for c in chunks] == [32, 32, 32, 32, 32]


def test_dense_116_frames_split_like_xlsx_v8() -> None:
    n, raw = 116, 97570
    size = frames_per_batch(n_frames=n, json_bytes=raw, dense=True, target_batches=5)
    assert size == 24
    assert should_batch_apply_ops(n_frames=n, json_bytes=raw, dense=True, target_batches=5)
    chunks = split_frames(list(range(n)), size)
    assert [len(c) for c in chunks] == [24, 24, 24, 24, 20]


def test_light_analytics_keeps_116_in_one_call() -> None:
    n, raw = 116, 97570
    size = frames_per_batch(n_frames=n, json_bytes=raw, dense=False)
    assert size >= n
    assert not should_batch_apply_ops(n_frames=n, json_bytes=raw, dense=False)


def test_pending_skips_top_level_shot_fields() -> None:
    frames = [
        {
            "uuid": "a" * 24,
            "voiceover_text": "one",
            "main_action": "x",
            "shot01_description": "y",
        },
        {
            "uuid": "b" * 24,
            "voiceover_text": "two",
        },
    ]
    assert _frame_complete(frames[0], dense=True)
    pending = _pending_frames(frames, dense=True)
    assert [f["uuid"] for f in pending] == ["b" * 24]


def test_dense_retry_skips_filled_and_keeps_one_tail_batch() -> None:
    frames = []
    for i in range(160):
        row = {
            "uuid": f"{i:024d}",
            "voiceover_text": f"vo {i}",
        }
        if i < 129:
            row["main_action"] = "x"
            row["shot01_description"] = "y"
        frames.append(row)
    selected = select_frames_for_batches(frames, dense=True, target_batches=5)
    assert len(selected) == 31
    size = frames_per_batch(n_frames=len(selected), json_bytes=24_000, dense=True, target_batches=5)
    assert size == 31
    chunks = split_frames(selected, size)
    assert [len(c) for c in chunks] == [31]


def test_pending_skips_filled_shot01() -> None:
    frames = [
        {
            "uuid": "a" * 24,
            "voiceover_text": "one",
            "attrs": {"main_action": "x", "shot01_description": "y"},
        },
        {
            "uuid": "b" * 24,
            "voiceover_text": "two",
            "attrs": {},
        },
        {"uuid": "c" * 24, "voiceover_text": "", "attrs": {}},
    ]
    assert _frame_complete(frames[0], dense=True)
    pending = _pending_frames(frames, dense=True)
    assert [f["uuid"] for f in pending] == ["b" * 24]


def test_img_prompt_skip_and_small_batches() -> None:
    n, raw = 40, 80_000
    size = frames_per_batch(n_frames=n, json_bytes=raw, dense=False, skip_if_field="image_prompt")
    assert size <= 8
    assert should_batch_apply_ops(n_frames=n, json_bytes=raw, dense=False, skip_if_field="image_prompt")
    frames = [
        {"uuid": "a" * 24, "voiceover_text": "one", "image_prompt": "already"},
        {"uuid": "b" * 24, "voiceover_text": "two", "image_prompt": ""},
        {"uuid": "c" * 24, "attrs": {"промт_картинки": "old"}},
    ]
    pending = _pending_frames(frames, dense=False, skip_if_field="image_prompt")
    assert [f["uuid"] for f in pending] == ["b" * 24]


def _frame(i: int) -> dict:
    return {
        "uuid": f"{i:024d}",
        "voiceover_text": f"vo {i}",
    }


@pytest.mark.asyncio
async def test_run_apply_ops_dense_splits_104_into_bounded_packs(tmp_path, monkeypatch) -> None:
    """104 кадра НЕ уходят одной пачкой — иначе провайдер отвечает 504.

    Живой случай 11.11 (проект #86, нода «ИИ-редактор сцен 2»): off/low
    отправлял все 104 кадра одним вызовом (144 КБ входа) → 504 → лестница
    1→2→4→8→16 → нода висела 62 минуты. Теперь размер пачки считается по
    лимитам frames_per_batch (dense — 32 кадра / 40 КБ).
    """
    import json

    from app.services.gpt_operator_client import OperatorApiResult

    calls: list[int] = []

    async def fake_run(**kwargs):
        path = kwargs["input_paths"][0]
        frames = json.loads(path.read_text(encoding="utf-8"))["frames"]
        calls.append(len(frames))
        ops = [{"frame_uuid": fr["uuid"], "fields": {"main_action": "x"}} for fr in frames]
        return OperatorApiResult(
            reply_text='{"ops":[]}',
            output_paths=[path],
            apply_ops={"ops": ops},
        )

    monkeypatch.setattr("app.services.apply_ops_batches.run_operator_api", fake_run)
    frames = [_frame(i) for i in range(104)]
    ctx = tmp_path / "db_frames.json"
    ctx.write_text("{}", encoding="utf-8")
    res = await run_apply_ops_batched(
        project_dir=tmp_path,
        node_key="n_excel_gpt_2",
        role="excel_gpt",
        output_mode="project_file",
        prompt="p",
        accompanying="",
        db_ctx={"frames": frames},
        ctx_path=ctx,
        project_id=86,
        dense=True,
    )
    # Ни одна пачка не больше 32 кадров (лимит dense), и их больше одной.
    assert max(calls) <= 32
    assert len(calls) > 1
    assert sum(calls) == 104
    assert len(res.apply_ops["ops"]) == 104


@pytest.mark.asyncio
async def test_run_apply_ops_provider_502_retries_same_pack_without_split(tmp_path, monkeypatch) -> None:
    """Провайдерский 502 → повтор ТОЙ ЖЕ пачки, без дробления.

    Дробить при 502 бессмысленно: лежит провайдер, а не «модель не поняла
    задачу» — на 13 кадрах он вернёт то же самое. Дробление на 502 и было
    причиной 62-минутного вися ноды.
    """
    import json

    from app.services.gpt_operator_client import OperatorApiResult

    calls: list[int] = []
    attempts = {"n": 0}

    async def fake_run(**kwargs):
        path = kwargs["input_paths"][0]
        frames = json.loads(path.read_text(encoding="utf-8"))["frames"]
        calls.append(len(frames))
        attempts["n"] += 1
        if attempts["n"] <= 2:
            raise RuntimeError("GPT HTTP 502: Bad Gateway")
        ops = [{"frame_uuid": fr["uuid"], "fields": {"main_action": "x"}} for fr in frames]
        return OperatorApiResult(
            reply_text='{"ops":[]}',
            output_paths=[path],
            apply_ops={"ops": ops},
        )

    monkeypatch.setattr("app.services.apply_ops_batches.run_operator_api", fake_run)
    monkeypatch.setattr("app.services.apply_ops_batches.PROVIDER_PACK_BACKOFF_S", 0.0)
    frames = [_frame(i) for i in range(30)]
    ctx = tmp_path / "db_frames.json"
    ctx.write_text("{}", encoding="utf-8")
    res = await run_apply_ops_batched(
        project_dir=tmp_path,
        node_key="n_excel_gpt_2",
        role="excel_gpt",
        output_mode="project_file",
        prompt="p",
        accompanying="",
        db_ctx={"frames": frames},
        ctx_path=ctx,
        project_id=86,
        dense=True,
    )
    # Первые две попытки — та же пачка (30 кадров), потом успех той же пачки.
    assert calls[0] == calls[1] == calls[2] == 30
    assert len(res.apply_ops["ops"]) == 30


@pytest.mark.asyncio
async def test_run_apply_ops_provider_502_gives_up_after_retries(tmp_path, monkeypatch) -> None:
    """Провайдер не ожил — честный fail, а не бесконечное дробление."""
    import json

    calls: list[int] = []

    async def fake_run(**kwargs):
        path = kwargs["input_paths"][0]
        frames = json.loads(path.read_text(encoding="utf-8"))["frames"]
        calls.append(len(frames))
        raise RuntimeError("GPT HTTP 502: Bad Gateway")

    monkeypatch.setattr("app.services.apply_ops_batches.run_operator_api", fake_run)
    monkeypatch.setattr("app.services.apply_ops_batches.PROVIDER_PACK_BACKOFF_S", 0.0)
    frames = [_frame(i) for i in range(30)]
    ctx = tmp_path / "db_frames.json"
    ctx.write_text("{}", encoding="utf-8")
    with pytest.raises(RuntimeError, match="502"):
        await run_apply_ops_batched(
            project_dir=tmp_path,
            node_key="n_excel_gpt_2",
            role="excel_gpt",
            output_mode="project_file",
            prompt="p",
            accompanying="",
            db_ctx={"frames": frames},
            ctx_path=ctx,
            project_id=86,
            dense=True,
        )
    # Одна пачка, без дробления; попыток — PROVIDER_PACK_RETRIES + 1.
    assert len(set(calls)) == 1
    assert len(calls) <= 4


@pytest.mark.asyncio
async def test_run_apply_ops_node_deadline_stops_run(tmp_path, monkeypatch) -> None:
    """Дедлайн ноды останавливает прогон, а не даёт висеть часами."""
    import asyncio
    import json

    from app.services.gpt_operator_client import OperatorApiResult

    calls: list[int] = []

    async def fake_run(**kwargs):
        path = kwargs["input_paths"][0]
        frames = json.loads(path.read_text(encoding="utf-8"))["frames"]
        calls.append(len(frames))
        # Каждая пачка «думает» дольше дедлайна — иначе проверка не срабатывает.
        await asyncio.sleep(0.05)
        ops = [{"frame_uuid": fr["uuid"], "fields": {"main_action": "x"}} for fr in frames]
        return OperatorApiResult(
            reply_text='{"ops":[]}',
            output_paths=[path],
            apply_ops={"ops": ops},
        )

    monkeypatch.setattr("app.services.apply_ops_batches.run_operator_api", fake_run)
    monkeypatch.setattr("app.services.apply_ops_batches.apply_ops_node_deadline_s", lambda: 0.01)
    frames = [_frame(i) for i in range(104)]
    ctx = tmp_path / "db_frames.json"
    ctx.write_text("{}", encoding="utf-8")
    with pytest.raises(RuntimeError, match="дедлайн ноды"):
        await run_apply_ops_batched(
            project_dir=tmp_path,
            node_key="n_excel_gpt_2",
            role="excel_gpt",
            output_mode="project_file",
            prompt="p",
            accompanying="",
            db_ctx={"frames": frames},
            ctx_path=ctx,
            project_id=86,
            dense=True,
        )
    # Успеть можно было только первую пачку — дальше дедлайн.
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_run_apply_ops_starts_with_one_batch(tmp_path, monkeypatch) -> None:
    """Успех с первого раза = ровно один LLM-вызов, без дробления.

    32 кадра — ровно лимит dense-пачки, поэтому уходит одним вызовом.
    """
    import json

    from app.services.gpt_operator_client import OperatorApiResult

    calls: list[int] = []

    async def fake_run(**kwargs):
        path = kwargs["input_paths"][0]
        frames = json.loads(path.read_text(encoding="utf-8"))["frames"]
        calls.append(len(frames))
        ops = [{"frame_uuid": fr["uuid"], "fields": {"main_action": "x"}} for fr in frames]
        return OperatorApiResult(
            reply_text='{"ops":[]}',
            output_paths=[path],
            apply_ops={"ops": ops},
        )

    monkeypatch.setattr("app.services.apply_ops_batches.run_operator_api", fake_run)
    frames = [_frame(i) for i in range(32)]
    ctx = tmp_path / "db_frames.json"
    ctx.write_text("{}", encoding="utf-8")
    res = await run_apply_ops_batched(
        project_dir=tmp_path,
        node_key="n_excel_gpt_2",
        role="excel_gpt",
        output_mode="project_file",
        prompt="p",
        accompanying="",
        db_ctx={"frames": frames},
        ctx_path=ctx,
        project_id=1,
        dense=True,
    )
    assert calls == [32]
    assert len(res.apply_ops["ops"]) == 32


@pytest.mark.asyncio
async def test_run_apply_ops_splits_1_to_2_on_error(tmp_path, monkeypatch) -> None:
    """Модельный отказ → пачка делится пополам (1→2)."""
    import json

    from app.services.gpt_operator_client import OperatorApiResult

    calls: list[int] = []

    async def fake_run(**kwargs):
        path = kwargs["input_paths"][0]
        frames = json.loads(path.read_text(encoding="utf-8"))["frames"]
        calls.append(len(frames))
        if len(frames) > 16:
            raise RuntimeError("too big")
        ops = [{"frame_uuid": fr["uuid"], "fields": {"main_action": "x"}} for fr in frames]
        return OperatorApiResult(
            reply_text='{"ops":[]}',
            output_paths=[path],
            apply_ops={"ops": ops},
        )

    monkeypatch.setattr("app.services.apply_ops_batches.run_operator_api", fake_run)
    frames = [_frame(i) for i in range(32)]
    ctx = tmp_path / "db_frames.json"
    ctx.write_text("{}", encoding="utf-8")
    res = await run_apply_ops_batched(
        project_dir=tmp_path,
        node_key="n_excel_gpt_2",
        role="excel_gpt",
        output_mode="project_file",
        prompt="p",
        accompanying="",
        db_ctx={"frames": frames},
        ctx_path=ctx,
        project_id=1,
        dense=True,
    )
    assert calls == [32, 16, 16]
    assert len(res.apply_ops["ops"]) == 32


@pytest.mark.asyncio
async def test_run_apply_ops_splits_2_to_4_on_second_error(tmp_path, monkeypatch) -> None:
    """Полупачка тоже падает → ещё раз пополам (4 куска исходного)."""
    import json

    from app.services.gpt_operator_client import OperatorApiResult

    calls: list[int] = []

    async def fake_run(**kwargs):
        path = kwargs["input_paths"][0]
        frames = json.loads(path.read_text(encoding="utf-8"))["frames"]
        calls.append(len(frames))
        if len(frames) > 8:
            raise RuntimeError("still too big")
        ops = [{"frame_uuid": fr["uuid"], "fields": {"main_action": "x"}} for fr in frames]
        return OperatorApiResult(
            reply_text='{"ops":[]}',
            output_paths=[path],
            apply_ops={"ops": ops},
        )

    monkeypatch.setattr("app.services.apply_ops_batches.run_operator_api", fake_run)
    frames = [_frame(i) for i in range(32)]
    ctx = tmp_path / "db_frames.json"
    ctx.write_text("{}", encoding="utf-8")
    res = await run_apply_ops_batched(
        project_dir=tmp_path,
        node_key="n_excel_gpt_2",
        role="excel_gpt",
        output_mode="project_file",
        prompt="p",
        accompanying="",
        db_ctx={"frames": frames},
        ctx_path=ctx,
        project_id=1,
        dense=True,
    )
    # 32 fail → 16+16, каждая 16 fail → 8+8
    assert calls == [32, 16, 8, 8, 16, 8, 8]
    assert len(res.apply_ops["ops"]) == 32


@pytest.mark.asyncio
async def test_run_apply_ops_medium_reasoning_batches_16(tmp_path, monkeypatch) -> None:
    """В режиме medium reasoning 104 кадра режутся на пачки по 16, чтобы не виснуть на 300с."""
    import json

    from app.services.gpt_operator_client import OperatorApiResult
    from app.services.llm_override import NodeLlmOverride, use_override

    calls: list[int] = []

    async def fake_run(**kwargs):
        path = kwargs["input_paths"][0]
        frames = json.loads(path.read_text(encoding="utf-8"))["frames"]
        calls.append(len(frames))
        ops = [{"frame_uuid": fr["uuid"], "fields": {"main_action": "x"}} for fr in frames]
        return OperatorApiResult(
            reply_text='{"ops":[]}',
            output_paths=[path],
            apply_ops={"ops": ops},
        )

    monkeypatch.setattr("app.services.apply_ops_batches.run_operator_api", fake_run)
    frames = [_frame(i) for i in range(104)]
    ctx = tmp_path / "db_frames.json"
    ctx.write_text("{}", encoding="utf-8")
    ov = NodeLlmOverride(
        model_id="gpt-6.1-sol",
        channel="stable",
        kind="text",
        provider="52pay",
        label="GPT 6.1 Sol",
        reasoning_effort="medium",
    )
    with use_override(ov):
        res = await run_apply_ops_batched(
            project_dir=tmp_path,
            node_key="n_excel_gpt_2",
            role="excel_gpt",
            output_mode="project_file",
            prompt="p",
            accompanying="",
            db_ctx={"frames": frames},
            ctx_path=ctx,
            project_id=86,
            dense=True,
        )
    # 104 = 6*16 + 8
    assert calls == [16, 16, 16, 16, 16, 16, 8]
    assert len(res.apply_ops["ops"]) == 104


@pytest.mark.asyncio
async def test_run_apply_ops_high_reasoning_batches_10(tmp_path, monkeypatch) -> None:
    """В режиме high/xhigh reasoning кадры режутся на пачки по 10."""
    import json

    from app.services.gpt_operator_client import OperatorApiResult
    from app.services.llm_override import NodeLlmOverride, use_override

    calls: list[int] = []

    async def fake_run(**kwargs):
        path = kwargs["input_paths"][0]
        frames = json.loads(path.read_text(encoding="utf-8"))["frames"]
        calls.append(len(frames))
        ops = [{"frame_uuid": fr["uuid"], "fields": {"main_action": "x"}} for fr in frames]
        return OperatorApiResult(
            reply_text='{"ops":[]}',
            output_paths=[path],
            apply_ops={"ops": ops},
        )

    monkeypatch.setattr("app.services.apply_ops_batches.run_operator_api", fake_run)
    frames = [_frame(i) for i in range(35)]
    ctx = tmp_path / "db_frames.json"
    ctx.write_text("{}", encoding="utf-8")
    ov = NodeLlmOverride(
        model_id="gpt-6.1-sol",
        channel="stable",
        kind="text",
        provider="52pay",
        label="GPT 6.1 Sol",
        reasoning_effort="high",
    )
    with use_override(ov):
        res = await run_apply_ops_batched(
            project_dir=tmp_path,
            node_key="n_excel_gpt_2",
            role="excel_gpt",
            output_mode="project_file",
            prompt="p",
            accompanying="",
            db_ctx={"frames": frames},
            ctx_path=ctx,
            project_id=86,
            dense=True,
        )
    # 35 = 10 + 10 + 10 + 5
    assert calls == [10, 10, 10, 5]
    assert len(res.apply_ops["ops"]) == 35
