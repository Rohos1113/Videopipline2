"""Фикс slug-бага: проверка уникальности slug — ВНЕ RLS.

Индекс ``ix_projects_slug`` уникален ГЛОБАЛЬНО (не по тенанту), а политика
``tenant_isolation`` прячет чужие проекты. Без снятия RLS проверка не видит
занятый slug → вставка падает на ``UniqueViolationError``, и стартовое
обслуживание студии умирает с «duplicate key value violates unique constraint
ix_projects_slug» (наблюдалось на VPS 11.11 при каждом старте).
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app import seed_pilot


def _use_postgres(monkeypatch) -> None:
    """Включить ветку Postgres: ``is_postgres`` выводится из ``db_dialect``."""
    from app.settings import settings

    monkeypatch.setattr(type(settings), "db_dialect", property(lambda self: "postgresql"))


def _use_sqlite(monkeypatch) -> None:
    """Включить ветку SQLite."""
    from app.settings import settings

    monkeypatch.setattr(type(settings), "db_dialect", property(lambda self: "sqlite"))


class _Result:
    """Ответ SELECT: scalar_one_or_none() отдаёт заранее заданное значение."""

    def __init__(self, value: object) -> None:
        self._value = value

    def scalar_one_or_none(self) -> object:
        return self._value


class _FakeSession:
    """Сессия, которая на каждый SELECT slug отвечает из заранее заданного списка.

    ``taken`` — список занятых slug; каждый следующий SELECT проходит по нему.
    ``executed`` — журнал выполненных SQL (для проверки set_config).
    """

    def __init__(self, taken: list[str]) -> None:
        self._taken = list(taken)
        self.executed: list[str] = []

    async def execute(self, stmt, *args, **kwargs):
        sql = str(stmt)
        self.executed.append(sql)
        if "set_config" in sql:
            return _Result(None)
        # SELECT ... WHERE projects.slug = ? → отдаём следующий занятый slug.
        slug = self._taken.pop(0) if self._taken else None
        return _Result(SimpleNamespace(slug=slug) if slug else None)


@pytest.mark.asyncio
async def test_slug_check_runs_outside_rls(monkeypatch) -> None:
    """Проверка занятости slug идёт с поднятым app.is_admin — иначе RLS прячет чужой проект."""
    _use_postgres(monkeypatch)
    session = _FakeSession([])

    slug = await seed_pilot._unique_slug(session, "my-slug")

    assert slug == "my-slug"
    assert any("set_config" in sql and "app.is_admin" in sql for sql in session.executed)
    # set_config идёт ПЕРВЫМ — иначе проверка успела бы увидеть «свой» пустой мир.
    assert "set_config" in session.executed[0]


@pytest.mark.asyncio
async def test_slug_gets_suffix_when_taken(monkeypatch) -> None:
    """Занятый slug → следующий свободный (``base-2``), без падения на UniqueViolation."""
    _use_postgres(monkeypatch)
    session = _FakeSession(["my-slug"])

    slug = await seed_pilot._unique_slug(session, "my-slug")

    assert slug == "my-slug-2"


@pytest.mark.asyncio
async def test_slug_check_skips_admin_flag_on_sqlite(monkeypatch) -> None:
    """На SQLite политик нет — set_config не выполняется (невалидный SQL для SQLite)."""
    _use_sqlite(monkeypatch)
    session = _FakeSession([])

    slug = await seed_pilot._unique_slug(session, "my-slug")

    assert slug == "my-slug"
    assert not any("set_config" in sql for sql in session.executed)
