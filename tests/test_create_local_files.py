"""Create local files: import legacy + history order."""

from __future__ import annotations

import json
from pathlib import Path

from app.services.generation_storage import (
    import_legacy_create_media,
    invalidate_generation_list_cache,
    list_generation_files,
)


def test_import_legacy_outsee_create(tmp_path: Path, monkeypatch) -> None:
    from app.services import generation_storage as gs

    monkeypatch.setattr(gs.settings, "data_dir", tmp_path)
    legacy = tmp_path / "outsee_create"
    legacy.mkdir()
    src = legacy / "img_old.png"
    src.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 64)

    n = import_legacy_create_media()
    assert n == 1
    items = list_generation_files(kind="image", import_legacy=False)
    assert any(i["status"] == "done" and i["preview_url"] for i in items)
    # исходник на месте
    assert src.is_file()
    # повторно не дублируем
    assert import_legacy_create_media() == 0


def test_list_includes_legacy_flat_and_generations(tmp_path: Path, monkeypatch) -> None:
    from app.services import generation_storage as gs
    from app.services.generation_storage import build_generation_path, write_sidecar

    monkeypatch.setattr(gs.settings, "data_dir", tmp_path)
    p = build_generation_path(media="image", model="gpt-image-2", ext=".png")
    p.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 80)
    write_sidecar(
        p,
        media="image",
        model="gpt-image-2",
        prompt="hi",
        provider="outsee",
        status="done",
    )
    items = list_generation_files(kind="image")
    assert any(i["id"] == f"gen-{p.name}" for i in items)


def test_foreign_machine_path_resolved_to_local_sibling(tmp_path: Path, monkeypatch) -> None:
    """Sidecar с чужим абсолютным путем (с другой машины) разрешается в локальный файл-сиблинг."""
    from app.services import generation_storage as gs

    monkeypatch.setattr(gs.settings, "data_dir", tmp_path)
    invalidate_generation_list_cache()

    gen_dir = tmp_path / "generations" / "image" / "gpt-image-2" / "20260917"
    gen_dir.mkdir(parents=True, exist_ok=True)
    media_file = gen_dir / "140700_test.png"
    media_file.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 80)

    sidecar = gen_dir / "140700_test.json"
    sidecar.write_text(
        json.dumps(
            {
                "id": "140700_test",
                "media": "image",
                "model": "gpt-image-2",
                "prompt": "test",
                "file": "140700_test.png",
                "path": r"C:\Users\ForeignUser\Documents\video-pipeline-web\data\generations\image\gpt-image-2\20260917\140700_test.png",
                "status": "done",
                "bytes": 88,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    items = list_generation_files(kind="image", import_legacy=False)
    matched = next((i for i in items if i["id"] == "gen-140700_test.png"), None)
    assert matched is not None
    assert matched["status"] == "done"
    assert "ForeignUser" not in str(matched["preview_url"])
    assert str(media_file.resolve()) in str(matched["preview_url"])
    assert matched["path"] == str(media_file.resolve())
