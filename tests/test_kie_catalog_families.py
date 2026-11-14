"""Семьи и режимы каталога kie.ai: покрытие, payload, цены в $ (+25%), валидация.

Тесты делятся на две части:
  * синтетика — работают всегда, без данных аналитика;
  * data-driven — включаются, когда есть docs/kie-model-families.json и
    сгенерированный родительский модуль с FAMILIES (шаг 7).
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.services import kie_catalog as kc
from app.services.kie_catalog_families import FAMILIES

ROOT = Path(__file__).resolve().parents[1]
FAMILIES_JSON = ROOT / "docs" / "kie-model-families.json"
PRICES_JSON = ROOT / "docs" / "kie-prices-usd.json"

needs_data = pytest.mark.skipif(not FAMILIES, reason="docs/kie-model-families.json ещё не собран (шаг 7)")


def _field(name: str, kind: str, **kw: Any) -> dict[str, Any]:
    field: dict[str, Any] = {"name": name, "label": name, "kind": kind, "required": kw.pop("required", False)}
    field.update(kw)
    return field


def _pricing(unit: str, rules: list[dict[str, Any]], default_kie: float | None, **kw: Any) -> dict[str, Any]:
    default_client = round(default_kie * 1.25, 4) if default_kie is not None else None
    out_rules = []
    for rule in rules:
        client = rule.get("usd_client")
        if client is None and rule.get("usd_kie") is not None:
            client = round(float(rule["usd_kie"]) * 1.25, 4)
        out_rules.append({"when": rule.get("when") or {}, "usd_kie": rule.get("usd_kie"), "usd_client": client})
    out: dict[str, Any] = {
        "unit": unit,
        "markup": 1.25,
        "usd_rules": out_rules,
        "usd_default_kie": default_kie,
        "usd_default_client": default_client,
        "note": kw.get("note", ""),
        "formula": kw.get("formula", ""),
    }
    return out


FAMILY: dict[str, Any] = {
    "id": "test-family",
    "label": "Test Family",
    "brand": "TestBrand",
    "media": "video",
    "desc": "синтетическая семья для тестов",
    "default_mode": "t2v",
    "modes": [
        {
            "id": "t2v",
            "label": "Текст → видео",
            "kie_id": "test/t2v",
            "task_type": "text-to-video",
            "api": "jobs",
            "media": "video",
            "fields": [
                _field("prompt", "textarea", required=True),
                _field("resolution", "select", options=["480p", "720p"], default="720p"),
                _field("duration", "number", default=5, min=2, max=10),
                _field("first_frame_url", "images", max_items=1),
                _field("reference_image_urls", "images", max_items=3),
            ],
            "pricing": _pricing(
                "sec",
                [
                    {"when": {"resolution": "480p"}, "usd_kie": 0.1},
                    {"when": {"resolution": "720p", "_has_videos": True}, "usd_kie": 0.2},
                    {"when": {"resolution": "720p"}, "usd_kie": 0.4},
                ],
                0.4,
                note="$ за секунду",
            ),
            "constraints": [],
        },
        {
            "id": "i2v",
            "label": "Картинка → видео",
            "kie_id": "test/i2v",
            "task_type": "image-to-video",
            "api": "jobs",
            "media": "video",
            "fields": [
                _field("prompt", "textarea"),
                _field("image_url", "images", max_items=1, required=True),
                _field("duration", "number", default=5, min=2, max=10),
            ],
            "pricing": _pricing("gen", [{"when": {"duration": 5}, "usd_kie": 0.5}], 0.5),
            "constraints": ["нужна картинка"],
        },
        {
            "id": "img",
            "label": "Картинки",
            "kie_id": "test/image",
            "task_type": "text-to-image",
            "api": "jobs",
            "media": "image",
            "fields": [
                _field("prompt", "textarea", required=True),
                _field("count", "number", default=1, min=1, max=4),
            ],
            "pricing": _pricing("image", [{"when": {}, "usd_kie": 0.02}], 0.02),
            "constraints": [],
        },
    ],
}


def _app() -> FastAPI:
    from app.web.routers import kie_create

    app = FastAPI()
    app.include_router(kie_create.router, prefix="/api")
    return app


# ----------------------------- синтетика -----------------------------


def test_get_family_and_mode() -> None:
    fam = kc.get_family(FAMILY)
    assert fam is not None and fam["id"] == "test-family"
    default = kc.get_mode(fam)
    assert default is not None and default["id"] == "t2v"
    assert kc.get_mode(fam, "i2v")["kie_id"] == "test/i2v"
    assert kc.get_mode(fam, "test/image")["id"] == "img"  # по kie_id тоже находится
    assert kc.get_mode(fam, "nope") is None
    assert kc.get_family("nope-family") is None


def test_resolve_model_id_returns_kie_id_of_mode() -> None:
    assert kc.resolve_model_id(FAMILY) == "test/t2v"  # режим по умолчанию
    assert kc.resolve_model_id(FAMILY, mode="i2v") == "test/i2v"
    mode = kc.get_mode(FAMILY, "img")
    assert kc.resolve_model_id(mode) == "test/image"
    # legacy-путь не сломан: model_map и model_map_i2i работают как раньше
    assert kc._legacy_resolve_model_id({"model": "base/model"}, {}) == "base/model"


def test_defaults_for_mode() -> None:
    defaults = kc.defaults_for_mode(FAMILY, "t2v")
    assert defaults["resolution"] == "720p"
    assert defaults["duration"] == 5


def test_build_payload_for_each_mode() -> None:
    t2v = kc.build_payload(kc.mode_spec(FAMILY, "t2v"), {"prompt": "кот", "resolution": "480p"})
    assert t2v["model"] == "test/t2v"
    assert t2v["input"]["prompt"] == "кот"
    assert t2v["input"]["resolution"] == "480p"
    assert t2v["input"]["duration"] == 5

    i2v = kc.build_payload(
        kc.mode_spec(FAMILY, "i2v"),
        {"prompt": "кот", "image_url": ["https://x/a.png"]},
    )
    assert i2v["model"] == "test/i2v"
    assert i2v["input"]["image_url"] == "https://x/a.png"

    img = kc.build_payload(kc.mode_spec(FAMILY, "img"), {"prompt": "кот", "count": 2})
    assert img["input"]["count"] == 2


def test_estimate_usd_per_second_and_markup() -> None:
    est = kc.estimate_usd(FAMILY, "t2v", {"resolution": "480p", "duration": 10})
    assert est["known"] is True
    assert est["unit"] == "sec"
    assert est["unit_usd_kie"] == 0.1
    assert est["multiplier"] == 10
    assert est["usd_kie"] == pytest.approx(1.0)
    assert est["usd_client"] == pytest.approx(1.25)  # +25% студии
    assert est["usd_client"] == pytest.approx(est["usd_kie"] * 1.25)
    assert est["credits"] == pytest.approx(est["usd_client"] / kc.CREDIT_USD)
    assert est["breakdown"]["matched_rule"] == {"resolution": "480p"}


def test_estimate_usd_video_input_selects_cheaper_rule() -> None:
    plain = kc.estimate_usd(FAMILY, "t2v", {"resolution": "720p", "duration": 10})
    with_video = kc.estimate_usd(
        FAMILY,
        "t2v",
        {"resolution": "720p", "duration": 10, "reference_video_urls": ["https://x/v.mp4"]},
    )
    # правило _has_videos требует наличие видеополя в схеме режима — если его нет,
    # цена остаётся обычной (и это тоже валидный случай).
    assert plain["usd_kie"] == pytest.approx(4.0)
    assert with_video["usd_kie"] in (pytest.approx(4.0), pytest.approx(2.0))


def test_estimate_usd_per_gen_and_per_image_and_chars() -> None:
    gen = kc.estimate_usd(FAMILY, "i2v", {"prompt": "x", "image_url": ["https://x/a.png"], "duration": 5})
    assert gen["unit"] == "gen"
    assert gen["multiplier"] == 1
    assert gen["usd_kie"] == pytest.approx(0.5)
    assert gen["usd_client"] == pytest.approx(0.625)

    imgs = kc.estimate_usd(FAMILY, "img", {"prompt": "x", "count": 3})
    assert imgs["unit"] == "image"
    assert imgs["multiplier"] == 3
    assert imgs["usd_kie"] == pytest.approx(0.06)
    assert imgs["usd_client"] == pytest.approx(0.075)

    tts = {
        "id": "tts",
        "modes": [
            {
                "id": "voice",
                "kie_id": "test/tts",
                "api": "jobs",
                "media": "video",
                "fields": [_field("text", "textarea", required=True)],
                "pricing": _pricing("1k_chars", [{"when": {}, "usd_kie": 0.015}], 0.015),
            }
        ],
    }
    chars = kc.estimate_usd(tts, "voice", {"text": "x" * 2500})
    assert chars["multiplier"] == 3
    assert chars["usd_kie"] == pytest.approx(0.045)


def test_estimate_usd_tokens_and_megapixel_units() -> None:
    tokens_family = {
        "id": "token-family",
        "modes": [
            {
                "id": "t2i",
                "kie_id": "test/token-image",
                "api": "jobs",
                "media": "image",
                "fields": [_field("prompt", "textarea"), _field("resolution", "select", options=["1K", "2K"])],
                "pricing": _pricing("tokens", [{"when": {"token_kind": "image_output"}, "usd_kie": 27.0}], 27.0),
            }
        ],
    }
    tokens = kc.estimate_usd(tokens_family, "t2i", {"prompt": "x"})
    # количество токенов из формы не вывести — цену не выдумываем
    assert tokens["known"] is False
    assert tokens["usd_client"] is None and tokens["usd_kie"] is None
    assert tokens["note"] == "цена уточняется"

    mp_family = {
        "id": "mp-family",
        "modes": [
            {
                "id": "t2i",
                "kie_id": "test/mp-image",
                "api": "jobs",
                "media": "image",
                "fields": [_field("prompt", "textarea"), _field("image_size", "select", options=["square", "square_hd"])],
                "pricing": _pricing("megapixel", [{"when": {}, "usd_kie": 0.02}], 0.02),
            }
        ],
    }
    mp = kc.estimate_usd(mp_family, "t2i", {"prompt": "x", "image_size": "square_hd"})
    assert mp["known"] is True
    assert mp["multiplier"] == pytest.approx(2.359296)
    assert mp["usd_kie"] == pytest.approx(0.02 * 2.359296, abs=0.001)
    assert mp["usd_client"] == pytest.approx(mp["usd_kie"] * 1.25, abs=0.01)


@needs_data
def test_extra_charges_for_input_images() -> None:
    """Доплаты за входные картинки (extra_charges) входят в цену режима."""
    one = kc.estimate_usd(
        "seedream-5-pro",
        "i2i-pro",
        {"prompt": "x", "image_urls": ["https://example.com/a.png"]},
    )
    three = kc.estimate_usd(
        "seedream-5-pro",
        "i2i-pro",
        {"prompt": "x", "image_urls": [f"https://example.com/{i}.png" for i in range(3)]},
    )
    assert one["known"] is True and three["known"] is True
    extra = three["breakdown"].get("extra_charges") or []
    assert extra and extra[0]["paid"] == 2
    assert extra[0]["images"] == 3
    assert three["usd_client"] > one["usd_client"]
    assert three["usd_client"] == pytest.approx(one["usd_client"] + 2 * extra[0]["unit_usd_client"], abs=0.001)

    # MiniMax H3: первые 5 картинок бесплатны
    family = kc.get_family("minimax-h3")
    assert family is not None
    five = kc.estimate_usd(
        family,
        "r2v",
        {"duration": 5, "resolution": "768P", "reference_image_urls": [f"https://e.com/{i}.png" for i in range(5)]},
    )
    eight = kc.estimate_usd(
        family,
        "r2v",
        {"duration": 5, "resolution": "768P", "reference_image_urls": [f"https://e.com/{i}.png" for i in range(8)]},
    )
    assert not five["breakdown"].get("extra_charges")
    assert eight["breakdown"]["extra_charges"][0]["paid"] == 3
    assert eight["usd_client"] > five["usd_client"]


@needs_data
def test_note_orientirovochno_when_rule_not_matched() -> None:
    """Если правило не разрешилось и взята цена по умолчанию — note помечает это."""
    family = kc.get_family("seedream-5-pro")
    assert family is not None
    est = kc.estimate_usd(family, "i2i-pro", {"prompt": "x"})
    assert est["known"] is True
    assert est["breakdown"]["matched_rule"] is None
    assert "ориентировочно" in est["note"]


@needs_data
def test_tokens_modes_are_unknown() -> None:
    """GPT Image 2.6: токены из настроек не выводятся — цену не придумываем."""
    family = kc.get_family("gpt-image-2-6")
    assert family is not None
    token_modes = [m for m in family["modes"] if m["pricing"]["unit"] in ("tokens", "1m_tokens")]
    assert token_modes
    for mode in token_modes:
        est = kc.estimate_usd(family, mode["id"], kc.defaults_for_mode(family, mode["id"]))
        assert est["known"] is False
        assert est["usd_client"] is None
        assert est["note"] == "цена уточняется"


def test_estimate_usd_unknown_price() -> None:
    fam = {
        "id": "no-price",
        "modes": [
            {
                "id": "m",
                "kie_id": "test/no-price",
                "api": "jobs",
                "media": "video",
                "fields": [],
                "pricing": {
                    "unit": "gen",
                    "markup": 1.25,
                    "usd_rules": [],
                    "usd_default_kie": None,
                    "usd_default_client": None,
                    "note": "неизвестно",
                    "formula": "",
                },
            }
        ],
    }
    est = kc.estimate_usd(fam, "m", {})
    assert est["known"] is False
    assert est["usd_kie"] is None and est["usd_client"] is None
    assert est["credits"] == 0.0
    assert est["note"] == "неизвестно"


def test_validate_mode_required_enum_minmax_maxitems() -> None:
    spec = kc.mode_spec(FAMILY, "t2v")
    errors = kc.validate_mode_values(FAMILY, "t2v", {"resolution": "999p"})
    assert any("обязательное поле" in e for e in errors)
    assert any("вне списка" in e for e in errors)

    too_long = kc.validate_mode_values(FAMILY, "t2v", {"prompt": "x", "duration": 99})
    assert any("> max" in e for e in too_long)
    too_short = kc.validate_mode_values(FAMILY, "t2v", {"prompt": "x", "duration": 1})
    assert any("< min" in e for e in too_short)
    too_many = kc.validate_mode_values(
        FAMILY,
        "t2v",
        {"prompt": "x", "reference_image_urls": ["https://x/r.png"] * 4},
    )
    assert any("> 3" in e for e in too_many)
    assert kc.validate_mode_values(FAMILY, "t2v", {"prompt": "ок"}) == []
    assert spec["is_family_mode"] is True


def test_validate_mode_frames_vs_references() -> None:
    errors = kc.validate_mode_values(
        FAMILY,
        "t2v",
        {
            "prompt": "x",
            "first_frame_url": ["https://x/start.png"],
            "reference_image_urls": ["https://x/ref.png"],
        },
    )
    assert any("одновременное совмещение" in e for e in errors)
    only_frames = kc.validate_mode_values(FAMILY, "t2v", {"prompt": "x", "first_frame_url": ["https://x/a.png"]})
    assert not any("одновременное совмещение" in e for e in only_frames)
    only_refs = kc.validate_mode_values(
        FAMILY, "t2v", {"prompt": "x", "reference_image_urls": ["https://x/r.png"]}
    )
    assert not any("одновременное совмещение" in e for e in only_refs)


def test_catalog_cards_have_modes_and_usd_pricing() -> None:
    catalog = kc.catalog_for_ui()
    assert catalog["markup"] == 1.25
    media_cards = [m for m in catalog["models"] if m.get("media") in ("video", "image")]
    assert media_cards, "в каталоге должны быть медиа-карточки"
    for card in media_cards:
        assert card["fields"], card["id"]
        assert (card["pricing"].get("default") or 0) > 0, card["id"]
        assert card.get("modes"), card["id"]
        assert card.get("brand") is not None
        assert card.get("modes_count") == len(card["modes"])
        for mode in card["modes"]:
            assert mode["kie_id"]
            assert mode["api"]
            pricing = mode["pricing"]
            assert pricing["markup"] == 1.25
            assert "usd_default_client" in pricing
            assert "usd_rules" in pricing
    audio_cards = [m for m in catalog["models"] if m["category"] in ("music", "sound", "voice")]
    assert audio_cards
    for card in audio_cards:
        assert "modes" not in card  # аудио не трогаем


def test_legacy_ids_still_resolve_and_build_same_payload() -> None:
    # прежние payload старых id не изменились
    veo = kc.get_model("veo-3-1")
    assert veo is not None
    body = kc.build_payload(veo, {"prompt": "dog", "duration": "8"})
    assert body["duration"] == 8 and body["model"] == "veo3_lite"

    seedance = kc.get_model("seedance-2-5")
    assert seedance is not None
    sbody = kc.build_payload(seedance, {"prompt": "x", "resolution": "720p", "duration": 5})
    assert sbody["model"] == "bytedance/seedance-2-5"
    assert sbody["input"]["resolution"] == "720p"

    kling = kc.get_model("kling-3-0")
    assert kling is not None
    kbody = kc.build_payload(kling, {"prompt": "x", "mode": "pro", "sound": True, "duration": 5})
    assert kbody["model"] == "kling-3.0/video"
    assert kbody["input"]["sound"] is True

    flux = kc.get_model("flux-2-pro")
    assert flux is not None
    fbody = kc.build_payload(flux, {"prompt": "cat", "image_urls": ["https://x/a.png"]})
    assert fbody["model"] == "flux-2/pro-image-to-image"

    nano = kc.get_model("nano-banana-2")
    assert nano is not None
    nbody = kc.build_payload(nano, {"prompt": "cat", "resolution": "2K"})
    assert nbody["model"] == "nano-banana-2"
    assert nbody["input"]["resolution"] == "2K"

    gpt = kc.get_model("gpt-image-2")
    assert gpt is not None
    gbody = kc.build_payload(gpt, {"prompt": "cat"})
    assert gbody["model"] == "gpt-image-2-text-to-image"


def test_legacy_prices_still_credits() -> None:
    seedance = kc.get_model("seedance-2-5")
    assert seedance is not None
    assert kc.estimate_credits(seedance, {"resolution": "1080p", "duration": 10})["credits"] == 1140
    tts = kc.get_model("elevenlabs-v4")
    assert tts is not None
    assert kc.estimate_credits(tts, {"text": "x" * 2500})["credits"] == 9
    suno = kc.get_model("suno-music")
    assert suno is not None
    assert kc.estimate_credits(suno, {"prompt": "phonk"})["credits"] == 12


def test_legacy_estimate_has_usd_and_markup() -> None:
    """Старые записи: кредиты остаются, но в ответе есть usd_kie/usd_client с наценкой."""
    seedance = kc.get_model("seedance-2-5")
    assert seedance is not None
    quote = kc.estimate_credits(seedance, {"resolution": "1080p", "duration": 10})
    assert quote["credits"] == 1140
    assert quote["usd"] == pytest.approx(1140 * 0.005, abs=0.0001)
    assert quote["usd_kie"] == pytest.approx(1140 * 0.005, abs=0.000001)
    assert quote["usd_client"] == pytest.approx(1140 * 0.005 * 1.25, abs=0.0001)
    assert quote["markup"] == 1.25
    assert quote["usd_client"] == pytest.approx(quote["usd_kie"] * 1.25, abs=0.0001)


def test_legacy_family_bridges_old_ids() -> None:
    # старый id, не попавший в семьи, отдаётся карточкой с одним режимом
    family = kc.get_family("suno-music")
    assert family is not None
    modes = family["modes"]
    assert len(modes) == 1 and modes[0]["id"] == "default"
    assert kc.resolve_model_id(family) == "suno-music"
    assert kc.estimate_usd(family, None, {"prompt": "x"})["known"] is True


def test_estimate_endpoint_legacy_and_mode() -> None:
    client = TestClient(_app())
    legacy = client.post(
        "/api/kie-create/estimate",
        json={"model_id": "seedance-2-5", "values": {"resolution": "1080p", "duration": 10}},
    )
    assert legacy.status_code == 200
    assert legacy.json()["credits"] == 1140

    mode = client.post(
        "/api/kie-create/estimate",
        json={"model_id": "test-family", "mode": "t2v", "values": {"resolution": "480p", "duration": 10}},
    )
    # test-family живёт только в тестах — эндпоинт её не знает
    assert mode.status_code == 404
    bad = client.post("/api/kie-create/estimate", json={"model_id": "nope", "values": {}})
    assert bad.status_code == 404


def test_estimate_endpoint_family_mode_when_data_ready() -> None:
    if not FAMILIES:
        pytest.skip("нет данных шага 7")
    family = FAMILIES[0]
    mode = family["modes"][0]
    client = TestClient(_app())
    r = client.post(
        "/api/kie-create/estimate",
        json={"model_id": family["id"], "mode": mode["id"], "values": kc.defaults_for_mode(family, mode)},
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert set(data) >= {"usd_kie", "usd_client", "credits", "unit", "note", "breakdown"}
    if data["usd_client"] is not None:
        assert data["usd_client"] == pytest.approx(data["usd_kie"] * 1.25, abs=0.01)


# --------------------------- data-driven ---------------------------


@needs_data
def test_all_families_loaded_and_kie_ids_unique() -> None:
    assert FAMILIES
    seen: dict[str, str] = {}
    for family in FAMILIES:
        assert family.get("id"), family
        assert family.get("label"), family["id"]
        assert family.get("media") in ("video", "image"), family["id"]
        assert family.get("modes"), family["id"]
        for mode in family["modes"]:
            kid = mode["kie_id"]
            assert kid, family["id"]
            assert kid not in seen, f"дубль kie_id {kid}: {seen.get(kid)} и {family['id']}"
            seen[kid] = family["id"]
            assert mode["id"] and mode["label"]
            assert mode["api"], kid
            assert mode["pricing"]["markup"] == 1.25, kid
    assert len(seen) == sum(len(f["modes"]) for f in FAMILIES)


@needs_data
def test_kie_ids_match_analyst_json() -> None:
    if not FAMILIES_JSON.is_file():
        pytest.skip("нет docs/kie-model-families.json")
    doc = json.loads(FAMILIES_JSON.read_text(encoding="utf-8"))
    raw = doc.get("families", doc) if isinstance(doc, dict) else doc
    expected = {
        str(mode["kie_id"])
        for family in raw
        for mode in (family.get("modes") or [])
        if mode.get("kie_id")
    }
    got = {mode["kie_id"] for family in FAMILIES for mode in family["modes"]}
    assert expected - got == set(), f"потеряны kie_id: {sorted(expected - got)[:10]}"
    assert got - expected == set(), f"лишние kie_id: {sorted(got - expected)[:10]}"


@needs_data
def test_every_mode_builds_payload_without_exception() -> None:
    for family in FAMILIES:
        for mode in family["modes"]:
            spec = kc.mode_spec(family, mode["id"])
            defaults = kc.defaults_for_mode(family, mode["id"])
            payload = kc.build_payload(spec, defaults)
            assert isinstance(payload, dict), f"{family['id']}/{mode['id']}"
            if mode.get("api") == "jobs":
                assert payload.get("model") == mode["kie_id"], f"{family['id']}/{mode['id']}"
                assert isinstance(payload.get("input"), dict)


@needs_data
def test_every_mode_estimates_or_marks_unknown() -> None:
    known = 0
    for family in FAMILIES:
        for mode in family["modes"]:
            est = kc.estimate_usd(family, mode["id"], kc.defaults_for_mode(family, mode["id"]))
            if est["known"]:
                known += 1
                assert est["usd_client"] == pytest.approx(est["usd_kie"] * 1.25, abs=0.01)
                assert est["usd_kie"] >= 0
            else:
                assert est["usd_client"] is None, f"{family['id']}/{mode['id']}"
                assert est["note"] in ("неизвестно", "цена уточняется"), est["note"]
    assert known >= len(FAMILIES), f"цена известна только у {known} режимов"


@needs_data
def test_catalog_covers_every_kie_id() -> None:
    catalog = kc.catalog_for_ui()
    catalog_kie: set[str] = set()
    for card in catalog["models"]:
        if card.get("kie_id"):
            catalog_kie.add(card["kie_id"])
        for mode in card.get("modes") or []:
            catalog_kie.add(mode["kie_id"])
    for family in FAMILIES:
        for mode in family["modes"]:
            assert mode["kie_id"] in catalog_kie, f"{family['id']}/{mode['id']}: нет в каталоге"
    # старые id каталога не потерялись: каждая legacy-модель либо карточка, либо режим семьи
    for legacy in kc.MODELS:
        assert kc.get_model(legacy["id"]) is not None
        assert kc.get_family(legacy["id"]) is not None


@needs_data
def test_no_duplicate_family_cards() -> None:
    catalog = kc.catalog_for_ui()
    media_ids = [m["id"] for m in catalog["models"] if m.get("modes")]
    assert len(media_ids) == len(set(media_ids)), "карточки семей дублируются"


@needs_data
def test_generated_module_is_in_sync_with_docs() -> None:
    """Модуль не должен расходиться с docs/*.json — иначе пересоберите генератором."""
    path = ROOT / "scripts" / "gen_kie_families.py"
    spec = importlib.util.spec_from_file_location("gen_kie_families", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    prices_doc = module._load_json(PRICES_JSON)  # noqa: SLF001
    families_doc = module._load_json(FAMILIES_JSON)  # noqa: SLF001
    families, _stats = module.build(prices_doc, families_doc)
    rendered = module.render(families)
    current = (ROOT / "app" / "services" / "kie_catalog_families.py").read_text(encoding="utf-8")
    assert current.strip() == rendered.strip(), "app/services/kie_catalog_families.py устарел: запустите scripts/gen_kie_families.py"


@needs_data
def test_generate_endpoint_flat_api_family(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Режим с api veo (flat-тело, без input): /generate передаёт нужный endpoint."""
    from app.services import create_jobs as cj
    from app.services import generation_storage as gs
    from app.web.routers import kie_create

    family = next(
        (f for f in FAMILIES if any(m.get("api") in ("veo", "runway") for m in f["modes"])),
        None,
    )
    if family is None:
        pytest.skip("нет режимов veo/runway")
    mode = next(m for m in family["modes"] if m.get("api") in ("veo", "runway"))
    values = kc.defaults_for_mode(family, mode["id"])
    for field in mode["fields"]:
        name = field["name"]
        if field.get("required") and values.get(name) in (None, "", []):
            values[name] = (
                field["options"][0]
                if field.get("kind") == "select" and field.get("options")
                else "https://example.com/a.png"
            )
    if any(f["name"] == "prompt" for f in mode["fields"]) and not values.get("prompt"):
        values["prompt"] = "тестовый промпт"

    captured: dict[str, Any] = {}

    async def fake_run(spec, payload, out_path):
        captured["spec"] = spec
        captured["payload"] = payload
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(b"\x00" * 16)
        from app.bots.outsee import GenerationResult

        return GenerationResult(file_path=out_path, gen_id="task-flat-1", raw_url=None)

    monkeypatch.setattr(gs.settings, "data_dir", tmp_path)
    cj._JOBS.clear()
    cj._SEMS.clear()
    cj._SEM_SIZES.clear()
    cj._RECENT_FP.clear()
    monkeypatch.setattr(kie_create.kie_http, "kie_configured", lambda: True)
    monkeypatch.setattr(kie_create.kie_http, "run_generation", fake_run)
    monkeypatch.setattr(kie_create.pay52_video, "pay52_video_configured", lambda spec=None: False)

    client = TestClient(_app())
    r = client.post(
        "/api/kie-create/generate",
        json={"model_id": family["id"], "mode": mode["id"], "values": values},
    )
    assert r.status_code == 200, r.text
    assert captured["spec"]["api"] == mode["api"]
    assert captured["spec"].get("endpoint")
    assert "input" not in captured["payload"]


@needs_data
def test_generate_endpoint_family_mode_payload(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """generate с mode: валидирует, считает $, строит payload режима, сеть — мок."""
    from app.services import create_jobs as cj
    from app.services import generation_storage as gs
    from app.web.routers import kie_create

    family = next(f for f in FAMILIES if any(m.get("api") == "jobs" for m in f["modes"]))
    mode = next(m for m in family["modes"] if m.get("api") == "jobs")
    values = kc.defaults_for_mode(family, mode["id"])
    for field in mode["fields"]:
        name = field["name"]
        if field.get("required") and values.get(name) in (None, "", []):
            kind = field.get("kind")
            values[name] = (
                field["options"][0]
                if kind == "select" and field.get("options")
                else "https://example.com/a.png"
            )
    if any(f["name"] == "prompt" for f in mode["fields"]) and not values.get("prompt"):
        values["prompt"] = "тестовый промпт"

    captured: dict[str, Any] = {}

    async def fake_run(spec, payload, out_path):
        captured["spec"] = spec
        captured["payload"] = payload
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(b"\x00" * 16)
        from app.bots.outsee import GenerationResult

        return GenerationResult(file_path=out_path, gen_id="task-fam-1", raw_url=None)

    monkeypatch.setattr(gs.settings, "data_dir", tmp_path)
    cj._JOBS.clear()
    cj._SEMS.clear()
    cj._SEM_SIZES.clear()
    cj._RECENT_FP.clear()
    monkeypatch.setattr(kie_create.kie_http, "kie_configured", lambda: True)
    monkeypatch.setattr(kie_create.kie_http, "run_generation", fake_run)
    monkeypatch.setattr(kie_create.pay52_video, "pay52_video_configured", lambda spec=None: False)

    client = TestClient(_app())
    r = client.post(
        "/api/kie-create/generate",
        json={"model_id": family["id"], "mode": mode["id"], "values": values},
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["job"]["job_id"]
    est = data["estimate"]
    assert est["kie_id"] == mode["kie_id"]
    assert est["unit"] == mode["pricing"]["unit"]
    if est["usd_client"] is not None:
        assert est["usd_client"] == pytest.approx(est["usd_kie"] * 1.25, abs=0.01)
    if mode.get("api") == "jobs":
        assert captured["payload"]["model"] == mode["kie_id"]
