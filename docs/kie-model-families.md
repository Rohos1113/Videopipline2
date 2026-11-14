# Семейства и режимы медиа-моделей kie.ai

Собрано 2026-11-14 (шаг 7 мастер-задачи, ветка `test`). Семейство = одна карточка в меню выбора модели; режим = вариант внутри неё (тип входа, тир, утилита).

Источники: живой `GET https://api.kie.ai/api/v1/models` (`docs/kie-ai-raw/models.json`, 251 модель), OpenAPI-схемы `input` со страниц docs.kie.ai (`docs/kie-ai-raw/docs-schemas.json` + догруженные `docs-schemas-extra.json`), таблица `docs/kie-ai-models.csv`, каталог студии `app/services/kie_catalog.py`, прайс `docs/kie-prices-usd.json` (первичен по деньгам). Платных генераций не было, ключ в файлы не попадал.

## 1. Итог

| Показатель | Значение |
|---|---|
| Семейств (карточек) | **72** (видео 37, картинки 35) |
| Режимов | **182** = 181 по id живого API + 1 каталожный (`bytedance/seedance-1.5-pro`) |
| Медиа-id из живого API разложено | **181/181** (видео 100, картинки 81) |
| Потерянных id | 0 |
| Дублей id (в двух режимах) | 0 |
| id каталога студии покрыто | 28/28 |
| id вне живого API (только каталог студии) | 1: bytedance/seedance-1.5-pro |

## 2. Сверки (цифрами)

### Сверка 1 — покрытие живого API

- В живом `/api/v1/models` 251 моделей, из них медиа **181** = видео 100 + картинки 81 (остальные — чат-LLM, музыка, TTS, ASR; не входят в задачу).
- Живой API перепроверен 2026-11-14 12:42 MSK (бесплатные GET, `credit` → HTTP 200): уже **253** модели — маркет добавил `gemini-4-hydrogen`, `gemini-4-hydrogen-openai` с taskType Chat/Chat, медиа по-прежнему **181** (видео 100, картинки 81). Новые id вне задачи.
- В семействах и режимах ровно **181** id из живого API: потеряно 0, дублей 0. Всего уникальных id (с каталожным) — 182.
- Переклассифицировано: `ideogram/v3-text-to-image` — kie.ai отдаёт taskType `Text to Video`, хотя модель картинная (см. §5).
- Каталог студии: 28 медиа-id (из 33 записей каталога; 9 записей — музыка/звук/голос, вне задачи) — покрыто 28/28.
- `wan/2-7-r2v` в API помечен сразу двумя тегами (`Image to Image` и `Image to Video`) — по правилу «вход = режим» отнесён к видео, поэтому видео 100 и картинки 81 сходятся с таблицей без пересечений.

### Сверка 2 — поля против docs-схем

- Режимов всего **182**.
- С OpenAPI-схемой в docs.kie.ai: **175**, поля выписаны полностью у **175** (расхождений 0).
- Поля взяты из каталога студии (схемы в доках нет): **7**.
- Без полей вообще (нет ни схемы, ни каталога): **0** — у таких режимов `fields_known: false` и `hint: «схема полей неизвестна»`, чтобы UI не подставлял поля карточки семейства; режим и цена сохранены.
- `fields_known` у каждого режима: `true` — набор полей известен по схеме/каталогу, `false` — не угадываем. Сейчас `true` у 182 из 182.
- Обязательность полей сверена с колонкой «обязательные поля» в `kie-ai-models.csv`: совпало 127/142.
  Расхождения (15) — это разное понимание обязательности: в CSV колонка собрана по тексту описания (там пишут «Required field»), а в OpenAPI-схеме то же поле может стоять с флагом `required: false`, потому что один `input` обслуживает и text-to-video, и image-to-video (у `bytedance/seedance-2` в описании «Required field», в схеме все поля необязательные). Источник для полей — схема, CSV не переписывался.

### Сверка 3 — цены (прайс `docs/kie-prices-usd.json` первичен)

- Цена есть (есть хотя бы одно правило): **178** режимов; без правил **4** (в прайсе цены нет — токены/неизвестно).
- Единицы (из прайса): 1m_tokens — 4, gen — 28, image — 72, mp — 2, sec — 72, unknown — 4
- Единица в families.json совпала с прайсом у **178/178** режимов, где она в прайсе указана.
- Набор правил (when + кредиты) совпал с прайсом у **178/178**.
- Числа из `kie-ai-models.csv` — сверка справочная: 171 режимов, совпало 149, расхождений 22. CSV — снимок текста `pricingDesc`; в прайсе правила дробнее (тиры, звук, длительность, видеовход), поэтому набор кредитов в CSV может быть уже прайса. Деньги считает прайс.
- Единиц, где families/прайс расходятся с CSV: 63 — это картинки (`image` в прайсе против «за картинку» → `gen` в CSV) и токены; единица взята из прайса.

| id | числа в CSV | числа из моего разбора |
|---|---|---|
| `minimax-h3/text-to-video` | [4.0, 8.0, 13.0] | [8.0, 13.0] |
| `minimax-h3/image-to-video` | [4.0, 8.0, 13.0] | [8.0, 13.0] |
| `minimax-h3/reference-to-video` | [4.0, 8.0, 13.0] | [8.0, 13.0] |
| `video/upscale` | [6.0] | [1.5, 3.0, 6.0] |
| `wan/2-6-text-to-video` | [210.0, 315.0] | [70.0, 105.0, 140.0, 210.0, 315.0] |
| `wan/2-6-image-to-video` | [210.0, 315.0] | [70.0, 105.0, 140.0, 210.0, 315.0] |
| `wan/2-6-video-to-video` | [210.0, 315.0] | [70.0, 105.0, 140.0, 210.0, 315.0] |
| `wan/2-6-flash-image-to-video` | [60.0, 90.0, 120.0, 180.0] | [20.0, 30.0, 40.0, 60.0, 80.0, 90.0, 120.0, 180.0] |
| `wan/2-6-flash-video-to-video` | [40.0, 60.0, 80.0, 120.0] | [20.0, 30.0, 40.0, 60.0, 80.0, 120.0] |
| `seedream/5-pro-text-to-image` | [0.5, 7.0, 14.0] | [7.0, 14.0] |
| `seedream/5-pro-image-to-image` | [0.5, 7.0, 14.0] | [7.0, 14.0] |
| `seedream/5-5-image-to-image` | [1.44, 3.6, 6.3, 9.18] | [3.6, 6.3] |
| `seedream/5-5-layer-decomposition` | [1.44, 3.6, 6.3, 15.84] | [3.6, 6.3] |
| `minimax-h3/image-edit` | [0.5, 1.8, 5.5] | [1.8, 5.5] |
| `gpt-image-2-6/flare-text-to-image` | [36.0, 900.0] | [225.0, 360.0, 900.0, 1440.0, 5400.0] |
| `gpt-image-2-6/flare-image-to-image` | [36.0, 900.0] | [225.0, 360.0, 900.0, 1440.0, 5400.0] |
| `gpt-image-2-6/sunburst-text-to-image` | [36.0, 900.0] | [225.0, 360.0, 900.0, 1440.0, 5400.0] |
| `gpt-image-2-6/sunburst-image-to-image` | [36.0, 900.0] | [225.0, 360.0, 900.0, 1440.0, 5400.0] |
| `qwen3/image-to-image` | [0.5, 4.8] | [4.8] |
| `qwen3/pro-image-to-image` | [0.5, 6.4, 12.0] | [6.4, 12.0] |
| `wan/2-7-image` | [4.8, 12.0] | [4.8] |
| `wan/2-7-image-pro` | [4.8, 12.0] | [12.0] |

### Сверка 4 — дефолты полей, от которых зависит цена

- Поставлено дефолтов: **50** у **45** режимов (было `default: null`). Правило: `toggle` → `false`, `select` → первый option, и только если это значение реально есть в правилах цены; остальным полям дефолт не выдумываем.
- Зачем: бэкенд сопоставляет правило по значению поля. Пока значение `null`, правило `when` не разрешается и `/estimate` берёт fallback-цену — в UI она расходится с выбранной настройкой (например, Kling 3.0 Omni 1080p: $0.47 вместо $0.63 из-за `audio:null`).

| id | поле | тип | новый дефолт | ключ правила |
|---|---|---|---|---|
| `bytedance/seedance-2-5-draft` | resolution | select | `1080p` | resolution |
| `gemini-omni-video` | duration | select | `4` | duration |
| `google/gemini-omni-flash-1-1` | duration | select | `4` | duration |
| `hailuo/02-image-to-video-standard` | resolution | select | `512P` | resolution |
| `hailuo/2-3-image-to-video-pro` | duration | select | `6` | duration |
| `hailuo/2-3-image-to-video-pro` | resolution | select | `768P` | resolution |
| `hailuo/2-3-image-to-video-standard` | duration | select | `6` | duration |
| `hailuo/2-3-image-to-video-standard` | resolution | select | `768P` | resolution |
| `kling/v2-1-master-text-to-video` | duration | select | `5` | duration |
| `kling/v2-1-master-image-to-video` | duration | select | `5` | duration |
| `kling/v2-1-pro` | duration | select | `5` | duration |
| `kling/v2-1-standard` | duration | select | `5` | duration |
| `kling/v2-5-turbo-text-to-video-pro` | duration | select | `5` | duration |
| `kling/v2-5-turbo-image-to-video-pro` | duration | select | `5` | duration |
| `kling-2.6/image-to-video` | duration | select | `5` | duration |
| `kling-2.6/image-to-video` | sound | toggle | false | sound |
| `kling-2.6/motion-control` | mode | select | `720p` | resolution |
| `kling-3.0/video` | mode | select | `std` | resolution |
| `kling-3.0/video` | sound | toggle | false | sound |
| `kling-3.0-omni/image-to-video` | audio | toggle | false | sound |
| `kling-3.0-omni/reference-to-video` | audio | toggle | false | sound |
| `pixverse-v6/text-to-video` | quality | select | `360p` | resolution |
| `pixverse-v6/image-to-video` | quality | select | `360p` | resolution |
| `pixverse-v6-max/text-to-video` | quality | select | `360p` | resolution |
| `pixverse-v6-max/image-to-video` | quality | select | `360p` | resolution |
| `pixverse-v6/transition` | quality | select | `360p` | resolution |
| `pixverse-v6/extend` | quality | select | `360p` | resolution |
| `pixverse-v6/extend` | generate_audio_switch | toggle | false | sound |
| `pixverse-v6/reference-to-video` | quality | select | `360p` | resolution |
| `wan/2-5-text-to-video` | resolution | select | `720p` | resolution |
| `wan/2-5-image-to-video` | resolution | select | `720p` | resolution |
| `wan/2-6-text-to-video` | resolution | select | `720p` | resolution |
| `wan/2-6-video-to-video` | resolution | select | `720p` | resolution |
| `wan/2-6-flash-image-to-video` | audio | toggle | false | sound |
| `wan/2-6-flash-video-to-video` | audio | toggle | false | sound |
| `flux-2/pro-text-to-image` | resolution | select | `1K` | resolution |
| `flux-2/pro-image-to-image` | resolution | select | `1K` | resolution |
| `flux-2/flex-text-to-image` | resolution | select | `1K` | resolution |
| `flux-2/flex-image-to-image` | resolution | select | `1K` | resolution |
| `ideogram/v3-text-to-image` | rendering_speed | select | `TURBO` | mode |
| `gpt-image/1.5-text-to-image` | quality | select | `medium` | mode |
| `gpt-image/1.5-image-to-image` | quality | select | `medium` | mode |
| `gpt-image-2-text-to-image` | resolution | select | `1K` | resolution |
| `gpt-image-2-image-to-image` | resolution | select | `1K` | resolution |
| `gpt-image-2-5-flare-text-to-image` | resolution | select | `1K` | resolution |
| `gpt-image-2-5-flare-image-to-image` | resolution | select | `1K` | resolution |
| `gpt-image-2-5-sunburst-text-to-image` | resolution | select | `1K` | resolution |
| `gpt-image-2-5-sunburst-image-to-image` | resolution | select | `1K` | resolution |
| `qwen3/text-to-image` | resolution | select | `1K` | resolution |
| `qwen3/pro-text-to-image` | resolution | select | `1K` | resolution |

## 3. Семейства по брендам — видео

| Бренд | Семейство | Режимов | id | Режимы (kie_id) | Цена |
|---|---|---|---|---|---|
| Kling | **Kling 2.1** (`kling-2-1`) | 4 | 4 | Master: текст → видео (`kling/v2-1-master-text-to-video`), Master: картинка → видео (`kling/v2-1-master-image-to-video`), Pro: картинка → видео (`kling/v2-1-pro`), Standard: картинка → видео (`kling/v2-1-standard`) | 252–504 кр/gen, 88–176 кр/gen, 50.5–101 кр/gen |
|  | **Kling 2.5 Turbo** (`kling-2-5-turbo`) | 2 | 2 | Текст → видео (Pro) (`kling/v2-5-turbo-text-to-video-pro`), Картинка → видео (Pro) (`kling/v2-5-turbo-image-to-video-pro`) | 63–126 кр/gen |
|  | **Kling 2.6** (`kling-2-6`) | 3 | 3 | Текст → видео (`kling-2.6/text-to-video`), Картинка → видео (`kling-2.6/image-to-video`), Motion Control (`kling-2.6/motion-control`) | 63–252 кр/gen, 12.6–20.2 кр/sec |
|  | **Kling 3.0** (`kling-3-0`) | 8 | 8 | Видео (Pro / Standard / 4K) (`kling-3.0/video`), Motion Control (`kling-3.0/motion-control`), Omni: текст → видео (`kling-3.0-omni/text-to-video`), Omni: картинка → видео (`kling-3.0-omni/image-to-video`), Omni: референс → видео (`kling-3.0-omni/reference-to-video`), Omni: трансформация (`kling-3.0-omni/transformation`), Turbo: текст → видео (`kling/v3-turbo-text-to-video`), Turbo: картинка → видео (`kling/v3-turbo-image-to-video`) | 15.1–75.5 кр/sec, 22.7–30.2 кр/sec, 22.7–75.5 кр/sec, 20.2–25.2 кр/sec |
|  | **Kling 4.0** (`kling-4-0`) | 4 | 4 | Ключевые кадры → видео (`kling-4.0/keyframe-to-video`), Flash: ключевые кадры → видео (`kling-4.0/flash-keyframe-to-video`), Референс → видео (`kling-4.0/reference-to-video`), Flash: референс → видео (`kling-4.0/flash-reference-to-video`) | 28.5–42.5 кр/sec, 17 кр/sec, 17–42.5 кр/sec, 11.3–17 кр/sec |
|  | **Kling AI Avatar** (`kling-avatar`) | 2 | 2 | Аватар (Pro) (`kling/ai-avatar-pro`), Аватар (Standard) (`kling/ai-avatar-standard`) | 10.1–20.2 кр/sec |
| Wan | **WAN 2.2 A14B** (`wan-2-2`) | 3 | 3 | Текст → видео (Turbo) (`wan/2-2-a14b-text-to-video-turbo`), Картинка → видео (Turbo) (`wan/2-2-a14b-image-to-video-turbo`), Речь → видео (Turbo) (`wan/2-2-a14b-speech-to-video-turbo`) | 8–16 кр/sec, 12–24 кр/sec |
|  | **WAN 2.2 Animate** (`wan-2-2-animate`) | 2 | 2 | Перенос движения (`wan/2-2-animate-move`), Замена персонажа (`wan/2-2-animate-replace`) | 12.5 кр/sec, 6–12.5 кр/sec |
|  | **WAN 2.5** (`wan-2-5`) | 2 | 2 | Текст → видео (`wan/2-5-text-to-video`), Картинка → видео (`wan/2-5-image-to-video`) | 12–20 кр/sec |
|  | **WAN 2.6** (`wan-2-6`) | 5 | 5 | Текст → видео (`wan/2-6-text-to-video`), Картинка → видео (`wan/2-6-image-to-video`), Видео → видео (`wan/2-6-video-to-video`), Flash: картинка → видео (`wan/2-6-flash-image-to-video`), Flash: видео → видео (`wan/2-6-flash-video-to-video`) | 70–315 кр/gen, 20–180 кр/gen, 20–120 кр/gen |
|  | **WAN 2.7** (`wan-2-7`) | 4 | 4 | Текст → видео (`wan/2-7-text-to-video`), Картинка → видео (`wan/2-7-image-to-video`), Референс → видео (`wan/2-7-r2v`), Редактирование видео (`wan/2-7-videoedit`) | 16–24 кр/sec |
|  | **WAN 3.0** (`wan-3-0`) | 2 | 2 | Видео (текст / картинка / видео) (`wan/3-0-video`), Видео Prime (`wan/3-0-video-prime`) | 8–32 кр/sec, 12.2–50.4 кр/sec |
| ByteDance | **Seedance 2.0** (`seedance-2-0`) | 3 | 3 | Стандарт (текст / картинка / видео) (`bytedance/seedance-2`), Fast (`bytedance/seedance-2-fast`), Mini (`bytedance/seedance-2-mini`) | 11.5–208 кр/sec, 6.8–24.8 кр/sec, 2.4–8.2 кр/sec |
|  | **Seedance 2.5** (`seedance-2-5`) | 2 | 2 | Стандарт (текст / картинка / видео) (`bytedance/seedance-2-5`), Draft (черновик) (`bytedance/seedance-2-5-draft`) | 17–158 кр/sec |
|  | **Seedance 1.0** (`seedance-1-0`) | 5 | 5 | Pro: текст → видео (`bytedance/v1-pro-text-to-video`), Pro: картинка → видео (`bytedance/v1-pro-image-to-video`), Pro Fast: картинка → видео (`bytedance/v1-pro-fast-image-to-video`), Lite: текст → видео (`bytedance/v1-lite-text-to-video`), Lite: картинка → видео (`bytedance/v1-lite-image-to-video`) | 2.8–14 кр/sec, 16–72 кр/gen, 2–10 кр/sec |
|  | **Seedance 1.5** (`seedance-1-5`) | 1 | 1 | Pro (текст / картинка) (`bytedance/seedance-1.5-pro`) | 1.75–15 кр/sec |
| Google | **Veo 3.1** (`veo-3-1`) | 4 | 4 | Генерация (Lite / Fast / Quality) (`veo-3-1`), Продление видео (`veo/extend`), Апскейл до 1080p (`veo/get-1080p-video`), Апскейл до 4K (`veo/get-4k-video`) | 30–370 кр/gen, 30–250 кр/gen, 5 кр/gen, 120 кр/gen |
|  | **Gemini Omni** (`gemini-omni`) | 2 | 2 | Видео (текст / картинка) (`gemini-omni-video`), Персонаж (`gemini-omni-character`) | 63–252 кр/gen |
|  | **Gemini Omni Flash 1.1** (`gemini-omni-flash-1-1`) | 1 | 1 | Видео (текст / картинка / видео) (`google/gemini-omni-flash-1-1`) | 63–252 кр/gen |
|  | **Gemini Omni Flash 1.2** (`gemini-omni-flash-1-2`) | 2 | 2 | Видео (текст / картинка / видео) (`google/gemini-omni-flash-1-2`), Продление видео (`google/gemini-omni-flash-1-2-extend`) | 4–22 кр/sec, 4–9 кр/sec |
| Hailuo | **Hailuo 02** (`hailuo-02`) | 4 | 4 | Текст → видео (Pro) (`hailuo/02-text-to-video-pro`), Текст → видео (Standard) (`hailuo/02-text-to-video-standard`), Картинка → видео (Pro) (`hailuo/02-image-to-video-pro`), Картинка → видео (Standard) (`hailuo/02-image-to-video-standard`) | 9.5 кр/sec, 5 кр/sec, 2–5 кр/sec |
|  | **Hailuo 2.3** (`hailuo-2-3`) | 2 | 2 | Картинка → видео (Pro) (`hailuo/2-3-image-to-video-pro`), Картинка → видео (Standard) (`hailuo/2-3-image-to-video-standard`) | 30–90 кр/gen |
|  | **MiniMax H3 (видео)** (`minimax-h3`) | 3 | 3 | Текст → видео (`minimax-h3/text-to-video`), Картинка → видео (`minimax-h3/image-to-video`), Референс → видео (`minimax-h3/reference-to-video`) | 8–13 кр/sec |
| Alibaba | **HappyHorse 1.1** (`happyhorse-1-1`) | 3 | 3 | Текст → видео (`happyhorse-1-1/text-to-video`), Картинка → видео (`happyhorse-1-1/image-to-video`), Референс → видео (`happyhorse-1-1/reference-to-video`) | 22.5–29 кр/sec |
|  | **HappyHorse** (`happyhorse`) | 4 | 4 | Текст → видео (`happyhorse/text-to-video`), Картинка → видео (`happyhorse/image-to-video`), Референс → видео (`happyhorse/reference-to-video`), Редактирование видео (`happyhorse/video-edit`) | 28–48 кр/sec |
| Grok | **Grok Imagine Video** (`grok-imagine-video`) | 4 | 4 | Текст → видео (`grok-imagine/text-to-video`), Картинка → видео (`grok-imagine/image-to-video`), Продление видео (`grok-imagine/extend`), Апскейл (`grok-imagine/upscale`) | 2.4–8 кр/sec, 14.4–45 кр/gen, 10–30 кр/gen |
|  | **Grok Imagine Video 1.5 (preview)** (`grok-imagine-video-1-5`) | 1 | 1 | Картинка → видео (`grok-imagine-video-1-5-preview`) | 2.4–8 кр/sec |
| OmniHuman | **OmniHuman 1.5** (`omnihuman-1-5`) | 1 | 1 | Оживление фото (`omnihuman-1-5`) | 27 кр/sec |
|  | **OmniHuman 2.0** (`omnihuman-2-0`) | 1 | 1 | Оживление фото (`omnihuman-2-0`) | 14 кр/sec |
| Infinitalk | **Infinitalk (липсинк по аудио)** (`infinitalk`) | 1 | 1 | Аудио → видео (`infinitalk/from-audio`) | 3–12 кр/sec |
| Kie | **Kie — апскейл видео** (`kie-video-upscale`) | 1 | 1 | Апскейл видео (`video/upscale`) | 1.5–6 кр/sec |
| Pixverse | **PixVerse V6** (`pixverse-v6`) | 7 | 7 | Текст → видео (`pixverse-v6/text-to-video`), Картинка → видео (`pixverse-v6/image-to-video`), Текст → видео (Max) (`pixverse-v6-max/text-to-video`), Картинка → видео (Max) (`pixverse-v6-max/image-to-video`), Первый + последний кадр (`pixverse-v6/transition`), Продление видео (`pixverse-v6/extend`), Референс → видео (Fusion) (`pixverse-v6/reference-to-video`) | 4–18.4 кр/sec, 4.8–22.4 кр/sec |
| Runway | **Runway** (`runway`) | 2 | 2 | Генерация (текст / картинка) (`runway`), Продление видео (`runway/extend-ai-video`) | 12–30 кр/gen |
| Suno | **Suno — музыкальный клип** (`suno-music-video`) | 1 | 1 | Аудио → клип (`ai-music-api/create-music-video`) | 2 кр/gen |
| Topaz | **Topaz Video Upscale** (`topaz-video-upscale`) | 1 | 1 | Апскейл видео (`topaz/video-upscale`) | 8–14 кр/sec |
| Vidu | **Vidu Q4** (`vidu-q4`) | 2 | 2 | Картинка → видео (`vidu-q4/image-to-video`), Референс → видео (`vidu-q4/reference-to-video`) | 7.2–62.4 кр/sec |
| Volcengine | **Volcengine Lip Sync** (`volcengine-lipsync`) | 1 | 1 | Липсинк по видео (`volcengine/video-to-video-lip-sync`) | 8 кр/sec |

## 4. Семейства по брендам — картинки

| Бренд | Семейство | Режимов | id | Режимы (kie_id) | Цена |
|---|---|---|---|---|---|
| Google | **Imagen 4** (`imagen-4`) | 3 | 3 | Текст → картинка (`google/imagen4`), Fast (`google/imagen4-fast`), Ultra (`google/imagen4-ultra`) | 8 кр/image, 4 кр/image, 12 кр/image |
|  | **Nano Banana** (`nano-banana`) | 2 | 2 | Текст → картинка (`google/nano-banana`), Редактирование (`google/nano-banana-edit`) | 4 кр/image |
|  | **Nano Banana 2** (`nano-banana-2`) | 1 | 1 | Текст / картинка → картинка (`nano-banana-2`) | 8–18 кр/image |
|  | **Nano Banana 2.1** (`nano-banana-2-1`) | 1 | 1 | Текст / картинка → картинка (`nano-banana-2-1`) | 4–9 кр/image |
|  | **Nano Banana 2 Lite** (`nano-banana-2-lite`) | 1 | 1 | Текст / картинка → картинка (`nano-banana-2-lite`) | 4 кр/image |
|  | **Nano Banana Pro** (`nano-banana-pro`) | 1 | 1 | Текст / картинка → картинка (`nano-banana-pro`) | 18–24 кр/image |
| ByteDance | **Seedream 3** (`seedream-3`) | 1 | 1 | Текст → картинка (`bytedance/seedream`) | 3.5 кр/image |
|  | **Seedream 4.0** (`seedream-4-0`) | 2 | 2 | Текст → картинка (`bytedance/seedream-v4-text-to-image`), Редактирование (`bytedance/seedream-v4-edit`) | 5 кр/image |
|  | **Seedream 4.5** (`seedream-4-5`) | 2 | 2 | Текст → картинка (`seedream/4.5-text-to-image`), Редактирование (`seedream/4.5-edit`) | 6.5 кр/image |
|  | **Seedream 5** (`seedream-5`) | 8 | 8 | Pro: текст → картинка (`seedream/5-pro-text-to-image`), Pro: картинка → картинка (`seedream/5-pro-image-to-image`), Pro: разбор по слоям (`seedream/5-pro-layer-decomposition`), Flash: текст → картинка (`seedream/5-flash-text-to-image`), Flash: картинка → картинка (`seedream/5-flash-image-to-image`), Flash: разбор по слоям (`seedream/5-flash-layer-decomposition`), Lite: текст → картинка (`seedream/5-lite-text-to-image`), Lite: картинка → картинка (`seedream/5-lite-image-to-image`) | 7–14 кр/image, 3.24 кр/image, 5.5 кр/image |
|  | **Seedream 5.5** (`seedream-5-5`) | 3 | 3 | Текст → картинка (`seedream/5-5-text-to-image`), Картинка → картинка (`seedream/5-5-image-to-image`), Разбор по слоям (`seedream/5-5-layer-decomposition`) | 3.6–6.3 кр/image |
| OpenAI | **GPT-4o Image** (`gpt-4o-image`) | 1 | 1 | Текст / картинка → картинка (`4o-image-api`) | 6 кр/image |
|  | **GPT Image 1.5** (`gpt-image-1-5`) | 2 | 2 | Текст → картинка (`gpt-image/1.5-text-to-image`), Картинка → картинка (`gpt-image/1.5-image-to-image`) | 4–22 кр/image |
|  | **GPT Image 2** (`gpt-image-2`) | 2 | 2 | Текст → картинка (`gpt-image-2-text-to-image`), Картинка → картинка (`gpt-image-2-image-to-image`) | 6–16 кр/image |
|  | **GPT Image 2.5** (`gpt-image-2-5`) | 4 | 4 | Flare: текст → картинка (`gpt-image-2-5-flare-text-to-image`), Flare: картинка → картинка (`gpt-image-2-5-flare-image-to-image`), Sunburst: текст → картинка (`gpt-image-2-5-sunburst-text-to-image`), Sunburst: картинка → картинка (`gpt-image-2-5-sunburst-image-to-image`) | 6–16 кр/image |
|  | **GPT Image 2.6** (`gpt-image-2-6`) | 6 | 6 | Economy: текст → картинка (`gpt-image-2-6/economy-text-to-image`), Economy: картинка → картинка (`gpt-image-2-6/economy-image-to-image`), Flare: текст → картинка (`gpt-image-2-6/flare-text-to-image`), Flare: картинка → картинка (`gpt-image-2-6/flare-image-to-image`), Sunburst: текст → картинка (`gpt-image-2-6/sunburst-text-to-image`), Sunburst: картинка → картинка (`gpt-image-2-6/sunburst-image-to-image`) | 5 кр/image, 225–5400 кр/1m_tokens |
| Qwen | **Qwen Image** (`qwen-image`) | 3 | 3 | Текст → картинка (`qwen/text-to-image`), Картинка → картинка (`qwen/image-to-image`), Редактирование (`qwen/image-edit`) | 4 кр/mp, 4 кр/image, 6 кр/mp |
|  | **Qwen2 Image** (`qwen2-image`) | 2 | 2 | Текст → картинка (`qwen2/text-to-image`), Редактирование (`qwen2/image-edit`) | 6 кр/image |
|  | **Qwen 2.1 Image** (`qwen2-1-image`) | 2 | 2 | Текст → картинка (`qwen2-1/text-to-image`), Картинка → картинка (`qwen2-1/image-to-image`) | 4–8 кр/image |
|  | **Qwen3 Image** (`qwen3-image`) | 4 | 4 | Текст → картинка (`qwen3/text-to-image`), Картинка → картинка (`qwen3/image-to-image`), Pro: текст → картинка (`qwen3/pro-text-to-image`), Pro: картинка → картинка (`qwen3/pro-image-to-image`) | 4.8 кр/image, 6.4–12 кр/image |
| Black Forest Labs | **Flux 2** (`flux-2`) | 4 | 4 | Pro: текст → картинка (`flux-2/pro-text-to-image`), Pro: картинка → картинка (`flux-2/pro-image-to-image`), Flex: текст → картинка (`flux-2/flex-text-to-image`), Flex: картинка → картинка (`flux-2/flex-image-to-image`) | 5–7 кр/image, 14–24 кр/image |
|  | **Flux 3** (`flux-3`) | 2 | 2 | Klein: текст → картинка (`flux-3/klein-text-to-image`), Klein: редактирование (`flux-3/klein-edit-image`) | 1.6–6.5 кр/image |
|  | **Flux Kontext** (`flux-1-kontext`) | 1 | 1 | Редактирование по тексту (`flux1-kontext`) | 5–10 кр/image |
| Grok | **Grok Imagine Image** (`grok-imagine-image`) | 2 | 2 | Текст → картинка (`grok-imagine/text-to-image`), Картинка → картинка (`grok-imagine/image-to-image`) | 4–5 кр/gen, 4 кр/image |
|  | **Grok Imagine Image 2.0** (`grok-imagine-image-2-0`) | 4 | 4 | Текст → картинка (`grok-imagine-image-2-0/text-to-image`), Редактирование (`grok-imagine-image-2-0/image-edit`), Правка сегментов (`grok-imagine-image-2-0/segment-edit`), Карта сегментов (`grok-imagine-image-2-0/segment-map`) | 4 кр/image, 0 кр/image |
| Ideogram | **Ideogram Character** (`ideogram-character`) | 3 | 3 | Персонаж (`ideogram/character`), Персонаж: редактирование (`ideogram/character-edit`), Персонаж: ремикс (`ideogram/character-remix`) | 12–24 кр/image |
|  | **Ideogram V3** (`ideogram-v3`) | 3 | 3 | Текст → картинка (`ideogram/v3-text-to-image`), Редактирование (`ideogram/v3-edit`), Ремикс (`ideogram/v3-remix`) | 3.5–10 кр/image |
| Hailuo | **MiniMax H3 (картинки)** (`minimax-h3-image`) | 2 | 2 | Текст → картинка (`minimax-h3/text-to-image`), Редактирование (`minimax-h3/image-edit`) | 1.8–5.5 кр/image |
| Kie | **Kie — апскейл картинки** (`kie-image-upscale`) | 1 | 1 | Апскейл картинки (`kie/image-upscale`) | 1.5–12 кр/image |
| OmniHuman | **OmniHuman 1.5 — разметка** (`omnihuman-1-5-image`) | 2 | 2 | Поиск человека (`omnihuman-1-5/human-identification`), Детекция объектов (`omnihuman-1-5/subject-detection`) | цена не указана |
| Recraft | **Recraft** (`recraft`) | 2 | 2 | Апскейл (Crisp) (`recraft/crisp-upscale`), Удаление фона (`recraft/remove-background`) | 0.5 кр/image, 1 кр/image |
| Suno | **Suno — обложка трека** (`suno-cover`) | 1 | 1 | Текст → обложка (`ai-music-api/cover-generate`) | 0 кр/image |
| Tongyi (Z-Image) | **Z-Image Turbo** (`z-image`) | 1 | 1 | Текст → картинка (`z-image`) | 0.8 кр/image |
| Topaz | **Topaz Image Upscale** (`topaz-image-upscale`) | 1 | 1 | Апскейл картинки (`topaz/image-upscale`) | 10–20 кр/image |
| Wan | **WAN 2.7 Image** (`wan-2-7-image`) | 2 | 2 | Текст / картинка → картинка (`wan/2-7-image`), Pro: текст / картинка → картинка (`wan/2-7-image-pro`) | 4.8 кр/image, 12 кр/image |

## 5. Правила слияния и спорные случаи

- Семейство = бренд + поколение в базовом названии. Служебные суффиксы и тиры (`Pro`, `Standard`, `Fast`, `Lite`, `Mini`, `Draft`, `Turbo`, `Omni`, `Flash`, `Max`, `Master`, `Economy`, `Flare`, `Sunburst`, `Klein`, `Flex`, `Prime`) — режимы одного семейства.
- Тип входа (`Text to Video`, `Image to Video`, `Reference to Video`, `Video to Video`, `Image to Image`, `Image Editing`) — всегда режим внутри семейства, а не отдельная карточка.
- Утилиты того же эндпоинта (`Extend`, `upscale`, `get-1080p/4k`, `Video Edit`, `Motion Control`, `Transformation`, `Layer Decomposition`, `Remove Background`) — режимы семейства.
- Разные поколения не слиты: Kling 2.1 / 2.5 Turbo / 2.6 / 3.0 / 4.0 — разные семейства; Seedream 3 / 4.0 / 4.5 / 5 / 5.5 — разные; WAN 2.2 / 2.5 / 2.6 / 2.7 / 3.0 — разные.

Спорные слияния, где правило допускало два прочтения:

| Случай | Как решено | Почему |
|---|---|---|
| `kling-3.0/video`, `kling-3.0/motion-control`, `kling-3.0-omni/*`, `kling/v3-turbo-*` | одно семейство **Kling 3.0**, 8 режимов | прямая формулировка мастер-задачи: «Kling 3.0 Pro/Turbo/Omni — режимы одного семейства 3.0» |
| `gemini-omni-video`, `gemini-omni-character` | семейство **Gemini Omni** | одна генерация без тира; `character` — отдельный вход (персонаж), а не другое поколение |
| `google/gemini-omni-flash-1-1` и `...-1-2` (+`-extend`) | два семейства | разные поколения (1.1 и 1.2), как Kling 2.6 vs 3.0; `extend` — режим поколения 1.2 |
| `pixverse-v6-max/*` | режимы **PixVerse V6** (`t2v-max`, `i2v-max`) | `Max` — тир качества того же поколения, своего поколения/эндпоинта нет |
| `grok-imagine-video-1-5-preview` | отдельное семейство | версия 1.5 против базового Grok Imagine |
| `wan/2-2-animate-*` | отдельное семейство **WAN 2.2 Animate** | своя механика (перенос движения / замена персонажа) и своя схема, хотя поколение то же |
| `kling/v2-5-turbo-*` | отдельное семейство **Kling 2.5 Turbo** | отдельная линейка поколения 2.5, а не тир Kling 2.6 |
| `kling/ai-avatar-*` | семейство **Kling AI Avatar** | отдельный продукт-аватар, не режим 3.0 |
| `topaz/video-upscale` / `topaz/image-upscale`, `video/upscale` / `kie/image-upscale`, `veo/get-1080p/4k` | отдельные утилитные семейства / режимы Veo | у Topaz и Kie нет «поколения», у Veo апскейл — режим Veo 3.1 |
| `ideogram/v3-text-to-image` | режим семейства **Ideogram V3** (картинки) | kie.ai отдаёт taskType `Text to Video`, но id, схема и прайс — картинка; ошибка метаданных kie.ai |
| `bytedance/seedance-1.5-pro` | семейство **Seedance 1.5**, режим помечен `in_live_api: false` | id есть в каталоге студии, но маркет его не отдаёт — сохранён как есть, чтобы не потерять |
| `ai-music-api/create-music-video`, `ai-music-api/cover-generate` | семейства Suno (видео / обложка) | лежат в `/api/v1/models` как медиа, бренд Suno |
| `omnihuman-1-5/human-identification`, `subject-detection` | семейство **OmniHuman 1.5 — разметка** | это утилиты разметки картинки, не генерация видео |

Полное сопоставление id → семейство/режим — в `docs/kie-model-families.json` (`families[].modes[].kie_id`).

## 6. Чего нет в источниках

1. **Нет OpenAPI-схемы** у 7 режимов: страница модели не разобрана в docs.kie.ai. У 7 из них поля взяты из кода каталога студии, у остальных 0 — `fields_known: false` (схема неизвестна). Схемы догружаются скриптом `docs/fetch_kie_docs_extra.py` в `docs/kie-ai-raw/docs-schemas-extra.json` (31 страница 14.11.2026), чтобы не держать «мёртвые» поля из карточки семейства.
2. **Нет цены** (пустой `pricingDesc` или цена в токенах) — режимы без правил цены перечислены в сверке 3; при этом сами id и режимы сохранены.
3. **Связи «параметр → множитель цены» в доках нет.** Правила `pricing.rules` берутся из `docs/kie-prices-usd.json` (там они восстановлены из текста `pricingDesc` эвристикой: разрешение / длительность / звук / наличие видео на входе / тир). Единица, набор правил и дефолт выровнены по прайсу; исходный текст `pricingDesc` остался в `note`/`source_text`.
4. **Единицы цены шире двух базовых** (`sec` / `gen`): у 72 картинных режимов `image` (прайс считает за картинку), у 4 режимов GPT Image 2.6 — `1m_tokens`, у 2 режимов Qwen Image — `mp` (за мегапиксель), у 4 режимов цены нет (`unknown`). Для `1m_tokens`/`mp` кредиты за генерацию не считаются — единица и правила как в прайсе, без подмены оценкой.
5. **Точные эндпоинты** известны только для `jobs` / `veo` / `runway` / `suno`; у режимов без разобранной страницы `api` проставлен по умолчанию (`jobs`), это допущение, а не факт из доков.
6. **Фактических списаний нет** — цены из прайса, не из истории генераций.
7. **Названия брендов** взяты из колонки CSV (`Alibaba`, `Hailuo`, `Pixverse`, `Kie`, `Tongyi (Z-Image)` и т.п.); в `/api/v1/models` бренд местами другой (`Other`), поэтому бренд семейства — из CSV, provider API — в `meta`.
8. **Формат `pricing.when`** — не контракт kie.ai, а наша реконструкция: спец-ключи `sound` (звук вкл/выкл), `with_video` (есть видео на входе), `mode` (тир), `resolution`, `duration`, `max_mp`. Шаг 8 должен читать их как «условия первого совпадения».
9. **Описаний нет у части семейств**: у 19 из 72 в `/api/v1/models` пустой `description` и нет осмысленного `title`, в CSV колонка «описание модели» тоже пустая — стоит `desc: «описания в источниках нет»`. Это не мешает меню: `label` и режимы на месте.
10. **`ideogram/v3-edit`: поле `mask_url`** есть в OpenAPI-схеме docs.kie.ai и в каталоге студии; в families.json оно тоже есть (`required: true` в схеме). Если UI его не показывает, теряется не в данных — смотреть бэкенд/UI.

## 7. Структура JSON

```
{
  "meta": {"generated_at", "source_api", "source_docs", "source_table", "source_catalog",
           "source_prices", "catalog_git_blob_sha", "credit_usd", "counts", "checks"},
  "families": [
    {"id", "label", "brand", "media": "video|image", "desc",
     "modes": [{"id", "label", "kie_id", "task_type", "api", "endpoint",
                "fields": [{"name","label","kind","required","default",
                            "options","min","max","max_items","hint"}],
                "fields_known": true/false, "fields_source", "in_live_api",
                "pricing": {"unit","rules":[{"when","credits","usd_kie","usd_client"}],
                            "default","note","formula","affects_price","pricing_source",
                            "credit_usd","source_text"},
                "constraints", "docs_url"}]}
  ]
}
```

`kind` полей: `text`, `textarea`, `select`, `number`, `toggle`, `images`, `videos`, `audios`, `json` (вложенный объект — расширение сверх контракта, помечено `fields_source`). Результаты трёх сверок машинно — в `docs/kie-model-families-checks.json`.

## 8. Как пересобрать

```
python docs/fetch_kie_docs_extra.py   # догрузить схемы недостающих страниц docs.kie.ai
python docs/build_kie_families.py     # пишет json + md + checks
python docs/validate_kie_families.py  # независимая проверка записанного json
```
