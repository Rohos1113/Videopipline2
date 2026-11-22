# -*- coding: utf-8 -*-
"""Обложки каталога «406 стилей»: PNG 1536×1024 → webp 448×299 в web/public/gen-styles/fisher.

Источник PNG: папка fisher-images-additional на рабочем столе (имя файла начинается с номера стиля).
Список стилей берётся из _fisher_work/fisher-styles.json (его пишет build_fisher_style_catalog.py).

Запуск:
  python scripts/make_fisher_style_covers.py [--force]
      обычные обложки: 448×299, quality 70, в web/public/gen-styles/fisher/<id>.webp

  python scripts/make_fisher_style_covers.py --big [--force] [--quality N]
      HQ-обложки для всплывающего просмотра: 896×597, quality 78, method 6,
      в web/public/gen-styles/fisher/big/<id>.webp (те же имена, что у обычных).
      78 вместо 82 — по весу: 82 даёт 41.6 MB на 406 файлов, 78 — 35.8 MB.
      --quality N перекрывает quality по умолчанию (для обоих режимов).
"""
from __future__ import annotations

import json
import os
import re
import sys

from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC_DIR = r"C:\Users\Admin\Desktop\fisher-images-additional"
STYLES_JSON = os.path.join(ROOT, "_fisher_work", "fisher-styles.json")
OUT_DIR = os.path.join(ROOT, "web", "public", "gen-styles", "fisher")
WIDTH = 448
QUALITY = 70
BIG_DIR = "big"
BIG_WIDTH = 896
BIG_QUALITY = 78


def png_by_num() -> dict[int, str]:
    out: dict[int, str] = {}
    for name in os.listdir(SRC_DIR):
        if not name.lower().endswith('.png'):
            continue
        m = re.match(r'^(\d+)-', name)
        if not m:
            continue
        out.setdefault(int(m.group(1)), os.path.join(SRC_DIR, name))
    return out


def main() -> None:
    force = '--force' in sys.argv
    big = '--big' in sys.argv
    width = BIG_WIDTH if big else WIDTH
    quality = BIG_QUALITY if big else QUALITY
    if '--quality' in sys.argv:
        quality = int(sys.argv[sys.argv.index('--quality') + 1])
    out_dir = os.path.join(OUT_DIR, BIG_DIR) if big else OUT_DIR
    styles = json.load(open(STYLES_JSON, encoding='utf-8'))
    pngs = png_by_num()
    os.makedirs(out_dir, exist_ok=True)
    made = skipped = missing = 0
    total = 0.0
    for s in styles:
        num = int(s['num'])
        dst = os.path.join(out_dir, f"{s['id']}.webp")
        if os.path.isfile(dst) and not force:
            skipped += 1
            total += os.path.getsize(dst)
            continue
        src = pngs.get(num)
        if not src:
            print(f'нет PNG для стиля {num} ({s["name"]})')
            missing += 1
            continue
        with Image.open(src) as im:
            im = im.convert('RGB')
            w, h = im.size
            im = im.resize((width, max(1, round(h * width / w))), Image.LANCZOS)
            im.save(dst, 'WEBP', quality=quality, method=6)
        made += 1
        total += os.path.getsize(dst)
        if made % 50 == 0:
            print(f'  ... {made} готово', flush=True)
    mode = 'big ' if big else ''
    print(f'{mode}обложки {width}px q{quality}: сделано {made}, пропущено {skipped}, без PNG {missing}, '
          f'всего {total/1e6:.1f} MB → {os.path.relpath(out_dir, ROOT)}')


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    main()
