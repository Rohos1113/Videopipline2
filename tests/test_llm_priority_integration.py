"""Гейт приоритета в реальном транспорте: ручной вызов уступает плановому.

Проверяем сквозной путь (не только модуль гейта): ``gpt_api.chat`` →
``_record_transport_call`` → гейт. Ручной вызов (вне обвязки шага) должен
получить отказ, пока плановый вызов держит провайдера; плановый — пройти
без ожидания.
"""

from __future__ import annotations

import asyncio

import httpx
import pytest

from app.services import gpt_api, llm_priority
from app.services.llm_override import LlmAccountingContext, use_accounting


@pytest.fixture(autouse=True)
def _reset_gate() -> None:
    llm_priority._planar_active = 0


def _enable(monkeypatch) -> None:
    from app.settings import settings

    monkeypatch.setattr(settings, "text_llm_provider", "kie")
    monkeypatch.setattr(settings, "gpt_api_key", "test-key")
    monkeypatch.setattr(settings, "gpt_base_url", "https://gw.test")
    monkeypatch.setattr(settings, "gpt_chat_path", "/v1/chat/completions")
    monkeypatch.setattr(settings, "gpt_api_mode", "chat")
    monkeypatch.setattr(settings, "gpt_max_retries", 0)
    monkeypatch.setattr(settings, "gpt_proxy_url", None)
    monkeypatch.setattr(settings, "llm_priority_enabled", True)
    monkeypatch.setattr(settings, "llm_priority_wait_s", 0.3)
    monkeypatch.setattr(gpt_api, "_PROXY_LOGGED", False)


def _mock_httpx(monkeypatch, handler) -> None:
    real_client = httpx.AsyncClient

    def factory(*args, **kwargs):
        kwargs.pop("proxy", None)
        kwargs["transport"] = httpx.MockTransport(handler)
        kwargs["trust_env"] = False
        return real_client(*args, **kwargs)

    monkeypatch.setattr(gpt_api.httpx, "AsyncClient", factory)


def _completion(text: str) -> dict:
    return {
        "choices": [{"message": {"content": text}, "finish_reason": "stop"}],
        "usage": {"total_tokens": 10},
    }


@pytest.mark.asyncio
async def test_adhoc_call_is_refused_while_planar_runs(monkeypatch) -> None:
    """Ручной вызов во время планового — внятный отказ, а не таймаут."""
    _enable(monkeypatch)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_completion("ok"))

    _mock_httpx(monkeypatch, handler)

    # Плановый вызов держит провайдера.
    llm_priority._planar_enter()
    try:
        with pytest.raises(llm_priority.LlmPriorityBusy) as exc:
            await gpt_api.chat(prompt="ручной тест", auto_pack=False)
        assert "отложен" in str(exc.value)
    finally:
        llm_priority._planar_exit()


@pytest.mark.asyncio
async def test_planar_call_passes_while_another_planar_runs(monkeypatch) -> None:
    """Плановый вызов проходит без ожидания, даже если плановый уже в полёте."""
    _enable(monkeypatch)
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json=_completion("ok"))

    _mock_httpx(monkeypatch, handler)

    llm_priority._planar_enter()
    try:
        acct = LlmAccountingContext(project_id=86, node_key="n_excel_gpt_2")
        with use_accounting(acct):
            res = await gpt_api.chat(prompt="плановый", auto_pack=False)
        assert res.text == "ok"
        assert len(calls) == 1
    finally:
        llm_priority._planar_exit()


@pytest.mark.asyncio
async def test_priority_disabled_keeps_old_behaviour(monkeypatch) -> None:
    """Фича выключена — ручной вызов проходит, как раньше."""
    from app.settings import settings

    _enable(monkeypatch)
    monkeypatch.setattr(settings, "llm_priority_enabled", False)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_completion("ok"))

    _mock_httpx(monkeypatch, handler)

    llm_priority._planar_enter()
    try:
        res = await gpt_api.chat(prompt="ручной тест", auto_pack=False)
        assert res.text == "ok"
    finally:
        llm_priority._planar_exit()


@pytest.mark.asyncio
async def test_adhoc_call_passes_when_nothing_planar_runs(monkeypatch) -> None:
    """Никого нет — ручной вызов идёт сразу (гейт не добавляет задержки)."""
    _enable(monkeypatch)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_completion("ok"))

    _mock_httpx(monkeypatch, handler)

    res = await asyncio.wait_for(
        gpt_api.chat(prompt="ручной тест", auto_pack=False),
        timeout=10,
    )
    assert res.text == "ok"
