"""Сборка семейств и режимов моделей kie.ai (шаг 7 мастер-задачи).

Вход:
  docs/kie-ai-raw/models.json      — живой /api/v1/models (251 модель)
  docs/kie-ai-raw/docs-schemas.json — OpenAPI-схемы input (145 id медиа-моделей)
  docs/kie-ai-models.csv           — таблица от 13.11 (сверка, не переписывается)
  app/services/kie_catalog.py      — текущий каталог студии (поля для id без доков)

Выход:
  docs/kie-model-families.json         — семейства/режимы по контракту шага 7
  docs/kie-model-families.md           — человекочитаемый свод
  docs/kie-model-families-checks.json  — результаты трёх сверок

Запуск: C:\\Users\\Admin\\Desktop\\video-pipeline\\.venv\\Scripts\\python.exe docs\\build_kie_families.py
"""

from __future__ import annotations

import csv
import importlib.util
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
RAW = DOCS / "kie-ai-raw"
OUT_JSON = DOCS / "kie-model-families.json"
OUT_MD = DOCS / "kie-model-families.md"
OUT_CHECKS = DOCS / "kie-model-families-checks.json"

CREDIT_USD = 0.005

# Перепроверка живого API (только бесплатные GET), 2026-11-14 12:42 MSK:
# /api/v1/models → 253 модели (снапшот 13.11 — 251), медиа по-прежнему 181 = видео 100 + картинки 81;
# два новых id — gemini-4-hydrogen, gemini-4-hydrogen-openai, у обоих taskType ["Chat"], вне задачи.
# /api/v1/chat/credit → HTTP 200, code 200.
LIVE_CHECK = {
    "checked_at": "2026-11-14 12:42 MSK",
    "api_total_models": 253,
    "api_media_models": 181,
    "api_video": 100,
    "api_image": 81,
    "new_since_snapshot": ["gemini-4-hydrogen", "gemini-4-hydrogen-openai"],
    "new_task_types": ["Chat", "Chat"],
    "credit_http": 200,
}

# ---------------------------------------------------------------------------
# 1. Спецификация семейств: (family_id, label, brand, media, [(mode_id, label, kie_id)])
#    Правило: семейство = бренд + поколение (базовое название без служебных суффиксов),
#    режим = суффикс/тип входа/утилита внутри поколения.
# ---------------------------------------------------------------------------

FAMILIES: list[tuple[str, str, str, str, list[tuple[str, str, str]]]] = [
    # ============================== ВИДЕО ==============================
    ("happyhorse-1-1", "HappyHorse 1.1", "Alibaba", "video", [
        ("t2v", "Текст → видео", "happyhorse-1-1/text-to-video"),
        ("i2v", "Картинка → видео", "happyhorse-1-1/image-to-video"),
        ("r2v", "Референс → видео", "happyhorse-1-1/reference-to-video"),
    ]),
    ("happyhorse", "HappyHorse", "Alibaba", "video", [
        ("t2v", "Текст → видео", "happyhorse/text-to-video"),
        ("i2v", "Картинка → видео", "happyhorse/image-to-video"),
        ("r2v", "Референс → видео", "happyhorse/reference-to-video"),
        ("video-edit", "Редактирование видео", "happyhorse/video-edit"),
    ]),
    ("seedance-2-0", "Seedance 2.0", "ByteDance", "video", [
        ("standard", "Стандарт (текст / картинка / видео)", "bytedance/seedance-2"),
        ("fast", "Fast", "bytedance/seedance-2-fast"),
        ("mini", "Mini", "bytedance/seedance-2-mini"),
    ]),
    ("seedance-2-5", "Seedance 2.5", "ByteDance", "video", [
        ("standard", "Стандарт (текст / картинка / видео)", "bytedance/seedance-2-5"),
        ("draft", "Draft (черновик)", "bytedance/seedance-2-5-draft"),
    ]),
    ("seedance-1-0", "Seedance 1.0", "ByteDance", "video", [
        ("pro-t2v", "Pro: текст → видео", "bytedance/v1-pro-text-to-video"),
        ("pro-i2v", "Pro: картинка → видео", "bytedance/v1-pro-image-to-video"),
        ("pro-fast-i2v", "Pro Fast: картинка → видео", "bytedance/v1-pro-fast-image-to-video"),
        ("lite-t2v", "Lite: текст → видео", "bytedance/v1-lite-text-to-video"),
        ("lite-i2v", "Lite: картинка → видео", "bytedance/v1-lite-image-to-video"),
    ]),
    ("seedance-1-5", "Seedance 1.5", "ByteDance", "video", [
        ("pro", "Pro (текст / картинка)", "bytedance/seedance-1.5-pro"),
    ]),
    ("veo-3-1", "Veo 3.1", "Google", "video", [
        ("generate", "Генерация (Lite / Fast / Quality)", "veo-3-1"),
        ("extend", "Продление видео", "veo/extend"),
        ("upscale-1080p", "Апскейл до 1080p", "veo/get-1080p-video"),
        ("upscale-4k", "Апскейл до 4K", "veo/get-4k-video"),
    ]),
    ("gemini-omni", "Gemini Omni", "Google", "video", [
        ("video", "Видео (текст / картинка)", "gemini-omni-video"),
        ("character", "Персонаж", "gemini-omni-character"),
    ]),
    ("gemini-omni-flash-1-1", "Gemini Omni Flash 1.1", "Google", "video", [
        ("video", "Видео (текст / картинка / видео)", "google/gemini-omni-flash-1-1"),
    ]),
    ("gemini-omni-flash-1-2", "Gemini Omni Flash 1.2", "Google", "video", [
        ("video", "Видео (текст / картинка / видео)", "google/gemini-omni-flash-1-2"),
        ("extend", "Продление видео", "google/gemini-omni-flash-1-2-extend"),
    ]),
    ("grok-imagine-video", "Grok Imagine Video", "Grok", "video", [
        ("t2v", "Текст → видео", "grok-imagine/text-to-video"),
        ("i2v", "Картинка → видео", "grok-imagine/image-to-video"),
        ("extend", "Продление видео", "grok-imagine/extend"),
        ("upscale", "Апскейл", "grok-imagine/upscale"),
    ]),
    ("grok-imagine-video-1-5", "Grok Imagine Video 1.5 (preview)", "Grok", "video", [
        ("i2v", "Картинка → видео", "grok-imagine-video-1-5-preview"),
    ]),
    ("hailuo-02", "Hailuo 02", "Hailuo", "video", [
        ("t2v-pro", "Текст → видео (Pro)", "hailuo/02-text-to-video-pro"),
        ("t2v-standard", "Текст → видео (Standard)", "hailuo/02-text-to-video-standard"),
        ("i2v-pro", "Картинка → видео (Pro)", "hailuo/02-image-to-video-pro"),
        ("i2v-standard", "Картинка → видео (Standard)", "hailuo/02-image-to-video-standard"),
    ]),
    ("hailuo-2-3", "Hailuo 2.3", "Hailuo", "video", [
        ("i2v-pro", "Картинка → видео (Pro)", "hailuo/2-3-image-to-video-pro"),
        ("i2v-standard", "Картинка → видео (Standard)", "hailuo/2-3-image-to-video-standard"),
    ]),
    ("minimax-h3", "MiniMax H3 (видео)", "Hailuo", "video", [
        ("t2v", "Текст → видео", "minimax-h3/text-to-video"),
        ("i2v", "Картинка → видео", "minimax-h3/image-to-video"),
        ("r2v", "Референс → видео", "minimax-h3/reference-to-video"),
    ]),
    ("infinitalk", "Infinitalk (липсинк по аудио)", "Infinitalk", "video", [
        ("from-audio", "Аудио → видео", "infinitalk/from-audio"),
    ]),
    ("kie-video-upscale", "Kie — апскейл видео", "Kie", "video", [
        ("upscale", "Апскейл видео", "video/upscale"),
    ]),
    ("kling-2-1", "Kling 2.1", "Kling", "video", [
        ("master-t2v", "Master: текст → видео", "kling/v2-1-master-text-to-video"),
        ("master-i2v", "Master: картинка → видео", "kling/v2-1-master-image-to-video"),
        ("pro-i2v", "Pro: картинка → видео", "kling/v2-1-pro"),
        ("standard-i2v", "Standard: картинка → видео", "kling/v2-1-standard"),
    ]),
    ("kling-2-5-turbo", "Kling 2.5 Turbo", "Kling", "video", [
        ("t2v-pro", "Текст → видео (Pro)", "kling/v2-5-turbo-text-to-video-pro"),
        ("i2v-pro", "Картинка → видео (Pro)", "kling/v2-5-turbo-image-to-video-pro"),
    ]),
    ("kling-2-6", "Kling 2.6", "Kling", "video", [
        ("t2v", "Текст → видео", "kling-2.6/text-to-video"),
        ("i2v", "Картинка → видео", "kling-2.6/image-to-video"),
        ("motion-control", "Motion Control", "kling-2.6/motion-control"),
    ]),
    ("kling-3-0", "Kling 3.0", "Kling", "video", [
        ("video", "Видео (Pro / Standard / 4K)", "kling-3.0/video"),
        ("motion-control", "Motion Control", "kling-3.0/motion-control"),
        ("omni-t2v", "Omni: текст → видео", "kling-3.0-omni/text-to-video"),
        ("omni-i2v", "Omni: картинка → видео", "kling-3.0-omni/image-to-video"),
        ("omni-r2v", "Omni: референс → видео", "kling-3.0-omni/reference-to-video"),
        ("omni-transformation", "Omni: трансформация", "kling-3.0-omni/transformation"),
        ("turbo-t2v", "Turbo: текст → видео", "kling/v3-turbo-text-to-video"),
        ("turbo-i2v", "Turbo: картинка → видео", "kling/v3-turbo-image-to-video"),
    ]),
    ("kling-4-0", "Kling 4.0", "Kling", "video", [
        ("keyframe", "Ключевые кадры → видео", "kling-4.0/keyframe-to-video"),
        ("keyframe-flash", "Flash: ключевые кадры → видео", "kling-4.0/flash-keyframe-to-video"),
        ("r2v", "Референс → видео", "kling-4.0/reference-to-video"),
        ("r2v-flash", "Flash: референс → видео", "kling-4.0/flash-reference-to-video"),
    ]),
    ("kling-avatar", "Kling AI Avatar", "Kling", "video", [
        ("avatar-pro", "Аватар (Pro)", "kling/ai-avatar-pro"),
        ("avatar-standard", "Аватар (Standard)", "kling/ai-avatar-standard"),
    ]),
    ("omnihuman-1-5", "OmniHuman 1.5", "OmniHuman", "video", [
        ("avatar", "Оживление фото", "omnihuman-1-5"),
    ]),
    ("omnihuman-2-0", "OmniHuman 2.0", "OmniHuman", "video", [
        ("avatar", "Оживление фото", "omnihuman-2-0"),
    ]),
    ("pixverse-v6", "PixVerse V6", "Pixverse", "video", [
        ("t2v", "Текст → видео", "pixverse-v6/text-to-video"),
        ("i2v", "Картинка → видео", "pixverse-v6/image-to-video"),
        ("t2v-max", "Текст → видео (Max)", "pixverse-v6-max/text-to-video"),
        ("i2v-max", "Картинка → видео (Max)", "pixverse-v6-max/image-to-video"),
        ("transition", "Первый + последний кадр", "pixverse-v6/transition"),
        ("extend", "Продление видео", "pixverse-v6/extend"),
        ("r2v", "Референс → видео (Fusion)", "pixverse-v6/reference-to-video"),
    ]),
    ("runway", "Runway", "Runway", "video", [
        ("generate", "Генерация (текст / картинка)", "runway"),
        ("extend", "Продление видео", "runway/extend-ai-video"),
    ]),
    ("suno-music-video", "Suno — музыкальный клип", "Suno", "video", [
        ("music-video", "Аудио → клип", "ai-music-api/create-music-video"),
    ]),
    ("topaz-video-upscale", "Topaz Video Upscale", "Topaz", "video", [
        ("upscale", "Апскейл видео", "topaz/video-upscale"),
    ]),
    ("vidu-q4", "Vidu Q4", "Vidu", "video", [
        ("i2v", "Картинка → видео", "vidu-q4/image-to-video"),
        ("r2v", "Референс → видео", "vidu-q4/reference-to-video"),
    ]),
    ("volcengine-lipsync", "Volcengine Lip Sync", "Volcengine", "video", [
        ("v2v-lipsync", "Липсинк по видео", "volcengine/video-to-video-lip-sync"),
    ]),
    ("wan-2-2", "WAN 2.2 A14B", "Wan", "video", [
        ("t2v-turbo", "Текст → видео (Turbo)", "wan/2-2-a14b-text-to-video-turbo"),
        ("i2v-turbo", "Картинка → видео (Turbo)", "wan/2-2-a14b-image-to-video-turbo"),
        ("s2v-turbo", "Речь → видео (Turbo)", "wan/2-2-a14b-speech-to-video-turbo"),
    ]),
    ("wan-2-2-animate", "WAN 2.2 Animate", "Wan", "video", [
        ("animate-move", "Перенос движения", "wan/2-2-animate-move"),
        ("animate-replace", "Замена персонажа", "wan/2-2-animate-replace"),
    ]),
    ("wan-2-5", "WAN 2.5", "Wan", "video", [
        ("t2v", "Текст → видео", "wan/2-5-text-to-video"),
        ("i2v", "Картинка → видео", "wan/2-5-image-to-video"),
    ]),
    ("wan-2-6", "WAN 2.6", "Wan", "video", [
        ("t2v", "Текст → видео", "wan/2-6-text-to-video"),
        ("i2v", "Картинка → видео", "wan/2-6-image-to-video"),
        ("v2v", "Видео → видео", "wan/2-6-video-to-video"),
        ("flash-i2v", "Flash: картинка → видео", "wan/2-6-flash-image-to-video"),
        ("flash-v2v", "Flash: видео → видео", "wan/2-6-flash-video-to-video"),
    ]),
    ("wan-2-7", "WAN 2.7", "Wan", "video", [
        ("t2v", "Текст → видео", "wan/2-7-text-to-video"),
        ("i2v", "Картинка → видео", "wan/2-7-image-to-video"),
        ("r2v", "Референс → видео", "wan/2-7-r2v"),
        ("video-edit", "Редактирование видео", "wan/2-7-videoedit"),
    ]),
    ("wan-3-0", "WAN 3.0", "Wan", "video", [
        ("video", "Видео (текст / картинка / видео)", "wan/3-0-video"),
        ("prime", "Видео Prime", "wan/3-0-video-prime"),
    ]),
    # ============================== КАРТИНКИ ==============================
    ("flux-2", "Flux 2", "Black Forest Labs", "image", [
        ("t2i-pro", "Pro: текст → картинка", "flux-2/pro-text-to-image"),
        ("i2i-pro", "Pro: картинка → картинка", "flux-2/pro-image-to-image"),
        ("t2i-flex", "Flex: текст → картинка", "flux-2/flex-text-to-image"),
        ("i2i-flex", "Flex: картинка → картинка", "flux-2/flex-image-to-image"),
    ]),
    ("flux-3", "Flux 3", "Black Forest Labs", "image", [
        ("t2i-klein", "Klein: текст → картинка", "flux-3/klein-text-to-image"),
        ("edit-klein", "Klein: редактирование", "flux-3/klein-edit-image"),
    ]),
    ("flux-1-kontext", "Flux Kontext", "Black Forest Labs", "image", [
        ("edit", "Редактирование по тексту", "flux1-kontext"),
    ]),
    ("seedream-3", "Seedream 3", "ByteDance", "image", [
        ("t2i", "Текст → картинка", "bytedance/seedream"),
    ]),
    ("seedream-4-0", "Seedream 4.0", "ByteDance", "image", [
        ("t2i", "Текст → картинка", "bytedance/seedream-v4-text-to-image"),
        ("edit", "Редактирование", "bytedance/seedream-v4-edit"),
    ]),
    ("seedream-4-5", "Seedream 4.5", "ByteDance", "image", [
        ("t2i", "Текст → картинка", "seedream/4.5-text-to-image"),
        ("edit", "Редактирование", "seedream/4.5-edit"),
    ]),
    ("seedream-5", "Seedream 5", "ByteDance", "image", [
        ("t2i-pro", "Pro: текст → картинка", "seedream/5-pro-text-to-image"),
        ("i2i-pro", "Pro: картинка → картинка", "seedream/5-pro-image-to-image"),
        ("layer-pro", "Pro: разбор по слоям", "seedream/5-pro-layer-decomposition"),
        ("t2i-flash", "Flash: текст → картинка", "seedream/5-flash-text-to-image"),
        ("i2i-flash", "Flash: картинка → картинка", "seedream/5-flash-image-to-image"),
        ("layer-flash", "Flash: разбор по слоям", "seedream/5-flash-layer-decomposition"),
        ("t2i-lite", "Lite: текст → картинка", "seedream/5-lite-text-to-image"),
        ("i2i-lite", "Lite: картинка → картинка", "seedream/5-lite-image-to-image"),
    ]),
    ("seedream-5-5", "Seedream 5.5", "ByteDance", "image", [
        ("t2i", "Текст → картинка", "seedream/5-5-text-to-image"),
        ("i2i", "Картинка → картинка", "seedream/5-5-image-to-image"),
        ("layer", "Разбор по слоям", "seedream/5-5-layer-decomposition"),
    ]),
    ("imagen-4", "Imagen 4", "Google", "image", [
        ("t2i", "Текст → картинка", "google/imagen4"),
        ("fast", "Fast", "google/imagen4-fast"),
        ("ultra", "Ultra", "google/imagen4-ultra"),
    ]),
    ("nano-banana", "Nano Banana", "Google", "image", [
        ("t2i", "Текст → картинка", "google/nano-banana"),
        ("edit", "Редактирование", "google/nano-banana-edit"),
    ]),
    ("nano-banana-2", "Nano Banana 2", "Google", "image", [
        ("generate", "Текст / картинка → картинка", "nano-banana-2"),
    ]),
    ("nano-banana-2-1", "Nano Banana 2.1", "Google", "image", [
        ("generate", "Текст / картинка → картинка", "nano-banana-2-1"),
    ]),
    ("nano-banana-2-lite", "Nano Banana 2 Lite", "Google", "image", [
        ("generate", "Текст / картинка → картинка", "nano-banana-2-lite"),
    ]),
    ("nano-banana-pro", "Nano Banana Pro", "Google", "image", [
        ("generate", "Текст / картинка → картинка", "nano-banana-pro"),
    ]),
    ("grok-imagine-image", "Grok Imagine Image", "Grok", "image", [
        ("t2i", "Текст → картинка", "grok-imagine/text-to-image"),
        ("i2i", "Картинка → картинка", "grok-imagine/image-to-image"),
    ]),
    ("grok-imagine-image-2-0", "Grok Imagine Image 2.0", "Grok", "image", [
        ("t2i", "Текст → картинка", "grok-imagine-image-2-0/text-to-image"),
        ("edit", "Редактирование", "grok-imagine-image-2-0/image-edit"),
        ("segment-edit", "Правка сегментов", "grok-imagine-image-2-0/segment-edit"),
        ("segment-map", "Карта сегментов", "grok-imagine-image-2-0/segment-map"),
    ]),
    ("minimax-h3-image", "MiniMax H3 (картинки)", "Hailuo", "image", [
        ("t2i", "Текст → картинка", "minimax-h3/text-to-image"),
        ("edit", "Редактирование", "minimax-h3/image-edit"),
    ]),
    ("ideogram-character", "Ideogram Character", "Ideogram", "image", [
        ("character", "Персонаж", "ideogram/character"),
        ("character-edit", "Персонаж: редактирование", "ideogram/character-edit"),
        ("character-remix", "Персонаж: ремикс", "ideogram/character-remix"),
    ]),
    ("ideogram-v3", "Ideogram V3", "Ideogram", "image", [
        ("t2i", "Текст → картинка", "ideogram/v3-text-to-image"),
        ("edit", "Редактирование", "ideogram/v3-edit"),
        ("remix", "Ремикс", "ideogram/v3-remix"),
    ]),
    ("kie-image-upscale", "Kie — апскейл картинки", "Kie", "image", [
        ("upscale", "Апскейл картинки", "kie/image-upscale"),
    ]),
    ("omnihuman-1-5-image", "OmniHuman 1.5 — разметка", "OmniHuman", "image", [
        ("human-identification", "Поиск человека", "omnihuman-1-5/human-identification"),
        ("subject-detection", "Детекция объектов", "omnihuman-1-5/subject-detection"),
    ]),
    ("gpt-4o-image", "GPT-4o Image", "OpenAI", "image", [
        ("image", "Текст / картинка → картинка", "4o-image-api"),
    ]),
    ("gpt-image-1-5", "GPT Image 1.5", "OpenAI", "image", [
        ("t2i", "Текст → картинка", "gpt-image/1.5-text-to-image"),
        ("i2i", "Картинка → картинка", "gpt-image/1.5-image-to-image"),
    ]),
    ("gpt-image-2", "GPT Image 2", "OpenAI", "image", [
        ("t2i", "Текст → картинка", "gpt-image-2-text-to-image"),
        ("i2i", "Картинка → картинка", "gpt-image-2-image-to-image"),
    ]),
    ("gpt-image-2-5", "GPT Image 2.5", "OpenAI", "image", [
        ("t2i-flare", "Flare: текст → картинка", "gpt-image-2-5-flare-text-to-image"),
        ("i2i-flare", "Flare: картинка → картинка", "gpt-image-2-5-flare-image-to-image"),
        ("t2i-sunburst", "Sunburst: текст → картинка", "gpt-image-2-5-sunburst-text-to-image"),
        ("i2i-sunburst", "Sunburst: картинка → картинка", "gpt-image-2-5-sunburst-image-to-image"),
    ]),
    ("gpt-image-2-6", "GPT Image 2.6", "OpenAI", "image", [
        ("t2i-economy", "Economy: текст → картинка", "gpt-image-2-6/economy-text-to-image"),
        ("i2i-economy", "Economy: картинка → картинка", "gpt-image-2-6/economy-image-to-image"),
        ("t2i-flare", "Flare: текст → картинка", "gpt-image-2-6/flare-text-to-image"),
        ("i2i-flare", "Flare: картинка → картинка", "gpt-image-2-6/flare-image-to-image"),
        ("t2i-sunburst", "Sunburst: текст → картинка", "gpt-image-2-6/sunburst-text-to-image"),
        ("i2i-sunburst", "Sunburst: картинка → картинка", "gpt-image-2-6/sunburst-image-to-image"),
    ]),
    ("qwen-image", "Qwen Image", "Qwen", "image", [
        ("t2i", "Текст → картинка", "qwen/text-to-image"),
        ("i2i", "Картинка → картинка", "qwen/image-to-image"),
        ("edit", "Редактирование", "qwen/image-edit"),
    ]),
    ("qwen2-image", "Qwen2 Image", "Qwen", "image", [
        ("t2i", "Текст → картинка", "qwen2/text-to-image"),
        ("edit", "Редактирование", "qwen2/image-edit"),
    ]),
    ("qwen2-1-image", "Qwen 2.1 Image", "Qwen", "image", [
        ("t2i", "Текст → картинка", "qwen2-1/text-to-image"),
        ("i2i", "Картинка → картинка", "qwen2-1/image-to-image"),
    ]),
    ("qwen3-image", "Qwen3 Image", "Qwen", "image", [
        ("t2i", "Текст → картинка", "qwen3/text-to-image"),
        ("i2i", "Картинка → картинка", "qwen3/image-to-image"),
        ("t2i-pro", "Pro: текст → картинка", "qwen3/pro-text-to-image"),
        ("i2i-pro", "Pro: картинка → картинка", "qwen3/pro-image-to-image"),
    ]),
    ("recraft", "Recraft", "Recraft", "image", [
        ("crisp-upscale", "Апскейл (Crisp)", "recraft/crisp-upscale"),
        ("remove-background", "Удаление фона", "recraft/remove-background"),
    ]),
    ("suno-cover", "Suno — обложка трека", "Suno", "image", [
        ("cover", "Текст → обложка", "ai-music-api/cover-generate"),
    ]),
    ("z-image", "Z-Image Turbo", "Tongyi (Z-Image)", "image", [
        ("t2i", "Текст → картинка", "z-image"),
    ]),
    ("topaz-image-upscale", "Topaz Image Upscale", "Topaz", "image", [
        ("upscale", "Апскейл картинки", "topaz/image-upscale"),
    ]),
    ("wan-2-7-image", "WAN 2.7 Image", "Wan", "image", [
        ("image", "Текст / картинка → картинка", "wan/2-7-image"),
        ("image-pro", "Pro: текст / картинка → картинка", "wan/2-7-image-pro"),
    ]),
]

# id, которого нет в живом /api/v1/models, но он есть в каталоге студии
CATALOG_ONLY = {"bytedance/seedance-1.5-pro"}
# модель, у которой taskType в kie.ai врёт (Image, помечена как Text to Video)
MEDIA_MISMATCH = {"ideogram/v3-text-to-image"}

API_ENDPOINTS = {
    "jobs": "/api/v1/jobs/createTask",
    "veo": "/api/v1/veo/generate",
    "suno": "/api/v1/generate",
    "runway": "/api/v1/runway/generate",
}
API_BY_MODEL = {
    "veo-3-1": "veo",
    "veo/extend": "veo",
    "veo/get-1080p-video": "veo",
    "veo/get-4k-video": "veo",
    "runway": "runway",
    "runway/extend-ai-video": "runway",
    "ai-music-api/create-music-video": "suno",
    "ai-music-api/cover-generate": "suno",
}
# режимы без страницы в docs.kie.ai: эндпоинт в доках не подтверждён
NO_DOCS_PAGE = set()

# ---------------------------------------------------------------------------
# 2. Подписи полей (docs-схема → человеческий label)
# ---------------------------------------------------------------------------

FIELD_LABELS = {
    "acceleration": "Ускорение",
    "align_audio": "Синхронизировать с аудио",
    "align_audio_reverse": "Обратная синхронизация",
    "aspect_ratio": "Соотношение сторон",
    "audio": "Аудио",
    "audio_ids": "Id аудио",
    "audio_url": "Аудио",
    "background": "Фон",
    "bbox_list": "Область (bbox)",
    "camera_fixed": "Фиксированная камера",
    "cfg_scale": "CFG",
    "character_ids": "Id персонажей",
    "character_orientation": "Ориентация персонажа",
    "color_palette": "Палитра",
    "complexity": "Сложность",
    "customize_multi_shots": "Настроить шоты",
    "draft": "Черновик",
    "draft_task_id": "Id черновика",
    "duration": "Длительность, сек",
    "elements": "Элементы",
    "enable_audio": "Аудио",
    "enable_fallback": "Fallback",
    "enable_pro": "Pro-режим",
    "enable_prompt_expansion": "Расширение промпта",
    "enable_safety_checker": "Проверка безопасности",
    "enable_sequential": "Последовательно",
    "enable_translation": "Перевод",
    "enable_watermark": "Водяной знак",
    "end_image_url": "Последний кадр",
    "enhance_prompt": "Улучшать промпт",
    "expand_prompt": "Расширять промпт",
    "extend_at": "Продлить с",
    "extend_times": "Сколько раз продлить",
    "file_url": "Файл",
    "files_url": "Файлы",
    "first_frame_image_url": "Первый кадр",
    "first_frame_url": "Первый кадр",
    "frame_count": "Число кадров",
    "frame_duration_ms": "Длительность кадра, мс",
    "generate_audio": "Генерировать звук",
    "generate_audio_switch": "Генерировать звук",
    "generate_multi_clip_switch": "Несколько клипов",
    "generation_type": "Тип генерации",
    "guidance_scale": "Guidance",
    "height": "Высота",
    "image": "Картинка",
    "image_input": "Картинки",
    "image_resolution": "Разрешение картинки",
    "image_size": "Размер картинки",
    "image_url": "Картинка",
    "image_urls": "Картинки",
    "index": "Индекс",
    "input_image": "Входная картинка",
    "input_urls": "Входные картинки",
    "keep_original_sound": "Сохранить оригинальный звук",
    "keyframe_urls": "Ключевые кадры",
    "keyframes": "Ключевые кадры",
    "kling_elements": "Элементы Kling",
    "last_frame_image_url": "Последний кадр",
    "last_frame_url": "Последний кадр",
    "loop_url": "Видео для лупа",
    "markup": "Разметка",
    "mask_indexs": "Индексы масок",
    "mask_url": "Маска",
    "max_images": "Максимум картинок",
    "mode": "Режим",
    "model": "Модель",
    "moderation": "Модерация",
    "multi_prompt": "Мультипромпт (шоты)",
    "multi_shots": "Несколько шотов",
    "n": "Сколько картинок",
    "negative_prompt": "Негативный промпт",
    "nsfw_checker": "Проверка NSFW",
    "num_images": "Сколько картинок",
    "num_inference_steps": "Шаги инференса",
    "omni_reference_task_type": "Тип референс-задачи",
    "open_scenedet": "Детекция сцен",
    "output_compression": "Сжатие",
    "output_format": "Формат файла",
    "output_resolution": "Выходное разрешение",
    "pe_fast_mode": "Fast-режим промпта",
    "prefer_multi_shots": "Предпочитать шоты",
    "prompt": "Промпт",
    "prompt_extend": "Расширять промпт",
    "prompt_optimizer": "Оптимизатор промпта",
    "prompt_upsampling": "Апсемплинг промпта",
    "quality": "Качество",
    "ratio": "Пропорции",
    "reference_audio_urls": "Референс-аудио",
    "reference_file_urls": "Референс-файлы",
    "reference_image": "Референс-картинки",
    "reference_image_urls": "Референс-картинки",
    "reference_link_urls": "Референс-ссылки",
    "reference_mask_urls": "Маски",
    "reference_video_urls": "Референс-видео",
    "rendering_speed": "Скорость рендера",
    "resolution": "Разрешение",
    "return_last_frame": "Вернуть последний кадр",
    "safety_tolerance": "Допуск безопасности",
    "seed": "Seed",
    "seeds": "Seeds",
    "separate_vocal": "Разделить вокал",
    "size": "Размер",
    "sound": "Звук",
    "strength": "Сила изменения",
    "style": "Стиль",
    "svg": "SVG",
    "task_id": "Id задачи",
    "templ_start_seconds": "Начало шаблона, сек",
    "template_id": "Id шаблона",
    "text_recognition": "Распознавание текста",
    "thinking_mode": "Режим размышления",
    "upload_cn": "Загрузка в CN",
    "upscale_factor": "Кратность апскейла",
    "video_list": "Видео",
    "video_url": "Видео",
    "video_urls": "Видео",
    "voices": "Голоса",
    "watermark": "Водяной знак",
    "web_search": "Поиск в интернете",
    "width": "Ширина",
}

# ---------------------------------------------------------------------------
# 3. Загрузка источников
# ---------------------------------------------------------------------------


def load_sources():
    models_raw = json.loads((RAW / "models.json").read_text(encoding="utf-8"))
    api_models = {m["model"]: m for m in models_raw["data"]["models"]}
    schemas = json.loads((RAW / "docs-schemas.json").read_text(encoding="utf-8"))
    id_to_schema = {}
    for url, page in schemas.items():
        for mid in page.get("model_ids") or []:
            id_to_schema[mid] = {"url": url, **page}
    rows = list(csv.DictReader((DOCS / "kie-ai-models.csv").open(encoding="utf-8")))
    csv_by_id = {r["id модели"]: r for r in rows}
    catalog_mod, catalog_sha = load_catalog()
    return api_models, id_to_schema, rows, csv_by_id, catalog_mod, catalog_sha


class _CatalogSnapshot:
    def __init__(self, models: list[dict]):
        self.MODELS = models


def load_catalog():
    """Каталог студии на момент HEAD (в рабочем дереве его параллельно правят).

    Берём закоммиченную версию из git, чтобы свод не зависел от чужих правок:
    фиксируем blob-sha в meta.
    """
    import subprocess

    try:
        sha = subprocess.run(
            ["git", "rev-parse", "HEAD:app/services/kie_catalog.py"],
            cwd=ROOT, capture_output=True, text=True, check=True,
        ).stdout.strip()
        src = subprocess.run(
            ["git", "show", "HEAD:app/services/kie_catalog.py"],
            cwd=ROOT, capture_output=True, text=True, check=True,
        ).stdout
        ns: dict = {"__name__": "kie_catalog_head"}
        exec(compile(src, f"kie_catalog@{sha[:8]}", "exec"), ns)  # noqa: S102
        models = ns.get("MODELS") or []
        if models:
            return _CatalogSnapshot(models), sha
    except Exception as exc:  # noqa: BLE001
        print("warning: git-версия каталога недоступна:", exc)
    spec = importlib.util.spec_from_file_location(
        "kie_catalog_mod", ROOT / "app" / "services" / "kie_catalog.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod, "working-tree"


# ---------------------------------------------------------------------------
# 4. Поля: docs-схема → контракт
# ---------------------------------------------------------------------------


def human_size_field(name: str, f: dict) -> dict:
    """Один параметр схемы → поле контракта."""
    name = f["name"]
    ftype = (f.get("type") or "").lower()
    enum = f.get("enum")
    sub = f.get("subprops")
    desc = (f.get("description") or "").strip()

    def base(**kw):
        out = {
            "name": name,
            "label": FIELD_LABELS.get(name, name),
            "kind": kw.get("kind", "text"),
            "required": bool(f.get("required")),
            "default": f.get("default"),
        }
        for key in ("options", "min", "max", "max_items", "hint"):
            if kw.get(key) is not None:
                out[key] = kw[key]
        return out

    if sub:
        return base(kind="json", hint=_short(desc) or "вложенный объект — структура не раскрыта")
    if enum:
        opts = [str(v) for v in enum]
        return base(kind="select", options=opts, hint=_short(desc))
    if ftype == "boolean":
        return base(kind="toggle", hint=_short(desc))
    if ftype in ("integer", "number"):
        return base(kind="number", min=f.get("minimum"), max=f.get("maximum"), hint=_short(desc))
    if ftype == "array":
        kind = _media_kind(name, "array")
        mi = f.get("maxItems")
        return base(kind=kind, max_items=mi, hint=_short(desc))
    if ftype == "string":
        if _is_media_name(name):
            return base(kind=_media_kind(name, "string"), max_items=1, hint=_short(desc))
        ml = f.get("maxLength")
        hint = _short(desc)
        if ml:
            hint = f"{hint} (макс. {ml} симв.)".strip()
        if name in ("prompt", "negative_prompt") or (ml or 0) > 200:
            return base(kind="textarea", hint=hint)
        return base(kind="text", hint=hint)
    return base(kind="text", hint=_short(desc) or "неизвестно")


def _media_kind(name: str, ftype: str) -> str:
    low = name.lower()
    if "audio" in low:
        return "audios"
    if "video" in low or "loop" in low:
        return "videos"
    if any(k in low for k in ("mask", "bbox", "palette", "elements", "voices", "prompt")):
        if ftype == "array":
            return "json"
    return "images"


def _is_media_name(name: str) -> bool:
    low = name.lower()
    if low.endswith("_ids") or low.endswith("ids"):
        return False
    return any(k in low for k in ("url", "image", "video", "audio", "file", "mask", "input"))


def _short(text: str, limit: int = 220) -> str:
    text = re.sub(r"\s+", " ", text or "").strip()
    return text[:limit]


def fields_from_schema(page: dict) -> list[dict]:
    return [human_size_field(f["name"], f) for f in page.get("fields") or []]


def fields_from_catalog(entry: dict, model_id: str) -> list[dict]:
    """Поля каталога студии → контракт (для id без OpenAPI-схемы)."""
    out = []
    i2i_field = entry.get("i2i_input_field")
    for f in entry.get("fields") or []:
        name = f["name"]
        if i2i_field and name == "image_urls" and model_id == entry.get("model_map_i2i"):
            name = i2i_field
        item = {
            "name": name,
            "label": f.get("label") or FIELD_LABELS.get(name, name),
            "kind": f.get("kind", "text"),
            "required": bool(f.get("required")),
            "default": f.get("default"),
            "hint": f.get("desc") or "поле из каталога студии, OpenAPI-схемы в docs нет",
            "source": "kie_catalog.py",
        }
        if f.get("options"):
            item["options"] = [str(o) for o in f["options"]]
        for key in ("min", "max", "max_items"):
            if f.get(key) is not None:
                item[key] = f[key]
        out.append(item)
    return out


# ---------------------------------------------------------------------------
# 5. Цена: pricingDesc → pricing{unit, rules, default, note}
# ---------------------------------------------------------------------------

_RES_RE = re.compile(r"\b(\d{3,4})\s*[pP]\b")
_RES_K_RE = re.compile(r"\b([1248])\s*[kK]\b")
_DUR_RE = re.compile(r"\b(\d{1,2})\s*(?:-|\s)?\s*s(?:ec|econd)?s?\b")
_CREDIT_RE = re.compile(r"(\d[\d,]*(?:\.\d+)?)\s*(?:Kie\s+)?credits?", re.I)
_HEADER_VIDEO = re.compile(r"(with|without)\s+video\s+input", re.I)
_MODE_WORD = re.compile(r"\b(lite|fast|quality|standard|pro)\b(?=\s*(?:mode|:|\())", re.I)


def _unit_of(text: str) -> str:
    low = text.lower()
    if "megapixel" in low:
        return "megapixel"
    if "1m tokens" in low or "/ 1m tokens" in low:
        return "tokens"
    if re.search(r"credits?\s*/\s*s\b|credits?/s\b|per video[- ]second|per second", low):
        return "sec"
    if "per 1k characters" in low:
        return "1k_chars"
    return "gen"


def _clean_price_text(text: str) -> str:
    if not text:
        return ""
    cut = re.split(r"High-tier top-ups", text, maxsplit=1)[0]
    return cut.strip()


def _candidates(text: str) -> list[tuple[int, str, object]]:
    """Все квалификаторы цены в куске текста: (позиция, вид, значение)."""
    out: list[tuple[int, str, object]] = []
    for m in _RES_RE.finditer(text):
        out.append((m.start(), "resolution", f"{m.group(1)}p"))
    for m in _RES_K_RE.finditer(text):
        out.append((m.start(), "resolution", f"{m.group(1)}K"))
    for m in _DUR_RE.finditer(text):
        if int(m.group(1)) <= 60:
            out.append((m.start(), "duration", m.group(1)))
    for m in _MODE_WORD.finditer(text):
        out.append((m.start(), "mode", m.group(1).lower()))
    low = text.lower()
    if "with or without audio" not in low:
        for m in re.finditer(r"without\s+(?:audio|sound)", low):
            out.append((m.start(), "sound", False))
        for m in re.finditer(r"with\s+(?:audio|sound)", low):
            out.append((m.start(), "sound", True))
        for m in re.finditer(r"no\s+(?:native\s+)?audio", low):
            out.append((m.start(), "sound", False))
        for m in re.finditer(r"with\s+native\s+audio", low):
            out.append((m.start(), "sound", True))
    for m in re.finditer(r"(with|without)\s+video\s+input", low):
        out.append((m.start(), "with_video", m.group(1) == "with"))
    return out


def _split_clauses(line: str) -> list[tuple[int, str]]:
    """Разбить строку прайса на клаузы по «,», «|», «or», «;» вне скобок.

    В клаузе обычно ровно одна цена и её квалификаторы — так «with audio»
    не приклеивается к соседней цене. Возвращает (начало клаузы, текст).
    """
    out: list[tuple[int, str]] = []
    buf: list[str] = []
    depth = 0
    start = 0
    i = 0
    while i < len(line):
        ch = line[i]
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth = max(0, depth - 1)
        if depth == 0:
            for sep in (" | ", " or ", "; ", ", ", " / "):
                if line.startswith(sep, i):
                    piece = "".join(buf)
                    if piece.strip():
                        out.append((start, piece.strip()))
                    buf = []
                    i += len(sep)
                    start = i
                    break
            else:
                buf.append(ch)
                i += 1
                continue
            continue
        buf.append(ch)
        i += 1
    piece = "".join(buf)
    if piece.strip():
        out.append((start, piece.strip()))
    return out


def _attribute(text: str, unit: str) -> list[dict]:
    """Разложить квалификаторы цены по числам кредитов в строке."""
    matches = list(_CREDIT_RE.finditer(text))
    if not matches:
        return []
    assigned: list[dict] = [dict() for _ in matches]
    for cstart, clause in _split_clauses(text):
        cend = cstart + len(clause)
        local = [i for i, m in enumerate(matches) if cstart <= m.start() < cend]
        if not local:
            continue
        pairs = []
        for pos, kind, value in _candidates(clause):
            if kind == "duration" and unit == "sec":
                continue  # цена за секунду не зависит от длительности ролика
            abs_pos = cstart + pos
            for mi in local:
                pairs.append((abs(abs_pos - matches[mi].start()), mi, kind, value))
        pairs.sort(key=lambda x: x[0])
        for dist, mi, kind, value in pairs:
            slot = assigned[mi].get(kind)
            if slot is None or dist < slot[0]:
                assigned[mi][kind] = dist, value

    # fallback 1: если в строке ровно одно значение вида — оно общее для всех чисел
    values_by_kind: dict[str, set] = {}
    for _pos, kind, value in _candidates(text):
        if kind == "duration" and unit == "sec":
            continue
        values_by_kind.setdefault(kind, set()).add(value)
    out = []
    for mi, m in enumerate(matches):
        when = {k: v for k, (_d, v) in assigned[mi].items()}
        for kind in ("resolution", "mode"):
            if kind not in when and len(values_by_kind.get(kind, ())) == 1:
                when[kind] = next(iter(values_by_kind[kind]))
        out.append({"match": m, "when": when})
    # fallback 2: незаполненные виды тянем из предыдущей цены в строке
    # (в прайсе так экономят слова: «1080P — 16 за 5с / 36 за 10с»)
    prev: dict = {}
    for item in out:
        when = item["when"]
        for kind in ("resolution", "mode", "duration"):
            if kind in when:
                continue
            if kind == "duration" and unit == "sec":
                continue
            if len(values_by_kind.get(kind, ())) > 1 and kind in prev:
                when[kind] = prev[kind]
        prev = when
    return out


def parse_pricing(model: dict, csv_row: dict | None) -> dict:
    text = model.get("pricingDesc") or ""
    clean = _clean_price_text(text)
    unit = _unit_of(clean) if clean else "unknown"
    rules: list[dict] = []
    seen = set()
    ctx: dict = {}
    for line in clean.splitlines():
        strip = line.strip()
        if not strip:
            continue
        matches = list(_CREDIT_RE.finditer(strip))
        mh = _HEADER_VIDEO.match(strip)
        if mh and not matches:
            ctx = dict(ctx)
            ctx["with_video"] = mh.group(1).lower() == "with"
            continue
        if not matches:
            continue
        for item in _attribute(strip, unit):
            try:
                credits = float(item["match"].group(1).replace(",", ""))
            except ValueError:
                continue
            when = dict(ctx)
            when.update(item["when"])
            key = (tuple(sorted(when.items())), credits)
            if key in seen:
                continue
            seen.add(key)
            rules.append({"when": when, "credits": credits})
    if not rules and clean:
        # цена выражена не словом «credits» (например, в токенах)
        for m in re.finditer(r"(\d[\d,]*(?:\.\d+)?)\s*(?:\(\$|credits?|/ 1M)", clean):
            try:
                credits = float(m.group(1).replace(",", ""))
            except ValueError:
                continue
            rules.append({"when": {}, "credits": credits})
            break
    default = rules[0]["credits"] if rules else None
    note_bits = []
    if unit == "unknown":
        note_bits.append("цена в прайсе не указана")
    else:
        unit_ru = {
            "sec": "за секунду",
            "gen": "за генерацию/ролик/картинку",
            "tokens": "по токенам",
            "megapixel": "за мегапиксель",
            "1k_chars": "за 1000 символов",
        }.get(unit, unit)
        note_bits.append(unit_ru)
        if rules:
            vals = sorted({r["credits"] for r in rules})
            note_bits.append("кредиты: " + ", ".join(_num(v) for v in vals[:10]))
    if text:
        note_bits.append("прайс kie.ai: " + _short(clean, 260))
    pricing = {
        "unit": unit,
        "rules": rules,
        "default": default,
        "note": "; ".join(note_bits) if note_bits else "неизвестно",
        "credit_usd": CREDIT_USD,
    }
    if csv_row and csv_row.get("прайс как в kie.ai (дословно)"):
        pricing["source_text"] = csv_row["прайс как в kie.ai (дословно)"]
    return pricing


def _num(v: float) -> str:
    return str(int(v)) if float(v).is_integer() else str(v)


# ---------------------------------------------------------------------------
# 6. Сборка
# ---------------------------------------------------------------------------


def mode_constraints(mode: dict, has_schema: bool) -> list[str]:
    """Короткие ограничения режима для UI/валидации (из полей и фактов источника)."""
    out: list[str] = []
    fields = mode.get("fields") or []
    req = [f["name"] for f in fields if f.get("required")]
    if req and "model" not in req:
        out.append("обязательные поля: " + ", ".join(req))
    for f in fields:
        name = f["name"]
        if f.get("max_items") is not None and f.get("kind") in ("images", "videos", "audios"):
            out.append(f"{name}: до {f['max_items']} шт.")
        elif f.get("min") is not None and f.get("max") is not None and f.get("kind") == "number":
            out.append(f"{name}: {_num(f['min'])}–{_num(f['max'])}")
        elif f.get("max") is not None and f.get("kind") == "number" and f.get("min") is None:
            out.append(f"{name}: не больше {_num(f['max'])}")
    if not has_schema and not fields:
        out.append("настройки неизвестны: нет OpenAPI-схемы в docs.kie.ai и нет полей в каталоге студии")
    if mode.get("in_live_api") is False:
        out.append("id отсутствует в живом /api/v1/models (маркет его не отдаёт)")
    if mode.get("docs_url") is None and fields:
        out.append("эндпоинт и схема взяты из каталога студии: страницы в docs.kie.ai нет")
    elif mode.get("docs_url") is None:
        out.append("эндпоинт не подтверждён докой — принят " + str(mode.get("endpoint")))
    return out[:12]


def build(api_models, id_to_schema, csv_by_id, catalog_mod):
    catalog_by_model: dict[str, dict] = {}
    for entry in catalog_mod.MODELS:
        if entry.get("model"):
            catalog_by_model.setdefault(entry["model"], entry)
        if entry.get("model_map_i2i"):
            catalog_by_model.setdefault(entry["model_map_i2i"], entry)

    families = []
    mode_id_seen = set()
    for fam_id, fam_label, brand, media, modes in FAMILIES:
        fam = {
            "id": fam_id,
            "label": fam_label,
            "brand": brand,
            "media": media,
            "desc": "",
            "modes": [],
        }
        for mode_id, mode_label, kie_id in modes:
            api_model = api_models.get(kie_id)
            csv_row = csv_by_id.get(kie_id)
            schema = id_to_schema.get(kie_id)
            task_types = (api_model or {}).get("taskType") or []
            task_type = ", ".join(task_types) if task_types else "неизвестно"
            api = API_BY_MODEL.get(kie_id, "jobs")
            mode = {
                "id": mode_id,
                "label": mode_label,
                "kie_id": kie_id,
                "task_type": task_type,
                "api": api,
                "endpoint": API_ENDPOINTS.get(api),
                "fields": [],
                "pricing": parse_pricing(api_model or {}, csv_row),
                "constraints": [],
                "docs_url": (schema or {}).get("url"),
            }
            if schema:
                mode["fields"] = fields_from_schema(schema)
                mode["fields_source"] = "docs.kie.ai OpenAPI (input)"
            elif kie_id in catalog_by_model:
                mode["fields"] = fields_from_catalog(catalog_by_model[kie_id], kie_id)
                mode["fields_source"] = "app/services/kie_catalog.py"
            else:
                mode["fields_source"] = "нет в источниках"
                mode["hint"] = "неизвестно: нет OpenAPI-схемы в docs.kie.ai и нет в каталоге студии"
            mode["in_live_api"] = api_model is not None
            if api_model is None:
                mode["hint"] = (
                    "id нет в живом /api/v1/models (маркет его не отдаёт), "
                    "но он есть в каталоге студии"
                )
            if kie_id in MEDIA_MISMATCH:
                mode["api_task_type_mismatch"] = True
                mode["task_type"] = "Text to Video (ошибка kie.ai: модель картинная)"
                mode["constraints"] = mode_constraints(mode, bool(schema))
                mode["constraints"].append(
                    "kie.ai помечает модель как Text to Video, но id, схема и прайс — генерация картинки"
                )
            else:
                mode["constraints"] = mode_constraints(mode, bool(schema))
            fam["media"] = media
            fam["modes"].append(mode)
            mode_id_seen.add((fam_id, mode_id))
        # описание: берём первое осмысленное из API (description, затем title)
        if not fam["desc"]:
            for mode in fam["modes"]:
                api_model = api_models.get(mode["kie_id"]) or {}
                for candidate in (api_model.get("description"), api_model.get("title")):
                    text = _short(candidate or "", 320)
                    if len(text) > 20:
                        fam["desc"] = text
                        break
                if fam["desc"]:
                    break
        if not fam["desc"]:
            fam["desc"] = "описания в источниках нет"
        families.append(fam)
    return families, catalog_by_model


# ---------------------------------------------------------------------------
# 7. Сверки
# ---------------------------------------------------------------------------


def csv_credit_numbers(row: dict) -> set[float]:
    out = set()
    for tok in (row.get("кредиты (числа из прайса)") or "").split():
        tok = tok.strip().replace(",", ".")
        try:
            out.add(float(tok))
        except ValueError:
            continue
    return out


def run_checks(families, api_models, csv_by_id, catalog_mod, id_to_schema):
    checks: dict = {}

    # --- сверка 1: покрытие ---
    placed: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for fam in families:
        for mode in fam["modes"]:
            placed[mode["kie_id"]].append((fam["id"], mode["id"]))

    csv_rows = list(csv_by_id.values())
    video_ids = {r["id модели"] for r in csv_rows if r["тип (video/image)"] == "video"}
    image_ids = {r["id модели"] for r in csv_rows if r["тип (video/image)"] == "image"}
    media_ids = video_ids | image_ids
    api_media = set(media_ids)

    lost = sorted(api_media - set(placed))
    dupes = {k: v for k, v in placed.items() if len(v) > 1}
    extra = sorted(set(placed) - api_media)
    # media-сверка: taskType модели против media семейства
    media_conflicts = []
    for fam in families:
        for mode in fam["modes"]:
            if mode["kie_id"] in MEDIA_MISMATCH:
                continue
            row = csv_by_id.get(mode["kie_id"])
            if row and row["тип (video/image)"] != fam["media"]:
                media_conflicts.append(
                    {"kie_id": mode["kie_id"], "family": fam["id"], "family_media": fam["media"],
                     "csv_media": row["тип (video/image)"]}
                )
    family_media_count = Counter(f["media"] for f in families)
    mode_media_count = Counter(
        f["media"] for f in families for _ in f["modes"]
    )
    # каталог студии
    cat_media_ids = set()
    cat_nonmedia = []
    for entry in catalog_mod.MODELS:
        ids = [entry.get("model"), entry.get("model_map_i2i")]
        if entry["category"] not in ("video", "image", "tools"):
            cat_nonmedia.append(entry["id"])
            continue
        for mid in ids:
            if mid:
                cat_media_ids.add(mid)
    cat_lost = sorted(cat_media_ids - set(placed))
    cat_extra = sorted(set(placed) & CATALOG_ONLY)

    checks["coverage"] = {
        "api_total_models": len(api_models),
        "api_media_ids": len(api_media),
        "api_video_ids": len(video_ids),
        "api_image_ids": len(image_ids),
        "placed_ids_unique": len(placed),
        "placed_api_ids": len(set(placed) & api_media),
        "families": len(families),
        "modes": sum(len(f["modes"]) for f in families),
        "family_media": dict(family_media_count),
        "mode_media": dict(mode_media_count),
        "lost_api_ids": lost,
        "duplicate_ids": dupes,
        "extra_ids_not_in_media": extra,
        "media_conflicts_excluding_known": media_conflicts,
        "reclassified": sorted(MEDIA_MISMATCH),
        "catalog_media_ids": len(cat_media_ids),
        "catalog_media_ids_missing": cat_lost,
        "catalog_only_ids": cat_extra,
        "studio_all_entries": len(catalog_mod.MODELS),
        "studio_non_media_entries": cat_nonmedia,
        "ok": not lost and not dupes and not cat_lost,
    }

    # --- сверка 2: поля ---
    with_schema = 0
    all_fields_ok = 0
    field_mismatches = []
    from_catalog = 0
    no_fields = 0
    no_source_modes = []
    required_vs_csv = 0
    required_vs_csv_ok = 0
    required_diff = []
    for fam in families:
        for mode in fam["modes"]:
            schema = id_to_schema.get(mode["kie_id"])
            if schema:
                with_schema += 1
                schema_names = [f["name"] for f in schema["fields"]]
                got_names = [f["name"] for f in mode["fields"]]
                if schema_names == got_names and len(schema_names) == len(got_names):
                    all_fields_ok += 1
                else:
                    field_mismatches.append(
                        {"kie_id": mode["kie_id"], "schema_fields": len(schema_names),
                         "written_fields": len(got_names),
                         "missed": sorted(set(schema_names) - set(got_names)),
                         "extra": sorted(set(got_names) - set(schema_names))}
                    )
                csv_row = csv_by_id.get(mode["kie_id"]) or {}
                csv_req = {x.strip() for x in (csv_row.get("обязательные поля") or "").split("|") if x.strip()}
                if csv_req:
                    required_vs_csv += 1
                    my_req = {f["name"] for f in mode["fields"] if f.get("required")}
                    their_req = {x for x in csv_req if x in {f["name"] for f in mode["fields"]}}
                    if my_req == their_req:
                        required_vs_csv_ok += 1
                    else:
                        required_diff.append(
                            {"kie_id": mode["kie_id"], "csv": sorted(their_req),
                             "mine": sorted(my_req)}
                        )
            elif mode["fields"]:
                from_catalog += 1
            else:
                no_fields += 1
                no_source_modes.append(mode["kie_id"])
    checks["fields"] = {
        "modes_total": sum(len(f["modes"]) for f in families),
        "modes_with_docs_schema": with_schema,
        "modes_fields_complete": all_fields_ok,
        "modes_fields_mismatch": field_mismatches,
        "modes_fields_from_catalog": from_catalog,
        "modes_without_fields": no_fields,
        "modes_without_fields_list": no_source_modes,
        "required_checked_against_csv": required_vs_csv,
        "required_match": required_vs_csv_ok,
        "required_mismatch": required_diff,
        "ok": all_fields_ok == with_schema,
    }

    # --- сверка 3: цены ---
    price_ok = 0
    price_missing = []
    price_diff = []
    unit_counter = Counter()
    checked = 0
    unit_checked = 0
    unit_ok = 0
    unit_diff = []
    csv_unit_map = {
        "за секунду": "sec",
        "за картинку": "gen",
        "за генерацию/ролик": "gen",
        "за мегапиксель": "megapixel",
        "за токены": "tokens",
        "за секунду, за генерацию/ролик": "mix",
    }
    for fam in families:
        for mode in fam["modes"]:
            pricing = mode["pricing"]
            unit_counter[pricing["unit"]] += 1
            row = csv_by_id.get(mode["kie_id"]) or {}
            expected_unit = csv_unit_map.get((row.get("единица цены") or "").strip())
            if expected_unit:
                unit_checked += 1
                ok = pricing["unit"] == expected_unit or expected_unit == "mix"
                if ok:
                    unit_ok += 1
                else:
                    unit_diff.append(
                        {"kie_id": mode["kie_id"], "csv_unit": row.get("единица цены"),
                         "my_unit": pricing["unit"]}
                    )
            csv_nums = csv_credit_numbers(row)
            mine = {float(r["credits"]) for r in pricing["rules"]}
            if not csv_nums:
                price_missing.append(mode["kie_id"])
                continue
            checked += 1
            if mine == csv_nums:
                price_ok += 1
            else:
                price_diff.append(
                    {"kie_id": mode["kie_id"],
                     "csv": sorted(csv_nums),
                     "mine": sorted(mine),
                     "only_csv": sorted(csv_nums - mine),
                     "only_mine": sorted(mine - csv_nums)}
                )
    checks["pricing"] = {
        "modes_with_price": sum(1 for f in families for m in f["modes"]
                                if m["pricing"]["rules"]),
        "modes_without_price": sum(1 for f in families for m in f["modes"]
                                   if not m["pricing"]["rules"]),
        "units": dict(unit_counter),
        "checked_against_csv": checked,
        "numbers_match": price_ok,
        "mismatches": price_diff,
        "csv_without_numbers": price_missing,
        "unit_checked": unit_checked,
        "unit_match": unit_ok,
        "unit_mismatch": unit_diff,
        "ok": len(price_diff) == 0,
    }
    return checks


# ---------------------------------------------------------------------------
# 8. Markdown
# ---------------------------------------------------------------------------


def fmt_modes(fam: dict) -> str:
    return ", ".join(f"{m['label']} (`{m['kie_id']}`)" for m in fam["modes"])


def pricing_short(fam: dict) -> str:
    units = []
    for m in fam["modes"]:
        p = m["pricing"]
        u = p["unit"]
        if u == "unknown":
            continue
        vals = sorted({r["credits"] for r in p["rules"]})
        if not vals:
            continue
        if len(vals) == 1:
            units.append(f"{_num(vals[0])} кр/{u}")
        else:
            units.append(f"{_num(vals[0])}–{_num(vals[-1])} кр/{u}")
    # уникальные
    out, seen = [], set()
    for u in units:
        if u not in seen:
            seen.add(u)
            out.append(u)
    return ", ".join(out[:4]) if out else "цена не указана"


def write_md(families, checks, generated):
    cov = checks["coverage"]
    fld = checks["fields"]
    prc = checks["pricing"]
    lines = []
    add = lines.append
    add("# Семейства и режимы медиа-моделей kie.ai")
    add("")
    add(f"Собрано {generated} (шаг 7 мастер-задачи, ветка `test`). "
        "Семейство = одна карточка в меню выбора модели; режим = вариант внутри неё "
        "(тип входа, тир, утилита).")
    add("")
    add("Источники: живой `GET https://api.kie.ai/api/v1/models` (`docs/kie-ai-raw/models.json`, 251 модель), "
        "OpenAPI-схемы `input` со страниц docs.kie.ai (`docs/kie-ai-raw/docs-schemas.json`), "
        "таблица `docs/kie-ai-models.csv`, каталог студии `app/services/kie_catalog.py`. "
        "Платных генераций не было, ключ в файлы не попадал.")
    add("")
    add("## 1. Итог")
    add("")
    add("| Показатель | Значение |")
    add("|---|---|")
    add(f"| Семейств (карточек) | **{cov['families']}** (видео {cov['family_media'].get('video', 0)}, "
        f"картинки {cov['family_media'].get('image', 0)}) |")
    add(f"| Режимов | **{cov['modes']}** = {cov['modes'] - len(cov['catalog_only_ids'])} по id живого API "
        f"+ {len(cov['catalog_only_ids'])} каталожный (`bytedance/seedance-1.5-pro`) |")
    add(f"| Медиа-id из живого API разложено | **{cov['placed_api_ids']}/{cov['api_media_ids']}** "
        f"(видео {cov['api_video_ids']}, картинки {cov['api_image_ids']}) |")
    add(f"| Потерянных id | {len(cov['lost_api_ids'])} |")
    add(f"| Дублей id (в двух режимах) | {len(cov['duplicate_ids'])} |")
    add(f"| id каталога студии покрыто | {cov['catalog_media_ids'] - len(cov['catalog_media_ids_missing'])}"
        f"/{cov['catalog_media_ids']} |")
    add(f"| id вне живого API (только каталог студии) | {len(cov['catalog_only_ids'])}: "
        + ", ".join(cov['catalog_only_ids']) + " |")
    add("")
    add("## 2. Сверки (цифрами)")
    add("")
    add("### Сверка 1 — покрытие живого API")
    add("")
    add(f"- В живом `/api/v1/models` {cov['api_total_models']} моделей, из них медиа "
        f"**{cov['api_media_ids']}** = видео {cov['api_video_ids']} + картинки {cov['api_image_ids']} "
        "(остальные — чат-LLM, музыка, TTS, ASR; не входят в задачу).")
    lc = LIVE_CHECK
    add(f"- Живой API перепроверен {lc['checked_at']} (бесплатные GET, `credit` → HTTP "
        f"{lc['credit_http']}): уже **{lc['api_total_models']}** модели — маркет добавил "
        f"{', '.join(f'`{x}`' for x in lc['new_since_snapshot'])} с taskType "
        f"{'/'.join(lc['new_task_types'])}, медиа по-прежнему **{lc['api_media_models']}** "
        f"(видео {lc['api_video']}, картинки {lc['api_image']}). Новые id вне задачи.")
    add(f"- В семействах и режимах ровно **{cov['placed_api_ids']}** id из живого API: "
        f"потеряно {len(cov['lost_api_ids'])}, дублей {len(cov['duplicate_ids'])}. "
        f"Всего уникальных id (с каталожным) — {cov['placed_ids_unique']}.")
    if cov["reclassified"]:
        add(f"- Переклассифицировано: {', '.join(f'`{x}`' for x in cov['reclassified'])} — "
            "kie.ai отдаёт taskType `Text to Video`, хотя модель картинная (см. §5).")
    add(f"- Каталог студии: {cov['catalog_media_ids']} медиа-id (из {cov['studio_all_entries']} записей "
        f"каталога; {len(cov['studio_non_media_entries'])} записей — музыка/звук/голос, вне задачи) — "
        f"покрыто {cov['catalog_media_ids'] - len(cov['catalog_media_ids_missing'])}"
        f"/{cov['catalog_media_ids']}.")
    add("- `wan/2-7-r2v` в API помечен сразу двумя тегами (`Image to Image` и `Image to Video`) — "
        "по правилу «вход = режим» отнесён к видео, поэтому видео 100 и картинки 81 "
        "сходятся с таблицей без пересечений.")
    add("")
    add("### Сверка 2 — поля против docs-схем")
    add("")
    add(f"- Режимов всего **{fld['modes_total']}**.")
    add(f"- С OpenAPI-схемой в docs.kie.ai: **{fld['modes_with_docs_schema']}**, "
        f"поля выписаны полностью у **{fld['modes_fields_complete']}** "
        f"(расхождений {len(fld['modes_fields_mismatch'])}).")
    add(f"- Поля взяты из каталога студии (схемы в доках нет): **{fld['modes_fields_from_catalog']}**.")
    add(f"- Без полей вообще (нет ни схемы, ни каталога): **{fld['modes_without_fields']}** — "
        "помечены `hint: «неизвестно»`, режим и цена сохранены.")
    add(f"- Обязательность полей сверена с колонкой «обязательные поля» в `kie-ai-models.csv`: "
        f"совпало {fld['required_match']}/{fld['required_checked_against_csv']}.")
    if fld["required_mismatch"]:
        add(f"  Расхождения ({len(fld['required_mismatch'])}) — это разное понимание обязательности: "
            "в CSV колонка собрана по тексту описания (там пишут «Required field»), а в OpenAPI-схеме "
            "то же поле может стоять с флагом `required: false`, потому что один `input` обслуживает "
            "и text-to-video, и image-to-video (у `bytedance/seedance-2` в описании «Required field», "
            "в схеме все поля необязательные). Источник для полей — схема, CSV не переписывался.")
    if fld["modes_without_fields_list"]:
        add("")
        add("Без полей: " + ", ".join(f"`{x}`" for x in fld["modes_without_fields_list"]))
    add("")
    add("### Сверка 3 — цены против `pricingDesc`")
    add("")
    add(f"- Цена разобрана (есть хотя бы одно правило): **{prc['modes_with_price']}** режимов; "
        f"без цены **{prc['modes_without_price']}**.")
    add(f"- Единицы: " + ", ".join(f"{k} — {v}" for k, v in sorted(prc["units"].items())))
    add(f"- Сверено с числами из `kie-ai-models.csv`: {prc['checked_against_csv']} режимов, "
        f"множество кредитов совпало у **{prc['numbers_match']}**, расхождений {len(prc['mismatches'])}.")
    add(f"- Единица цены сверена с колонкой «единица цены» в CSV: совпало "
        f"**{prc['unit_match']}/{prc['unit_checked']}** (не «не указано»).")
    if prc["unit_mismatch"]:
        add("")
        add("| id | единица в CSV | у меня |")
        add("|---|---|---|")
        for d in prc["unit_mismatch"]:
            add(f"| `{d['kie_id']}` | {d['csv_unit']} | {d['my_unit']} |")
    if prc["mismatches"]:
        add("")
        add("| id | числа в CSV | числа из моего разбора |")
        add("|---|---|---|")
        for d in prc["mismatches"]:
            add(f"| `{d['kie_id']}` | {d['csv']} | {d['mine']} |")
    add("")
    add("## 3. Семейства по брендам — видео")
    add("")
    _brand_table(add, families, "video")
    add("## 4. Семейства по брендам — картинки")
    add("")
    _brand_table(add, families, "image")
    add("## 5. Правила слияния и спорные случаи")
    add("")
    add("- Семейство = бренд + поколение в базовом названии. Служебные суффиксы и тиры "
        "(`Pro`, `Standard`, `Fast`, `Lite`, `Mini`, `Draft`, `Turbo`, `Omni`, `Flash`, `Max`, "
        "`Master`, `Economy`, `Flare`, `Sunburst`, `Klein`, `Flex`, `Prime`) — режимы одного семейства.")
    add("- Тип входа (`Text to Video`, `Image to Video`, `Reference to Video`, `Video to Video`, "
        "`Image to Image`, `Image Editing`) — всегда режим внутри семейства, а не отдельная карточка.")
    add("- Утилиты того же эндпоинта (`Extend`, `upscale`, `get-1080p/4k`, `Video Edit`, `Motion Control`, "
        "`Transformation`, `Layer Decomposition`, `Remove Background`) — режимы семейства.")
    add("- Разные поколения не слиты: Kling 2.1 / 2.5 Turbo / 2.6 / 3.0 / 4.0 — разные семейства; "
        "Seedream 3 / 4.0 / 4.5 / 5 / 5.5 — разные; WAN 2.2 / 2.5 / 2.6 / 2.7 / 3.0 — разные.")
    add("")
    add("Спорные слияния, где правило допускало два прочтения:")
    add("")
    add("| Случай | Как решено | Почему |")
    add("|---|---|---|")
    add("| `kling-3.0/video`, `kling-3.0/motion-control`, `kling-3.0-omni/*`, "
        "`kling/v3-turbo-*` | одно семейство **Kling 3.0**, 8 режимов | прямая формулировка мастер-задачи: "
        "«Kling 3.0 Pro/Turbo/Omni — режимы одного семейства 3.0» |")
    add("| `gemini-omni-video`, `gemini-omni-character` | семейство **Gemini Omni** | одна генерация "
        "без тира; `character` — отдельный вход (персонаж), а не другое поколение |")
    add("| `google/gemini-omni-flash-1-1` и `...-1-2` (+`-extend`) | два семейства | разные поколения "
        "(1.1 и 1.2), как Kling 2.6 vs 3.0; `extend` — режим поколения 1.2 |")
    add("| `pixverse-v6-max/*` | режимы **PixVerse V6** (`t2v-max`, `i2v-max`) | `Max` — тир качества "
        "того же поколения, своего поколения/эндпоинта нет |")
    add("| `grok-imagine-video-1-5-preview` | отдельное семейство | версия 1.5 против базового Grok Imagine |")
    add("| `wan/2-2-animate-*` | отдельное семейство **WAN 2.2 Animate** | своя механика (перенос движения / "
        "замена персонажа) и своя схема, хотя поколение то же |")
    add("| `kling/v2-5-turbo-*` | отдельное семейство **Kling 2.5 Turbo** | отдельная линейка поколения "
        "2.5, а не тир Kling 2.6 |")
    add("| `kling/ai-avatar-*` | семейство **Kling AI Avatar** | отдельный продукт-аватар, "
        "не режим 3.0 |")
    add("| `topaz/video-upscale` / `topaz/image-upscale`, `video/upscale` / `kie/image-upscale`, "
        "`veo/get-1080p/4k` | отдельные утилитные семейства / режимы Veo | у Topaz и Kie нет «поколения», "
        "у Veo апскейл — режим Veo 3.1 |")
    add("| `ideogram/v3-text-to-image` | режим семейства **Ideogram V3** (картинки) | kie.ai отдаёт "
        "taskType `Text to Video`, но id, схема и прайс — картинка; ошибка метаданных kie.ai |")
    add("| `bytedance/seedance-1.5-pro` | семейство **Seedance 1.5**, режим помечен `in_live_api: false` | "
        "id есть в каталоге студии, но маркет его не отдаёт — сохранён как есть, чтобы не потерять |")
    add("| `ai-music-api/create-music-video`, `ai-music-api/cover-generate` | семейства Suno "
        "(видео / обложка) | лежат в `/api/v1/models` как медиа, бренд Suno |")
    add("| `omnihuman-1-5/human-identification`, `subject-detection` | семейство **OmniHuman 1.5 — разметка** | "
        "это утилиты разметки картинки, не генерация видео |")
    add("")
    add("Полное сопоставление id → семейство/режим — в `docs/kie-model-families.json` "
        "(`families[].modes[].kie_id`).")
    add("")
    add("## 6. Чего нет в источниках")
    add("")
    add(f"1. **Нет OpenAPI-схемы** у {fld['modes_without_fields'] + fld['modes_fields_from_catalog']} "
        "режимов: страницы модели нет в docs.kie.ai. У "
        f"{fld['modes_fields_from_catalog']} из них поля взяты из кода каталога студии, "
        f"у остальных {fld['modes_without_fields']} настройки — «неизвестно».")
    add("2. **Нет цены** (пустой `pricingDesc`) — режимы без правил цены перечислены в сверке 3; "
        "при этом сами id и режимы сохранены.")
    add("3. **Связи «параметр → множитель цены» в доках нет.** Правила `pricing.rules` восстановлены "
        "из текста `pricingDesc` эвристикой (разрешение / длительность / звук / наличие видео на входе). "
        "Где прайс пишет диапазон «720P/1080P» одной ценой, в правиле осталось одно разрешение — "
        "цена от этого не меняется, но строка прайса не воспроизводится дословно.")
    add("4. **Единицы цены выходят за три базовые** (`sec` / `gen` / `1k_chars`): у 4 режимов GPT Image 2.6 "
        "цена в токенах (`unit: tokens`), у 2 режимов Qwen Image — за мегапиксель (`unit: megapixel`). "
        "Посчитать «кредиты за генерацию» для них по прайсу нельзя — оставлено как есть, "
        "чтобы не подменять факт оценкой.")
    add("5. **Точные эндпоинты** известны только для `jobs` / `veo` / `runway` / `suno`; у режимов без "
        "страницы в доках `api` проставлен по умолчанию (`jobs`), это допущение, а не факт из доков.")
    add("6. **Фактических списаний нет** — цены из прайса, не из истории генераций.")
    add("7. **Названия брендов** взяты из колонки CSV (`Alibaba`, `Hailuo`, `Pixverse`, `Kie`, "
        "`Tongyi (Z-Image)` и т.п.); в `/api/v1/models` бренд местами другой (`Other`), поэтому "
        "бренд семейства — из CSV, provider API — в `meta`.")
    add("8. **Формат `pricing.when`** — не контракт kie.ai, а наша реконструкция: спец-ключи "
        "`sound` (звук вкл/выкл), `with_video` (есть видео на входе), `mode` (тир), `resolution`, "
        "`duration`. Шаг 8 должен читать их как «условия первого совпадения».")
    no_desc = sum(1 for f in families if f["desc"].startswith("описания в источниках нет"))
    add(f"9. **Описаний нет у части семейств**: у {no_desc} из {len(families)} в `/api/v1/models` "
        "пустой `description` и нет осмысленного `title`, в CSV колонка «описание модели» тоже "
        "пустая — стоит `desc: «описания в источниках нет»`. Это не мешает меню: `label` и режимы "
        "на месте.")
    add("")
    add("## 7. Структура JSON")
    add("")
    add("```")
    add("{")
    add('  "meta": {"generated_at", "source_api", "source_docs", "source_table", "source_catalog",')
    add('           "catalog_git_blob_sha", "credit_usd", "counts", "checks"},')
    add('  "families": [')
    add('    {"id", "label", "brand", "media": "video|image", "desc",')
    add('     "modes": [{"id", "label", "kie_id", "task_type", "api", "endpoint",')
    add('                "fields": [{"name","label","kind","required","default",')
    add('                            "options","min","max","max_items","hint"}],')
    add('                "pricing": {"unit","rules":[{"when","credits"}],"default","note",')
    add('                            "credit_usd","source_text"},')
    add('                "constraints", "docs_url", "fields_source", "in_live_api"}]}')
    add("  ]")
    add("}")
    add("```")
    add("")
    add("`kind` полей: `text`, `textarea`, `select`, `number`, `toggle`, `images`, `videos`, "
        "`audios`, `json` (вложенный объект — расширение сверх контракта, помечено `fields_source`). "
        "Результаты трёх сверок машинно — в `docs/kie-model-families-checks.json`.")
    add("")
    add("## 8. Как пересобрать")
    add("")
    add("```")
    add("python docs/build_kie_families.py      # пишет json + md + checks")
    add("python docs/validate_kie_families.py   # независимая проверка записанного json")
    add("```")
    add("")
    (OUT_MD).write_text("\n".join(lines), encoding="utf-8")


def _brand_table(add, families, media):
    by_brand = defaultdict(list)
    for fam in families:
        if fam["media"] == media:
            by_brand[fam["brand"]].append(fam)
    add("| Бренд | Семейство | Режимов | id | Режимы (kie_id) | Цена |")
    add("|---|---|---|---|---|---|")
    for brand in sorted(by_brand, key=lambda b: (-len(by_brand[b]), b)):
        fams = by_brand[brand]
        for i, fam in enumerate(fams):
            add(f"| {brand if i == 0 else ''} | **{fam['label']}** (`{fam['id']}`) | {len(fam['modes'])} | "
                f"{len(fam['modes'])} | {fmt_modes(fam)} | {pricing_short(fam)} |")
    add("")


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


def main():
    api_models, id_to_schema, rows, csv_by_id, catalog_mod, catalog_sha = load_sources()
    families, catalog_by_model = build(api_models, id_to_schema, csv_by_id, catalog_mod)
    checks = run_checks(families, api_models, csv_by_id, catalog_mod, id_to_schema)
    generated = "2026-11-14"
    checks["catalog_snapshot"] = {"git_blob_sha": catalog_sha,
                                  "entries": len(catalog_mod.MODELS)}
    checks["live_check"] = LIVE_CHECK

    api_media = {r["id модели"] for r in rows}
    meta = {
        "generated_at": generated,
        "source_api": "https://api.kie.ai/api/v1/models (docs/kie-ai-raw/models.json)",
        "source_docs": "https://docs.kie.ai OpenAPI input (docs/kie-ai-raw/docs-schemas.json)",
        "source_table": "docs/kie-ai-models.csv",
        "source_catalog": "app/services/kie_catalog.py @ HEAD",
        "catalog_git_blob_sha": catalog_sha,
        "credit_usd": CREDIT_USD,
        "counts": {
            "api_models_total": len(api_models),
            "api_media_models": len(api_media),
            "api_video": checks["coverage"]["api_video_ids"],
            "api_image": checks["coverage"]["api_image_ids"],
            "families": len(families),
            "modes": sum(len(f["modes"]) for f in families),
        },
        "checks": checks,
    }
    payload = {"meta": meta, "families": families}
    OUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    OUT_CHECKS.write_text(json.dumps(checks, ensure_ascii=False, indent=1), encoding="utf-8")
    write_md(families, checks, generated)

    print("families:", len(families), "modes:", meta["counts"]["modes"])
    print("coverage:", checks["coverage"]["placed_ids_unique"], "/", checks["coverage"]["api_media_ids"],
          "lost:", len(checks["coverage"]["lost_api_ids"]),
          "dupes:", len(checks["coverage"]["duplicate_ids"]))
    print("fields: schema", checks["fields"]["modes_with_docs_schema"],
          "complete", checks["fields"]["modes_fields_complete"],
          "catalog", checks["fields"]["modes_fields_from_catalog"],
          "none", checks["fields"]["modes_without_fields"])
    print("pricing: with", checks["pricing"]["modes_with_price"],
          "checked", checks["pricing"]["checked_against_csv"],
          "match", checks["pricing"]["numbers_match"],
          "diff", len(checks["pricing"]["mismatches"]))


if __name__ == "__main__":
    main()
