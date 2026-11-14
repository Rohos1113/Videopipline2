"""Догрузка OpenAPI-схем docs.kie.ai для режимов, которых не было в docs-schemas.json.

Бесплатные GET публичных страниц документации (без ключа). Пишет
docs/kie-ai-raw/docs-schemas-extra.json в том же формате, что docs-schemas.json
(model_ids, path, method, fields, top_fields), чтобы build_kie_families.py мог их слить.

Запуск: python docs/fetch_kie_docs_extra.py [--force]
"""
from __future__ import annotations

import json
import re
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "docs" / "kie-ai-raw"
OUT = RAW / "docs-schemas-extra.json"

PAGES = {
    "https://docs.kie.ai/market/happyhorse/video-edit.md": "happyhorse/video-edit",
    "https://docs.kie.ai/veo3-api/get-veo-3-1080-p-video.md": "veo/get-1080p-video",
    "https://docs.kie.ai/market/gemini-omni-character.md": "gemini-omni-character",
    "https://docs.kie.ai/market/minimax-h3/reference-to-video.md": "minimax-h3/reference-to-video",
    "https://docs.kie.ai/market/kling/v2-1-master-text-to-video.md": "kling/v2-1-master-text-to-video",
    "https://docs.kie.ai/market/kling/v2-1-master-image-to-video.md": "kling/v2-1-master-image-to-video",
    "https://docs.kie.ai/market/kling/v2-1-pro.md": "kling/v2-1-pro",
    "https://docs.kie.ai/market/kling/v25-turbo-text-to-video-pro.md": "kling/v2-5-turbo-text-to-video-pro",
    "https://docs.kie.ai/market/kling/v25-turbo-image-to-video-pro.md": "kling/v2-5-turbo-image-to-video-pro",
    "https://docs.kie.ai/market/kling/motion-control.md": "kling-2.6/motion-control",
    "https://docs.kie.ai/market/pixverse/text-to-video.md": "pixverse-v6/text-to-video",
    "https://docs.kie.ai/market/pixverse/extend.md": "pixverse-v6/extend",
    "https://docs.kie.ai/market/pixverse/reference-to-video.md": "pixverse-v6/reference-to-video",
    "https://docs.kie.ai/runway-api/generate-ai-video.md": "runway",
    "https://docs.kie.ai/runway-api/extend-ai-video.md": "runway/extend-ai-video",
    "https://docs.kie.ai/suno-api/create-music-video.md": "ai-music-api/create-music-video",
    "https://docs.kie.ai/suno-api/cover-suno.md": "ai-music-api/cover-generate",
    "https://docs.kie.ai/market/wan/2-2-a14b-text-to-video-turbo.md": "wan/2-2-a14b-text-to-video-turbo",
    "https://docs.kie.ai/market/wan/2-2-a14b-speech-to-video-turbo.md": "wan/2-2-a14b-speech-to-video-turbo",
    "https://docs.kie.ai/market/wan/2-2-animate-move.md": "wan/2-2-animate-move",
    "https://docs.kie.ai/market/wan/2-5-text-to-video.md": "wan/2-5-text-to-video",
    "https://docs.kie.ai/market/wan/2-5-image-to-video.md": "wan/2-5-image-to-video",
    "https://docs.kie.ai/market/wan/2-6-text-to-video.md": "wan/2-6-text-to-video",
    "https://docs.kie.ai/market/wan/2-6-video-to-video.md": "wan/2-6-video-to-video",
    "https://docs.kie.ai/market/wan/2-6-flash-image-to-video.md": "wan/2-6-flash-image-to-video",
    "https://docs.kie.ai/market/wan/2-6-flash-video-to-video.md": "wan/2-6-flash-video-to-video",
    "https://docs.kie.ai/market/wan/2-7-r2v.md": "wan/2-7-r2v",
    "https://docs.kie.ai/market/wan/2-7-videoedit.md": "wan/2-7-videoedit",
    "https://docs.kie.ai/market/omnihuman-1-5/human-identification.md": "omnihuman-1-5/human-identification",
    "https://docs.kie.ai/market/omnihuman-1-5/subject-detection.md": "omnihuman-1-5/subject-detection",
    # контрольная страница: mask_url у ideogram/v3-edit (в families.json уже есть)
    "https://docs.kie.ai/market/ideogram/v3-edit.md": "ideogram/v3-edit",
}


def fetch(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (docs-schema-fetch)"})
    with urllib.request.urlopen(req, timeout=40) as resp:  # noqa: S310
        return resp.read().decode("utf-8", errors="replace")


def yaml_block(md: str) -> str | None:
    blocks = re.findall(r"```yaml\s*\n(.*?)```", md, re.S)
    return blocks[0] if blocks else None


def unescape_props(schema: dict) -> dict:
    """OpenAPI → поля в формате docs-schemas.json.

    Поддерживает input как anyOf/oneOf/allOf: свойства объединяются, обязательность —
    общая для всех веток; поля, обязательные только в части веток, получают hint.
    """
    fields = []
    required_common: set[str] = set()
    required_variant: set[str] = set()
    variants = schema.get("anyOf") or schema.get("oneOf")
    if isinstance(variants, list) and variants:
        merged: dict = {}
        variant_reqs: list[set[str]] = []
        for variant in variants:
            if not isinstance(variant, dict):
                continue
            for name, spec in (variant.get("properties") or {}).items():
                extra = dict(spec or {})
                desc = (extra.get("description") or "").strip()
                if name in merged and "variant" in desc.lower():
                    continue
                merged.setdefault(name, extra)
            variant_reqs.append(set(variant.get("required") or []))
        required_common = set.intersection(*variant_reqs) if variant_reqs else set()
        required_all: set[str] = set().union(*variant_reqs) if variant_reqs else set()
        required_variant = required_all - required_common
        props = merged
        top_required = required_common
    else:
        props = schema.get("properties") or {}
        top_required = set(schema.get("required") or [])

    for name, spec in props.items():
        if not isinstance(spec, dict):
            continue
        spec = dict(spec)
        if "enum" in spec and isinstance(spec["enum"], list):
            enum = [str(v) for v in spec["enum"]]
        elif str(spec.get("type")) == "string" and "examples" in spec and name in ("model",):
            enum = [str(v) for v in spec["examples"]]
        else:
            enum = None
        desc = spec.get("description")
        field = {
            "name": name,
            "type": spec.get("type"),
            "required": name in top_required,
            "default": spec.get("default"),
            "enum": enum,
            "description": desc,
            "minimum": spec.get("minimum"),
            "maximum": spec.get("maximum"),
            "minLength": spec.get("minLength"),
            "maxLength": spec.get("maxLength"),
            "minItems": spec.get("minItems"),
            "maxItems": spec.get("maxItems"),
            "items_type": ((spec.get("items") or {}) or {}).get("type") if isinstance(spec.get("items"), dict) else None,
            "format": spec.get("format"),
            "subprops": None,
        }
        if name in required_variant:
            field["hint"] = "обязателен в одной из взаимоисключающих веток input"
        fields.append(field)
    return fields


def parse_page(url: str, md: str) -> dict | None:
    import yaml

    raw = yaml_block(md)
    if not raw:
        return None
    spec = yaml.safe_load(raw)
    if not isinstance(spec, dict):
        return None
    paths = spec.get("paths") or {}
    for path, item in paths.items():
        for method, op in (item or {}).items():
            if method.lower() != "post":
                continue
            rb = op.get("requestBody") or {}
            content = ((rb.get("content") or {}).get("application/json") or {}).get("schema") or {}
            if "$ref" in content:
                name = content["$ref"].split("/")[-1]
                content = ((spec.get("components") or {}).get("schemas") or {}).get(name) or {}
            top_props = content.get("properties") or {}
            input_schema = top_props.get("input") or {}
            if "$ref" in input_schema:
                name = input_schema["$ref"].split("/")[-1]
                input_schema = ((spec.get("components") or {}).get("schemas") or {}).get(name) or {}
            if not input_schema and top_props:
                # страницы без обёртки input: свойства лежат прямо в схеме запроса
                skip = {"model", "callBackUrl", "callbackUrl"}
                direct = {k: v for k, v in top_props.items() if k not in skip}
                if direct:
                    input_schema = {"properties": direct,
                                    "required": [r for r in (content.get("required") or []) if r not in skip]}
            model_ids = []
            model_spec = top_props.get("model") or {}
            for cand in (model_spec.get("enum"), model_spec.get("examples")):
                if isinstance(cand, list) and cand:
                    model_ids = [str(v) for v in cand]
                    break
            return {
                "model_ids": model_ids,
                "path": path,
                "method": method.upper(),
                "fields": unescape_props(input_schema) if input_schema else [],
                "top_fields": unescape_props(content) if content else [],
            }
    return None


def main() -> int:
    force = "--force" in sys.argv
    existing = json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() and not force else {}
    out = dict(existing)
    for url, kie_id in PAGES.items():
        if not force and url in out and out[url].get("model_ids"):
            continue
        try:
            md = fetch(url)
        except Exception as exc:  # noqa: BLE001
            print(f"FAIL fetch {url}: {exc}")
            continue
        page = parse_page(url, md)
        if not page:
            print(f"FAIL parse {url}")
            continue
        if not page["model_ids"]:
            page["model_ids"] = [kie_id]
        out[url] = page
        print(f"ok {kie_id:<45} fields={len(page['fields']):>2} path={page['path']} "
              f"models={page['model_ids'][:2]}")
        time.sleep(0.25)
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print("written:", OUT, "pages:", len(out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
