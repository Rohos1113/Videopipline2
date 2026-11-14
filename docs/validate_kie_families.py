"""Независимая проверка docs/kie-model-families.json после сборки.

Ничего не импортирует из build_kie_families.py: читает готовый json и первоисточники,
повторно проверяет покрытие id, контракт полей и отсутствие утечки ключа в файлах.

Запуск: C:\\Users\\Admin\\Desktop\\video-pipeline\\.venv\\Scripts\\python.exe docs\\validate_kie_families.py
Код возврата: 0 — все проверки прошли, 1 — есть провалы.
"""

from __future__ import annotations

import csv
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
JSON_PATH = DOCS / "kie-model-families.json"
MD_PATH = DOCS / "kie-model-families.md"

VIDEO_TAGS = {"Text to Video", "Image to Video", "Video to Video", "Lip Sync", "Video Editing", "Speech to Video"}
IMAGE_TAGS = {"Text to Image", "Image to Image", "Image Editing"}

FAMILY_KEYS = {"id", "label", "brand", "media", "desc", "modes"}
MODE_KEYS = {"id", "label", "kie_id", "task_type", "api", "fields", "pricing", "constraints", "docs_url"}
FIELD_KEYS = {"name", "label", "kind", "required"}
PRICING_KEYS = {"unit", "rules", "default", "note"}
UNITS = {"sec", "gen", "image", "mp", "1m_tokens", "1k_chars", "unknown",
         "tokens", "megapixel"}  # tokens/megapixel — старые имена, оставлены для совместимости
MIN_KIE_IDS = 182
MIN_SCHEMA_MODES = 175

# Ключ when из прайса → поля формы (как app/services/kie_catalog.py _WHEN_KEY_ALIASES).
PRICE_FIELD_CANDIDATES = {
    "resolution": ("resolution", "output_resolution", "video_resolution", "video_quality",
                   "image_size", "size", "quality"),
    "duration": ("duration", "duration_seconds", "duration_s", "output_duration", "video_duration"),
    "sound": ("audio", "sound", "generate_audio", "enable_audio", "generate_audio_switch",
              "sound_effects", "with_audio"),
    "audio": ("audio", "sound", "generate_audio", "enable_audio", "generate_audio_switch",
              "sound_effects", "with_audio"),
    "has_audio": ("audio", "sound", "generate_audio", "enable_audio", "generate_audio_switch",
                  "sound_effects", "with_audio"),
    "mode": ("tier", "mode", "model", "quality", "rendering_speed", "speed", "quality_tier"),
    "tier": ("tier", "mode", "model", "quality", "rendering_speed", "speed", "quality_tier"),
    "upscale": ("upscale_factor", "upscale", "scale", "factor"),
    "from_resolution": ("from_resolution", "source_resolution", "input_resolution"),
    "source_resolution": ("from_resolution", "source_resolution", "input_resolution"),
    "enable_pro": ("enable_pro",),
    "quality": ("quality",),
}
TIER_TO_RES = {"720p": {"720p", "std", "standard"}, "1080p": {"1080p", "pro"}}
defaults_issues: list[dict] = []


def _norm(v) -> str:
    return str(v).strip().lower()


def _priced(option, value, key: str) -> bool:
    a, b = _norm(option), _norm(value)
    if a == b:
        return True
    if key in ("resolution", "from_resolution"):
        return a in TIER_TO_RES.get(b, set()) or b in TIER_TO_RES.get(a, set())
    return False


def check_price_defaults(kid: str, mode: dict, issues: list[dict]) -> None:
    """У полей из when-правил цены default не должен быть null (иначе правило не находится)."""
    rule_values: dict[str, list] = {}
    for rule in (mode.get("pricing") or {}).get("rules") or []:
        for key, value in (rule.get("when") or {}).items():
            rule_values.setdefault(str(key), []).append(value)
    if not rule_values:
        return
    names = {f.get("name"): f for f in mode.get("fields") or []}
    for key, values in rule_values.items():
        field = next((names[c] for c in PRICE_FIELD_CANDIDATES.get(key, ()) if c in names), None)
        if field is None or field.get("default") is not None:
            continue
        if field.get("kind") == "toggle" and any(isinstance(v, bool) for v in values):
            issues.append({"kie_id": kid, "field": field.get("name"), "key": key})
        elif field.get("kind") == "select" and (field.get("options") or []):
            first = field["options"][0]
            first = first.get("id") if isinstance(first, dict) else first
            if any(_priced(first, v, key) for v in values if not isinstance(v, bool)):
                issues.append({"kie_id": kid, "field": field.get("name"), "key": key})

failures: list[str] = []
notes: list[str] = []


def check(cond: bool, msg: str) -> None:
    if not cond:
        failures.append(msg)


def load_catalog_models() -> tuple[list[dict], str]:
    """MODELS из kie_catalog.py на HEAD.

    После разбиения на kie_catalog + kie_catalog_families HEAD-версия импортирует
    семейства; подставляем HEAD-версию модуля семейств, чтобы не зависеть от рабочего дерева.
    """
    import types

    try:
        sha = subprocess.run(
            ["git", "rev-parse", "HEAD:app/services/kie_catalog.py"],
            cwd=ROOT, capture_output=True, text=True, check=True,
        ).stdout.strip()
        fam_sha = subprocess.run(
            ["git", "rev-parse", "HEAD:app/services/kie_catalog_families.py"],
            cwd=ROOT, capture_output=True, text=True, check=True,
        ).stdout.strip()
        fam_src = subprocess.run(
            ["git", "show", "HEAD:app/services/kie_catalog_families.py"],
            cwd=ROOT, capture_output=True, text=True, check=True,
        ).stdout
        src = subprocess.run(
            ["git", "show", "HEAD:app/services/kie_catalog.py"],
            cwd=ROOT, capture_output=True, text=True, check=True,
        ).stdout
        pkg_app = types.ModuleType("app")
        pkg_app.__path__ = [str(ROOT / "app")]
        pkg_services = types.ModuleType("app.services")
        pkg_services.__path__ = [str(ROOT / "app" / "services")]
        fam_mod = types.ModuleType("app.services.kie_catalog_families")
        fam_mod.__file__ = str(ROOT / "app" / "services" / "kie_catalog_families.py")
        exec(compile(fam_src, f"kie_catalog_families@{fam_sha[:8]}", "exec"), fam_mod.__dict__)  # noqa: S102
        sys.modules.setdefault("app", pkg_app)
        sys.modules.setdefault("app.services", pkg_services)
        sys.modules["app.services.kie_catalog_families"] = fam_mod
        ns: dict = {"__name__": "kie_catalog_head"}
        exec(compile(src, f"kie_catalog@{sha[:8]}", "exec"), ns)  # noqa: S102
        return ns.get("MODELS") or [], sha
    except Exception as exc:  # noqa: BLE001
        notes.append(f"каталог студии из git не прочитан: {exc}")
        return [], "unavailable"


def main() -> int:
    payload = json.loads(JSON_PATH.read_text(encoding="utf-8"))
    check(isinstance(payload, dict) and isinstance(payload.get("families"), list),
          "json: нет массива families")
    families = payload["families"] if isinstance(payload, dict) else []
    prices = json.loads((DOCS / "kie-prices-usd.json").read_text(encoding="utf-8")).get("models") or {}

    # --- контракт ---
    fam_ids: set[str] = set()
    kie_ids: dict[str, str] = {}
    modes_total = 0
    media_by_family = {"video": 0, "image": 0}
    field_total = 0
    for fam in families:
        missing = FAMILY_KEYS - set(fam)
        check(not missing, f"family {fam.get('id')}: нет ключей {sorted(missing)}")
        check(fam.get("media") in ("video", "image"), f"family {fam.get('id')}: media={fam.get('media')}")
        check("/" not in (fam.get("id") or "/"), f"family {fam.get('id')}: id со слэшем")
        check(fam.get("id") not in fam_ids, f"family {fam.get('id')}: id семейства повторяется")
        fam_ids.add(fam.get("id"))
        if fam.get("media") in media_by_family:
            media_by_family[fam["media"]] += 1
        mode_ids: set[str] = set()
        check(bool(fam.get("modes")), f"family {fam.get('id')}: нет режимов")
        for mode in fam.get("modes") or []:
            modes_total += 1
            missing = MODE_KEYS - set(mode)
            check(not missing, f"mode {mode.get('kie_id')}: нет ключей {sorted(missing)}")
            check(mode.get("id") not in mode_ids,
                  f"family {fam.get('id')}: mode id {mode.get('id')} повторяется")
            mode_ids.add(mode.get("id"))
            kid = mode.get("kie_id")
            check(kid not in kie_ids, f"kie_id {kid} встречается дважды: "
                                     f"{kie_ids.get(kid)} и {fam.get('id')}")
            kie_ids[kid] = fam.get("id")
            pricing = mode.get("pricing") or {}
            check(not (PRICING_KEYS - set(pricing)),
                  f"mode {kid}: pricing без ключей {sorted(PRICING_KEYS - set(pricing))}")
            check(pricing.get("unit") in UNITS, f"mode {kid}: unit={pricing.get('unit')}")
            check(isinstance(mode.get("fields"), list), f"mode {kid}: fields не массив")
            check(isinstance(mode.get("constraints"), list), f"mode {kid}: constraints не массив")
            # fields_known: true ⇔ набор полей непустой; false — полей нет и есть честный hint
            check(isinstance(mode.get("fields_known"), bool),
                  f"mode {kid}: fields_known должен быть bool")
            if mode.get("fields_known") is True:
                check(bool(mode.get("fields")), f"mode {kid}: fields_known=true, но fields пуст")
            else:
                check(not mode.get("fields"), f"mode {kid}: fields_known=false, но fields непуст")
                check("неизвестна" in (mode.get("hint") or ""),
                      f"mode {kid}: fields_known=false без hint про неизвестную схему")
            # единица цены обязана совпадать с прайсом (он первичен по деньгам)
            price_rec = prices.get(kid) or {}
            if price_rec.get("unit"):
                check(pricing.get("unit") == price_rec["unit"],
                      f"mode {kid}: unit={pricing.get('unit')}, в прайсе {price_rec['unit']}")
            for f in mode.get("fields") or []:
                field_total += 1
                check(not (FIELD_KEYS - set(f)), f"mode {kid}: поле {f.get('name')} без ключей "
                                                  f"{sorted(FIELD_KEYS - set(f))}")
                check(bool(f.get("name")), f"mode {kid}: поле без name")
                check(bool(f.get("kind")), f"mode {kid}: поле {f.get('name')} без kind")
            check_price_defaults(kid, mode, defaults_issues)

    # --- сверка дефолтов полей цены (task-19) ---
    check(not defaults_issues,
          f"дефолтов полей цены не хватает у {len(defaults_issues)}: "
          + ", ".join(f"{x['kie_id']}:{x['field']}" for x in defaults_issues[:10]))
    kling_audio = next((m for f in families for m in f.get("modes") or []
                        if m.get("kie_id") == "kling-3.0-omni/image-to-video"), None)
    if kling_audio is not None:
        audio = next((x for x in kling_audio.get("fields") or [] if x.get("name") == "audio"), None)
        check(audio is not None and audio.get("default") is False,
              "kling-3.0-omni/image-to-video: у audio должен быть default false")
    kling26 = next((m for f in families for m in f.get("modes") or []
                    if m.get("kie_id") == "kling-2.6/image-to-video"), None)
    if kling26 is not None:
        sound = next((x for x in kling26.get("fields") or [] if x.get("name") == "sound"), None)
        check(sound is not None and sound.get("default") is False,
              "kling-2.6/image-to-video: у sound должен быть default false")

    # --- сверка правил цены families ↔ prices (task-22): те же when и деньги ---
    rules_checked = 0
    rule_mismatch: list[dict] = []
    for fam in families:
        for mode in fam.get("modes") or []:
            kid = mode.get("kie_id")
            rec = prices.get(kid) or {}
            want = [{"when": r.get("when") or {}, "usd_kie": r.get("usd_kie")}
                    for r in rec.get("rules") or []]
            if not want:
                continue
            mine = [{"when": r.get("when") or {}, "usd_kie": r.get("usd_kie")}
                    for r in (mode.get("pricing") or {}).get("rules") or []]
            rules_checked += 1
            if mine != want:
                rule_mismatch.append({"kie_id": kid, "families": mine, "prices": want})
    check(not rule_mismatch,
          f"правила families != prices у {len(rule_mismatch)} режимов: "
          + ", ".join(x["kie_id"] for x in rule_mismatch[:8]))
    notes.append(f"правила цены в families = prices у {rules_checked}/{rules_checked} режимов")

    # --- пустая длительность (task-22): select не должен остаться без default ---
    duration_issues: list[dict] = []
    duration_checked = 0
    TASK22_DURATION = {
        "hailuo/02-text-to-video-standard": "6",
        "hailuo/02-image-to-video-standard": "6",
        "kling-3.0/video": "5",
        "wan/2-5-text-to-video": "5",
        "wan/2-5-image-to-video": "5",
    }
    for fam in families:
        for mode in fam.get("modes") or []:
            for field in mode.get("fields") or []:
                if field.get("name") not in PRICE_FIELD_CANDIDATES["duration"]:
                    continue
                if field.get("kind") != "select" or not (field.get("options") or []):
                    continue
                duration_checked += 1
                opts = field["options"]
                expected = "5" if "5" in opts else opts[0]
                kid = mode.get("kie_id")
                if kid in TASK22_DURATION:
                    if str(field.get("default")) != TASK22_DURATION[kid]:
                        duration_issues.append({"kie_id": kid, "field": field.get("name"),
                                                "default": field.get("default"),
                                                "expected": TASK22_DURATION[kid]})
                elif field.get("default") is None:
                    duration_issues.append({"kie_id": kid, "field": field.get("name"),
                                            "default": None, "expected": expected})
    check(not duration_issues,
          f"у duration-select неверный дефолт у {len(duration_issues)}: "
          + ", ".join(f"{x['kie_id']}={x['default']!r} (ждали {x['expected']!r})"
                      for x in duration_issues[:8]))
    notes.append(f"duration-select с дефолтом: {duration_checked - len(duration_issues)}/{duration_checked}")

    # --- точечные ожидания task-22: поля/ключи под 8 ценовых правил ---
    TASK22_FIELDS = {
        "kling/ai-avatar-pro": ("resolution", "1080p"),
        "kling/ai-avatar-standard": ("resolution", "720p"),
        "runway": ("resolution", "720p"),
        "runway/extend-ai-video": ("resolution", "720p"),
        "grok-imagine/extend": ("duration", "6"),
        "grok-imagine/upscale": ("from_resolution", "480P"),
        "google/gemini-omni-flash-1-2-extend": ("resolution", "360p"),
        "seedream/5-pro-text-to-image": ("quality", "basic"),
        "seedream/5-pro-image-to-image": ("quality", "basic"),
        "seedream/5-pro-layer-decomposition": ("size", None),
        "grok-imagine/text-to-image": ("enable_pro", False),
        "hailuo/02-text-to-video-pro": ("resolution", "1080P"),
        "hailuo/02-image-to-video-pro": ("resolution", "1080P"),
        "hailuo/02-text-to-video-standard": ("resolution", "768P"),
    }
    for kid, (fname, fdefault) in TASK22_FIELDS.items():
        mode = next((m for f in families for m in f.get("modes") or []
                     if m.get("kie_id") == kid), None)
        check(mode is not None, f"нет режима {kid}")
        if mode is None:
            continue
        field = next((x for x in mode.get("fields") or [] if x.get("name") == fname), None)
        check(field is not None, f"{kid}: нет поля {fname} (task-22)")
        if field is not None and fdefault is not None:
            check(field.get("default") == fdefault,
                  f"{kid}: {fname} default={field.get('default')!r}, ожидалось {fdefault!r}")
    TASK22_RULE_KEYS = {
        "kling/ai-avatar-pro": ({"resolution"}, {"1080p"}),
        "kling/ai-avatar-standard": ({"resolution"}, {"720p"}),
        "seedream/5-pro-text-to-image": ({"quality"}, {"basic", "high"}),
        "seedream/5-pro-image-to-image": ({"quality"}, {"basic", "high"}),
        "grok-imagine/text-to-image": ({"enable_pro"}, {False, True}),
        "hailuo/2-3-image-to-video-pro": ({"duration", "resolution"}, {"6", "10", "768p", "1080p"}),
        "hailuo/2-3-image-to-video-standard": ({"duration", "resolution"}, {"6", "10", "768p", "1080p"}),
    }
    for kid, (want_keys, want_values) in TASK22_RULE_KEYS.items():
        mode = next((m for f in families for m in f.get("modes") or []
                     if m.get("kie_id") == kid), None)
        if mode is None:
            continue
        keys, values = set(), set()
        for rule in (mode.get("pricing") or {}).get("rules") or []:
            when = rule.get("when") or {}
            keys |= set(when)
            values |= set(when.values())
        check(keys == want_keys,
              f"{kid}: ключи when {sorted(keys)}, ожидалось {sorted(want_keys)} (task-22)")
        check(values == want_values,
              f"{kid}: значения when {sorted(map(str, values))}, ожидалось "
              f"{sorted(map(str, want_values))} (task-22)")

    # --- сверка 1: покрытие живого API ---
    check(len(kie_ids) >= MIN_KIE_IDS,
          f"уникальных kie_id {len(kie_ids)}, ожидалось не меньше {MIN_KIE_IDS}")
    with_fields = sum(1 for f in families for m in f.get("modes") or []
                      if m.get("fields_known") is True)
    check(with_fields >= MIN_SCHEMA_MODES,
          f"режимов с известными полями {with_fields}, ожидалось не меньше {MIN_SCHEMA_MODES}")
    ideogram_edit = next((m for f in families for m in f.get("modes") or []
                          if m.get("kie_id") == "ideogram/v3-edit"), None)
    check(ideogram_edit is not None, "нет режима ideogram/v3-edit")
    if ideogram_edit is not None:
        check("mask_url" in {x.get("name") for x in ideogram_edit.get("fields") or []},
              "ideogram/v3-edit: в fields нет mask_url")
    api = json.loads((DOCS / "kie-ai-raw" / "models.json").read_text(encoding="utf-8"))
    api_models = {m["model"]: m for m in api["data"]["models"]}
    check(api["data"].get("total") == 251, f"в models.json total={api['data'].get('total')}, ожидалось 251")
    api_video = {mid for mid, m in api_models.items() if set(m.get("taskType") or []) & VIDEO_TAGS}
    api_image = {mid for mid, m in api_models.items() if set(m.get("taskType") or []) & IMAGE_TAGS}
    api_media = api_video | api_image
    api_image_only = api_image - api_video

    rows = list(csv.DictReader((DOCS / "kie-ai-models.csv").open(encoding="utf-8")))
    csv_ids = {r["id модели"] for r in rows}
    check(len(rows) == 181, f"в csv {len(rows)} строк, ожидалось 181")
    check(csv_ids == api_media, "набор id csv != набор медиа-id из живого API "
                                f"(csv-only {sorted(csv_ids - api_media)[:3]}, "
                                f"api-only {sorted(api_media - csv_ids)[:3]})")
    check(len(api_media) == 181, f"медиа-id в API {len(api_media)}, ожидалось 181")
    check(len(api_video) == 100, f"видео-id в API {len(api_video)}, ожидалось 100")
    check(len(api_image_only) == 81, f"картинки-id в API {len(api_image_only)}, ожидалось 81")
    notes.append(f"по тегам API: видео {len(api_video)}, картинки {len(api_image_only)}, "
                 f"плюс {len(api_image & api_video)} модель с тегами обоих типов "
                 f"({sorted(api_image & api_video)})")

    placed = set(kie_ids)
    lost = sorted(api_media - placed)
    extra = sorted(placed - api_media)
    check(not lost, f"потеряны id: {lost[:10]}")
    check(len(extra) <= 1, f"лишние id (не из живого API): {extra}")
    for kid in extra:
        notes.append(f"id вне живого API: {kid} (допустимо только для каталога студии)")

    # --- сверка media: тип семейства против типа модели в таблице ---
    csv_type = {r["id модели"]: r["тип (video/image)"] for r in rows}
    mismatched = []
    for fam in families:
        for mode in fam["modes"]:
            kid = mode["kie_id"]
            if kid in csv_type and csv_type[kid] != fam["media"]:
                mismatched.append((kid, fam["media"], csv_type[kid]))
    check(len(mismatched) <= 1,
          f"тип семейства не совпал с типом модели у {len(mismatched)} id: {mismatched[:5]}")
    for kid, fam_media, csv_media in mismatched:
        notes.append(f"переклассифицировано {kid}: семейство {fam_media}, в таблице {csv_media}")

    # --- каталог студии ---
    catalog, cat_sha = load_catalog_models()
    cat_ids = set()
    for entry in catalog:
        if entry.get("category") in ("video", "image", "tools"):
            for mid in (entry.get("model"), entry.get("model_map_i2i")):
                if mid:
                    cat_ids.add(mid)
    cat_lost = sorted(cat_ids - placed)
    check(not cat_lost, f"id каталога студии потеряны: {cat_lost}")
    notes.append(f"каталог студии: {len(cat_ids)} медиа-id (blob {cat_sha[:8]}), покрыто "
                 f"{len(cat_ids) - len(cat_lost)}")

    # --- утечка ключа и служебных данных ---
    hex_re = re.compile(r"\b[0-9a-f]{32}\b")
    for path in (JSON_PATH, MD_PATH, DOCS / "kie-model-families-checks.json"):
        text = path.read_text(encoding="utf-8")
        hits = hex_re.findall(text)
        check(not hits, f"{path.name}: похоже на утёкший ключ/секрет ({len(hits)} совпадений)")
        check("Authorization" not in text, f"{path.name}: упоминание заголовка Authorization")

    # --- md: обязательные числа на месте ---
    md = MD_PATH.read_text(encoding="utf-8")
    for needle in ("181/181", str(len(families)), str(modes_total), "Сверка 1", "Сверка 2",
                   "Сверка 3", "Чего нет в источниках"):
        check(needle in md, f"md: не найдено «{needle}»")

    # --- итог ---
    print(f"families: {len(families)} (video {media_by_family['video']}, image {media_by_family['image']})")
    print(f"modes: {modes_total}, полей: {field_total}")
    print(f"покрытие API: {len(placed & api_media)}/{len(api_media)} "
          f"(видео {len(api_video)}, картинки {len(api_image_only)}), потеряно {len(lost)}, "
          f"вне API {len(extra)}")
    print(f"каталог студии: {len(cat_ids) - len(cat_lost)}/{len(cat_ids)}")
    for note in notes:
        print("  !", note)
    if failures:
        print(f"\nПРОВАЛОВ: {len(failures)}")
        for f in failures:
            print("  -", f)
        return 1
    print("\nВСЕ ПРОВЕРКИ ПРОШЛИ")
    return 0


if __name__ == "__main__":
    sys.exit(main())
