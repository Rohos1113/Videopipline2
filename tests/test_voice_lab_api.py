"""REST `/api/voice-lab`: реестр клонов, создание без ключа и с ключом, лимит.

Приложение студии (`app.web.api`) не поднимаем: у него lifespan с worker'ом,
базой и фоновыми циклами — для роутера это лишний шум. Собираем `FastAPI()` и
включаем роутер с префиксом `/api`, как это делает api.py.

Каталог данных подменяем явно: conftest уже уводит `settings.data_dir` в tmp,
но здесь свой подкаталог — так путь видно в самом тесте, и прогон не оставляет
клонов в боевом `data/`.

Сеть не ходит ни один тест: провайдер подменяется monkeypatch'ем
`voice_lab.create_voice` / `voice_lab.synthesize_preview`.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.bots import elevenlabs_clone
from app.bots.elevenlabs_clone import ElevenLabsCloneError
from app.settings import settings
from app.web.routers import voice_lab

FAKE_MP3 = b"ID3\x04\x00\x00\x00\x00\x00\x00fake-mp3-payload"


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """Приложение с одним роутером и своим каталогом данных."""
    monkeypatch.setattr(settings, "data_dir", tmp_path / "data")
    app = FastAPI()
    app.include_router(voice_lab.router, prefix="/api")
    return TestClient(app)


@pytest.fixture()
def no_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """Студия без ключа ElevenLabs — штатный режим «клон ждёт ключа»."""
    monkeypatch.setattr(settings, "elevenlabs_api_key", "")


@pytest.fixture()
def with_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "elevenlabs_api_key", "test-key-not-real")


def _clones_root() -> Path:
    return Path(settings.data_dir) / "voices" / "clones"


def _create(
    client: TestClient,
    *,
    name: str = "Тестовый голос",
    files: list[tuple[str, tuple[str, bytes, str]]] | None = None,
    **form_extra: str,
) -> Any:
    form = {
        "name": name,
        "description": "описание",
        "language": "ru",
        "kind": "instant",
        **form_extra,
    }
    payload = files if files is not None else [("samples", ("sample-1.mp3", FAKE_MP3, "audio/mpeg"))]
    return client.post("/api/voice-lab/clones", data=form, files=payload)


def _write_index(records: list[dict[str, Any]]) -> None:
    root = _clones_root()
    root.mkdir(parents=True, exist_ok=True)
    (root / "index.json").write_text(
        json.dumps({"version": 1, "voices": records}, ensure_ascii=False),
        encoding="utf-8",
    )


def _record(created_at: str) -> dict[str, Any]:
    return {
        "id": str(uuid.uuid4()),
        "name": "Старый клон",
        "status": "ready",
        "source": "clone",
        "created_at": created_at,
        "samples": [],
    }


def _today_iso() -> str:
    return datetime.now(UTC).astimezone().isoformat(timespec="seconds")


# ── Список ────────────────────────────────────────────────────────────────


def test_list_is_empty_and_reports_not_configured(client: TestClient, no_key: None) -> None:
    r = client.get("/api/voice-lab/voices")
    assert r.status_code == 200
    body = r.json()
    assert body == {"configured": False, "daily_used": 0, "daily_limit": 10, "voices": []}


# ── Создание без ключа ────────────────────────────────────────────────────


def test_create_without_key_saves_samples_and_pending(client: TestClient, no_key: None) -> None:
    r = _create(client)
    assert r.status_code == 201
    body = r.json()
    voice = body["voice"]
    assert voice["status"] == "pending_provider"
    assert body["provider_error"]
    assert "ELEVENLABS_API_KEY" in body["provider_error"]
    assert voice["name"] == "Тестовый голос"
    assert voice["language"] == "ru"
    assert voice["source"] == "clone"
    assert voice["samples_count"] == 1
    assert voice["sample_url"] == f"/api/voice-lab/clones/{voice['id']}/sample?index=0"
    assert voice["external_voice_id"] is None
    assert voice["created_at"]

    # Сэмплы и реестр реально легли на диск, а не только в ответ.
    clone_dir = _clones_root() / voice["id"]
    assert (clone_dir / "sample-1.mp3").read_bytes() == FAKE_MP3
    assert (clone_dir / "meta.json").is_file()
    index = json.loads((_clones_root() / "index.json").read_text(encoding="utf-8"))
    assert [v["id"] for v in index["voices"]] == [voice["id"]]

    listing = client.get("/api/voice-lab/voices").json()
    assert listing["configured"] is False
    assert listing["daily_used"] == 1
    assert [v["id"] for v in listing["voices"]] == [voice["id"]]
    assert listing["voices"][0]["provider_error"] == body["provider_error"]


def test_create_with_key_marks_ready(
    client: TestClient, with_key: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: dict[str, Any] = {}

    async def fake_create_voice(
        name: str,
        description: str = "",
        files: list[Path] | None = None,
        *,
        language: str | None = None,
    ) -> str:
        calls.update(name=name, description=description, files=list(files or []), language=language)
        return "ext-voice-42"

    monkeypatch.setattr(voice_lab, "create_voice", fake_create_voice)
    r = _create(client, name="Голос студии")
    assert r.status_code == 201
    body = r.json()
    assert body["provider_error"] is None
    assert body["voice"]["status"] == "ready"
    assert body["voice"]["external_voice_id"] == "ext-voice-42"
    assert calls["name"] == "Голос студии"
    assert calls["language"] == "ru"
    assert len(calls["files"]) == 1
    assert calls["files"][0].is_file()
    assert client.get("/api/voice-lab/voices").json()["configured"] is True


def test_provider_error_is_not_500(
    client: TestClient, with_key: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fake_create_voice(*args: Any, **kwargs: Any) -> str:
        raise ElevenLabsCloneError("ElevenLabs запретил запрос (HTTP 403): гео-блок")

    monkeypatch.setattr(voice_lab, "create_voice", fake_create_voice)
    r = _create(client)
    assert r.status_code == 201
    body = r.json()
    assert body["voice"]["status"] == "pending_provider"
    assert "403" in body["provider_error"]
    # Загрузка пользователя при этом цела.
    clone_id = body["voice"]["id"]
    assert (_clones_root() / clone_id / "sample-1.mp3").is_file()
    assert body["voice"]["samples_count"] == 1


def test_unexpected_provider_crash_is_not_500(
    client: TestClient, with_key: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fake_create_voice(*args: Any, **kwargs: Any) -> str:
        raise RuntimeError("boom")

    monkeypatch.setattr(voice_lab, "create_voice", fake_create_voice)
    r = _create(client)
    assert r.status_code == 201
    assert r.json()["voice"]["status"] == "pending_provider"
    assert "boom" in r.json()["provider_error"]


# ── Валидация ─────────────────────────────────────────────────────────────


def test_validation_rejects_bad_input(client: TestClient, no_key: None) -> None:
    no_files = client.post("/api/voice-lab/clones", data={"name": "Без файлов"})
    assert no_files.status_code == 400
    assert "сэмпл" in no_files.json()["detail"]

    bad_ext = _create(
        client,
        files=[("samples", ("voice.txt", b"not audio", "text/plain"))],
    )
    assert bad_ext.status_code == 400
    assert "не поддерживается" in bad_ext.json()["detail"]

    empty_name = _create(client, name="   ")
    assert empty_name.status_code == 400
    assert "Название" in empty_name.json()["detail"]

    empty_file = _create(client, files=[("samples", ("empty.mp3", b"", "audio/mpeg"))])
    assert empty_file.status_code == 400
    assert "пустой" in empty_file.json()["detail"]

    # Ни одна неудачная попытка не оставила записи в реестре и не съела лимит.
    listing = client.get("/api/voice-lab/voices").json()
    assert listing["voices"] == []
    assert listing["daily_used"] == 0


# ── Лимит ─────────────────────────────────────────────────────────────────


def test_daily_limit_blocks_eleventh(client: TestClient, no_key: None) -> None:
    _write_index([_record(_today_iso()) for _ in range(voice_lab.DAILY_LIMIT)])
    r = _create(client)
    assert r.status_code == 429
    assert "Лимит" in r.json()["detail"]
    listing = client.get("/api/voice-lab/voices").json()
    assert listing["daily_used"] == voice_lab.DAILY_LIMIT
    assert len(listing["voices"]) == voice_lab.DAILY_LIMIT


def test_limit_ignores_yesterday(client: TestClient, no_key: None) -> None:
    yesterday = (datetime.now(UTC).astimezone() - timedelta(days=1)).isoformat(timespec="seconds")
    _write_index([_record(yesterday) for _ in range(voice_lab.DAILY_LIMIT)])
    r = _create(client)
    assert r.status_code == 201
    assert client.get("/api/voice-lab/voices").json()["daily_used"] == 1


# ── Правка и удаление ─────────────────────────────────────────────────────


def test_patch_updates_name_and_description(client: TestClient, no_key: None) -> None:
    voice = _create(client).json()["voice"]
    r = client.patch(
        f"/api/voice-lab/clones/{voice['id']}",
        json={"name": "Новое имя", "description": "новое описание"},
    )
    assert r.status_code == 200
    updated = r.json()["voice"]
    assert updated["name"] == "Новое имя"
    assert updated["description"] == "новое описание"
    # Правка переживает перечитывание реестра с диска.
    assert client.get("/api/voice-lab/voices").json()["voices"][0]["name"] == "Новое имя"

    assert client.patch(f"/api/voice-lab/clones/{voice['id']}", json={}).status_code == 400
    blank = client.patch(f"/api/voice-lab/clones/{voice['id']}", json={"name": "  "})
    assert blank.status_code == 400
    assert "пустым" in blank.json()["detail"]


def test_delete_removes_record_and_files(client: TestClient, no_key: None) -> None:
    voice = _create(client).json()["voice"]
    clone_dir = _clones_root() / voice["id"]
    assert clone_dir.is_dir()

    r = client.delete(f"/api/voice-lab/clones/{voice['id']}")
    assert r.status_code == 200
    assert r.json() == {"deleted": True}
    assert not clone_dir.exists()
    assert client.get("/api/voice-lab/voices").json()["voices"] == []
    assert client.delete(f"/api/voice-lab/clones/{voice['id']}").status_code == 404


def test_unknown_ids_are_404(client: TestClient, no_key: None) -> None:
    ghost = str(uuid.uuid4())
    assert client.delete(f"/api/voice-lab/clones/{ghost}").status_code == 404
    assert client.patch(f"/api/voice-lab/clones/{ghost}", json={"name": "x"}).status_code == 404
    assert client.get(f"/api/voice-lab/clones/{ghost}/sample").status_code == 404
    # Мусорный id (в том числе попытка выйти из каталога) — тоже 404, не 500.
    assert client.get("/api/voice-lab/clones/not-a-uuid/sample").status_code == 404
    assert client.delete("/api/voice-lab/clones/..").status_code == 404


# ── Сэмплы ────────────────────────────────────────────────────────────────


def test_sample_endpoint_serves_uploaded_bytes(client: TestClient, no_key: None) -> None:
    voice = _create(client).json()["voice"]
    r = client.get(f"/api/voice-lab/clones/{voice['id']}/sample?index=0")
    assert r.status_code == 200
    assert r.content == FAKE_MP3
    assert r.headers["content-type"].startswith("audio/mpeg")

    assert client.get(f"/api/voice-lab/clones/{voice['id']}/sample?index=5").status_code == 404


def test_index_recovered_from_meta_json(client: TestClient, no_key: None) -> None:
    voice = _create(client).json()["voice"]
    (_clones_root() / "index.json").unlink()
    listing = client.get("/api/voice-lab/voices").json()
    assert [v["id"] for v in listing["voices"]] == [voice["id"]]


def test_empty_index_does_not_resurrect_leftover_dir(client: TestClient, no_key: None) -> None:
    """Удалённый клон не возвращается из каталога, который не успели убрать."""
    voice = _create(client).json()["voice"]
    assert client.delete(f"/api/voice-lab/clones/{voice['id']}").status_code == 200
    leftover = _clones_root() / voice["id"]
    leftover.mkdir(parents=True, exist_ok=True)
    (leftover / "meta.json").write_text(json.dumps({"id": voice["id"], "name": "x"}), encoding="utf-8")
    assert client.get("/api/voice-lab/voices").json()["voices"] == []


# ── Предпросмотр ──────────────────────────────────────────────────────────


def test_preview_needs_provider_voice(client: TestClient, no_key: None) -> None:
    voice = _create(client).json()["voice"]
    r = client.post(f"/api/voice-lab/clones/{voice['id']}/preview", json={"text": "Привет"})
    assert r.status_code == 400
    assert "ElevenLabs" in r.json()["detail"]


def test_preview_returns_audio_url(
    client: TestClient, with_key: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fake_create_voice(*args: Any, **kwargs: Any) -> str:
        return "ext-voice-7"

    async def fake_synthesize_preview(voice_id: str, text: str, out_path: Path) -> Path:
        assert voice_id == "ext-voice-7"
        assert text == "Привет, мир"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(b"ID3preview")
        return out_path

    monkeypatch.setattr(voice_lab, "create_voice", fake_create_voice)
    monkeypatch.setattr(voice_lab, "synthesize_preview", fake_synthesize_preview)
    voice = _create(client).json()["voice"]
    assert voice["status"] == "ready"

    r = client.post(f"/api/voice-lab/clones/{voice['id']}/preview", json={"text": "Привет, мир"})
    assert r.status_code == 200
    audio_url = r.json()["audio_url"]
    assert f"/api/voice-lab/clones/{voice['id']}/preview-audio" in audio_url
    played = client.get(audio_url)
    assert played.status_code == 200
    assert played.content == b"ID3preview"
    assert played.headers["content-type"].startswith("audio/mpeg")

    empty = client.post(f"/api/voice-lab/clones/{voice['id']}/preview", json={"text": "  "})
    assert empty.status_code == 400


# ── Клиент провайдера (без сети: httpx.MockTransport) ─────────────────────


def _mock_httpx(monkeypatch: pytest.MonkeyPatch, handler: Any) -> None:
    """Подменить транспорт httpx: проверяем сам запрос, а не ответ сети."""
    real_client = httpx.AsyncClient

    def factory(*args: Any, **kwargs: Any) -> httpx.AsyncClient:
        return real_client(*args, transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(elevenlabs_clone.httpx, "AsyncClient", factory)


def _sample_file(tmp_path: Path) -> Path:
    path = tmp_path / "sample-1.mp3"
    path.write_bytes(FAKE_MP3)
    return path


async def test_provider_client_posts_multipart(
    tmp_path: Path,
    with_key: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sample = _sample_file(tmp_path)
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["key"] = request.headers.get("xi-api-key")
        seen["content_type"] = request.headers.get("content-type", "")
        seen["body"] = request.content
        return httpx.Response(200, json={"voice_id": "voice-abc"})

    _mock_httpx(monkeypatch, handler)
    voice_id = await elevenlabs_clone.create_voice(
        "Клон студии",
        "описание голоса",
        [sample],
        language="ru",
    )
    assert voice_id == "voice-abc"
    assert seen["path"] == "/v1/voices/add"
    assert seen["key"] == "test-key-not-real"
    assert seen["content_type"].startswith("multipart/form-data")
    body = seen["body"]
    # Поля ровно те, которые ждёт ElevenLabs: имя, файлы и язык в labels.
    assert b'name="name"' in body
    assert b'name="files"' in body
    assert b'name="labels"' in body
    assert b'{"language": "ru"}' in body


@pytest.mark.parametrize("status", [401, 402, 403, 422, 429])
async def test_provider_http_error_becomes_russian_message(
    status: int,
    tmp_path: Path,
    with_key: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sample = _sample_file(tmp_path)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json={"detail": {"message": "provider says no"}})

    _mock_httpx(monkeypatch, handler)
    with pytest.raises(ElevenLabsCloneError) as exc:
        await elevenlabs_clone.create_voice("Клон", files=[sample])
    message = str(exc.value)
    assert str(status) in message
    # Ключ в текст ошибки не попадает — она уходит в реестр и в UI.
    assert "test-key-not-real" not in message


async def test_provider_network_error_is_wrapped(
    tmp_path: Path,
    with_key: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sample = _sample_file(tmp_path)

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route")

    _mock_httpx(monkeypatch, handler)
    with pytest.raises(ElevenLabsCloneError, match="недоступен"):
        await elevenlabs_clone.create_voice("Клон", files=[sample])


async def test_provider_requires_key(tmp_path: Path, no_key: None) -> None:
    with pytest.raises(elevenlabs_clone.ElevenLabsNotConfigured):
        await elevenlabs_clone.create_voice("Клон", files=[_sample_file(tmp_path)])


async def test_preview_client_posts_tts(
    tmp_path: Path,
    with_key: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    out_path = tmp_path / "preview.mp3"
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["params"] = dict(request.url.params)
        seen["key"] = request.headers.get("xi-api-key")
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, content=b"ID3preview-mp3")

    _mock_httpx(monkeypatch, handler)
    result = await elevenlabs_clone.synthesize_preview("voice-xyz", "Привет, студия", out_path)
    assert result == out_path
    assert out_path.read_bytes() == b"ID3preview-mp3"
    assert seen["path"] == "/v1/text-to-speech/voice-xyz"
    assert seen["key"] == "test-key-not-real"
    assert seen["params"]["output_format"]
    assert seen["body"]["text"] == "Привет, студия"
    assert seen["body"]["model_id"]
