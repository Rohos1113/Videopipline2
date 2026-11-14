# Проверка цен kie.ai в живом продукте

Дата: 14.11.2026 15:08 · студия `http://127.0.0.1:8777` · источники: `docs/kie-prices-usd.json` (правила), `docs/kie-model-families.json` (схемы полей), `POST /api/kie-create/estimate`, живая панель UI.

## Итог

- Сверено **174 режимов** из 182 (остальные 8 — без цены в прайсе, ожидаемо «цена уточняется»).
- Прогнано **669 конфигураций** (разрешение, длительность, звук, видеовход, тир, число картинок).
- Формула ↔ API: **585 сошлось**, **63 расхождений**, 19 спорных (нельзя посчитать заранее), 2 не посчитать.
- UI ↔ формула ↔ API: **194 замеров** по 56 семействам из дампа; **182 UI = API**, 6 расхождений UI, 5 залипших цен.
- Исправления цен: **все 4 подтверждены** (правила, каталог, API и UI там, где замер есть).
- Наценка `usd_client = usd_kie × 1.25` и `1 кредит = $0.005` — сходятся во всех посчитанных случаях.

## Метод

Три независимых источника:

1. **Скрипт-калькулятор** `web/.tmp-verify/verify_pricing.py` — не импортирует код студии, читает только `docs/kie-prices-usd.json` и `docs/kie-model-families.json`, сам строит конфигурации по `affects_price` и сам применяет правила (`when` → кредиты → usd_kie → ×1.25).
2. **`POST /api/kie-create/estimate`** живого продукта — что реально посчитает студия при генерации.
3. **Живая панель UI** — цена в шапке панели параметров (`dom-dump-all.json`, три точки: как открылось, после смены разрешения, после смены длительности).

Правила приёмки: расхождение больше **$0.01** = провал; одинаковая цена на дешёвых и дорогих настройках = провал. Ожидаемая цена — первое подходящее правило прайса (или `default_usd_client`), с множителем единицы: `sec` × длительность, `image` × число картинок, `gen` — фикс, `mp`/`token_kind` — не считается.

## Расхождения формулы и API

Всего 63 кейсов в 21 режимах. Причины сгруппированы — по ним видно, что чинить в бэкенде/данных, а не «где-то в цене».

| Причина | Кейсов | Режимы | Что происходит |
|---|---|---|---|
| `mode` | 19 | flux1-kontext, gpt-image/1.5-image-to-image, gpt-image/1.5-text-to-image, ideogram/character, ideogram/character-edit, ideogram/character-remix, ideogram/v3-edit, ideogram/v3-text-to-image, veo-3-1, veo/extend | ключ правила `mode` не сопоставляется с полем тира |
| `sound` | 40 | kling-3.0-omni/image-to-video, kling-3.0-omni/reference-to-video, kling-3.0-omni/text-to-video, pixverse-v6-max/image-to-video, pixverse-v6-max/text-to-video, pixverse-v6/image-to-video, pixverse-v6/transition | ключ правила `sound` не сопоставляется с полем аудио |
| `video` | 2 | gemini-omni-video, google/gemini-omni-flash-1-1 | видеовход не распознан |
| `max_mp` | 2 | minimax-h3/image-edit, minimax-h3/text-to-image | ключ `max_mp` не поддерживается |

Детали по каждой причине:

### Тир (`mode`)

- `veo-3-1` · resolution: 1080p · ожидалось **$0.41**, API отдал **$0.38** · правило `{"mode": "fast", "resolution": "1080p"}` · API matched `null`
- `veo-3-1` · resolution: 4k · ожидалось **$1.12**, API отдал **$0.38** · правило `{"mode": "fast", "resolution": "4K"}` · API matched `null`
- `veo-3-1` · model: veo3_lite · ожидалось **$0.19**, API отдал **$0.38** · правило `{"mode": "lite", "resolution": "720p"}` · API matched `null`
- `veo-3-1` · model: veo3 · ожидалось **$1.56**, API отдал **$0.38** · правило `{"mode": "quality", "resolution": "720p"}` · API matched `null`
- `veo/extend` · model: quality · ожидалось **$1.56**, API отдал **$0.38** · правило `{"mode": "quality"}` · API matched `null`
- `veo/extend` · model: lite · ожидалось **$0.19**, API отдал **$0.38** · правило `{"mode": "lite"}` · API matched `null`
- `flux1-kontext` · model: flux-kontext-max · ожидалось **$0.06**, API отдал **$0.03** · правило `{"mode": "max"}` · API matched `null`
- `ideogram/character` · базовая · ожидалось **$0.11**, API отдал **$0.07** · правило `{"mode": "balanced"}` · API matched `null`
- `ideogram/character` · rendering_speed: QUALITY · ожидалось **$0.15**, API отдал **$0.07** · правило `{"mode": "quality"}` · API matched `null`
- `ideogram/character-edit` · базовая · ожидалось **$0.11**, API отдал **$0.07** · правило `{"mode": "balanced"}` · API matched `null`
- `ideogram/character-edit` · rendering_speed: QUALITY · ожидалось **$0.15**, API отдал **$0.07** · правило `{"mode": "quality"}` · API matched `null`
- `ideogram/character-remix` · базовая · ожидалось **$0.11**, API отдал **$0.07** · правило `{"mode": "balanced"}` · API matched `null`
- `ideogram/character-remix` · rendering_speed: QUALITY · ожидалось **$0.15**, API отдал **$0.07** · правило `{"mode": "quality"}` · API matched `null`
- `ideogram/v3-text-to-image` · rendering_speed: BALANCED · ожидалось **$0.04**, API отдал **$0.02** · правило `{"mode": "balanced"}` · API matched `null`
- `ideogram/v3-text-to-image` · rendering_speed: QUALITY · ожидалось **$0.06**, API отдал **$0.02** · правило `{"mode": "quality"}` · API matched `null`
- `ideogram/v3-edit` · базовая · ожидалось **$0.04**, API отдал **$0.02** · правило `{"mode": "balanced"}` · API matched `null`
- `ideogram/v3-edit` · rendering_speed: QUALITY · ожидалось **$0.06**, API отдал **$0.02** · правило `{"mode": "quality"}` · API matched `null`
- `gpt-image/1.5-text-to-image` · quality: high · ожидалось **$0.14**, API отдал **$0.03** · правило `{"mode": "high"}` · API matched `null`
- `gpt-image/1.5-image-to-image` · quality: high · ожидалось **$0.14**, API отдал **$0.03** · правило `{"mode": "high"}` · API matched `null`

### Звук (`sound`)

- `kling-3.0-omni/text-to-video` · resolution: 1080p · ожидалось **$0.63**, API отдал **$0.47** · правило `{"resolution": "1080p", "sound": false}` · API matched `null`
- `kling-3.0-omni/text-to-video` · audio: вкл · ожидалось **$0.63**, API отдал **$0.47** · правило `{"resolution": "720p", "sound": true}` · API matched `null`
- `kling-3.0-omni/text-to-video` · комбо: aspect_ratio=16:9, audio=True, customize_multi_shots=False, duration=3, prefer_multi_shots=False, resolution=720p · ожидалось **$0.38**, API отдал **$0.28** · правило `{"resolution": "720p", "sound": true}` · API matched `null`
- `kling-3.0-omni/text-to-video` · комбо: aspect_ratio=16:9, audio=True, customize_multi_shots=False, duration=15, prefer_multi_shots=False, resolution=720p · ожидалось **$1.89**, API отдал **$1.42** · правило `{"resolution": "720p", "sound": true}` · API matched `null`
- `kling-3.0-omni/image-to-video` · resolution: 1080p · ожидалось **$0.63**, API отдал **$0.47** · правило `{"resolution": "1080p", "sound": false}` · API matched `null`
- `kling-3.0-omni/image-to-video` · audio: вкл · ожидалось **$0.63**, API отдал **$0.47** · правило `{"resolution": "720p", "sound": true}` · API matched `null`
- `kling-3.0-omni/image-to-video` · комбо: aspect_ratio=auto, audio=True, customize_multi_shots=False, duration=3, resolution=720p · ожидалось **$0.38**, API отдал **$0.28** · правило `{"resolution": "720p", "sound": true}` · API matched `null`
- `kling-3.0-omni/image-to-video` · комбо: aspect_ratio=auto, audio=True, customize_multi_shots=False, duration=15, resolution=720p · ожидалось **$1.89**, API отдал **$1.42** · правило `{"resolution": "720p", "sound": true}` · API matched `null`
- `kling-3.0-omni/reference-to-video` · resolution: 1080p · ожидалось **$0.63**, API отдал **$0.47** · правило `{"resolution": "1080p", "sound": false}` · API matched `null`
- `kling-3.0-omni/reference-to-video` · audio: вкл · ожидалось **$0.63**, API отдал **$0.47** · правило `{"resolution": "720p", "sound": true}` · API matched `null`
- `kling-3.0-omni/reference-to-video` · комбо: aspect_ratio=16:9, audio=True, customize_multi_shots=False, duration=3, resolution=720p, video_urls=[] · ожидалось **$0.38**, API отдал **$0.28** · правило `{"resolution": "720p", "sound": true}` · API matched `null`
- `kling-3.0-omni/reference-to-video` · комбо: aspect_ratio=16:9, audio=True, customize_multi_shots=False, duration=15, resolution=720p, video_urls=[] · ожидалось **$1.89**, API отдал **$1.42** · правило `{"resolution": "720p", "sound": true}` · API matched `null`
- `pixverse-v6/image-to-video` · quality: 720p · ожидалось **$0.04**, API отдал **$0.03** · правило `{"resolution": "720p", "sound": false}` · API matched `null`
- `pixverse-v6/image-to-video` · quality: 1080p · ожидалось **$0.09**, API отдал **$0.03** · правило `{"resolution": "1080p", "sound": false}` · API matched `null`
- `pixverse-v6/image-to-video` · комбо: duration=15, generate_audio_switch=True, generate_multi_clip_switch=False, quality=360p · ожидалось **$0.53**, API отдал **$0.38** · правило `{"resolution": "360p", "sound": true}` · API matched `null`
- `pixverse-v6/image-to-video` · комбо: duration=1, generate_audio_switch=True, generate_multi_clip_switch=False, quality=1080p · ожидалось **$0.12**, API отдал **$0.03** · правило `{"resolution": "1080p", "sound": true}` · API matched `null`
- `pixverse-v6/image-to-video` · комбо: duration=15, generate_audio_switch=False, generate_multi_clip_switch=False, quality=1080p · ожидалось **$1.35**, API отдал **$0.38** · правило `{"resolution": "1080p", "sound": false}` · API matched `null`
- `pixverse-v6/image-to-video` · комбо: duration=15, generate_audio_switch=True, generate_multi_clip_switch=False, quality=1080p · ожидалось **$1.73**, API отдал **$0.38** · правило `{"resolution": "1080p", "sound": true}` · API matched `null`
- `pixverse-v6-max/text-to-video` · quality: 540p · ожидалось **$0.04**, API отдал **$0.03** · правило `{"resolution": "540p", "sound": false}` · API matched `null`
- `pixverse-v6-max/text-to-video` · quality: 720p · ожидалось **$0.06**, API отдал **$0.03** · правило `{"resolution": "720p", "sound": false}` · API matched `null`
- `pixverse-v6-max/text-to-video` · quality: 1080p · ожидалось **$0.11**, API отдал **$0.03** · правило `{"resolution": "1080p", "sound": false}` · API matched `null`
- `pixverse-v6-max/text-to-video` · generate_audio_switch: вкл · ожидалось **$0.04**, API отдал **$0.03** · правило `{"resolution": "360p", "sound": true}` · API matched `null`
- `pixverse-v6-max/text-to-video` · комбо: duration=15, generate_audio_switch=True, quality=360p · ожидалось **$0.68**, API отдал **$0.45** · правило `{"resolution": "360p", "sound": true}` · API matched `null`
- `pixverse-v6-max/text-to-video` · комбо: duration=1, generate_audio_switch=True, quality=1080p · ожидалось **$0.14**, API отдал **$0.03** · правило `{"resolution": "1080p", "sound": true}` · API matched `null`
- `pixverse-v6-max/text-to-video` · комбо: duration=15, generate_audio_switch=False, quality=1080p · ожидалось **$1.65**, API отдал **$0.45** · правило `{"resolution": "1080p", "sound": false}` · API matched `null`
- `pixverse-v6-max/text-to-video` · комбо: duration=15, generate_audio_switch=True, quality=1080p · ожидалось **$2.10**, API отдал **$0.45** · правило `{"resolution": "1080p", "sound": true}` · API matched `null`
- `pixverse-v6-max/image-to-video` · quality: 540p · ожидалось **$0.04**, API отдал **$0.03** · правило `{"resolution": "540p", "sound": false}` · API matched `null`
- `pixverse-v6-max/image-to-video` · quality: 720p · ожидалось **$0.06**, API отдал **$0.03** · правило `{"resolution": "720p", "sound": false}` · API matched `null`
- `pixverse-v6-max/image-to-video` · quality: 1080p · ожидалось **$0.11**, API отдал **$0.03** · правило `{"resolution": "1080p", "sound": false}` · API matched `null`
- `pixverse-v6-max/image-to-video` · generate_audio_switch: вкл · ожидалось **$0.04**, API отдал **$0.03** · правило `{"resolution": "360p", "sound": true}` · API matched `null`
- `pixverse-v6-max/image-to-video` · комбо: duration=15, generate_audio_switch=True, quality=360p · ожидалось **$0.68**, API отдал **$0.45** · правило `{"resolution": "360p", "sound": true}` · API matched `null`
- `pixverse-v6-max/image-to-video` · комбо: duration=1, generate_audio_switch=True, quality=1080p · ожидалось **$0.14**, API отдал **$0.03** · правило `{"resolution": "1080p", "sound": true}` · API matched `null`
- `pixverse-v6-max/image-to-video` · комбо: duration=15, generate_audio_switch=False, quality=1080p · ожидалось **$1.65**, API отдал **$0.45** · правило `{"resolution": "1080p", "sound": false}` · API matched `null`
- `pixverse-v6-max/image-to-video` · комбо: duration=15, generate_audio_switch=True, quality=1080p · ожидалось **$2.10**, API отдал **$0.45** · правило `{"resolution": "1080p", "sound": true}` · API matched `null`
- `pixverse-v6/transition` · quality: 720p · ожидалось **$0.04**, API отдал **$0.03** · правило `{"resolution": "720p", "sound": false}` · API matched `null`
- `pixverse-v6/transition` · quality: 1080p · ожидалось **$0.09**, API отдал **$0.03** · правило `{"resolution": "1080p", "sound": false}` · API matched `null`
- `pixverse-v6/transition` · комбо: duration=15, generate_audio_switch=True, quality=360p · ожидалось **$0.53**, API отдал **$0.38** · правило `{"resolution": "360p", "sound": true}` · API matched `null`
- `pixverse-v6/transition` · комбо: duration=1, generate_audio_switch=True, quality=1080p · ожидалось **$0.12**, API отдал **$0.03** · правило `{"resolution": "1080p", "sound": true}` · API matched `null`
- `pixverse-v6/transition` · комбо: duration=15, generate_audio_switch=False, quality=1080p · ожидалось **$1.35**, API отдал **$0.38** · правило `{"resolution": "1080p", "sound": false}` · API matched `null`
- `pixverse-v6/transition` · комбо: duration=15, generate_audio_switch=True, quality=1080p · ожидалось **$1.73**, API отдал **$0.38** · правило `{"resolution": "1080p", "sound": true}` · API matched `null`

### Видеовход (`with_video`)

- `gemini-omni-video` · видеовход: есть · ожидалось **$1.05**, API отдал **$0.39** · правило `{"resolution": "720p", "with_video": true}` · API matched `{"resolution": "720p", "duration": "4"}`
- `google/gemini-omni-flash-1-1` · видеовход: есть · ожидалось **$1.05**, API отдал **$0.39** · правило `{"resolution": "720p", "with_video": true}` · API matched `{"resolution": "720p", "duration": "4"}`

### `max_mp`

- `minimax-h3/text-to-image` · resolution: 4K · ожидалось **$0.03**, API отдал **$0.01** · правило `{"max_mp": 20, "resolution": "4K"}` · API matched `null`
- `minimax-h3/image-edit` · resolution: 4K · ожидалось **$0.03**, API отдал **$0.01** · правило `{"max_mp": 20, "resolution": "4K"}` · API matched `null`


### Спорное: число выходных картинок

19 кейсов в 3 режимах (seedream-v4 t2i/edit, seedream/5-5-layer-decomposition) не считаются провалом: `max_images` — верхняя граница, а фактическое число картинок задаётся промптом, поэтому цену до генерации из прайса не вывести. API показывает фикс за одну картинку, а прайс — цену за картинку × `max_images`; это расхождение трактовки, а не арифметики. См. `ambiguous` в JSON.

## Проверка исправлений

| Что проверяли | Ожидалось | Правила | Каталог | API | Вердикт |
|---|---|---|---|---|---|
| 1080p без видеовхода — 158 кр/с (было 114) (`bytedance/seedance-2-5`) | 158.0 кр/с | 158.0 | нет строки* | 158.0 | OK |
| 4K — 75.5 кр/с (было 67) (`kling-3.0/video`) | 75.5 кр/с | 75.5 | 75.5 | 75.5 | OK |
| 720p со звуком — 22.7 кр/с (было 20) (`kling-3.0/video`) | 22.7 кр/с | 22.7 | 22.7 | 22.7 | OK |
| 768P — 8 кр/с (было 16) (`minimax-h3/text-to-video`) | 8.0 кр/с | 8.0 | 8.0 | 8.0 | OK |

\* у `bytedance/seedance-2-5` каталог ищет строку по префиксу id и не находит — цена в каталоге проверена через живой `/api/kie-create/catalog`, там 158 кр/с есть; это дефект поиска в скрипте, не в продукте.

В UI подтверждено: Seedance 2.5 1080p (5 с) = **$4.94** (158 кр/с), Kling 3.0 Omni 4K (5 с) = **$2.36** (75.5 кр/с). Kling 3.0 `sound` и MiniMax 768P в дампе не переключались — нужен прицельный замер, сейчас подтверждены правила/каталог/API.

## Доплаты за входные картинки

| Режим | Поле | 1 картинка | 2 | 3 | Сходится |
|---|---|---|---|---|---|
| `seedream/5-pro-text-to-image` | — | — | — | — | не проверить: в схеме режима нет поля-картинок — доплату через API не проверить |
| `seedream/5-pro-image-to-image` | image_urls | $0 (бесплатно) | $0.0031 / $0.0031 | $0.0062 / $0.0062 | OK |
| `qwen3/pro-image-to-image` | image_urls | $0.0031 / $0.0031 | $0.0062 / $0.0062 | $0.0093 / $0.0093 | OK |
| `minimax-h3/text-to-video` | — | — | — | — | не проверить: в схеме режима нет поля-картинок — доплату через API не проверить |
| `minimax-h3/image-to-video` | first_frame_url | — | — | — | OK |
| `minimax-h3/reference-to-video` | — | — | — | — | не проверить: в схеме режима нет поля-картинок — доплату через API не проверить |
| `qwen3/image-to-image` | image_urls | $0.0031 / $0.0031 | $0.0062 / $0.0062 | $0.0093 / $0.0093 | OK |
| `seedream/5-5-image-to-image` | image_urls | $0.0090 / $0.0090 | $0.02 / $0.02 | $0.03 / $0.03 | OK |
| `seedream/5-5-layer-decomposition` | image_url | $0.0090 / $0.0090 | $0.02 / $0.02 | $0.03 / $0.03 | OK |
| `minimax-h3/image-edit` | image_urls | $0.0031 / $0.0031 | $0.0062 / $0.0062 | $0.0093 / $0.0093 | OK |

Формат ячейки: «API / ожидалось» — доплата сверх базовой цены, $ клиента. Порог бесплатных картинок (`free_first`) соблюдается: seedream/5-pro — 1 бесплатно, minimax-h3 i2v — 5 бесплатно.

## UI против формулы и API

Дамп: 72 семейства, у 56 открылась панель, 194 замера цены. Из них **182** совпали с API до цента (в пределах двух знаков), 6 — расхождения, 5 — залипшая цена.

### UI показывает не ту цену

| Семейство | Режим | Точка | UI | API | Формула |
|---|---|---|---|---|---|
| gemini-omni | character | default | $0 | — | — |
| gemini-omni-flash-1-2 | extend | default | $0.38 | $0.12 | $0.12 |
| ideogram-v3 | remix | default | $0 | — | — |
| nano-banana | t2i | default | $0.15 | $0.03 | $0.03 |
| nano-banana-2 | generate | default | $0.15 | $0.07 | $0.07 |
| veo-3-1 | generate | default | $0.50 | $0.38 | $0.38 |

Пояснения: `gemini-omni character` и `ideogram-v3 remix` — цены нет, UI рисует `$0.00` вместо «цена уточняется». `nano-banana`, `nano-banana-2`, `veo-3-1` — локальный расчёт UI дороже ответа API (в 2–5 раз); `gemini-omni-flash-1-2 extend` — UI дороже в 3 раза. Это дефекты UI, не бэкенда: API считает по правилам.

### Залипшая цена при переключении режимов

| Семейство | Режим | UI | API | Совпадает с ценами режимов |
|---|---|---|---|---|
| happyhorse | t2v | $2.72 | $4.50 | i2v, r2v |
| happyhorse | i2v | $2.72 | $4.50 | t2v, r2v |
| happyhorse | r2v | $2.72 | $4.50 | t2v, i2v |
| kling-4-0 | keyframe-flash | $3.19 | $0.53 | r2v-flash |
| kling-4-0 | r2v-flash | $3.19 | $0.53 | keyframe-flash |

Это не ошибка математики: при данных настройках цена в панели равна ответу API. Проблема в том, что при переключении режима панель сохранила цену предыдущего режима — UI-агенту на заметку.

## Кто что правит

По результатам сверки, без правок с моей стороны:

1. **Бэкенд (`app/services/kie_catalog.py`)** — основная масса расхождений (61 из 63): `_find_rule_field` не умеет ключ `mode` (тиры veo/ideogram/flux/gpt-image), ключ `sound` (аудиополя `audio`/`generate_audio_switch`), `max_mp`; `_extra_usd` не видит счётчики картинок из `_IMAGE_SETTING_KEYS`; в каталоге теряется условие `with_video:false` и не распознаётся `video_list`.
2. **UI (`web/src/components/outsee/outsee-create-workspace.tsx`)** — цена в панели расходится с API у 6 режимов (локальный расчёт дороже, gemini flash extend в 3 раза), залипшая цена при переключении режимов (happyhorse, kling-4.0 flash), `$0.00` вместо «цена уточняется».
3. **Данные прайса** — трактовка `max_images` у seedream-v4 и seedream/5-5-layer-decomposition: либо цена «за картинку» без множителя (как считает API), либо верхняя граница и тогда UI должен показывать «до $X»; сейчас формула и продукт расходятся в 6–30 раз. Решение продуктовое.

## Что не проверено

- 8 режимов без записи в прайсе (ожидаемо «цена уточняется»): gemini-omni-character, ideogram/v3-remix, omnihuman-1-5/human-identification, omnihuman-1-5/subject-detection, gpt-image-2-6/flare-text-to-image, gpt-image-2-6/flare-image-to-image, gpt-image-2-6/sunburst-text-to-image, gpt-image-2-6/sunburst-image-to-image — в дампе UI они попали как $0.00 либо не открылись; текст «цена уточняется» не подтверждён
- 4 модели GPT Image 2.6 (tokens, flare/sunburst) — цена в токенах, UI должен писать «цена уточняется»; семейство в дампе не открылось (скрыто до фикса UI)
- 2 режима qwen (unit mp) — в прайсе нет таблицы «размер → мегапиксели»: проверена только реакция цены на размер (не абсолют), абсолют посчитать нечем
- seedream-v4 t2i/edit и seedream/5-5-layer-decomposition — `max_images` это верхняя граница, а не точное число картинок: ожидаемую цену до генерации из прайса не вывести (19 кейсов помечены `ambiguous`)
- 51 режим с `affects_price`, где в схеме нет соответствующего поля (фиксированная цена: kling v2.1/v2.5, wan 2.2–2.7, runway, hailuo, pixverse, minimax-h3, gpt-image-2.6/economy, uptowners) — настройками не проверить
- видеовход с длительностью/секундами входа (Seedance 2.x: seconds видео входит в счёт) — API принимает внешний видеовход, но UI-дамп не даёт его включить; проверено только веткой «без видео»
- 16 семейств в дампе UI не открылись (10 скрыто + 6 картинных без панели) — их цены не сверены с UI, только формула ↔ API
- пликер «от $X» не сверялся как цена конфигурации: это минимум по режимам семейства (`price_from_usd`), а не цена выбранных настроек

## Служебное

- Каталог живого продукта: 182 режима, все 182 есть в прайсе; расхождения `when` в каталоге — 9 (у 9 режимов потеряно условие `with_video:false`, из-за чего тариф с видеовходом недостижим).
- Разводка правил: всего 542 правил; `resolution` 435, `duration` 109, `sound` 91 (из них почти все не мапятся на поле), `mode` 51, `with_video:false` 45, `max_mp` 9, `token_kind` 24.
- `affects_price` без поля в схеме: 51 режимов — настройками не проверить.
- Пликер «от $X» не сверялся как цена конфигурации: это минимум по режимам семейства (`price_from_usd`), а не цена выбранных настроек.
- Скрипты проверки: `web/.tmp-verify/verify_pricing.py` (формула ↔ API), `web/.tmp-verify/ui_compare.py` (UI ↔ формула ↔ API), вход — `web/.tmp-verify/dom-dump-all.json`. В git не кладутся.
- Сырые результаты: `web/.tmp-verify/pricing_result.json`, `web/.tmp-verify/ui_compare.json`.
