"""Приоритет плановых (проектных) LLM-вызовов над ручными (adhoc).

Зачем. Ручной тест промта из UI (вне конвейера) идёт в того же провайдера,
что и работающая нода. 11.11 на VPS таких вызовов было 12 за день, и они шли
ПАРАЛЛЕЛЬНО с нодой: шлюз 52pay деградировал (успех → 504 → успех), и
страдала нода — она стояла в очереди к общему ключу.

Как. Плановые вызовы (у них есть учётный контекст проекта) идут без ожидания.
Ручные (вне обвязки шага) — встают в очередь, пока плановый вызов в полёте,
и уходят с внятным отказом, если очередь не рассасывается за отведённое
время. Плановые вызовы при этом НЕ ждут никогда: приоритет — односторонний,
нода не может встать из-за ручного теста.

Отказ — не «молчалка»: ручной вызов получает ``LlmPriorityBusy`` с текстом,
который видно в UI. Дефолт — фича выключена (``LLM_PRIORITY_ENABLED=0``),
поведение не меняется, пока владелец её не включит.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

from loguru import logger

from app.services.llm_override import current_accounting

#: Активные плановые вызовы (идут сейчас). Ручные ждут, пока их нет.
#:
#: Счётчик намеренно без asyncio.Lock: он живёт в одном event loop, а между
#: чтением и записью нет await — гонки невозможны. Lock здесь был бы
#: привязан к первому loop, который его коснулся, и ломал бы тесты (у
#: каждого теста свой loop).
_planar_active: int = 0


class LlmPriorityBusy(RuntimeError):
    """Ручной вызов не дождался, пока освободится провайдер.

    Отказ, а не таймаут: пользователь видит причину и может повторить позже.
    """


def is_planar_call() -> bool:
    """Плановый ли это вызов (есть привязка к проекту)?

    Плановым считается вызов внутри обвязки шага (``bind_project_llm`` ставит
    учётный контекст). Всё остальное — ручное: тест промта, чат студии,
    воркспейс.
    """
    acct = current_accounting()
    return acct is not None and acct.project_id is not None


async def wait_for_provider_idle(timeout_s: float) -> None:
    """Дождаться, пока плановых вызовов не останется.

    Вызывается ручными вызовами. Ничего не делает, если плановых вызовов
    нет — ручной тест не должен ждать понапрасну.
    """
    if timeout_s <= 0:
        return
    deadline = asyncio.get_running_loop().time() + timeout_s
    waited = False
    while True:
        if _planar_active == 0:
            break
        if not waited:
            waited = True
            logger.info(
                "llm_priority: ручной вызов ждёт, пока идут плановые ({} активн.)",
                _planar_active,
            )
        if asyncio.get_running_loop().time() >= deadline:
            raise LlmPriorityBusy(
                "Плановый шаг сейчас работает и занимает провайдера. "
                "Тестовый запрос отложен — повторите после окончания шага."
            )
        await asyncio.sleep(0.5)


def _planar_enter() -> None:
    global _planar_active
    _planar_active += 1


def _planar_exit() -> None:
    global _planar_active
    if _planar_active > 0:
        _planar_active -= 1


class PriorityGate:
    """Контекстный менеджер: плановый вызов занимает провайдера.

    Ручные вызовы (см. ``wait_for_provider_idle``) ждут, пока активных
    плановых вызовов не останется. Плановые не ждут никогда.
    """

    def __init__(self, *, enabled: bool = True, timeout_s: float = 30.0) -> None:
        self._enabled = enabled
        self._timeout_s = timeout_s
        self._planar = False

    async def __aenter__(self) -> PriorityGate:
        if not self._enabled:
            return self
        self._planar = is_planar_call()
        if self._planar:
            _planar_enter()
        else:
            await wait_for_provider_idle(self._timeout_s)
        return self

    async def __aexit__(self, *exc: object) -> None:
        if self._enabled and self._planar:
            _planar_exit()
        self._planar = False


async def with_priority(
    fn: Callable[[], Awaitable],
    *,
    enabled: bool,
    timeout_s: float,
):
    """Выполнить ``fn`` под гейтом приоритета.

    Ручной вызов ждёт конца плановых; плановый — не ждёт ничего.
    """
    async with PriorityGate(enabled=enabled, timeout_s=timeout_s):
        return await fn()
