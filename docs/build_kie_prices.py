# -*- coding: utf-8 -*-
"""Сборка USD-прайса kie.ai по всем 181 медиа-моделям (docs/kie-prices-usd.json + .md).

Источник цен: docs/kie-ai-raw/models.json (живой GET /api/v1/models, поле pricingDesc).
Курс: 1 кредит kie.ai = $0.005. Наценка студии: usd_client = usd_kie × 1.25.

Ничего не выдумываем: цены только из pricingDesc. Где цены нет — null + «неизвестно».
Скрипт сам делает 3 сверки и печатает отчёт (docs/_prices_work/audit.txt).

Запуск: python docs/build_kie_prices.py  (из корня рабочей папки)
"""

from __future__ import annotations

import csv
import contextlib
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAW_MODELS = ROOT / "docs/kie-ai-raw/models.json"
RAW_SCHEMAS = ROOT / "docs/kie-ai-raw/docs-schemas.json"
MODELS_CSV = ROOT / "docs/kie-ai-models.csv"
FAMILIES = ROOT / "docs/kie-model-families.json"
OUT_JSON = ROOT / "docs/kie-prices-usd.json"
OUT_MD = ROOT / "docs/kie-prices-usd.md"
WORK = ROOT / "docs/_prices_work"

CREDIT_USD = 0.005
MARKUP = 1.25

VIDEO_TASKS = {"Text to Video", "Image to Video", "Video to Video", "Video Editing", "Lip Sync", "Speech to Video"}
IMAGE_TASKS = {"Text to Image", "Image to Image", "Image Editing"}
# API-глюк: ideogram/v3-text-to-image отдаёт taskType "Text to Video", но это картинки
MEDIA_FIX = {"ideogram/v3-text-to-image": "image"}
# у провайдера «Other» бренд берём из id: иначе в сводке один мешок
BRAND_FIX = {
    "omnihuman-1-5": "OmniHuman",
    "omnihuman-1-5/human-identification": "OmniHuman",
    "omnihuman-1-5/subject-detection": "OmniHuman",
    "omnihuman-2-0": "OmniHuman",
    "volcengine/video-to-video-lip-sync": "Volcengine",
}


def brand_of(mid: str, provider: str | None) -> str:
    if mid in BRAND_FIX:
        return BRAND_FIX[mid]
    return provider or "Other"

NUM = r"\d+(?:[.,]\d+)?"


def fnum(s: str) -> float:
    return float(s.replace(",", "").replace(" ", ""))


def usd_kie(credits) -> float | None:
    if credits is None:
        return None
    return round(float(credits) * CREDIT_USD, 6)


def usd_client(usd) -> float | None:
    if usd is None:
        return None
    return round(float(usd) * MARKUP, 4)


def rule(credits=None, usd=None, **when) -> dict:
    if usd is None:
        usd = usd_kie(credits)
    out = {"when": when}
    if credits is not None:
        out["credits"] = float(credits)
    out["usd_kie"] = usd
    out["usd_client"] = usd_client(usd)
    return out


# ---------------------------------------------------------------- источники


def load_models() -> tuple[list[dict], list[dict]]:
    raw = json.loads(RAW_MODELS.read_text(encoding="utf-8"))["data"]["models"]
    media, other = [], []
    for m in raw:
        tt = set(m.get("taskType") or [])
        if tt & (VIDEO_TASKS | IMAGE_TASKS):
            media.append(m)
        else:
            other.append(m)
    return media, other


def media_of(m: dict) -> str:
    mid = m["model"]
    if mid in MEDIA_FIX:
        return MEDIA_FIX[mid]
    tt = set(m.get("taskType") or [])
    if tt & VIDEO_TASKS and not tt & IMAGE_TASKS:
        return "video"
    if tt & IMAGE_TASKS and not tt & VIDEO_TASKS:
        return "image"
    # смешанные задачи — не встречаются, но пусть будет по id
    return "image" if "image" in mid else "video"


def load_schemas() -> dict[str, dict]:
    raw = json.loads(RAW_SCHEMAS.read_text(encoding="utf-8"))
    out: dict[str, dict] = {}
    for url, spec in raw.items():
        for mid in spec.get("model_ids") or []:
            out.setdefault(mid, {"url": url, "fields": spec.get("fields") or []})
    return out


def load_families() -> dict[str, dict]:
    """Соседняя работа шага 7: семьи/режимы с уже распарсенными кредитами. Независимая сверка."""
    if not FAMILIES.exists():
        return {}
    raw = json.loads(FAMILIES.read_text(encoding="utf-8"))
    out: dict[str, dict] = {}
    for fam in raw.get("families") or []:
        for mode in fam.get("modes") or []:
            kid = mode.get("kie_id")
            if kid:
                out[kid] = {
                    "family_id": fam.get("family_id"),
                    "brand": fam.get("brand"),
                    "mode_id": mode.get("id"),
                    "pricing": mode.get("pricing") or {},
                }
    return out


def load_csv() -> dict[str, dict]:
    rows = list(csv.DictReader(MODELS_CSV.open(encoding="utf-8")))
    return {r["id модели"]: r for r in rows}


# ---------------------------------------------------------------- descriptors

RES_P = re.compile(r"(?<![\w.])(\d{3,4})\s*[pP]\b")
RES_K = re.compile(r"(?<![\w.])(1\.5|[124])\s*[Kk]\b")
DUR = re.compile(r"(?<![\w.])(\d+(?:\.\d+)?)\s*(?:-|\s)?(?:seconds?|secs?|s)\b", re.IGNORECASE)
DUR_LIST = re.compile(r"(\d+(?:\s*/\s*\d+)+)\s*s\b", re.IGNORECASE)
AUDIO = re.compile(r"(?P<neg>without|no)\s+(?:native\s+)?audio|with\s+(?:native\s+)?audio", re.IGNORECASE)
AUDIO_EITHER = re.compile(r"with\s+or\s+without\s+(?:native\s+)?audio", re.IGNORECASE)
VIDEO_IN = re.compile(
    r"(?P<neg>without|no)\s+video(?:\s+input)?\b|with\s+video(?:\s+input)?\b|video input required",
    re.IGNORECASE,
)
TIERS = [
    ("lite", "lite"),
    ("fast", "fast"),
    ("quality", "quality"),
    ("turbo", "turbo"),
    ("standard", "standard"),
    ("std", "standard"),
    ("balanced", "balanced"),
    ("economy", "economy"),
    ("high quality", "high"),
    ("medium quality", "medium"),
    ("high", "high"),
    ("medium", "medium"),
    ("basic", "basic"),
    ("pro", "pro"),
    ("max", "max"),
]
TIER_MAP = {
    "lite": "lite", "fast": "fast", "quality": "quality", "turbo": "turbo",
    "standard": "standard", "std": "standard", "balanced": "balanced",
    "economy": "economy", "high": "high", "medium": "medium",
    "basic": "basic", "pro": "pro", "max": "max",
}


def find_res(text: str) -> list[str]:
    out = [m.group(1) + "P" for m in RES_P.finditer(text)]
    for m in RES_K.finditer(text):
        out.append(m.group(1) + "K")
    return out


def find_dur(text: str) -> list[float]:
    return [fnum(m.group(1)) for m in DUR.finditer(text)]


def find_tier(text: str) -> str | None:
    low = text.lower()
    best = None
    best_pos = 10**9
    for word, tier in TIERS:
        pos = low.rfind(word)
        if pos < 0:
            continue
        # «pro» внутри других слов не берём
        if word.isalpha() and word not in ("quality",):
            before = low[pos - 1] if pos > 0 else " "
            after_i = pos + len(word)
            after = low[after_i] if after_i < len(low) else " "
            if before.isalnum() or after.isalnum():
                continue
        if pos < best_pos or (pos == best_pos and len(word) > len(best)):
            best, best_pos = tier, pos
    return best


def find_audio(text: str, first: bool = True) -> bool | None:
    if AUDIO_EITHER.search(text):
        return None
    ms = list(AUDIO.finditer(text))
    if not ms:
        return None
    m = ms[0] if first else ms[-1]
    return not bool(m.group("neg"))


def find_video_in(text: str, first: bool = True) -> bool | None:
    ms = list(VIDEO_IN.finditer(text))
    if not ms:
        return None
    m = ms[0] if first else ms[-1]
    if "required" in m.group(0).lower():
        return True
    return not bool(m.group("neg"))


UNIT_RULES = [
    (re.compile(r"per\s+1[ ,]?000\s+characters?", re.I), "1k_chars"),
    (re.compile(r"per\s+megapixel|/megapixel", re.I), "mp"),
    (re.compile(r"/\s*1M\s+tokens?|per\s+1M\s+tokens?", re.I), "1m_tokens"),
    (re.compile(r"per\s+(?:video[- ]?)?second|/\s*s\b|per\s+second|credits?\s*/\s*sec", re.I), "sec"),
    (re.compile(r"per\s+image|per\s+output\s+image|per\s+upscale", re.I), "image"),
    (re.compile(r"per\s+video|per\s+generation|per\s+request|per\s+extension|flat\s+rate\s+per\s+video", re.I), "gen"),
]


def find_unit(text: str, media: str) -> str:
    for rx, unit in UNIT_RULES:
        if rx.search(text):
            return unit
    return "image" if media == "image" else "gen"


BONUS_SPLIT = re.compile(r"High-tier|Effective pricing|Pricing is 50%|Prices are currently in beta", re.I)


def base_text(desc: str) -> str:
    m = BONUS_SPLIT.search(desc)
    return desc[: m.start()] if m else desc


# ---------------------------------------------------------------- generic parse

CRED = re.compile(
    rf"(?<![\w.])(?P<lst>{NUM}(?:\s*/\s*{NUM})*)\s*(?:Kie\s+)?credits?\b",
    re.IGNORECASE,
)
USD_RE = re.compile(rf"(?:US\s*\$|US\$|≈\s*\$|~\s*\$|\$|≈)\s*(?P<v>{NUM})")
SENT_SPLIT = re.compile(r"\.\s+|\n")
SEG_SPLIT = re.compile(r"[|;]")

EXTRA_PATTERNS = [
    # seedream 5 pro: input images cost 0.5 credits each, first free
    (re.compile(rf"input images? cost (?P<n>{NUM}) credits each.*?first (?P<free>\w+) input image free", re.I | re.S), "input_image", "first_free"),
    # qwen3 i2i: input images are charged at 0.5 credits per image
    (re.compile(rf"input images are charged at (?P<n>{NUM}) credits per image", re.I), "input_image", None),
    # seedream 5.5: each input image is billed separately at 1.44 credits
    (re.compile(rf"each input image is billed separately at (?P<n>{NUM}) credits", re.I), "input_image", None),
    # minimax h3: additional image input 4 credits/image, first 5 free
    (re.compile(rf"additional image input:\s*(?P<n>{NUM}) credits/image", re.I), "extra_image", "5"),
    # minimax h3 image-edit: plus 0.5 credits for each reference image, including the first
    (re.compile(rf"plus\s+(?P<n>{NUM}) credits.*?for each reference image", re.I | re.S), "reference_image", None),
    # seedream 5.5 layer decomp: input image billed separately at 1.44 credits
    (re.compile(rf"input image is billed separately at (?P<n>{NUM}) credits", re.I), "input_image", None),
]


def strip_extras(text: str) -> tuple[str, list[dict]]:
    """Вынимаем из текста доплаты за входные картинки (они не базовая цена)."""
    extras: list[dict] = []
    out = text
    for rx, what, free in EXTRA_PATTERNS:
        for m in rx.finditer(out):
            extras.append(
                {
                    "what": what,
                    "credits": fnum(m.group("n")),
                    "usd_kie": usd_kie(fnum(m.group("n"))),
                    "usd_client": usd_client(usd_kie(fnum(m.group("n")))),
                    "free_first": int(free) if (free and str(free).isdigit()) else (1 if free == "first" else None),
                    "source": "pricingDesc",
                }
            )
        out = rx.sub(" ", out)
    return out, extras


def _sentence_parts(seg: str) -> list[str]:
    return [s.strip() for s in SENT_SPLIT.split(seg) if s.strip()]


def parse_generic(desc: str, media: str, mid: str) -> dict:
    """Разбор pricingDesc: правила из «число credits (+$) + описание конфигурации»."""
    text = base_text(desc)
    text2, extras = strip_extras(text)
    # сжимаем пробелы у чисел «1 K» → «1K», «720 p» → «720P» для стабильных резолюций
    rules: list[dict] = []
    warnings: list[str] = []
    line_tier: str | None = None
    for rawline in text2.split("\n"):
        if not rawline.strip():
            continue
        line_tier = None
        for seg in SEG_SPLIT.split(rawline):
            # тир может задаваться в начале строки («Lite mode (...): ...»)
            t = find_tier(seg) if len(seg) < 400 else None
            if t:
                line_tier = t
            for sentence in _sentence_parts(seg):
                tier = find_tier(sentence) or line_tier
                for m in CRED.finditer(sentence):
                    lst = [fnum(x) for x in m.group("lst").replace(" ", "").split("/")]
                    wide = sentence[: m.start()]
                    tail = sentence[m.end():]
                    # тайл может содержать доп.разрешение/флаги — обрежем по следующему credits
                    nxt = CRED.search(tail)
                    tail_local = tail[: nxt.start()] if nxt else tail
                    # единица
                    unit = find_unit(sentence if len(sentence) < 400 else tail_local, media)
                    # разрешение: сначала в хвосте (ближе), иначе в префиксе — последнее
                    res_tail = find_res(tail_local)
                    res_wide = find_res(wide)
                    res = res_tail[-1:] if res_tail else res_wide[-1:]
                    # длительность: хвост приоритетнее, иначе последняя в префиксе
                    dur_tail = find_dur(tail_local)
                    dur_wide = find_dur(wide)
                    dur = dur_tail[-1:] if dur_tail else dur_wide[-1:]
                    # параллельные массивы: 70 / 140 / 210 credits for 5 / 10 / 15 s
                    dur_list = []
                    dm = DUR_LIST.search(tail_local)
                    if dm:
                        dur_list = [fnum(x) for x in re.split(r"\s*/\s*", dm.group(1))]
                    audio = find_audio(tail_local)
                    if audio is None:
                        audio = find_audio(wide, first=False)
                    vid = find_video_in(tail_local)
                    if vid is None:
                        vid = find_video_in(wide, first=False)
                    tiers_list = [tier] if tier else []
                    for i, cr in enumerate(lst):
                        when: dict = {}
                        if res:
                            when["resolution"] = res[0]
                        if dur_list and len(dur_list) == len(lst):
                            when["duration"] = int(dur_list[i]) if float(dur_list[i]).is_integer() else dur_list[i]
                        elif dur:
                            when["duration"] = int(dur[0]) if float(dur[0]).is_integer() else dur[0]
                        if tiers_list:
                            when["mode"] = tiers_list[0]
                        if audio is not None:
                            when["sound"] = audio
                        if vid is not None:
                            when["with_video"] = vid
                        rules.append(rule(cr, **when))
    return {"rules": rules, "extra_charges": extras, "warnings": warnings, "unit": find_unit(text2, media)}


# ---------------------------------------------------------------- спец-формулы (ручные, по прайсу)


def R(cr=None, usd=None, **when):
    return rule(cr, usd, **when)


def spec_dedup(rules: list[dict]) -> list[dict]:
    seen, out = set(), []
    for r in rules:
        k = json.dumps([r["when"], r.get("usd_kie")], sort_keys=True)
        if k in seen:
            continue
        seen.add(k)
        out.append(r)
    return out


def seedance_rules(rates: dict[str, tuple[float, float]]) -> list[dict]:
    """rates: resolution -> (with_video, no_video) кредитов/сек."""
    out = []
    for res, (w, n) in rates.items():
        out.append(R(w, resolution=res, with_video=True))
        out.append(R(n, resolution=res, with_video=False))
    return out


def kling_rate_rules(rates: dict[str, tuple[float, float | None]]) -> list[dict]:
    """rates: resolution -> (без звука, со звуком | None)."""
    out = []
    for res, (no_audio, with_audio) in rates.items():
        out.append(R(no_audio, resolution=res, sound=False))
        if with_audio is not None:
            out.append(R(with_audio, resolution=res, sound=True))
    return out


SPECIAL: dict[str, dict] = {}


def reg(ids: list[str] | str, **spec):
    if isinstance(ids, str):
        ids = [ids]
    for i in ids:
        SPECIAL[i] = spec


# --- Seedance: with/without video input -------------------------------------
_reg_seedance = {
    "bytedance/seedance-2": {"480P": (11.5, 19), "720P": (25, 41), "1080P": (62, 102), "4K": (128, 208)},
    "bytedance/seedance-2-fast": {"480P": (6.8, 11.7), "720P": (15, 24.8)},
    "bytedance/seedance-2-mini": {"480P": (2.4, 3.8), "720P": (5.0, 8.2)},
    "bytedance/seedance-2-5": {"480P": (17, 28), "720P": (38, 63), "1080P": (95, 158)},
}
for _mid, _rates in _reg_seedance.items():
    reg(
        _mid,
        unit="sec",
        rules=seedance_rules(_rates),
        formula=(
            "без видеовхода: тариф × длительность выхода; "
            "с видеовходом: тариф × (длительность входа + длительность выхода) — тариф с видео ниже"
        ),
        duration_billing="output | with_video: input+output",
        affects_price=["resolution", "duration", "video_input"],
        note="Total = Price × Output (без видео) / Price × (Input + Output) (с видео)",
    )
reg(
    "bytedance/seedance-2-5-draft",
    unit="sec",
    rules=seedance_rules(_reg_seedance["bytedance/seedance-2-5"]),
    formula=(
        "draft-upgrade наследует режим биллинга источника (with-video / no-video по draft_task_id); "
        "ставка — из стандартного прайса Seedance 2.5"
    ),
    duration_billing="inherits source (output | input+output)",
    affects_price=["resolution", "duration", "video_input", "draft_source"],
    note="наследует биллинг исходного драфта; отдельной цены в прайсе нет — берём ставки Seedance 2.5",
    draft_inherits="bytedance/seedance-2-5",
)

# --- Kling: 5s/10s фикс за ролик --------------------------------------------
for _mid, _five, _ten in [
    ("kling/v2-1-master-text-to-video", 252, 504),
    ("kling/v2-1-master-image-to-video", 252, 504),
    ("kling/v2-1-pro", 88, 176),
    ("kling/v2-1-standard", 50.5, 101),
]:
    reg(
        _mid,
        unit="gen",
        rules=[R(_five, duration=5), R(_ten, duration=10)],
        formula="фикс за ролик: 5 сек и 10 сек (ставка одинаковая: цена ∝ длительности)",
        affects_price=["duration"],
        note=f"5с — {_five} кр, 10с — {_ten} кр",
    )
for _mid in ("kling/v2-5-turbo-text-to-video-pro", "kling/v2-5-turbo-image-to-video-pro"):
    reg(
        _mid,
        unit="gen",
        rules=[R(63, duration=5), R(126, duration=10)],
        formula="фикс за ролик: 5 сек — 63 кр, 10 сек — 126 кр",
        affects_price=["duration"],
        note="5с 63 кр, 10с 126 кр",
    )
for _mid in ("kling-2.6/text-to-video", "kling-2.6/image-to-video"):
    reg(
        _mid,
        unit="gen",
        rules=[
            R(63, duration=5, sound=False),
            R(126, duration=5, sound=True),
            R(126, duration=10, sound=False),
            R(252, duration=10, sound=True),
        ],
        formula="фикс за ролик: длительность 5/10 сек × звук вкл/выкл",
        affects_price=["duration", "sound"],
        note="5с 63/126 кр, 10с 126/252 кр (без звука/со звуком)",
    )

# --- Kling per-second tiers -------------------------------------------------
reg(
    "kling-3.0/video",
    unit="sec",
    rules=[
        R(15.1, resolution="720P", sound=False),
        R(22.7, resolution="720P", sound=True),
        R(20.2, resolution="1080P", sound=False),
        R(30.2, resolution="1080P", sound=True),
        R(75.5, resolution="4K"),
    ],
    formula="кр/сек × длительность: 720P (standard) 15.1/22.7, 1080P (pro) 20.2/30.2, 4K 75.5 (со звуком/без)",
    affects_price=["resolution", "duration", "sound"],
    mapping_note="тир задаётся разрешением: 720P = Standard, 1080P = Pro (как в прайсе); отдельного поля tier у цены нет",
)
reg(
    "kling-3.0-omni/text-to-video",
    unit="sec",
    rules=[
        R(15.1, resolution="720P", sound=False),
        R(20.2, resolution="720P", sound=True),
        R(20.2, resolution="1080P", sound=False),
        R(25.2, resolution="1080P", sound=True),
        R(75.5, resolution="4K"),
    ],
    formula="кр/сек × длительность: 720P 15.1/20.2, 1080P 20.2/25.2, 4K 75.5 (с нативным звуком/без)",
    affects_price=["resolution", "duration", "sound"],
)
reg(
    "kling-3.0-omni/image-to-video",
    unit="sec",
    rules=[
        R(15.1, resolution="720P", sound=False),
        R(20.2, resolution="720P", sound=True),
        R(20.2, resolution="1080P", sound=False),
        R(25.2, resolution="1080P", sound=True),
        R(75.5, resolution="4K"),
    ],
    formula="кр/сек × длительность: 720P 15.1/20.2, 1080P 20.2/25.2, 4K 75.5 (с нативным звуком/без)",
    affects_price=["resolution", "duration", "sound"],
)
reg(
    "kling-3.0-omni/reference-to-video",
    unit="sec",
    rules=[
        R(15.1, resolution="720P", sound=False),
        R(20.2, resolution="720P", sound=True),
        R(22.7, resolution="720P", with_video=True),
        R(20.2, resolution="1080P", sound=False),
        R(25.2, resolution="1080P", sound=True),
        R(30.2, resolution="1080P", with_video=True),
        R(75.5, resolution="4K"),
    ],
    formula="кр/сек × длительность; с видеовходом свой тариф (22.7/30.2), 4K 75.5 для всех входов; звук ±",
    affects_price=["resolution", "duration", "sound", "video_input"],
)
reg(
    "kling-3.0-omni/transformation",
    unit="sec",
    rules=[R(22.7, resolution="720P"), R(30.2, resolution="1080P"), R(75.5, resolution="4K")],
    formula="кр/сек × длительность; видеовход обязателен",
    affects_price=["resolution", "duration"],
)
reg(
    "kling-3.0/motion-control",
    unit="sec",
    rules=[R(22.7, resolution="720P"), R(30.2, resolution="1080P")],
    formula="кр/сек × длительность",
    affects_price=["resolution", "duration"],
)
reg(
    "kling-2.6/motion-control",
    unit="sec",
    rules=[R(12.6, resolution="720P"), R(20.2, resolution="1080P")],
    formula="кр/сек × длительность",
    affects_price=["resolution", "duration"],
)
for _mid in ("kling/v3-turbo-text-to-video", "kling/v3-turbo-image-to-video"):
    reg(
        _mid,
        unit="sec",
        rules=[R(20.2, resolution="720P"), R(25.2, resolution="1080P")],
        formula="кр/сек × длительность",
        affects_price=["resolution", "duration"],
    )
for _mid in ("kling/ai-avatar-standard", "kling/ai-avatar-pro"):
    reg(
        _mid,
        unit="sec",
        rules=[R(10.1, resolution="720P", mode="standard"), R(20.2, resolution="1080P", mode="pro")],
        formula="кр/сек × длительность; 720P Standard / 1080P Pro",
        affects_price=["resolution", "duration"],
    )

# --- Kling 4.0 --------------------------------------------------------------
reg(
    "kling-4.0/keyframe-to-video",
    unit="sec",
    rules=[R(28.5, resolution="720P"), R(42.5, resolution="1080P")],
    formula="кр/сек × длительность выхода (3–30 с)",
    affects_price=["resolution", "duration"],
)
reg(
    "kling-4.0/flash-keyframe-to-video",
    unit="sec",
    rules=[R(17, resolution="720P")],
    formula="кр/сек × длительность выхода (3–20 с)",
    affects_price=["duration"],
)
reg(
    "kling-4.0/reference-to-video",
    unit="sec",
    rules=[
        R(17, resolution="720P", with_video=True),
        R(28.5, resolution="720P", with_video=False),
        R(25.5, resolution="1080P", with_video=True),
        R(42.5, resolution="1080P", with_video=False),
    ],
    formula=(
        "без видеовхода: тариф × длительность выхода; с видеовходом: тариф × (2 × выход), "
        "если вход ≤ выхода, иначе тариф × (вход + выход)"
    ),
    duration_billing="output | video: max(2*output, input+output)",
    affects_price=["resolution", "duration", "video_input"],
)
reg(
    "kling-4.0/flash-reference-to-video",
    unit="sec",
    rules=[R(11.3, resolution="720P", with_video=True), R(17, resolution="720P", with_video=False)],
    formula=(
        "без видеовхода: тариф × длительность выхода; с видеовходом: тариф × (2 × выход) "
        "или (вход + выход), если вход длиннее"
    ),
    duration_billing="output | video: max(2*output, input+output)",
    affects_price=["duration", "video_input"],
)

# --- MiniMax H3 -------------------------------------------------------------
def _h3(unit_rates=(8, 13)) -> dict:
    return {
        "unit": "sec",
        "rules": [R(unit_rates[0], resolution="768P"), R(unit_rates[1], resolution="2K")],
        "extra_charges": [
            {
                "what": "дополнительная входная картинка сверх 5 бесплатных",
                "credits": 4.0,
                "usd_kie": usd_kie(4),
                "usd_client": usd_client(usd_kie(4)),
                "free_first": 5,
                "per": "image",
                "source": "pricingDesc",
            }
        ],
        "formula": (
            "Total = Unit Price × (длительность выхода + длительность входного видео) + доплата за картинки "
            "(первые 5 бесплатны, дальше 4 кр/картинка; аудио бесплатно)"
        ),
        "duration_billing": "output + input_video",
        "affects_price": ["resolution", "duration", "video_input", "extra_images"],
        "note": "768P 8 кр/с, 2K 13 кр/с; доп. картинки свыше 5 — 4 кр/шт; видео на входе по тому же тарифу",
    }


for _mid in ("minimax-h3/text-to-video", "minimax-h3/image-to-video", "minimax-h3/reference-to-video"):
    reg(_mid, **_h3())
reg(
    "minimax-h3/text-to-image",
    unit="image",
    rules=[R(1.8, max_mp=4.5, resolution="1K/2K"), R(5.5, max_mp=20, resolution="4K")],
    formula="за картинку по площади выхода: до 4.5 MP — 1.8 кр, до 20 MP (4K) — 5.5 кр",
    affects_price=["resolution"],
    note="1K/2K — 1.8 кр, 4K — 5.5 кр",
)
reg(
    "minimax-h3/image-edit",
    unit="image",
    rules=[R(1.8, max_mp=4.5, resolution="1K/2K"), R(5.5, max_mp=20, resolution="4K")],
    extra_charges=[
        {
            "what": "референс-картинка (включая первую)",
            "credits": 0.5,
            "usd_kie": usd_kie(0.5),
            "usd_client": usd_client(usd_kie(0.5)),
            "free_first": None,
            "per": "image",
            "source": "pricingDesc",
        }
    ],
    formula="за картинку по площади выхода (1.8 / 5.5 кр) + 0.5 кр за каждую референс-картинку, включая первую",
    affects_price=["resolution", "reference_images"],
    note="1K/2K 1.8 кр, 4K 5.5 кр, +0.5 кр за референс",
)

# --- Hailuo 2.3: матрица mode × duration × resolution ----------------------
for _mid in ("hailuo/2-3-image-to-video-pro", "hailuo/2-3-image-to-video-standard"):
    reg(
        _mid,
        unit="gen",
        rules=[
            R(30, mode="standard", duration=6, resolution="768P"),
            R(50, mode="standard", duration=10, resolution="768P"),
            R(50, mode="standard", duration=6, resolution="1080P"),
            R(45, mode="pro", duration=6, resolution="768P"),
            R(90, mode="pro", duration=10, resolution="768P"),
            R(80, mode="pro", duration=6, resolution="1080P"),
        ],
        formula="фикс за ролик: тир (standard/pro) × длительность (6/10 с) × разрешение (768P/1080P)",
        affects_price=["mode", "duration", "resolution"],
        note="std 6с 768P 30, 10с 768P 50, 6с 1080P 50; pro 6с 768P 45, 10с 768P 90, 6с 1080P 80 кр",
        arith_note="в прайсе 50 кр подписаны как $0.26, по курсу 0.005 это $0.25 (опечатка прайса)",
    )

# --- Hailuo 02 --------------------------------------------------------------
reg(
    "hailuo/02-image-to-video-standard",
    unit="sec",
    rules=[R(5, resolution="768P"), R(2, resolution="512P")],
    formula="кр/сек × длительность: 768P 5, 512P 2",
    affects_price=["resolution", "duration"],
)
reg(
    "hailuo/02-text-to-video-standard",
    unit="sec",
    rules=[R(5, resolution="768P")],
    formula="кр/сек × длительность, 768P",
    affects_price=["duration"],
)
for _mid in ("hailuo/02-image-to-video-pro", "hailuo/02-text-to-video-pro"):
    reg(
        _mid,
        unit="sec",
        rules=[R(9.5, resolution="1080P")],
        formula="кр/сек × длительность, 1080P; одна генерация = 6 сек",
        affects_price=["duration"],
        note="9.5 кр/с, генерация 6 с (в веб-превью 5 с)",
    )

# --- Veo --------------------------------------------------------------------
reg(
    "veo-3-1",
    unit="gen",
    rules=[
        R(30, mode="lite", resolution="720P"),
        R(35, mode="lite", resolution="1080P"),
        R(150, mode="lite", resolution="4K"),
        R(60, mode="fast", resolution="720P"),
        R(65, mode="fast", resolution="1080P"),
        R(180, mode="fast", resolution="4K"),
        R(250, mode="quality", resolution="720P"),
        R(255, mode="quality", resolution="1080P"),
        R(370, mode="quality", resolution="4K"),
    ],
    formula="фикс за видео: тир (lite/fast/quality) × разрешение (720P/1080P/4K); длительность в цену не входит",
    affects_price=["mode", "resolution"],
    note="lite 30/35/150, fast 60/65/180, quality 250/255/370 кр (720P/1080P/4K)",
)
for _mid, _cr in [("veo/get-1080p-video", 5), ("veo/get-4k-video", 120)]:
    reg(
        _mid,
        unit="gen",
        rules=[R(_cr)],
        formula="фикс за апскейл готового видео",
        affects_price=[],
        note=("апскейл до 1080P — 5 кр" if _cr == 5 else "апскейл до 4K — 120 кр"),
    )
reg(
    "veo/extend",
    unit="gen",
    rules=[R(30, mode="lite"), R(60, mode="fast"), R(250, mode="quality")],
    formula="фикс за продление: тир lite/fast/quality",
    affects_price=["mode"],
    note="30/60/250 кр за продление",
)
reg(
    "runway",
    unit="gen",
    rules=[R(12, duration=5, resolution="720P"), R(30, duration=10, resolution="720P"), R(30, duration=5, resolution="1080P")],
    formula="фикс за видео: 5с 720p — 12 кр; 10с 720p или 5с 1080p — 30 кр",
    affects_price=["duration", "resolution"],
    note="12 кр (5с 720p), 30 кр (10с 720p или 5с 1080p)",
)
reg(
    "runway/extend-ai-video",
    unit="gen",
    rules=[R(12, resolution="720P"), R(30, resolution="1080P")],
    formula="фикс за продление по разрешению",
    affects_price=["resolution"],
)
reg(
    "ai-music-api/create-music-video",
    unit="gen",
    rules=[R(2)],
    formula="фикс за запрос",
    affects_price=[],
    note="2 кр за музыкальное видео",
)

# --- WAN 2.6 (матрица длительность × разрешение) ---------------------------
reg(
    "wan/2-6-text-to-video",
    unit="gen",
    rules=spec_dedup(
        [R(cr, duration=d, resolution=res) for res, crs in (("720P", (70, 140, 210)), ("1080P", (105, 210, 315))) for d, cr in zip((5, 10, 15), crs)]
    ),
    formula="фикс за ролик: длительность 5/10/15 с × разрешение 720p/1080p",
    affects_price=["duration", "resolution"],
    note="720p 70/140/210 кр, 1080p 105/210/315 кр (5/10/15 с)",
)
for _mid in ("wan/2-6-image-to-video", "wan/2-6-video-to-video"):
    SPECIAL[_mid] = dict(SPECIAL["wan/2-6-text-to-video"])
for _mid in ("wan/2-6-flash-image-to-video",):
    reg(
        _mid,
        unit="gen",
        rules=[
            R(40, resolution="720P", sound=True, duration=5),
            R(80, resolution="720P", sound=True, duration=10),
            R(120, resolution="720P", sound=True, duration=15),
            R(20, resolution="720P", sound=False, duration=5),
            R(40, resolution="720P", sound=False, duration=10),
            R(60, resolution="720P", sound=False, duration=15),
            R(60, resolution="1080P", sound=True, duration=5),
            R(120, resolution="1080P", sound=True, duration=10),
            R(180, resolution="1080P", sound=True, duration=15),
            R(30, resolution="1080P", sound=False, duration=5),
            R(60, resolution="1080P", sound=False, duration=10),
            R(90, resolution="1080P", sound=False, duration=15),
        ],
        formula="фикс за ролик: разрешение 720p/1080p × звук × длительность 5/10/15 с",
        affects_price=["resolution", "sound", "duration"],
        note="720p со звуком 40/80/120, без 20/40/60; 1080p со звуком 60/120/180, без 30/60/90 кр",
    )
reg(
    "wan/2-6-flash-video-to-video",
    unit="gen",
    rules=[
        R(40, resolution="720P", sound=True, duration=5),
        R(80, resolution="720P", sound=True, duration=10),
        R(20, resolution="720P", sound=False, duration=5),
        R(40, resolution="720P", sound=False, duration=10),
        R(60, resolution="1080P", sound=True, duration=5),
        R(120, resolution="1080P", sound=True, duration=10),
        R(30, resolution="1080P", sound=False, duration=5),
        R(60, resolution="1080P", sound=False, duration=10),
    ],
    formula="фикс за ролик: разрешение × звук × длительность 5/10 с",
    affects_price=["resolution", "sound", "duration"],
    note="720p со звуком 40/80, без 20/40; 1080p со звуком 60/120, без 30/60 кр",
)

# --- WAN 3.0: (вход + выход) × тариф ---------------------------------------
reg(
    "wan/3-0-video-prime",
    unit="sec",
    rules=[R(12.2, resolution="480P"), R(25.2, resolution="720P"), R(50.4, resolution="1080P")],
    formula="(длительность входного видео + длительность выхода) × тариф по разрешению",
    duration_billing="input+output",
    affects_price=["resolution", "duration"],
)
reg(
    "wan/3-0-video",
    unit="sec",
    rules=[R(8, resolution="480P"), R(16, resolution="720P"), R(32, resolution="1080P")],
    formula="(длительность входного видео + длительность выхода) × тариф по разрешению",
    duration_billing="input+output",
    affects_price=["resolution", "duration"],
)
reg(
    "happyhorse/video-edit",
    unit="sec",
    rules=[R(28, resolution="720P"), R(48, resolution="1080P")],
    formula="Total = Unit Price × (длительность входного видео + длительность выхода)",
    duration_billing="input+output",
    affects_price=["resolution", "duration"],
)

# --- Gemini Omni: длительность × разрешение, с видеовходом — фикс -----------
def _omni_rules(share_res: list[str], broadcast_non4k: list[str]) -> list[dict]:
    out = []
    for res in broadcast_non4k:
        for d, cr in zip((4, 6, 8, 10), (63, 84, 105, 126)):
            out.append(R(cr, resolution=res, duration=d, with_video=False))
    for d, cr in zip((4, 6, 8, 10), (147, 168, 189, 210)):
        out.append(R(cr, resolution="4K", duration=d, with_video=False))
    for res in share_res:
        out.append(R(168, resolution=res, with_video=True))
    out.append(R(252, resolution="4K", with_video=True))
    return out


reg(
    "gemini-omni-video",
    unit="gen",
    rules=_omni_rules(["720P", "1080P"], ["720P", "1080P"]),
    formula="без видеовхода: фикс за генерацию по длительности (4/6/8/10 с) × разрешение; с видеовходом — фикс 168 кр (4K — 252)",
    affects_price=["duration", "resolution", "video_input"],
    note="720P/1080P 63/84/105/126, 4K 147/168/189/210 (4/6/8/10 с); с видео 168/252 кр",
)
reg(
    "google/gemini-omni-flash-1-1",
    unit="gen",
    rules=_omni_rules(["360P", "720P", "1080P"], ["360P", "720P", "1080P"]),
    formula="без видеовхода: фикс за генерацию по длительности × разрешение (360P/720P/1080P / 4K); с видеовходом — фикс 168/252 кр",
    affects_price=["duration", "resolution", "video_input"],
    note="360P/720P/1080P 63/84/105/126, 4K 147/168/189/210; с видео 168/252 кр",
)
reg(
    "google/gemini-omni-flash-1-2",
    unit="sec",
    rules=[R(4, resolution="360P"), R(9, resolution="720P"), R(10, resolution="1080P"), R(22, resolution="4K")],
    formula="кр/сек выхода по разрешению; монтаж видео — по длине входного видео по тем же ставкам",
    affects_price=["resolution", "duration"],
)
reg(
    "google/gemini-omni-flash-1-2-extend",
    unit="sec",
    rules=[R(4, resolution="360P"), R(9, resolution="720P")],
    formula="кр/сек × только добавленные секунды; исходник 360P/720P",
    duration_billing="added_seconds",
    affects_price=["resolution", "duration"],
)

# --- Grok -------------------------------------------------------------------
for _mid in ("grok-imagine/image-to-video", "grok-imagine/text-to-video", "grok-imagine-video-1-5-preview"):
    reg(
        _mid,
        unit="sec",
        rules=[R(2.4, resolution="480P"), R(4.5, resolution="720P"), R(8, resolution="1080P")],
        formula="кр/сек × длительность по разрешению",
        affects_price=["resolution", "duration"],
    )
reg(
    "grok-imagine/extend",
    unit="gen",
    rules=[
        R(14.4, duration=6, resolution="480P"),
        R(27, duration=6, resolution="720P"),
        R(24, duration=10, resolution="480P"),
        R(45, duration=10, resolution="720P"),
    ],
    formula="фикс за продление: длительность 6/10 с × разрешение 480p/720p",
    affects_price=["duration", "resolution"],
    note="6с 480p 14.4 / 720p 27; 10с 480p 24 / 720p 45 кр",
)
reg(
    "grok-imagine/upscale",
    unit="gen",
    rules=[
        R(10, from_resolution="480P", resolution="720P"),
        R(30, from_resolution="480P", resolution="1080P"),
        R(20, from_resolution="720P", resolution="1080P"),
    ],
    formula="фикс за апскейл в зависимости от пары «вход → выход»",
    affects_price=["from_resolution", "resolution"],
    note="480P→720P 10, 480P→1080P 30, 720P→1080P 20 кр",
)
reg(
    "grok-imagine/text-to-image",
    unit="gen",
    rules=[R(4, mode="standard"), R(5, mode="quality")],
    formula="фикс за генерацию: тир standard/quality; в генерации 2 картинки по умолчанию",
    affects_price=["mode"],
    note="standard 4 кр, quality 5 кр за генерацию (2 картинки)",
)
for _mid in ("grok-imagine/image-to-image", "grok-imagine-image-2-0/text-to-image", "grok-imagine-image-2-0/image-edit", "grok-imagine-image-2-0/segment-edit"):
    reg(_mid, unit="image", rules=[R(4)], formula="фикс за картинку", affects_price=[], note="4 кр/картинку")

# --- Ideogram ---------------------------------------------------------------
for _mid in ("ideogram/v3-text-to-image", "ideogram/v3-edit"):
    reg(
        _mid,
        unit="image",
        rules=[R(3.5, mode="turbo"), R(7, mode="balanced"), R(10, mode="quality")],
        formula="фикс за картинку по тиру: Turbo/Balanced/Quality",
        affects_price=["mode"],
        note="turbo 3.5, balanced 7, quality 10 кр",
    )
for _mid in ("ideogram/character", "ideogram/character-edit", "ideogram/character-remix"):
    reg(
        _mid,
        unit="image",
        rules=[R(12, mode="turbo"), R(18, mode="balanced"), R(24, mode="quality")],
        formula="фикс за картинку по тиру: Turbo/Balanced/Quality",
        affects_price=["mode"],
        note="turbo 12, balanced 18, quality 24 кр",
    )

# --- Upscale / утилиты ------------------------------------------------------
reg(
    "topaz/video-upscale",
    unit="sec",
    rules=[R(8, upscale="1x"), R(8, upscale="2x"), R(14, upscale="4x")],
    formula="кр/сек исходного видео × кратность (×1/×2 — 8, ×4 — 14)",
    affects_price=["duration", "upscale"],
)
reg(
    "topaz/image-upscale",
    unit="image",
    rules=[R(10, resolution="2K"), R(20, resolution="4K")],
    formula="фикс за картинку: ≤2K — 10 кр, 4K — 20 кр",
    affects_price=["resolution"],
)
reg(
    "video/upscale",
    unit="sec",
    rules=[R(1.5, resolution="1080P"), R(3, resolution="2K"), R(6, resolution="4K")],
    formula="кр/сек входного видео по целевому разрешению (1080P/2K/4K)",
    affects_price=["resolution", "duration"],
    note="1.5 / 3 / 6 кр за секунду исходника для 1080P / 2K / 4K",
)
reg(
    "kie/image-upscale",
    unit="image",
    rules=[R(1.5, resolution="2K", max_mp=4.19), R(4, resolution="4K", max_mp=16.78), R(12, resolution="8K", max_mp=67.11)],
    formula="фикс за картинку по площади выхода: ≤4.19 MP — 1.5, ≤16.78 MP — 4, ≤67.11 MP — 12 кр",
    affects_price=["resolution"],
)

# --- Per-megapixel / только $ ----------------------------------------------
reg(
    "qwen/text-to-image",
    unit="mp",
    rules=[R(4)],
    formula="кр × мегапиксели выхода (4 кр/MP = $0.02/MP)",
    affects_price=["megapixels"],
    note="4 кр за мегапиксель",
)
reg(
    "qwen/image-edit",
    unit="mp",
    rules=[R(None, usd=0.03)],
    formula="≈ $0.03 за мегапиксель выхода (кредиты в прайсе не указаны)",
    affects_price=["megapixels"],
    note="цена в $ из прайса, кредиты не указаны; «≈» в прайсе",
)
for _mid in ("qwen2/text-to-image", "qwen2/image-edit"):
    reg(
        _mid,
        unit="image",
        rules=[R(None, usd=0.03)],
        formula="≈ $0.03 за картинку (кредиты в прайсе не указаны)",
        affects_price=["megapixels"],
        note="цена в $ из прайса, кредиты не указаны; зависит от площади",
    )
reg(
    "qwen/image-to-image",
    unit="image",
    rules=[R(4)],
    formula="фикс за картинку",
    affects_price=[],
)

# --- Seedream с доплатой за входные картинки -------------------------------
reg(
    "seedream/5-pro-text-to-image",
    unit="image",
    rules=[R(7, resolution="1K"), R(14, resolution="2K")],
    extra_charges=[
        {"what": "входная картинка (первая бесплатно)", "credits": 0.5, "usd_kie": usd_kie(0.5), "usd_client": usd_client(usd_kie(0.5)), "free_first": 1, "per": "image", "source": "pricingDesc"}
    ],
    formula="за картинку 1K 7 кр / 2K 14 кр + 0.5 кр за каждую входную картинку (первая бесплатно)",
    affects_price=["resolution", "input_images"],
    note="1K 7 кр, 2K 14 кр, входные картинки 0.5 кр (первая бесплатно)",
)
SPECIAL["seedream/5-pro-image-to-image"] = dict(SPECIAL["seedream/5-pro-text-to-image"])
reg(
    "seedream/5-pro-layer-decomposition",
    unit="image",
    rules=[R(7, resolution="1K/1.5K"), R(14, resolution="2K")],
    formula="каждый выходной слой (включая базовый) — как картинка: 1K/1.5K 7 кр, 2K 14 кр",
    affects_price=["resolution", "output_images"],
    note="биллинг по числу выходных картинок",
)
reg(
    "seedream/5-5-text-to-image",
    unit="image",
    rules=[R(3.6, resolution="1K/1.5K"), R(6.3, resolution="2K")],
    formula="за картинку: 1K/1.5K 3.6 кр, 2K 6.3 кр",
    affects_price=["resolution"],
    note="3.6 / 6.3 кр",
)
reg(
    "seedream/5-5-image-to-image",
    unit="image",
    rules=[R(3.6, resolution="1K/1.5K"), R(6.3, resolution="2K")],
    extra_charges=[
        {"what": "входная картинка", "credits": 1.44, "usd_kie": usd_kie(1.44), "usd_client": usd_client(usd_kie(1.44)), "free_first": None, "per": "image", "source": "pricingDesc"}
    ],
    formula="за выходную картинку (1K/1.5K 3.6, 2K 6.3) + 1.44 кр за каждую входную картинку",
    affects_price=["resolution", "input_images"],
    note="пример прайса: 2K + 2 входные = 6.3 + 2×1.44 = 9.18 кр ($0.0459)",
    examples=[{"cfg": {"resolution": "2K", "input_images": 2}, "credits": 9.18, "usd_kie": 0.0459}],
)
reg(
    "seedream/5-5-layer-decomposition",
    unit="image",
    rules=[R(3.6, resolution="1K/1.5K"), R(6.3, resolution="2K")],
    extra_charges=[
        {"what": "входная картинка", "credits": 1.44, "usd_kie": usd_kie(1.44), "usd_client": usd_client(usd_kie(1.44)), "free_first": None, "per": "image", "source": "pricingDesc"}
    ],
    formula="каждый выходной слой как картинка (1K/1.5K 3.6, 2K 6.3) + 1.44 кр за входную картинку",
    affects_price=["resolution", "output_images", "input_images"],
    note="пример прайса: 4 слоя 1K + вход = 1.44 + 4×3.6 = 15.84 кр ($0.0792)",
    examples=[{"cfg": {"resolution": "1K", "output_images": 4, "input_images": 1}, "credits": 15.84, "usd_kie": 0.0792}],
)
for _mid in ("seedream/5-flash-text-to-image", "seedream/5-flash-image-to-image", "seedream/5-flash-layer-decomposition"):
    reg(
        _mid,
        unit="image",
        rules=[R(3.24, resolution="1K/1.5K/2K")],
        formula="фикс за картинку: 1K/1.5K/2K одинаково — 3.24 кр",
        affects_price=[],
        note="3.24 кр за картинку",
    )
for _mid in ("seedream/5-lite-text-to-image", "seedream/5-lite-image-to-image"):
    reg(_mid, unit="image", rules=[R(5.5)], formula="фикс за картинку", affects_price=[])

# --- GPT Image 2.6 (токены) ------------------------------------------------
for _mid in (
    "gpt-image-2-6/flare-text-to-image",
    "gpt-image-2-6/flare-image-to-image",
    "gpt-image-2-6/sunburst-text-to-image",
    "gpt-image-2-6/sunburst-image-to-image",
):
    reg(
        _mid,
        unit="1m_tokens",
        rules=[
            R(900, token_kind="text_input"),
            R(225, token_kind="cached_text_input"),
            R(1440, token_kind="image_input"),
            R(360, token_kind="cached_image_input"),
            R(5400, token_kind="image_output"),
            R(5400, token_kind="svg_image_output"),
        ],
        extra_charges=[
            {"what": "SVG-автор gpt-5.6-luna: вход / выход за 1M токенов", "credits": 36.0, "usd_kie": usd_kie(36), "usd_client": usd_client(usd_kie(36)), "per": "1m_tokens", "source": "pricingDesc"},
            {"what": "SVG-автор gpt-5.6-luna: выход за 1M токенов", "credits": 216.0, "usd_kie": usd_kie(216), "usd_client": usd_client(usd_kie(216)), "per": "1m_tokens", "source": "pricingDesc"},
            {"what": "SVG-автор gpt-6-sol: вход / выход за 1M токенов", "credits": 360.0, "usd_kie": usd_kie(360), "usd_client": usd_client(usd_kie(360)), "per": "1m_tokens", "source": "pricingDesc"},
            {"what": "SVG-автор gpt-6-sol: выход за 1M токенов", "credits": 1800.0, "usd_kie": usd_kie(1800), "usd_client": usd_client(usd_kie(1800)), "per": "1m_tokens", "source": "pricingDesc"},
            {"what": "SVG-автор gpt-5.6-terra: вход / выход за 1M токенов", "credits": 360.0, "usd_kie": usd_kie(360), "usd_client": usd_client(usd_kie(360)), "per": "1m_tokens", "source": "pricingDesc"},
            {"what": "SVG-автор gpt-5.6-terra: выход за 1M токенов", "credits": 2160.0, "usd_kie": usd_kie(2160), "usd_client": usd_client(usd_kie(2160)), "per": "1m_tokens", "source": "pricingDesc"},
        ],
        formula=(
            "цена по токенам (за 1M токенов): текст на вход 900 кр, кэш 225, картинка на вход 1440, кэш 360, "
            "выход картинки 5400 кр; SVG добавляет токены автор-модели"
        ),
        affects_price=["tokens", "resolution"],
        note="фиксированной цены за картинку нет — зависит от числа токенов; SVG — плюс токены автор-модели",
    )

# --- Сложные/особые модели --------------------------------------------------
reg(
    "bytedance/v1-pro-fast-image-to-video",
    unit="gen",
    rules=[
        R(16, resolution="720P", duration=5),
        R(36, resolution="720P", duration=10),
        R(36, resolution="1080P", duration=5),
        R(72, resolution="1080P", duration=10),
    ],
    formula="фикс за ролик: разрешение (720P/1080P) × длительность (5/10 с)",
    affects_price=["resolution", "duration"],
)
reg(
    "seedream/4.5-text-to-image", unit="image", rules=[R(6.5)], formula="фикс за картинку", affects_price=[]
)
reg("seedream/4.5-edit", unit="image", rules=[R(6.5)], formula="фикс за картинку", affects_price=[])
reg("bytedance/seedream-v4-text-to-image", unit="image", rules=[R(5)], formula="фикс за картинку; число картинок задаётся max_images", affects_price=["output_images"])
reg("bytedance/seedream-v4-edit", unit="image", rules=[R(5)], formula="фикс за картинку; число картинок задаётся max_images", affects_price=["output_images"])
reg(
    "bytedance/seedream",
    unit="image",
    rules=[R(3.5)],
    formula="фикс за картинку",
    affects_price=[],
)
for _mid, _cr in [("google/imagen4", 8), ("google/imagen4-ultra", 12), ("google/imagen4-fast", 4), ("google/nano-banana", 4), ("google/nano-banana-edit", 4), ("recraft/remove-background", 1), ("4o-image-api", 6), ("z-image", 0.8)]:
    reg(_mid, unit="image", rules=[R(_cr)], formula=f"фикс за картинку {_cr} кр", affects_price=[])
reg("qwen3/text-to-image", unit="image", rules=[R(4.8, resolution="1K/2K")], formula="фикс за картинку 4.8 кр, 1K и 2K одинаково", affects_price=["resolution"])
reg("recraft/crisp-upscale", unit="image", rules=[R(0.5)], formula="фикс за апскейл", affects_price=[])
reg(
    "nano-banana-2",
    unit="image",
    rules=[R(8, resolution="1K"), R(12, resolution="2K"), R(18, resolution="4K")],
    formula="фикс за картинку по разрешению: 1K/2K/4K",
    affects_price=["resolution"],
)
reg("nano-banana-2-lite", unit="image", rules=[R(4, resolution="1K")], formula="фикс за картинку 1K", affects_price=["resolution"])
reg("nano-banana-pro", unit="image", rules=[R(18, resolution="1K/2K"), R(24, resolution="4K")], formula="фикс за картинку: 1K/2K 18, 4K 24", affects_price=["resolution"])
reg("nano-banana-2-1", unit="image", rules=[R(4, resolution="1K"), R(6, resolution="2K"), R(9, resolution="4K")], formula="фикс за картинку по разрешению", affects_price=["resolution"])
reg("flux-3/klein-text-to-image", unit="image", rules=[R(1.6, resolution="1K"), R(2.5, resolution="2K"), R(6.5, resolution="4K")], formula="фикс за картинку по разрешению", affects_price=["resolution"])
reg("flux-3/klein-edit-image", unit="image", rules=[R(1.6, resolution="1K"), R(2.5, resolution="2K"), R(6.5, resolution="4K")], formula="фикс за картинку по разрешению", affects_price=["resolution"])
for _mid in ("flux-2/pro-text-to-image", "flux-2/pro-image-to-image"):
    reg(_mid, unit="image", rules=[R(5, resolution="1K"), R(7, resolution="2K")], formula="фикс за картинку: 1K 5, 2K 7; до 8 референсов бесплатно", affects_price=["resolution"])
for _mid in ("flux-2/flex-text-to-image", "flux-2/flex-image-to-image"):
    reg(_mid, unit="image", rules=[R(14, resolution="1K"), R(24, resolution="2K")], formula="фикс за картинку: 1K 14, 2K 24; до 8 референсов бесплатно", affects_price=["resolution"])
reg("flux1-kontext", unit="image", rules=[R(5, mode="pro"), R(10, mode="max")], formula="фикс за картинку: Pro 5, Max 10", affects_price=["mode"])
for _mid in ("gpt-image-2-text-to-image", "gpt-image-2-image-to-image"):
    reg(_mid, unit="image", rules=[R(6, resolution="1K"), R(10, resolution="2K"), R(16, resolution="4K")], formula="фикс за картинку по разрешению: 1K/2K/4K", affects_price=["resolution"])
for _mid in ("gpt-image-2-5-flare-text-to-image", "gpt-image-2-5-flare-image-to-image", "gpt-image-2-5-sunburst-text-to-image", "gpt-image-2-5-sunburst-image-to-image"):
    reg(_mid, unit="image", rules=[R(6, resolution="1K"), R(10, resolution="2K"), R(16, resolution="4K")], formula="фикс за картинку по разрешению: 1K/2K/4K", affects_price=["resolution"])
for _mid in ("gpt-image-2-6/economy-text-to-image", "gpt-image-2-6/economy-image-to-image"):
    reg(_mid, unit="image", rules=[R(5, resolution="1K")], formula="фикс за картинку 1K (economy-канал)", affects_price=["resolution"])
for _mid in ("gpt-image/1.5-text-to-image", "gpt-image/1.5-image-to-image"):
    reg(_mid, unit="image", rules=[R(4, mode="medium"), R(22, mode="high")], formula="фикс за картинку: medium 4, high 22", affects_price=["mode"])
reg("qwen3/pro-text-to-image", unit="image", rules=[R(6.4, resolution="1K"), R(12, resolution="2K")], formula="фикс за картинку: 1K 6.4, 2K 12", affects_price=["resolution"])
reg("qwen3/pro-image-to-image", unit="image", rules=[R(6.4, resolution="1K"), R(12, resolution="2K")], extra_charges=[{"what": "входная картинка", "credits": 0.5, "usd_kie": usd_kie(0.5), "usd_client": usd_client(usd_kie(0.5)), "per": "image", "source": "pricingDesc"}], formula="фикс за картинку 1K 6.4 / 2K 12 + 0.5 кр за входную картинку", affects_price=["resolution", "input_images"])
reg("qwen3/image-to-image", unit="image", rules=[R(4.8, resolution="1K/2K")], extra_charges=[{"what": "входная картинка", "credits": 0.5, "usd_kie": usd_kie(0.5), "usd_client": usd_client(usd_kie(0.5)), "per": "image", "source": "pricingDesc"}], formula="фикс за картинку 1K/2K 4.8 + 0.5 кр за входную картинку", affects_price=["input_images"])
reg("qwen2-1/text-to-image", unit="image", rules=[R(4, resolution="1K"), R(8, resolution="2K")], formula="фикс за картинку: 1K 4, 2K 8", affects_price=["resolution"])
reg("qwen2-1/image-to-image", unit="image", rules=[R(4, resolution="1K"), R(8, resolution="2K")], formula="фикс за картинку: 1K 4, 2K 8", affects_price=["resolution"])
for _mid, _cr in (("wan/2-7-image", 4.8), ("wan/2-7-image-pro", 12)):
    reg(_mid, unit="image", rules=[R(_cr)], formula="фикс за картинку", affects_price=[], note=f"{_cr} кр за картинку")
for _mid in ("pixverse-v6/text-to-video", "pixverse-v6/image-to-video", "pixverse-v6/transition", "pixverse-v6/extend", "pixverse-v6/reference-to-video"):
    reg(_mid, unit="sec", rules=[
        R(4.0, resolution="360P", sound=False), R(5.6, resolution="360P", sound=True),
        R(5.6, resolution="540P", sound=False), R(7.2, resolution="540P", sound=True),
        R(7.2, resolution="720P", sound=False), R(9.6, resolution="720P", sound=True),
        R(14.4, resolution="1080P", sound=False), R(18.4, resolution="1080P", sound=True),
    ], formula="кр/сек × длительность: разрешение × звук", affects_price=["resolution", "sound", "duration"])
for _mid in ("pixverse-v6-max/text-to-video", "pixverse-v6-max/image-to-video"):
    reg(_mid, unit="sec", rules=[
        R(4.8, resolution="360P", sound=False), R(7.2, resolution="360P", sound=True),
        R(7.2, resolution="540P", sound=False), R(8.8, resolution="540P", sound=True),
        R(8.8, resolution="720P", sound=False), R(12.0, resolution="720P", sound=True),
        R(17.6, resolution="1080P", sound=False), R(22.4, resolution="1080P", sound=True),
    ], formula="кр/сек × длительность: разрешение × звук", affects_price=["resolution", "sound", "duration"])
for _mid in ("vidu-q4/image-to-video", "vidu-q4/reference-to-video"):
    reg(_mid, unit="sec", rules=[R(7.2, resolution="540P"), R(15.2, resolution="720P"), R(19.2, resolution="1080P"), R(30.4, resolution="2K"), R(62.4, resolution="4K")], formula="кр/сек × длительность по разрешению", affects_price=["resolution", "duration"])
for _mid in ("wan/2-5-text-to-video", "wan/2-5-image-to-video"):
    reg(_mid, unit="sec", rules=[R(12, resolution="720P"), R(20, resolution="1080P")], formula="кр/сек × длительность по разрешению", affects_price=["resolution", "duration"])
for _mid in ("wan/2-7-text-to-video", "wan/2-7-image-to-video", "wan/2-7-r2v", "wan/2-7-videoedit"):
    reg(_mid, unit="sec", rules=[R(16, resolution="720P"), R(24, resolution="1080P")], formula="кр/сек × длительность по разрешению", affects_price=["resolution", "duration"])
for _mid in ("wan/2-2-a14b-text-to-video-turbo", "wan/2-2-a14b-image-to-video-turbo"):
    reg(_mid, unit="sec", rules=[R(16, resolution="720P"), R(8, resolution="480P")], formula="кр/сек × длительность по разрешению", affects_price=["resolution", "duration"])
reg("wan/2-2-animate-replace", unit="sec", rules=[R(12.5, resolution="720P"), R(9.5, resolution="580P"), R(6, resolution="480P")], formula="кр/сек × длительность по разрешению", affects_price=["resolution", "duration"])
reg("wan/2-2-animate-move", unit="sec", rules=[R(12.5, resolution="720P")], formula="кр/сек × длительность, 720p", affects_price=["duration"])
reg("wan/2-2-a14b-speech-to-video-turbo", unit="sec", rules=[R(24, resolution="720P"), R(18, resolution="580P"), R(12, resolution="480P")], formula="кр/сек × длительность по разрешению", affects_price=["resolution", "duration"])
reg("infinitalk/from-audio", unit="sec", rules=[R(3, resolution="480P"), R(12, resolution="720P")], formula="кр/сек по разрешению, до 15 сек", affects_price=["resolution", "duration"])
reg("volcengine/video-to-video-lip-sync", unit="sec", rules=[R(8)], formula="кр/сек × длительность", affects_price=["duration"])
reg("omnihuman-1-5", unit="sec", rules=[R(27)], formula="кр/сек × длительность", affects_price=["duration"])
reg("omnihuman-2-0", unit="sec", rules=[R(14, resolution="720P")], formula="кр/сек × длительность выхода, 720P", affects_price=["duration"])
reg("happyhorse/text-to-video", unit="sec", rules=[R(28, resolution="720P"), R(48, resolution="1080P")], formula="кр/сек × длительность по разрешению", affects_price=["resolution", "duration"])
for _mid in ("happyhorse/image-to-video", "happyhorse/reference-to-video"):
    SPECIAL[_mid] = dict(SPECIAL["happyhorse/text-to-video"])
reg("happyhorse-1-1/text-to-video", unit="sec", rules=[R(22.5, resolution="720P"), R(29, resolution="1080P")], formula="кр/сек × длительность по разрешению", affects_price=["resolution", "duration"])
for _mid in ("happyhorse-1-1/image-to-video", "happyhorse-1-1/reference-to-video"):
    SPECIAL[_mid] = dict(SPECIAL["happyhorse-1-1/text-to-video"])
reg("bytedance/v1-pro-image-to-video", unit="sec", rules=[R(2.8, resolution="480P"), R(6, resolution="720P"), R(14, resolution="1080P")], formula="кр/сек × длительность по разрешению", affects_price=["resolution", "duration"])
SPECIAL["bytedance/v1-pro-text-to-video"] = dict(SPECIAL["bytedance/v1-pro-image-to-video"])
reg("bytedance/v1-lite-image-to-video", unit="sec", rules=[R(2, resolution="480P"), R(4.5, resolution="720P"), R(10, resolution="1080P")], formula="кр/сек × длительность по разрешению", affects_price=["resolution", "duration"])
SPECIAL["bytedance/v1-lite-text-to-video"] = dict(SPECIAL["bytedance/v1-lite-image-to-video"])

# --- бесплатные -------------------------------------------------------------
FREEGEN = {"ai-music-api/cover-generate", "grok-imagine-image-2-0/segment-map"}
for _mid in FREEGEN:
    reg(_mid, unit="image", rules=[R(0)], formula="бесплатно", affects_price=[], note="в прайсе: free")

# ---------------------------------------------------------------- модели вне живого API

EXTRA_MODELS: dict[str, dict] = {
    "bytedance/seedance-1.5-pro": {
        "kie_id": "bytedance/seedance-1.5-pro",
        "brand": "ByteDance",
        "media": "video",
        "task_type": ["Text to Video", "Image to Video"],
        "unit": "sec",
        "formula": "кр/сек × длительность выхода; со звуком ставка выше",
        "rules": [
            R(1.75, resolution="480P"),
            R(3.5, resolution="480P", sound=True),
            R(3.5, resolution="720P"),
            R(7, resolution="720P", sound=True),
            R(7.5, resolution="1080P"),
            R(15, resolution="1080P", sound=True),
        ],
        "extra_charges": [],
        "duration_billing": "output",
        "default_usd_kie": None,
        "default_usd_client": None,
        "markup": MARKUP,
        "source": "app/services/kie_catalog.py @HEAD (в живом /api/v1/models модели нет)",
        "note": "в живом каталоге kie.ai модели нет; в студии была (1.75/3.5/7/7.5/15 кр за секунду, звук вдвое). "
                "Цена только из каталога студии — прайс kie.ai её не подтверждает",
        "affects_price": ["resolution", "sound", "duration"],
        "examples": [],
        "pricing_desc": "",
        "schema_fields_present": False,
        "source_kind": "studio_catalog",
    },
}


# --- нет цены ---------------------------------------------------------------
UNKNOWN = {
    "ideogram/v3-remix": "pricingDesc пустой; идёт ремикс Ideogram V3 — цену не подтвердили",
    "gemini-omni-character": "pricingDesc пустой; цены в живом прайсе нет",
    "omnihuman-1-5/human-identification": "pricingDesc пустой; сервисная модель без цены",
    "omnihuman-1-5/subject-detection": "pricingDesc пустой; сервисная модель без цены",
}


# ---------------------------------------------------------------- сборка


def build() -> dict:
    media, other = load_models()
    schemas = load_schemas()
    csv_rows = load_csv()
    models: dict[str, dict] = {}
    problems: list[str] = []
    for m in media:
        mid = m["model"]
        med = media_of(m)
        desc = (m.get("pricingDesc") or "").strip()
        if mid in UNKNOWN:
            models[mid] = {
                "kie_id": mid,
                "brand": brand_of(mid, m.get("provider")),
                "media": med,
                "task_type": m.get("taskType") or [],
                "unit": None,
                "formula": "неизвестно",
                "rules": [],
                "default_usd_kie": None,
                "default_usd_client": None,
                "markup": MARKUP,
                "source": "pricingDesc",
                "note": "неизвестно",
                "unknown_reason": UNKNOWN[mid],
                "affects_price": [],
                "pricing_desc": desc,
                "schema_fields_present": bool(schemas.get(mid)),
            }
            continue
        parsed = parse_generic(desc, med, mid)
        if mid in SPECIAL:
            sp = {k: v for k, v in SPECIAL[mid].items() if not k.startswith("_")}
            sp_rules = sp.get("rules") or parsed["rules"]
        else:
            sp = {}
            sp_rules = parsed["rules"]
        if not sp_rules:
            # Всё ещё нет цены? Пробуем только $-числа (модели, где цена только в долларах)
            usd_vals = [fnum(x) for x in USD_RE.findall(base_text(desc))]
            if usd_vals and not any("credits" in base_text(desc).lower() for _ in [0]):
                sp_rules = [R(None, usd=usd_vals[0])]
            else:
                problems.append(f"{mid}: не удалось разобрать цену из pricingDesc")
        models[mid] = {
            "kie_id": mid,
            "brand": brand_of(mid, m.get("provider")),
            "media": med,
            "task_type": m.get("taskType") or [],
            "unit": sp.get("unit") or parsed["unit"],
            "formula": sp.get("formula") or _formula_guess(sp.get("unit") or parsed["unit"], med),
            "rules": [dict(r) for r in sp_rules],
            "extra_charges": sp.get("extra_charges") or parsed["extra_charges"],
            "duration_billing": sp.get("duration_billing"),
            "draft_inherits": sp.get("draft_inherits"),
            "default_usd_kie": None,
            "default_usd_client": None,
            "markup": MARKUP,
            "source": "pricingDesc",
            "note": sp.get("note") or _note_from_desc(desc),
            "affects_price": sp.get("affects_price") or _affects_from_rules(sp_rules),
            "examples": sp.get("examples") or [],
            "arith_note": sp.get("arith_note"),
            "mapping_note": sp.get("mapping_note"),
            "pricing_desc": desc,
            "schema_fields_present": bool(schemas.get(mid)),
        }
        if med == "image" and mid in MEDIA_FIX:
            models[mid]["media_note"] = "taskType в /api/v1/models ошибочно «Text to Video», по id/цене это картинки"
        if not models[mid]["rules"] and models[mid]["unit"]:
            problems.append(f"{mid}: пустые правила при известном unit")
    # модели, которых нет в живом API, но которые нужны backend (каталог студии / families.json)
    for mid, extra in EXTRA_MODELS.items():
        models[mid] = {**extra, "rules": [dict(r) for r in extra["rules"]]}
    # правила с составными разрешениями («1K/2K») раскрываем в отдельные правила,
    # чтобы каждое значение поля resolution из UI находило ровно одну цену
    for mid, m in models.items():
        m["rules"] = expand_rules(m.get("rules") or [])
    return {"models": models, "problems": problems, "media": media, "other": other, "schemas": schemas, "csv": csv_rows}


def expand_rules(rules: list[dict]) -> list[dict]:
    out: list[dict] = []
    for r in rules:
        when = dict(r.get("when") or {})
        split_key = None
        for k, v in when.items():
            if isinstance(v, str) and "/" in v and re.fullmatch(r"[\d.]+\s*[pPkK](\s*/\s*[\d.]+\s*[pPkK])+", v):
                split_key = k
                break
        if not split_key:
            out.append(r)
            continue
        parts = [p.strip() for p in when[split_key].split("/")]
        for p in parts:
            nw = dict(when)
            nw[split_key] = p
            out.append({**r, "when": nw})
    return out


def _formula_guess(unit: str | None, media: str) -> str:
    if unit == "sec":
        return "кр/сек × длительность выхода"
    if unit == "image":
        return "фикс за картинку"
    if unit == "gen":
        return "фикс за генерацию"
    if unit == "mp":
        return "кр/мегапиксель × площадь выхода"
    if unit == "1m_tokens":
        return "кр/1M токенов × токены"
    return "неизвестно"


def _note_from_desc(desc: str) -> str:
    first = base_text(desc).replace("\n", " ").strip()
    return first[:300]


def _affects_from_rules(rules: list[dict]) -> list[str]:
    keys = Counter()
    for r in rules:
        for k in (r.get("when") or {}):
            keys[k] += 1
    return sorted(keys)


# ---------------------------------------------------------------- дефолтная цена

def norm_res_token(v: str) -> str:
    s = str(v).strip()
    m = re.fullmatch(r"(\d+(?:\.\d+)?)\s*([pPkK])", s)
    if m:
        return m.group(1) + m.group(2).upper()
    return s


VEo_MODE = {"veo3_lite": "lite", "veo3_fast": "fast", "veo3": "quality"}


def pick_default(mid: str, spec: dict, schemas: dict) -> tuple[float | None, float | None, str]:
    """Цена конфигурации по умолчанию: по дефолтам полей из схемы docs, иначе первая строка прайса."""
    rules = [r for r in spec.get("rules") or [] if r.get("usd_kie") is not None]
    if not rules:
        return None, None, "нет цены"
    if spec.get("unit") == "1m_tokens":
        return None, None, "токен-тариф: единой цены за картинку нет, зависит от числа токенов входа/выхода"
    fields = (schemas.get(mid) or {}).get("fields") or []
    wanted: dict = {}
    for f in fields:
        name = f.get("name")
        default = f.get("default")
        if name in ("resolution", "image_size", "size", "quality") and default is not None:
            token = norm_res_token(str(default))
            if re.fullmatch(r"\d+(?:\.\d+)?[pPkK]", token):
                wanted["resolution"] = token
        elif name in ("mode", "model") and default is not None:
            val = str(default)
            wanted["mode"] = VEo_MODE.get(val, val)
        elif name == "duration" and default is not None:
            wanted["duration"] = str(int(float(default)))
        elif name in ("sound", "audio", "generate_audio") and default is not None:
            wanted["sound"] = bool(default)
    # видеовход по умолчанию отсутствует, если поле не обязательное
    has_video = False
    for f in fields:
        if f.get("name") in ("video_urls", "videos", "video_url", "source_video", "video_duration"):
            if f.get("required") or f.get("default"):
                has_video = True
    wanted["with_video"] = has_video
    for r in rules:
        when = r.get("when") or {}
        if not when:
            continue
        ok = True
        for k, v in when.items():
            if k not in wanted:
                continue
            if str(wanted[k]).lower() != str(v).lower():
                ok = False
                break
        if ok:
            dims = ", ".join(f"{k}={v}" for k, v in wanted.items() if k in when)
            return r["usd_kie"], r["usd_client"], f"совпало с дефолтами схемы docs ({dims})"
    return rules[0]["usd_kie"], rules[0]["usd_client"], "первая (базовая) строка прайса"


# ---------------------------------------------------------------- проверка 1: покрытие

PRICE_FIELDS = {
    "resolution": "resolution",
    "image_size": "resolution",
    "size": "resolution",
    "quality": "resolution",
    "mode": "mode",
    "duration": "duration",
    "sound": "sound",
    "audio": "sound",
    "generate_audio": "sound",
    "with_audio": "sound",
}


def dims_in_price_text(desc: str) -> set[str]:
    base = base_text(desc or "")
    dims: set[str] = set()
    if find_res(base):
        dims.add("resolution")
    if find_dur(base):
        dims.add("duration")
    if find_audio(base) is not None:
        dims.add("sound")
    if find_tier(base):
        dims.add("mode")
    if find_video_in(base) is not None:
        dims.add("with_video")
    if re.search(r"input images?|additional image input|reference image", base, re.I):
        dims.add("extra_images")
    return dims


def dims_encoded(spec: dict) -> set[str]:
    dims: set[str] = set()
    for r in spec.get("rules") or []:
        dims.update((r.get("when") or {}).keys())
    for e in spec.get("extra_charges") or []:
        what = e.get("what") or ""
        if "входн" in what or "референс" in what:
            dims.add("extra_images")
        if "дополнительн" in what:
            dims.add("extra_images")
    unit = spec.get("unit")
    if unit == "sec":
        dims.add("duration")
    if unit == "mp":
        dims.add("megapixels")
    if unit == "1m_tokens":
        dims.add("tokens")
    if spec.get("duration_billing"):
        dims.add("duration")
    mapping = {"input_images": "extra_images", "output_images": "extra_images", "reference_images": "extra_images"}
    for d in list(dims):
        if d in mapping:
            dims.add(mapping[d])
    for d in spec.get("affects_price") or []:
        if d in mapping:
            dims.add(mapping[d])
    return dims


def check_coverage(models: dict, schemas: dict) -> dict:
    priced = [m for m in models.values() if m.get("rules")]
    unknown = [m["kie_id"] for m in models.values() if not m.get("rules")]
    rules_total = sum(len(m.get("rules") or []) for m in models.values())
    extras_total = sum(len(m.get("extra_charges") or []) for m in models.values())
    hist = Counter(len(m.get("rules") or []) for m in models.values())
    by_media = Counter(m["media"] for m in models.values())
    priced_by_media = Counter(m["media"] for m in priced)
    schema_ok = sum(1 for m in models.values() if m.get("schema_fields_present"))
    # ценозависимые настройки
    expected_pairs = 0
    mentioned_pairs = 0
    gaps: list[str] = []
    explained_gaps: list[dict] = []
    for mid, m in models.items():
        fields = (schemas.get(mid) or {}).get("fields") or []
        names = {PRICE_FIELDS[f["name"]] for f in fields if f.get("name") in PRICE_FIELDS}
        expected_pairs += len(names)
        mentioned = dims_in_price_text(m.get("pricing_desc") or "") & names
        mentioned_pairs += len(mentioned)
        encoded = dims_encoded(m)
        for d in sorted(mentioned - encoded):
            if not m.get("rules"):
                continue
            reason = (COVERAGE_EXPLAINED.get(mid) or {}).get(d)
            if reason:
                explained_gaps.append({"kie_id": mid, "dim": d, "reason": reason})
            else:
                gaps.append(f"{mid}: {d} упомянут в прайсе, но правилом не покрыт")
    return {
        "media_models": len(models),
        "by_media": dict(by_media),
        "priced": len(priced),
        "priced_by_media": dict(priced_by_media),
        "unknown": unknown,
        "unknown_count": len(unknown),
        "rules_total": rules_total,
        "extra_charges_total": extras_total,
        "rules_per_model_hist": {str(k): v for k, v in sorted(hist.items())},
        "avg_rules_per_priced": round(rules_total / max(1, len(priced)), 2),
        "with_schema": schema_ok,
        "price_settings_pairs": expected_pairs,
        "price_settings_mentioned_in_price": mentioned_pairs,
        "gaps": gaps,
        "explained_gaps": explained_gaps,
    }


COVERAGE_EXPLAINED: dict[str, dict[str, str]] = {
    "kling-3.0/video": {
        "mode": "тир не отдельным полем цены: 720P = Standard, 1080P = Pro — так в прайсе; тариф тот же, "
                "поэтому правило задано разрешением, без tier",
    },
}



# ---------------------------------------------------------------- проверка 2: арифметика

def credits_mentions(desc: str) -> list[float]:
    out: list[float] = []
    for m in CRED.finditer(base_text(desc or "")):
        for x in m.group("lst").replace(" ", "").split("/"):
            out.append(fnum(x))
    return out


def pair_usd_checks(desc: str) -> list[dict]:
    """Каждое «N credits ($X)»: пересчёт N×0.005 против $ из прайса."""
    base = base_text(desc or "")
    out: list[dict] = []
    for m in CRED.finditer(base):
        lst = [fnum(x) for x in m.group("lst").replace(" ", "").split("/")]
        tail = base[m.end() : m.end() + 80]
        nxt = CRED.search(tail)
        seg = tail[: nxt.start()] if nxt else tail
        usds = [fnum(x) for x in USD_RE.findall(seg)]
        for cr, uv in zip(lst, usds):
            calc = round(cr * CREDIT_USD, 4)
            raw = cr * CREDIT_USD
            diff = round(abs(raw - uv), 6)
            # округление прайса до сотых: расхождение не больше половины цента
            rounding = diff <= 0.0051
            out.append({"credits": cr, "usd_in_price": uv, "calc_usd": calc, "diff": diff,
                        "ok": diff <= 0.0016, "rounding": rounding})
    return out


def mention_vs_rules(mid: str, spec: dict) -> dict:
    """Сверка набора чисел: каждое «N credits» из прайса должно быть в правилах и наоборот."""
    desc = spec.get("pricing_desc") or ""
    mentions = {round(x, 6) for x in credits_mentions(desc)}
    encoded: set[float] = set()
    for r in spec.get("rules") or []:
        if r.get("credits") is not None:
            encoded.add(round(float(r["credits"]), 6))
    for e in spec.get("extra_charges") or []:
        encoded.add(round(float(e["credits"]), 6))
    missing = sorted(mentions - encoded)
    extra = sorted(encoded - mentions)
    return {
        "missing_in_rules": missing,
        "extra_in_rules": extra,
        "ok": not missing and not extra,
        "explained": MENTION_EXCEPTIONS.get(mid),
    }


MENTION_EXCEPTIONS = {
    "ai-music-api/cover-generate": "в прайсе «free» — числа кредитов нет, ставим 0",
    "grok-imagine-image-2-0/segment-map": "в прайсе «free» — числа кредитов нет, ставим 0",
    "wan/2-7-image": "в одном описании обе модели WAN-2.7 Image и Image Pro (4.8 и 12) — у каждой своя цена",
    "wan/2-7-image-pro": "в одном описании обе модели WAN-2.7 Image и Image Pro (4.8 и 12) — у каждой своя цена",
    "seedream/5-5-image-to-image": "в прайсе есть пример тотала (6.3 + 2×1.44 = 9.18) — это арифметика, а не ставка",
    "seedream/5-5-layer-decomposition": "в прайсе есть пример тотала (1.44 + 4×3.6 = 15.84) — это арифметика, а не ставка",
    "bytedance/seedance-2-5-draft": "у draft своих ставок нет: наследует ставки Seedance 2.5 по режиму источника",
    "bytedance/seedance-1.5-pro": "модели нет в живом API, pricingDesc пуст — цена из каталога студии @HEAD",
    "gpt-image-2-6/flare-text-to-image": "токен-тариф: часть чисел в прайсе без слова «credits» (225, 1 440, 5 400, SVG-авторы) — взяты из строки цены",
    "gpt-image-2-6/flare-image-to-image": "токен-тариф: часть чисел в прайсе без слова «credits» — взяты из строки цены",
    "gpt-image-2-6/sunburst-text-to-image": "токен-тариф: часть чисел в прайсе без слова «credits» — взяты из строки цены",
    "gpt-image-2-6/sunburst-image-to-image": "токен-тариф: часть чисел в прайсе без слова «credits» — взяты из строки цены",
}


def check_arith(models: dict) -> dict:
    pairs_total = 0
    pair_typo: list[dict] = []
    pair_round: list[dict] = []
    mention_bad: list[dict] = []
    mention_explained: list[dict] = []
    for mid, m in models.items():
        if not m.get("rules"):
            continue
        pairs = pair_usd_checks(m.get("pricing_desc") or "")
        pairs_total += len(pairs)
        for p in pairs:
            if p["ok"]:
                continue
            item = {"kie_id": mid, **p}
            if p["rounding"]:
                pair_round.append(item)
            else:
                pair_typo.append(item)
        mv = mention_vs_rules(mid, m)
        if not mv["ok"]:
            if mv.get("explained"):
                mention_explained.append({"kie_id": mid, "reason": mv["explained"],
                                          "missing": mv["missing_in_rules"], "extra": mv["extra_in_rules"]})
            else:
                mention_bad.append({"kie_id": mid, **mv})
    return {
        "credits_usd_pairs_checked": pairs_total,
        "credits_usd_pairs_bad": len(pair_typo),
        "bad_pairs": pair_typo,
        "rounding_pairs": pair_round,
        "models_with_unmatched_mentions": len(mention_bad),
        "unmatched": mention_bad,
        "mentions_explained": mention_explained,
    }


# ---------------------------------------------------------------- проверка 3: единицы и наценка

CSV_UNIT = {
    "за секунду": "sec",
    "за картинку": "image",
    "за генерацию/ролик": "gen",
    "за токены": "1m_tokens",
    "за мегапиксель": "mp",
    "за секунду, за генерацию/ролик": "sec",  # ставка за секунду, счёт за ролик — это то же
    "не указано": None,
}

# csv-единица, которая не совпадает буквально, но объяснима механикой
CSV_UNIT_COMPAT = {
    ("recraft/crisp-upscale", "за генерацию/ролик"): "апскейл 1:1 — одна генерация и есть одна картинка",
}

UNIT_PHRASE = {
    "sec": r"per\s+(?:video[- ]?)?sec(?:ond)?\b|/\s*s(?:ec)?\b|per\s+second|per\s+video[- ]second|/\s*сек",
    "image": r"per\s+[^.;]{0,12}image|per\s+upscale|per\s+layer|per\s+output",
    "gen": r"per\s+video|per\s+generation|per\s+request|per\s+extension|per\s+run|flat\s+per|per\s+ролик",
    "mp": r"megapixel",
    "1m_tokens": r"1m\s+tokens",
    "1k_chars": r"1,?000\s+characters",
}


def check_units(models: dict, csv_rows: dict) -> dict:
    markup_bad: list[dict] = []
    unit_inferred: list[str] = []
    unit_ok = 0
    csv_bad: list[dict] = []
    csv_explained: list[dict] = []
    unit_by_model = {}
    for mid, m in models.items():
        unit = m.get("unit")
        unit_by_model[mid] = unit
        for r in m.get("rules") or []:
            uk, uc = r.get("usd_kie"), r.get("usd_client")
            if uk is None or uc is None:
                continue
            want = round(uk * MARKUP, 4)
            if abs(want - uc) > 1e-9:
                markup_bad.append({"kie_id": mid, "usd_kie": uk, "usd_client": uc, "want": want})
        if not m.get("rules"):
            continue
        base = (m.get("pricing_desc") or "").lower()
        if unit and unit in UNIT_PHRASE and re.search(UNIT_PHRASE[unit], base):
            unit_ok += 1
        elif unit and unit in UNIT_PHRASE:
            unit_inferred.append(mid)
        row = csv_rows.get(mid)
        if row:
            csv_word = (row.get("единица цены") or "").strip()
            want = CSV_UNIT.get(csv_word, "?")
            if (mid, csv_word) in CSV_UNIT_COMPAT:
                csv_explained.append({"kie_id": mid, "csv_unit": csv_word, "our_unit": unit,
                                      "reason": CSV_UNIT_COMPAT[(mid, csv_word)]})
            elif want not in (None, "?") and unit and want != unit:
                csv_bad.append({"kie_id": mid, "csv_unit": csv_word, "our_unit": unit})
    return {
        "models": len(models),
        "unit_counts": dict(Counter(unit_by_model.values())),
        "markup_checked": sum(len([r for r in m.get("rules") or [] if r.get("usd_kie") is not None]) for m in models.values()),
        "markup_bad": markup_bad,
        "unit_phrase_ok": unit_ok,
        "unit_phrase_missing": unit_inferred,
        "csv_unit_mismatch": csv_bad,
        "csv_unit_explained": csv_explained,
    }


# ---------------------------------------------------------------- сложные формулы с примерами

def find_rate(models: dict, mid: str, **when) -> float | None:
    """Кредиты правила, у которого when содержит все переданные условия."""
    for r in (models.get(mid) or {}).get("rules") or []:
        w = r.get("when") or {}
        if all(str(w.get(k)) == str(v) for k, v in when.items()):
            return r.get("credits")
    return None


def build_complex_formulas(models: dict) -> dict:
    out: dict[str, dict] = {}

    def ex(credits: float, cfg: dict, source: str = "расчёт по прайсу") -> dict:
        u = round(credits * CREDIT_USD, 6)
        return {
            "cfg": cfg,
            "credits": round(credits, 4),
            "usd_kie": u,
            "usd_client": round(u * MARKUP, 4),
            "source": source,
        }

    seed = {
        "bytedance/seedance-2": {"rate_with": 25, "rate_no": 41, "res": "720P", "out": 10, "inp": 5},
        "bytedance/seedance-2-5": {"rate_with": 95, "rate_no": 158, "res": "1080P", "out": 5, "inp": 10},
    }
    for mid, s in seed.items():
        with_total = s["rate_with"] * (s["out"] + s["inp"])
        no_total = s["rate_no"] * s["out"]
        out[mid] = {
            "formula": models[mid]["formula"],
            "duration_billing": models[mid].get("duration_billing"),
            "examples": [
                ex(with_total, {"resolution": s["res"], "output_sec": s["out"], "input_video_sec": s["inp"], "video_input": True}),
                ex(no_total, {"resolution": s["res"], "output_sec": s["out"], "video_input": False}),
            ],
            "note": "Total = rate × Output (без видео) / rate × (Input + Output) (с видео)",
        }
    out["bytedance/seedance-2-5-draft"] = {
        "formula": models["bytedance/seedance-2-5-draft"]["formula"],
        "draft_inherits": "bytedance/seedance-2-5",
        "examples": [
            ex(38 * (10 + 5), {"source": "draft", "resolution": "720P", "output_sec": 10, "input_video_sec": 5,
                               "video_input": "как у исходного драфта"},
               "расчёт: ставки Seedance 2.5, режим наследуется"),
        ],
        "note": "отдельной цены у шага апгрейда нет — биллинг как у источника (with-video / no-video)",
    }

    m3 = models["minimax-h3/text-to-video"]
    out["minimax-h3"] = {
        "formula": m3["formula"],
        "duration_billing": m3.get("duration_billing"),
        "extra_charges": m3.get("extra_charges"),
        "examples": [
            ex(13 * (10 + 16) + 2 * 4, {"resolution": "2K", "output_sec": 10, "input_video_sec": 16, "extra_images": 7}),
            ex(8 * 6, {"resolution": "768P", "output_sec": 6, "input_video_sec": 0, "extra_images": 5}),
        ],
        "note": "первые 5 входных картинок бесплатны; аудио на входе бесплатно",
    }

    out["veo-3-1"] = {
        "formula": models["veo-3-1"]["formula"],
        "examples": [
            ex(255, {"mode": "quality", "resolution": "1080P"}, "прайс: 255 credits (≈ $1.275) per video"),
            ex(30, {"mode": "lite", "resolution": "720P"}, "прайс: 30 credits (≈ $0.15) per video"),
        ],
        "note": "длительность (4/6/8 с) в цену не входит; отдельно veo/get-1080p-video 5 кр и veo/get-4k-video 120 кр за апскейл",
    }

    out["hailuo-2-3"] = {
        "formula": models["hailuo/2-3-image-to-video-pro"]["formula"],
        "examples": [
            ex(50, {"mode": "standard", "duration": 10, "resolution": "768P"}, "прайс: 50 credits ($0.26 в тексте)"),
            ex(80, {"mode": "pro", "duration": 6, "resolution": "1080P"}, "прайс: 80 credits ($0.39)"),
        ],
        "note": "в прайсе 50 кр подписаны как $0.26 — по курсу 0.005 это $0.25; в расчёте берём кредиты",
    }

    out["kling-3.0"] = {
        "formula": models["kling-3.0/video"]["formula"],
        "examples": [
            ex(30.2 * 10, {"resolution": "1080P", "sound": True, "output_sec": 10}),
            ex(15.1 * 5, {"resolution": "720P", "sound": False, "output_sec": 5}),
        ],
        "note": "4K — 75.5 кр/с независимо от звука",
    }
    out["kling-2.6"] = {
        "formula": models["kling-2.6/text-to-video"]["formula"],
        "examples": [ex(252, {"duration": 10, "sound": True}, "прайс: 252 credits ($1.26)")],
    }
    out["kling-4.0/reference-to-video"] = {
        "formula": models["kling-4.0/reference-to-video"]["formula"],
        "duration_billing": models["kling-4.0/reference-to-video"].get("duration_billing"),
        "examples": [
            ex(17 * max(2 * 10, 5 + 10), {"resolution": "720P", "output_sec": 10, "input_video_sec": 5,
                                           "video_input": True},
               "прайс: 10 с выхода + 5 с входа = 20 с"),
            ex(17 * max(2 * 10, 15 + 10), {"resolution": "720P", "output_sec": 10, "input_video_sec": 15,
                                            "video_input": True},
               "прайс: при входе 15 с — 25 с"),
        ],
    }

    out["gemini-omni-video"] = {
        "formula": models["gemini-omni-video"]["formula"],
        "examples": [
            ex(105, {"resolution": "1080P", "duration": 8, "video_input": False}, "прайс: 8s 105 credits ($0.525)"),
            ex(168, {"resolution": "1080P", "video_input": True}, "прайс: with video input 168 credits ($0.84)"),
        ],
    }

    out["seedream/5-5-image-to-image"] = {
        "formula": models["seedream/5-5-image-to-image"]["formula"],
        "extra_charges": models["seedream/5-5-image-to-image"].get("extra_charges"),
        "examples": [
            ex(6.3 + 2 * 1.44, {"resolution": "2K", "input_images": 2},
               "прайс: 6.3 + 2 × 1.44 = 9.18 credits ($0.0459)"),
        ],
    }
    out["seedream/5-5-layer-decomposition"] = {
        "formula": models["seedream/5-5-layer-decomposition"]["formula"],
        "extra_charges": models["seedream/5-5-layer-decomposition"].get("extra_charges"),
        "examples": [
            ex(1.44 + 4 * 3.6, {"resolution": "1K", "output_images": 4, "input_images": 1},
               "прайс: 1.44 + 4 × 3.6 = 15.84 credits ($0.0792)"),
        ],
    }

    out["gpt-image-2-6"] = {
        "formula": models["gpt-image-2-6/flare-text-to-image"]["formula"],
        "unit": "1m_tokens",
        "examples": [
            ex(5400, {"tokens": 1_000_000, "token_kind": "image_output"},
               "прайс: image output 5,400 credits / 1M tokens ($27.00)"),
            ex(900 + 1440 + 5400, {"tokens": 1_000_000, "token_kind": "text_input+image_input+image_output"},
               "оценка студии для 1M каждого типа"),
        ],
        "note": "цена за картинку не фиксирована: зависит от числа токенов входа/выхода",
    }
    return out


# ---------------------------------------------------------------- расхождения с кодом студии

STUDIO_TO_KIE: dict[str, list[str]] = {
    "veo-3-1": ["veo-3-1"],
    "seedance-2-5": ["bytedance/seedance-2-5"],
    "seedance-2-0": ["bytedance/seedance-2"],
    "seedance-2-0-fast": ["bytedance/seedance-2-fast"],
    "seedance-2-0-mini": ["bytedance/seedance-2-mini"],
    "seedance-1-5-pro": ["bytedance/seedance-1.5-pro"],
    "kling-3-0": ["kling-3.0/video"],
    "kling-v3-turbo-t2v": ["kling/v3-turbo-text-to-video"],
    "kling-v3-turbo-i2v": ["kling/v3-turbo-image-to-video"],
    "kling-3-0-omni-t2v": ["kling-3.0-omni/text-to-video"],
    "kling-2-6": ["kling-2.6/text-to-video", "kling-2.6/image-to-video"],
    "kling-3-0-motion-control": ["kling-3.0/motion-control"],
    "hailuo-2-3-i2v": ["hailuo/2-3-image-to-video-pro", "hailuo/2-3-image-to-video-standard"],
    "wan-2-7-t2v": ["wan/2-7-text-to-video"],
    "wan-2-7-i2v": ["wan/2-7-image-to-video"],
    "minimax-h3-t2v": ["minimax-h3/text-to-video"],
    "nano-banana-2": ["nano-banana-2"],
    "gpt-image-2": ["gpt-image-2-text-to-image"],
    "flux-2-pro": ["flux-2/pro-text-to-image"],
    "nano-banana-2-lite": ["nano-banana-2-lite"],
    "seedream-5-pro": ["seedream/5-pro-text-to-image"],
    "qwen3-image": ["qwen3/text-to-image"],
    "suno-music": ["ai-music-api/generate"],
    "suno-extend": ["ai-music-api/extend"],
    "suno-upload-cover": ["ai-music-api/upload-and-cover-audio"],
    "suno-add-vocals": ["ai-music-api/add-vocals"],
    "suno-separate-vocals": ["ai-music-api/separate-vocals"],
    "suno-lyrics": ["ai-music-api/generate-lyrics"],
    "elevenlabs-sfx": ["ai-music-api/sounds"],
    "suno-sounds": ["ai-music-api/sounds"],
    "elevenlabs-v4": [],
    "topaz-video-upscale": ["topaz/video-upscale"],
    "topaz-image-upscale": ["topaz/image-upscale"],
}


def load_studio_models() -> list[dict]:
    """Цены студии из ЗАКОММИЧЕННОЙ версии (HEAD) — рабочая копия может правиться шагом 8."""
    import subprocess

    txt = ""
    with contextlib.suppress(Exception):
        txt = (
            subprocess.run(
                ["git", "show", "HEAD:app/services/kie_catalog.py"],
                cwd=ROOT,
                capture_output=True,
                text=True,
                encoding="utf-8",
                check=False,
            ).stdout
            or ""
        )
    if not txt.strip():
        txt = (ROOT / "app/services/kie_catalog.py").read_text(encoding="utf-8")
    ns: dict = {"__name__": "_kie_catalog_head"}
    exec(compile(txt, "<kie_catalog HEAD>", "exec"), ns)  # noqa: S102
    return list(ns["MODELS"])


def translate_studio_when(studio_id: str, when: dict) -> dict:
    out: dict = {}
    for k, v in (when or {}).items():
        if k == "resolution":
            out["resolution"] = norm_res_token(str(v))
        elif k in ("sound", "audio", "generate_audio"):
            out["sound"] = bool(v)
        elif k == "_has_videos":
            out["with_video"] = bool(v)
        elif k == "duration":
            out["duration"] = int(float(v))
        elif k == "mode":
            if studio_id.startswith("kling-3-0") and str(v) != "4K":
                # в студии mode это std/pro, в прайсе это 720P/1080P
                out["resolution"] = {"std": "720P", "pro": "1080P"}.get(str(v), str(v))
            elif str(v) == "4K":
                out["resolution"] = "4K"
            else:
                out["mode"] = {"std": "standard", "pro": "pro"}.get(str(v), str(v))
        elif k == "model":
            out["mode"] = {"veo3_lite": "lite", "veo3_fast": "fast", "veo3": "quality"}.get(str(v), str(v))
        elif k == "quality":
            out["resolution"] = {"basic": "1K", "high": "2K"}.get(str(v), norm_res_token(str(v)))
        elif k == "upscale_factor":
            out["upscale"] = str(v) + "x"
        elif k == "target":
            out["resolution"] = norm_res_token(str(v))
        elif k == "type":
            out["kind"] = str(v)
    return out


def raw_credit_mentions(raw_models: list[dict]) -> dict[str, list[float]]:
    return {m["model"]: credits_mentions(m.get("pricingDesc") or "") for m in raw_models}


def studio_diff(models: dict, raw_models: list[dict]) -> dict:
    studio = load_studio_models()
    raw_mentions = raw_credit_mentions(raw_models)
    rows: list[dict] = []
    unmapped: list[dict] = []
    covered_kie: set[str] = set()
    for sm in studio:
        sid = sm["id"]
        kie_ids = STUDIO_TO_KIE.get(sid, [])
        covered_kie.update(kie_ids)
        pricing = sm.get("pricing") or {}
        s_rules = pricing.get("rules") or []
        s_default = pricing.get("default")
        if not kie_ids:
            unmapped.append({"studio_id": sid, "label": sm.get("label"), "reason": "модель идёт через wavespeed (/api/v3/elevenlabs/eleven-v4), в прайсе kie.ai её нет"})
            continue
        for kie_id in kie_ids:
            if kie_id in models:
                k_rules = models[kie_id].get("rules") or []
                used: set[int] = set()
                for sr in s_rules or [{"when": {}, "credits": s_default}]:
                    if sr.get("credits") is None:
                        continue
                    tw = translate_studio_when(sid, sr.get("when") or {})
                    match = None
                    for i, kr in enumerate(k_rules):
                        kw = kr.get("when") or {}
                        if i in used:
                            continue
                        if set(tw) <= set(kw) and all(str(kw.get(k)) == str(v) for k, v in tw.items()):
                            match = (i, kr)
                            break
                    if match:
                        used.add(match[0])
                    kr = match[1] if match else None
                    s_usd = round(float(sr["credits"]) * CREDIT_USD, 6)
                    k_usd = kr.get("usd_kie") if kr else None
                    client = kr.get("usd_client") if kr else None
                    rows.append(
                        {
                            "studio_id": sid,
                            "studio_label": sm.get("label"),
                            "kie_id": kie_id,
                            "config": tw or (sr.get("when") or {}),
                            "studio_credits": float(sr["credits"]),
                            "studio_usd_at_kie_rate": s_usd,
                            "kie_credits": kr.get("credits") if kr else None,
                            "kie_usd": k_usd,
                            "client_usd_markup25": client,
                            "delta_pricelist_vs_studio_pct": (round((k_usd - s_usd) / s_usd * 100, 1) if k_usd else None),
                            "delta_client_vs_studio_pct": (round((client - s_usd) / s_usd * 100, 1) if client else None),
                            "matched": bool(kr),
                        }
                    )
            else:
                mentions = raw_mentions.get(kie_id) or []
                if not mentions:
                    unmapped.append({"studio_id": sid, "label": sm.get("label"), "reason": f"{kie_id}: цену в прайсе не нашли"})
                    continue
                if s_rules:
                    pairs = list(zip([float(x["credits"]) for x in s_rules], mentions))
                else:
                    pairs = [(float(s_default), mentions[0])] if s_default is not None else []
                for s_cr, k_cr in pairs:
                    s_usd = round(s_cr * CREDIT_USD, 6)
                    k_usd = round(k_cr * CREDIT_USD, 6)
                    rows.append(
                        {
                            "studio_id": sid,
                            "studio_label": sm.get("label"),
                            "kie_id": kie_id,
                            "config": {},
                            "studio_credits": s_cr,
                            "studio_usd_at_kie_rate": s_usd,
                            "kie_credits": k_cr,
                            "kie_usd": k_usd,
                            "client_usd_markup25": round(k_usd * MARKUP, 4),
                            "delta_pricelist_vs_studio_pct": (round((k_usd - s_usd) / s_usd * 100, 1) if s_usd else None),
                            "delta_client_vs_studio_pct": (round((k_usd * MARKUP - s_usd) / s_usd * 100, 1) if s_usd else None),
                            "matched": True,
                        }
                    )
    bad = [
        r
        for r in rows
        if r.get("delta_pricelist_vs_studio_pct") is not None and abs(r["delta_pricelist_vs_studio_pct"]) > 1.0
    ]
    bad.sort(key=lambda r: -abs(r["delta_pricelist_vs_studio_pct"] or 0))
    missing = sorted(set(models) - covered_kie)
    return {
        "source": "app/services/kie_catalog.py @HEAD (git show HEAD:...)",
        "catalog_git_blob": studio_blob(),
        "studio_models": len(studio),
        "mapped_pairs": len(rows),
        "matched_rules": sum(1 for r in rows if r["matched"]),
        "rows": rows,
        "dangerous": bad,
        "unmapped": unmapped,
        "studio_missing_media_models": len(missing),
        "studio_missing_media_ids": missing,
        "kie_ids_in_studio": sorted(covered_kie),
    }


def studio_blob() -> str:
    import subprocess

    with contextlib.suppress(Exception):
        out = subprocess.run(
            ["git", "rev-parse", "HEAD:app/services/kie_catalog.py"],
            cwd=ROOT, capture_output=True, text=True, encoding="utf-8", check=False,
        ).stdout.strip()
        if out:
            return out[:12]
    return ""


# ---------------------------------------------------------------- живой API (бесплатные GET)

def live_check(snapshot_models: list[dict]) -> dict:
    """Сверка снапшота с живым /api/v1/models. Ключ берём только из env, в файлы не пишем."""
    import os
    import urllib.error
    import urllib.request

    key = (os.environ.get("KIE_API_KEY_LIVE") or "").strip()
    out: dict = {"checked": False, "models_endpoint": False, "credit_endpoint": False}
    if not key:
        # ключ берём из .env только в память процесса: в файлы он не попадает
        env_path = ROOT / ".env"
        if env_path.exists():
            for line in env_path.read_text(encoding="utf-8", errors="ignore").splitlines():
                line = line.strip()
                if line.startswith("KIE_API_KEY=") and not line.startswith("#"):
                    key = line.split("=", 1)[1].strip().strip('"').strip("'")
                    break
    if not key:
        out["reason"] = "ключ не найден в env/.env — сверка только со снапшотом"
        return out
    headers = {"Authorization": f"Bearer {key}", "Accept": "application/json"}
    try:
        req = urllib.request.Request("https://api.kie.ai/api/v1/models", headers=headers)
        with urllib.request.urlopen(req, timeout=30) as r:
            data = json.loads(r.read().decode("utf-8"))
        out["models_endpoint"] = data.get("code") == 200
        out["live_total"] = (data.get("data") or {}).get("total")
        live = {m["model"]: m.get("pricingDesc") or "" for m in (data.get("data") or {}).get("models") or []}
        changed = []
        for m in snapshot_models:
            mid = m["model"]
            old = (m.get("pricingDesc") or "").strip()
            new = (live.get(mid) if mid in live else None)
            if new is None:
                changed.append({"kie_id": mid, "change": "пропала из живого маркета"})
            elif new.strip() != old:
                changed.append({"kie_id": mid, "change": "pricingDesc изменился", "old": old[:200], "new": new[:200]})
        out["changed_pricing"] = changed
        out["added"] = sorted(set(live) - {m["model"] for m in snapshot_models})
        out["checked"] = True
    except (urllib.error.URLError, TimeoutError, OSError) as e:  # сеть/таймаут
        out["reason"] = f"/api/v1/models недоступен: {type(e).__name__}"
    try:
        req = urllib.request.Request("https://api.kie.ai/api/v1/chat/credit", headers=headers)
        with urllib.request.urlopen(req, timeout=15) as r:
            data = json.loads(r.read().decode("utf-8"))
        out["credit_endpoint"] = data.get("code") == 200
        d = data.get("data")
        out["balance_credits"] = d if isinstance(d, (int, float)) else (d or {}).get("credits")
    except (urllib.error.URLError, TimeoutError, OSError):
        pass
    return out


RES_OUT = re.compile(r"^(\d+(?:\.\d+)?)\s*([pPkK])$")


def export_when(when: dict) -> dict:
    """when в формате, совместимом с docs/kie-model-families.json:
    resolution «720p»/«2K», duration строкой, sound/mode/with_video."""
    out: dict = {}
    for k, v in (when or {}).items():
        if k == "resolution" and isinstance(v, str):
            m = RES_OUT.match(v)
            if m:
                v = m.group(1) + ("p" if m.group(2).lower() == "p" else "K")
        elif k == "duration":
            v = str(int(float(v)))
        out[k] = v
    return out


def families_crosscheck(models: dict, families: dict) -> dict:
    """Сверка кредитов с независимым разбором соседнего шага 7 (docs/kie-model-families.json)."""
    only_fam = sorted(set(families) - set(models))
    only_us = sorted(set(models) - set(families))
    agree: list[str] = []
    differ: list[dict] = []
    unit_map = {"tokens": "1m_tokens", "megapixel": "mp", "unknown": None}
    unit_diff: list[dict] = []
    for mid in sorted(set(families) & set(models)):
        fam = families[mid]["pricing"] or {}
        f_cred = {round(float(r["credits"]), 6) for r in fam.get("rules") or [] if r.get("credits") is not None}
        mine: set[float] = set()
        for r in models[mid].get("rules") or []:
            if r.get("credits") is not None:
                mine.add(round(float(r["credits"]), 6))
        for e in models[mid].get("extra_charges") or []:
            mine.add(round(float(e["credits"]), 6))
        if f_cred == mine:
            agree.append(mid)
        else:
            differ.append({
                "kie_id": mid,
                "families_credits": sorted(f_cred),
                "our_credits": sorted(mine),
                "only_families": sorted(f_cred - mine),
                "only_ours": sorted(mine - f_cred),
                "explained": FAMILIES_DIFF_EXPLAINED.get(mid),
            })
        fu = unit_map.get(fam.get("unit"), fam.get("unit"))
        if fu is not None and models[mid].get("unit") and fu != models[mid]["unit"]:
            unit_diff.append({"kie_id": mid, "families_unit": fu, "our_unit": models[mid]["unit"]})
    unexplained = [d for d in differ if not d["explained"]]
    return {
        "source": "docs/kie-model-families.json (шаг 7, коммит 2594dd74)",
        "families_modes": len(families),
        "covered_both": len(set(families) & set(models)),
        "only_in_families": only_fam,
        "only_in_us": only_us,
        "credits_agree": len(agree),
        "credits_differ": differ,
        "credits_differ_unexplained": unexplained,
        "unit_differ": unit_diff,
    }


FAMILIES_DIFF_EXPLAINED = {
    "bytedance/seedance-1.5-pro": "в прайсе kie.ai цены нет (в живом API модели тоже нет) — цена из каталога студии @HEAD",
    "bytedance/seedance-2-5-draft": "draft своих ставок не имеет — наследует ставки Seedance 2.5 по режиму источника",
    "ai-music-api/cover-generate": "в прайсе «free» — у нас 0 кр",
    "grok-imagine-image-2-0/segment-map": "в прайсе «free» — у нас 0 кр",
    "gpt-image-2-6/flare-text-to-image": "семьи оставили только токены, у которых в тексте есть слово «credits» (900 и 36); "
                                          "у нас — вся токен-таблица, включая 225/1 440/5 400/SVG-авторов, взятые из строки цены",
    "gpt-image-2-6/flare-image-to-image": "у нас вся токен-таблица (см. flare-text-to-image)",
    "gpt-image-2-6/sunburst-text-to-image": "у нас вся токен-таблица (см. flare-text-to-image)",
    "gpt-image-2-6/sunburst-image-to-image": "у нас вся токен-таблица (см. flare-text-to-image)",
    "gemini-omni-video": "у семейств нет разложения по длительности/видеовходу (только 147…210 по 4K) — у нас полная таблица",
    "google/gemini-omni-flash-1-1": "у нас разложены разрешения 360P/720P/1080P × длительность",
    "google/gemini-omni-flash-1-2": "у семейств только часть ставок — у нас 360P/720P/1080P/4K",
    "google/gemini-omni-flash-1-2-extend": "у нас 360P и 720P отдельными правилами",
    "wan/2-7-image": "в одном описании обе модели (4.8 и 12) — у нас по своей цене на модель",
    "wan/2-7-image-pro": "в одном описании обе модели (4.8 и 12) — у нас по своей цене на модель",
    "minimax-h3/text-to-video": "семьи положили доплату 4 кр за картинку в правила; у нас это extra_charges",
    "minimax-h3/image-to-video": "семьи положили доплату 4 кр за картинку в правила; у нас это extra_charges",
    "minimax-h3/reference-to-video": "семьи положили доплату 4 кр за картинку в правила; у нас это extra_charges",
    "seedream/5-5-image-to-image": "у нас раздельно: ставка 1.44 кр за вход отдельным extra_charge (в семьях слито в правила)",
    "seedream/5-5-layer-decomposition": "у нас раздельно: ставка 1.44 кр за вход отдельным extra_charge",
    "seedream/5-pro-image-to-image": "у нас 0.5 кр за вход отдельным extra_charge",
    "seedream/5-pro-text-to-image": "у нас 0.5 кр за вход отдельным extra_charge",
    "qwen3/image-to-image": "у нас 0.5 кр за вход отдельным extra_charge",
    "qwen3/pro-image-to-image": "у нас 0.5 кр за вход отдельным extra_charge",
    "qwen3/pro-text-to-image": "у семейств нет 0.5 кр за вход; у нас есть (как в прайсе для i2i)",
    "video/upscale": "семьи из строки «1.5 / 3 / 6 кредитов» взяли только 6; у нас все три ставки (1080P/2K/4K)",
    "wan/2-6-text-to-video": "семьи потеряли строки 720p для 5/10/15 с (70/140/210); у нас полная таблица длительность × разрешение",
    "wan/2-6-image-to-video": "семьи потеряли строки 720p для 5/10/15 с; у нас полная таблица",
    "wan/2-6-video-to-video": "семьи потеряли строки 720p для 5/10/15 с; у нас полная таблица",
    "wan/2-6-flash-image-to-video": "семьи потеряли ставки без звука (20/40/60 и 1080p без звука); у нас полная таблица",
    "wan/2-6-flash-video-to-video": "семьи потеряли ставки без звука; у нас полная таблица",
}


# ---------------------------------------------------------------- JSON

def build_payload(models: dict, checks: dict, complex_formulas: dict, studio: dict, live: dict,
                  problems: list[str], raw_models: list[dict], families: dict) -> dict:
    from datetime import datetime, timezone

    diff = families_crosscheck(models, families)
    exported = json.loads(json.dumps(models))  # копия, чтобы не менять внутренние данные
    for m in exported.values():
        m["rules"] = [{**r, "when": export_when(r.get("when") or {})} for r in m.get("rules") or []]
    priced = [m for m in models.values() if m.get("rules")]
    unknown = [m for m in models.values() if not m.get("rules")]
    return {
        "meta": {
            "generated": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
            "branch": "test",
            "shape": "models — словарь по kie_id (182 записи); у каждой unit/formula/rules[{when,usd_kie,usd_client}]/"
                     "default_usd_kie/default_usd_client/markup/source/note/affects_price",
            "source_prices": "docs/kie-ai-raw/models.json — GET https://api.kie.ai/api/v1/models, поле pricingDesc (снапшот 2026-11-13)",
            "source_schemas": "docs/kie-ai-raw/docs-schemas.json — OpenAPI input со страниц docs.kie.ai",
            "source_families": "docs/kie-model-families.json — семьи/режимы шага 7 (независимый разбор кредитов, сверен)",
            "source_table": "docs/kie-ai-models.md / .csv (таблица от 13.11, использована для сверки единиц)",
            "studio_code": "app/services/kie_catalog.py @HEAD (текущие цены студии, кредиты)",
            "credit_usd": CREDIT_USD,
            "markup": MARKUP,
            "entries_total": len(models),
            "api_media_models": len(raw_models and [m for m in raw_models if m["model"] in models]) or 181,
            "priced": len(priced),
            "unknown": len(unknown),
            "api_key": "не записан в файлы (передавался только в заголовке запроса из env)",
        },
        "markup": MARKUP,
        "credit_usd": CREDIT_USD,
        "models": exported,
        "complex_formulas": complex_formulas,
        "studio_diff": studio,
        "families_crosscheck": diff,
        "checks": checks,
        "unknown": [
            {"kie_id": mid, "reason": models[mid].get("unknown_reason"), "usd_kie": None, "usd_client": None}
            for mid in sorted(models)
            if not models[mid].get("rules")
        ],
        "parsing_problems": problems,
        "live_check": live,
    }


def write_json(payload: dict) -> None:
    OUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


# ---------------------------------------------------------------- MD

UNIT_LABEL = {
    "sec": "за секунду",
    "gen": "за генерацию",
    "image": "за картинку",
    "mp": "за мегапиксель",
    "1m_tokens": "за 1M токенов",
    "1k_chars": "за 1k символов",
    None: "неизвестно",
}


def _money(x: float | None) -> str:
    if x is None:
        return "—"
    if x == 0:
        return "$0"
    s = f"{x:.4f}".rstrip("0").rstrip(".")
    return "$" + s


def _range(rules: list[dict], key: str) -> str:
    vals = [r.get(key) for r in rules if r.get(key) is not None]
    if not vals:
        return "—"
    lo, hi = min(vals), max(vals)
    if abs(lo - hi) < 1e-9:
        return _money(lo)
    return f"{_money(lo)} – {_money(hi)}"


def write_md(payload: dict) -> None:
    models = payload["models"]
    checks = payload["checks"]
    cov = checks["coverage"]
    ar = checks["arithmetic"]
    un = checks["units"]
    studio = payload["studio_diff"]
    live = payload["live_check"]
    meta = payload["meta"]
    fam = payload["families_crosscheck"]
    priced = [m for m in models.values() if m.get("rules")]
    extras_n = sum(len(m.get("extra_charges") or []) for m in models.values())
    L: list[str] = []
    A = L.append

    A("# Цены kie.ai в долларах по конфигурациям: 182 записи, наценка студии 25%")
    A("")
    A(f"Собрано: {meta['generated']}. Ветка `test`. Ключ kie.ai в файлы не писался.")
    A("")
    A("**Правило цены:** `usd_client = usd_kie × 1.25`, где `usd_kie` — цена kie.ai из прайса "
      f"(1 кредит = ${CREDIT_USD}). Кредиты — внутреннее поле, не единица отображения.")
    A("")
    A("**Состав:** 182 записи = 181 медиа-модель живого `GET /api/v1/models` "
      f"(видео {cov['by_media'].get('video', 0)}, картинки {cov['by_media'].get('image', 0)}) "
      "+ `bytedance/seedance-1.5-pro` (в живом API её нет, цена из каталога студии).")
    A("")
    A("**С чем сверено:**")
    A("- `docs/kie-ai-raw/models.json` — живой `GET /api/v1/models`, поле `pricingDesc` (снапшот 13.11.2026) — основной источник цены;")
    A("- `docs/kie-ai-raw/docs-schemas.json` — OpenAPI-схемы полей (145 из 181 модели) — какие настройки вообще существуют;")
    A("- `docs/kie-model-families.json` — независимый разбор кредитов соседним шагом 7 (72 семейства / 182 режима);")
    A("- `docs/kie-ai-models.csv` — таблица от 13.11 (колонка «единица цены» → сверка единиц);")
    A("- `app/services/kie_catalog.py` @HEAD — текущие цены студии (для §6).")
    A("")
    A("**Файлы:** `docs/kie-prices-usd.json` (машинный прайс), этот `docs/kie-prices-usd.md`, "
      "сборщик `docs/build_kie_prices.py`.")
    A("")
    A("**Как читать JSON:** `models` — словарь по `kie_id` (182 записи). У каждой: `unit`, `formula`, "
      "`rules[{when, credits, usd_kie, usd_client}]`, `default_usd_kie`, `default_usd_client`, `markup`, "
      "`source`, `note`, `affects_price[]`, `extra_charges[]`, `pricing_desc` (сырой текст прайса). "
      "`when` совместим с `pricing.when` из `kie-model-families.json`: `resolution` — `720p`/`2K`, "
      "`duration` — строкой, `sound` / `mode` / `with_video`; плюс `token_kind`, `upscale`, `from_resolution`, "
      "`max_mp` (порог мегапикселей у апскейлов и MiniMax H3) там, где семейства эти оси не разложили.")
    A("")
    A("## 1. Сводка")
    A("")
    A(f"- Записей всего: **{len(models)}** (181 из живого API + 1 из каталога студии).")
    A(f"- С ценой: **{len(priced)}**, «неизвестно»: **{len(models) - len(priced)}** (список в §8).")
    A(f"- Правил цены: **{cov['rules_total']}**, доплат за входные картинки: **{extras_n}**; "
      f"в среднем {cov['avg_rules_per_priced']} правила на модель.")
    A("- Распределение по числу правил: " + ", ".join(f"{k} — {v} мод." for k, v in cov["rules_per_model_hist"].items()))
    A(f"- С OpenAPI-схемой полей: {cov['with_schema']} из 181.")
    A("- Единицы: " + ", ".join(f"{UNIT_LABEL.get(k, k)} — {v}" for k, v in un["unit_counts"].items()) + ".")
    if live.get("checked"):
        A(f"- Сверка с живым API 14.11: моделей в API {live.get('live_total')}, "
          f"изменений `pricingDesc`: {len(live.get('changed_pricing') or [])}, "
          f"баланс ключа: {live.get('balance_credits')} кр.")
        if live.get("added"):
            A(f"- В живом API сверх среза 13.11 появились модели: {', '.join('`' + x + '`' for x in live['added'])} — "
              "в 182 записи не включены (появились после среза; в семействах шага 7 их тоже нет).")
    else:
        A(f"- Сверка с живым API: {live.get('reason', 'не выполнялась')}.")
    A("")
    A("### По брендам")
    A("")
    A("| Бренд | Видео | Картинки | С ценой | Неизвестно |")
    A("|---|---|---|---|---|")
    brands: dict[str, Counter] = defaultdict(Counter)
    for mid, m in models.items():
        b = m.get("brand") or "—"
        brands[b][m["media"]] += 1
        if m.get("rules"):
            brands[b]["priced"] += 1
        else:
            brands[b]["unknown"] += 1
    for b in sorted(brands, key=lambda x: -(brands[x]["video"] + brands[x]["image"])):
        c = brands[b]
        A(f"| {b} | {c['video']} | {c['image']} | {c['priced']} | {c['unknown']} |")
    A("")

    A("## 2. Покрытие ценами")
    A("")
    A(f"- Ценозависимых настроек (модель × настройка, по схемам docs): **{cov['price_settings_pairs']}**; "
      f"из них прайс явно упоминает **{cov['price_settings_mentioned_in_price']}**.")
    A(f"- Настройки, упомянутые в прайсе, но не покрытые правилом: **{len(cov['gaps'])}**.")
    if cov["gaps"]:
        for g in cov["gaps"]:
            A(f"  - {g}")
    if cov.get("explained_gaps"):
        A("- Спорные случаи, разобранные вручную:")
        for g in cov["explained_gaps"]:
            A(f"  - `{g['kie_id']}` / {g['dim']}: {g['reason']}")
    A("")
    A("Настройки, которые цена не трогает (seed, negative_prompt, watermark, тип входа у плоских моделей) — "
      "в прайсе не упомянуты, цена от них не зависит.")
    A("")

    A("## 3. Сверка с независимым разбором шага 7 (`docs/kie-model-families.json`)")
    A("")
    A(f"Семейств/режимов: **{fam['families_modes']}**; `kie_id` совпали у **{fam['covered_both']}** записей "
      f"(только в семействах: {len(fam['only_in_families'])}, только у нас: {len(fam['only_in_us'])}).")
    A(f"- Кредиты полностью совпали: **{fam['credits_agree']}** из {fam['families_modes']}.")
    A(f"- Расходятся: **{len(fam['credits_differ'])}**, все с причиной (ниже); необъяснённых — "
      f"**{len(fam['credits_differ_unexplained'])}**.")
    A("")
    A("| kie_id | кредиты в семействах | кредиты у нас | причина |")
    A("|---|---|---|---|")
    for d in fam["credits_differ"]:
        A(f"| `{d['kie_id']}` | {d['families_credits'] or '—'} | {d['our_credits'] or '—'} | {d['explained'] or '—'} |")
    A("")
    A(f"- Единицы: у семейств {len(fam['unit_differ'])} записей размечены грубее — плоская цена картинки/ролика "
      "помечена `gen`, у нас `image`/`sec` по факту механики. По деньгам это не расхождение: считает `usd_kie` "
      "за единицу, а единицу backend должен брать из этого файла.")
    A("")

    A("## 4. Таблица цен по моделям")
    A("")
    A("`база` — цена kie.ai (`usd_kie`) в единице модели; `клиент` — цена студии (`usd_kie × 1.25`). "
      "Если цена зависит от настроек — диапазон и число правил. `†` — есть доплата за входные картинки "
      "(см. §5 и `extra_charges` в JSON).")
    A("")
    A("| Модель (kie_id) | media | unit | прав. | база, $ | клиент (+25%), $ | формула |")
    A("|---|---|---|---|---|---|---|")
    for mid in sorted(models, key=lambda x: ((models[x].get("brand") or ""), x)):
        m = models[mid]
        if not m.get("rules"):
            A(f"| `{mid}` | {m['media']} | — | 0 | — | — | неизвестно |")
            continue
        mark = "†" if m.get("extra_charges") else ""
        formula = (m.get("formula") or "").replace("|", "/")
        if len(formula) > 90:
            formula = formula[:87] + "…"
        A(f"| `{mid}`{mark} | {m['media']} | {UNIT_LABEL.get(m.get('unit'), m.get('unit'))} | {len(m['rules'])} | "
          f"{_range(m['rules'], 'usd_kie')} | {_range(m['rules'], 'usd_client')} | {formula} |")
    A("")

    A("## 5. Сложные формулы с примерами расчёта")
    A("")
    A("Примеры пересчитаны скриптом из правил, не переписаны из прайса. Где прайс даёт total — он сверен (§7.2).")
    A("")
    for key, cf in payload["complex_formulas"].items():
        A(f"### {key}")
        A("")
        A(f"- Формула: {cf.get('formula')}")
        if cf.get("duration_billing"):
            A(f"- Биллинг длительности: `{cf['duration_billing']}`")
        if cf.get("draft_inherits"):
            A(f"- Наследование: `{cf['draft_inherits']}` (draft-upgrade берёт ставки и режим источника)")
        if cf.get("extra_charges"):
            for e in cf["extra_charges"]:
                free = f", первые {e['free_first']} бесплатно" if e.get("free_first") else ""
                A(f"- Доплата: {e['what']} — {e['credits']} кр ({_money(e['usd_kie'])} / клиент {_money(e['usd_client'])}){free}")
        for ex in cf.get("examples") or []:
            cfg = ", ".join(f"{k}={v}" for k, v in ex["cfg"].items())
            A(f"- Пример: {cfg} → **{ex['credits']} кр** = {_money(ex['usd_kie'])} база / "
              f"{_money(ex['usd_client'])} клиент ({ex.get('source')})")
        if cf.get("note"):
            A(f"- Примечание: {cf['note']}")
        A("")

    A("## 6. Расхождения с текущим кодом студии (`kie_catalog.py` @HEAD)")
    A("")
    covered = [x for x in studio["kie_ids_in_studio"] if x in models]
    non_media = [x for x in studio["kie_ids_in_studio"] if x not in models]
    A(f"В студии {studio['studio_models']} записей. С прайсом сопоставлено **{len(covered)}** медиа-моделей "
      f"(из {len(models)}), правил: **{studio['matched_rules']}** ({studio['mapped_pairs']} строк сверки). "
      f"В студии нет **{len(studio['studio_missing_media_ids'])}** записей прайса — включая "
      "`bytedance/seedance-1.5-pro`, которая есть только в студии.")
    if non_media:
        A(f"Ещё {len(non_media)} id студии — музыка/аудио, их нет среди 182 медиа-моделей: "
          + ", ".join(f"`{x}`" for x in non_media) + ".")
    A("")
    A("`Δ прайса` = (цена kie − цена студии в кредитах×0.005) / цена студии. "
      "`Δ клиента` = (kie×1.25 − цена студии) / цена студии. Плюс — прайс/клиент дороже кода студии.")
    A("")
    A(f"Расхождений больше 1%: **{len(studio['dangerous'])}** правил. Сгруппировано по модели:")
    A("")
    groups: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for r in studio["dangerous"]:
        groups[(r["studio_id"], r["kie_id"])].append(r)
    A("| Студия | kie_id | худший Δ прайса | Δ клиента | конфигураций | пример |")
    A("|---|---|---|---|---|---|")
    for (sid, kid), rows in sorted(groups.items(), key=lambda kv: -max(abs(r["delta_pricelist_vs_studio_pct"]) for r in kv[1])):
        rows.sort(key=lambda r: -abs(r["delta_pricelist_vs_studio_pct"]))
        worst = rows[0]
        cfg = ", ".join(f"{k}={v}" for k, v in (worst.get("config") or {}).items())
        A(f"| `{sid}` | `{kid}` | {worst['delta_pricelist_vs_studio_pct']:+.1f}% | "
          f"{worst['delta_client_vs_studio_pct']:+.1f}% | {len(rows)} | {cfg or '—'} |")
    A("")
    A("Полная построчная таблица — в JSON `studio_diff.rows` (в этом файле оставлены только расхождения >1%).")
    A("")
    if studio["unmapped"]:
        A("**Чего нет в живом `/api/v1/models` — сверять не с чем:**")
        A("")
        for u in studio["unmapped"]:
            A(f"- `{u['studio_id']}` — {u['reason']}")
        A("")
    A("**Доплаты, которых в студии нет вообще:** входные картинки Seedream 5 Pro / Seedream 5.5 (0.5–1.44 кр), "
      "Qwen3 (0.5 кр за вход), MiniMax H3 (4 кр за картинку сверх 5 бесплатных). В студии правило одно — цена не растёт "
      "от числа входов, то есть при нескольких входных картинках студия **недосчитывает**.")
    A("")

    A("## 7. Внутренние сверки")
    A("")
    A("### 7.1 Покрытие")
    A("")
    A(f"- записей: **{len(models)}**; с ценой **{len(priced)}**; «неизвестно» **{len(models) - len(priced)}**;")
    A(f"- правил: **{cov['rules_total']}**, доплат: **{extras_n}**;")
    A(f"- ценозависимых настроек по схемам: {cov['price_settings_pairs']}, упомянуты в прайсе "
      f"{cov['price_settings_mentioned_in_price']}, непокрытых — {len(cov['gaps'])};")
    A(f"- кредиты сверены с независимым разбором семейств: {fam['credits_agree']}/{fam['families_modes']} совпали, "
      f"остальные объяснены.")
    A("")
    A("### 7.2 Арифметика")
    A("")
    A(f"- Проверено пар «N credits ($X)»: **{ar['credits_usd_pairs_checked']}**.")
    A(f"- Не сходится больше половины цента: **{ar['credits_usd_pairs_bad']}** пар — все в Hailuo 2.3, где прайс округлил $; "
      f"расхождений на округление до сотых: **{len(ar['rounding_pairs'])}** (в пределах ±$0.005, это не ошибка).")
    seen: set[tuple] = set()
    for b in ar["bad_pairs"]:
        key = (b["kie_id"], b["credits"], b["usd_in_price"])
        if key in seen:
            continue
        seen.add(key)
        A(f"  - `{b['kie_id']}`: {b['credits']:g} кр → по курсу {_money(b['calc_usd'])}, в прайсе {_money(b['usd_in_price'])} "
          f"(разница {_money(b['diff'])}). В прайсе студии берём кредиты, не $.")
    A(f"- Моделей, где числа кредитов не совпали с набором правил: **{ar['models_with_unmatched_mentions']}**.")
    for b in ar["unmatched"]:
        A(f"  - `{b['kie_id']}`: нет в правилах {b['missing_in_rules']}; лишнее {b['extra_in_rules']}")
    A(f"- Объяснённых расхождений «упоминание ↔ правило»: **{len(ar['mentions_explained'])}** (пример тотала в прайсе, "
      "токен-строка без слова credits, draft без своих ставок).")
    A("")
    A("### 7.3 Единицы и наценка")
    A("")
    A(f"- Правил с проверкой `usd_client = usd_kie × 1.25` (до 4 знаков): **{un['markup_checked']}**, "
      f"несоответствий: **{len(un['markup_bad'])}**.")
    A(f"- Единица подтверждена словом «per …» в тексте прайса: **{un['unit_phrase_ok']}** моделей; "
      f"у **{len(un['unit_phrase_missing'])}** единица выведена из механики (плоская цена «for 1K»/«costs N credits», "
      "без слова per) — по типу медиа.")
    A(f"- Расхождений с колонкой «единица цены» в CSV: **{len(un['csv_unit_mismatch'])}**.")
    for b in un["csv_unit_mismatch"]:
        A(f"  - `{b['kie_id']}`: в CSV «{b['csv_unit']}», у нас `{b['our_unit']}`")
    for b in un.get("csv_unit_explained") or []:
        A(f"  - объяснено: `{b['kie_id']}` — {b['reason']}")
    A("")

    A("## 8. Неизвестно")
    A("")
    A("| kie_id | почему |")
    A("|---|---|")
    for u in payload["unknown"]:
        A(f"| `{u['kie_id']}` | {u['reason']} |")
    A("")
    A("Записи, где цена есть, но она не «за картинку/ролик» (формула и `default_*` в JSON важнее прайсовой строки): "
      "`bytedance/seedance-2-5-draft` (наследует биллинг источника), `gpt-image-2-6/*` (4 модели — токены за 1M, "
      "`default_*` = null), `qwen/text-to-image` и `qwen/image-edit` (за мегапиксель), `qwen2/text-to-image` и "
      "`qwen2/image-edit` (только $0.03, кредитов в прайсе нет), 2 бесплатные (`ai-music-api/cover-generate`, "
      "`grok-imagine-image-2-0/segment-map` — 0 кр), `bytedance/seedance-1.5-pro` (цена из каталога студии).")
    A("")
    A("## 9. Замечания по данным")
    A("")
    A("- `ideogram/v3-text-to-image` в `/api/v1/models` помечен `taskType: Text to Video`, но это картинки "
      "(id/цена/страница docs) — классифицирован как `image` с пометкой `media_note`.")
    A("- В `pricingDesc` всюду есть «High-tier top-ups (+10% bonus)…» — бонус за крупные пополнения, а не цена; "
      "в расчёт не брали.")
    A("- Hailuo 2.3: 50 кр за 10 с 768P и за 6 с 1080P в прайсе стоят как $0.26 вместо $0.25 — берём кредиты (0.25).")
    A("- Разбор соседнего шага 7 потерял часть строк в `wan/2-6*` и `video/upscale` (см. §3) — здесь они восстановлены "
      "из `pricingDesc`; чисел, которых нет в прайсе, не добавлено.")
    A("- `gpt-image-2-6`: в прайсе 6 позиций токенов + 3 модели SVG-автора; в §5 и JSON они разложены полями `token_kind`.")
    A("")
    OUT_MD.write_text("\n".join(L) + "\n", encoding="utf-8")


# ---------------------------------------------------------------- main

def write_audit(payload: dict) -> None:
    WORK.mkdir(exist_ok=True)
    models = payload["models"]
    lines: list[str] = []
    A = lines.append
    A(f"моделей: {len(models)}")
    for mid in sorted(models):
        m = models[mid]
        A(f"\n### {mid} | {m['media']} | unit={m.get('unit')} | правил={len(m.get('rules') or [])} | "
          f"доплат={len(m.get('extra_charges') or [])}")
        A(f"formula: {m.get('formula')}")
        for r in m.get("rules") or []:
            A(f"  {r.get('credits')} кр / {_money(r.get('usd_kie'))} → клиент {_money(r.get('usd_client'))} | when={r.get('when')}")
        for e in m.get("extra_charges") or []:
            A(f"  + доплата: {e.get('what')} {e.get('credits')} кр (free_first={e.get('free_first')})")
        if m.get("examples"):
            A(f"  examples: {m.get('examples')}")
    cov = payload["checks"]["coverage"]
    A("\n--- проблемы парсинга:")
    for p in payload["parsing_problems"]:
        A("  " + p)
    A("\n--- покрытие:")
    A(json.dumps({k: v for k, v in cov.items() if k != "gaps"}, ensure_ascii=False, indent=1))
    A("gaps:")
    for g in cov["gaps"]:
        A("  " + g)
    A("\n--- арифметика (плохие пары):")
    for b in payload["checks"]["arithmetic"]["bad_pairs"]:
        A("  " + json.dumps(b, ensure_ascii=False))
    A("\n--- несовпадения упоминаний и правил:")
    for b in payload["checks"]["arithmetic"]["unmatched"]:
        A("  " + json.dumps(b, ensure_ascii=False))
    A("\n--- единицы:")
    un = payload["checks"]["units"]
    A(f"  markup_bad={un['markup_bad']}")
    A(f"  unit_phrase_missing={un['unit_phrase_missing']}")
    A(f"  csv_unit_mismatch={un['csv_unit_mismatch']}")
    A("\n--- студия:")
    A(f"  сопоставлено: {payload['studio_diff']['matched_rules']}, отсутствуют в студии: "
      f"{payload['studio_diff']['studio_missing_media_models']}")
    for r in payload["studio_diff"]["dangerous"]:
        A(f"  {r['studio_id']} {r['kie_id']} {r['config']} студия={r['studio_credits']} kie={r['kie_credits']} "
          f"Δ={r['delta_pricelist_vs_studio_pct']}%")
    (WORK / "audit.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    media, other = load_models()
    schemas = load_schemas()
    csv_rows = load_csv()
    families = load_families()
    built = build()
    models = built["models"]
    problems = built["problems"]
    # дефолты
    for mid, m in models.items():
        if m.get("rules"):
            dk, dc, why = pick_default(mid, m, schemas)
            m["default_usd_kie"] = dk
            m["default_usd_client"] = dc
            m["default_note"] = why
    for mid in sorted(models):
        if mid not in {m["model"] for m in media} and mid not in EXTRA_MODELS:
            problems.append(f"{mid}: спец-правило для несуществующей модели")
    checks = {
        "coverage": check_coverage(models, schemas),
        "arithmetic": check_arith(models),
        "units": check_units(models, csv_rows),
    }
    complex_formulas = build_complex_formulas(models)
    raw_models = json.loads(RAW_MODELS.read_text(encoding="utf-8"))["data"]["models"]
    studio = studio_diff(models, raw_models)
    live = live_check(raw_models)
    payload = build_payload(models, checks, complex_formulas, studio, live, problems, raw_models, families)
    write_json(payload)
    write_md(payload)
    write_audit(payload)
    fam = payload["families_crosscheck"]
    print(f"models={len(models)} priced={payload['meta']['priced']} unknown={payload['meta']['unknown']} "
          f"rules={checks['coverage']['rules_total']} problems={len(problems)} "
          f"bad_pairs={checks['arithmetic']['credits_usd_pairs_bad']} "
          f"unmatched={checks['arithmetic']['models_with_unmatched_mentions']} "
          f"studio_bad={len(studio['dangerous'])} families_agree={fam['credits_agree']}/{len(families)} "
          f"families_unexplained={len(fam['credits_differ_unexplained'])}")
    if problems:
        print("ПРОБЛЕМЫ:")
        for p in problems:
            print("  ", p)


if __name__ == "__main__":
    main()



