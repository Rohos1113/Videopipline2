"""H3: отказ модели из-за неполного входа — не ремонтируется и не повторяется.

Живой случай (#86, 11.11): модель ответила отказом (конверт без ops +
``error``), контракт считал это «пустым ops» и платил за repair-ретраи; тот
же вход давал тот же отказ, а в ноде вместо причины светилась «Неизвестная
ошибка».

Теперь отказ из-за неполного входа — отдельная ошибка (``kind="refusal"``):
без платного repair-ретрая, с понятным кодом в каталоге ошибок. Отказы
другого рода (модель ошиблась, перепутала формат) остаются ремонтируемыми —
repair-промпт даёт ей другой текст запроса, и она часто отвечает нормально.
"""

from __future__ import annotations

import pytest

from app.contracts import APPLY_OPS, LlmContractError
from app.contracts.apply_ops import apply_ops_input_refusal, apply_ops_refusal
from app.contracts.policy import run_with_contract
from app.services.error_catalog import describe_error

REFUSAL = '{"error":"missing_global_context","message":"Переданы только кадры 27–56 и список UUID проекта."}'
OK = '{"ops":[{"frame_uuid":"u1","fields":{"закадр":"текст"}}]}'
# Отказ не про вход: repair-промпт тут помогает (промт без xlsx).
OTHER_REFUSAL = '{"ops":[],"characters":[],"error":"Бинарный файл project.xlsx недоступен в рабочей среде"}'


def test_refusal_is_detected() -> None:
    reason = apply_ops_refusal({"error": "missing_global_context", "message": "Переданы только кадры 27–56."})
    assert reason == "missing_global_context: Переданы только кадры 27–56."


def test_data_present_is_not_refusal() -> None:
    """Отчёт/пояснение при обычном ответе отказом не считается."""
    assert apply_ops_refusal({"ops": [{"frame_uuid": "u1", "fields": {"место": "кухня"}}]}) == ""
    assert apply_ops_refusal({"ops": [], "error": ""}) == ""


def test_provider_error_object_is_not_refusal() -> None:
    """``error``-объект — это провайдерская ошибка в теле 200, а не отказ модели."""
    assert apply_ops_refusal({"error": {"message": "服务暂时没有响应"}}) == ""


def test_only_input_refusal_is_unrepairable() -> None:
    """Отказ «входа не хватило» — не ремонтируем; остальные — ремонтируемы."""
    assert apply_ops_input_refusal({"error": "missing_global_context"})
    assert apply_ops_input_refusal({"error": "Не удалось подготовить операции: нет реальных frame_uuid"})
    assert apply_ops_input_refusal({"error": OTHER_REFUSAL}) == ""


def test_contract_parse_raises_refusal() -> None:
    with pytest.raises(LlmContractError) as ei:
        APPLY_OPS.parse(REFUSAL)
    err = ei.value
    assert err.kind == "refusal"
    assert "missing_global_context" in str(err)


def test_other_refusal_stays_repairable() -> None:
    """Отказ не про вход — обычный брак формата: его чинит repair-промпт."""
    with pytest.raises(LlmContractError) as ei:
        APPLY_OPS.parse(OTHER_REFUSAL)
    assert ei.value.kind != "refusal"


@pytest.mark.asyncio
async def test_policy_does_not_repair_refusal(tmp_path) -> None:
    """Отказ не ремонтируется: один вызов модели, без repair-попытки."""
    calls: list[str | None] = []

    async def call(feedback: str | None) -> str:
        calls.append(feedback)
        return REFUSAL

    with pytest.raises(LlmContractError) as ei:
        await run_with_contract(
            contract=APPLY_OPS,
            call=call,
            reject_dir=tmp_path,
            label="apply_ops_n_excel_gpt_2",
        )
    err = ei.value
    assert err.kind == "refusal"
    assert len(calls) == 1, "отказ не должен оплачиваться повторным вызовом"
    assert "missing_global_context" in str(err)
    # Отклонённый ответ сохранён на диск — причина видна в llm_rejects.
    rejects = list(tmp_path.glob("*.txt"))
    assert len(rejects) == 1
    assert "missing_global_context" in rejects[0].read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_empty_ops_without_refusal_is_still_repaired() -> None:
    """Пустой ops без объяснения — обычный брак формата, его ремонтируем."""
    seen: list[str | None] = []

    async def call(feedback: str | None) -> str:
        seen.append(feedback)
        return '{"ops":[]}' if len(seen) == 1 else OK

    res = await run_with_contract(contract=APPLY_OPS, call=call)
    assert res.attempts == 2 and res.repairs == 1


def test_error_catalog_code() -> None:
    """В ноде — причина, а не «Неизвестная ошибка»."""
    with pytest.raises(LlmContractError) as ei:
        APPLY_OPS.parse(REFUSAL)
    code, message = describe_error(ei.value)
    assert code == "llm_model_refusal"
    assert "missing_global_context" in message
