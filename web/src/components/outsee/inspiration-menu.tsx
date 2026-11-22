"use client";

/**
 * «Каталог стилей» — кнопка над вертикальными «Фото / Видео / Аудио» и каталог стилей
 * помощника. Механика окна выбора модели: слева категории картинками, в центре стили
 * выбранной категории. Правая колонка деталей убрана: превью открывается КЛИКОМ по
 * карточке рядом с ней (наведение на другую карточку переключает открытое окно).
 * Клик не выбирает стиль — выбор только кнопкой «Выбрать стиль» в окне.
 *
 * Панель и превью рендерятся порталом в document.body: раньше панель жила внутри дока
 * (z-10 внутри панели z-[80]) и её перекрывало текстом/оверлеем результата генерации.
 * Позиция панели считается по getBoundingClientRect кнопки-триггера, а не absolute bottom-full.
 *
 * Выбранный стиль пишется в те же ключи localStorage, что и панель помощника,
 * и дописывается к промпту фото при генерации.
 */

import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode, type RefObject } from "react";
import { createPortal } from "react-dom";
import { Check, Grid3x3, Library, List, Search, X } from "lucide-react";
import { toast } from "sonner";

import { GenStyleArt as GenStyleArtView } from "@/components/outsee/gen-style-art";
import {
  INSPIRATION_ART_PREFIX,
  INSPIRATION_CATEGORIES,
  INSPIRATION_LS_CATEGORY,
  INSPIRATION_LS_STYLE,
  INSPIRATION_STYLES,
  inspirationStyle,
  type GenStyleDef,
} from "@/lib/inspiration-styles";
import { cn } from "@/lib/utils";

/**
 * Габариты окна: слева категории, в центре стили. Карточки не уменьшаются:
 * та же ширина CARD_W, три в ряд — окно просто шире.
 */
const CAT_W = 235;
const CARD_W = 317;
const GRID_GAP = 8;
const GRID_W = CARD_W * 3 + GRID_GAP * 2;

const PANEL_MAX_H = 576;

/*
 * Слои (классы в разметке ниже):
 *   панель каталога — z-[120], превью — z-[124].
 * В outsee-create-workspace.tsx панель Create — z-[80], просмотр референса — z-[95],
 * док с кнопками — z-10 внутри панели. Каталог живёт порталом в body, поэтому выше
 * всех них, но ниже модалок (voice-library — z-[200], дропдауны — z-[1000]).
 * Превью выше панели: когда оно прижимается к левому краю карточки, то ложится на колонки.
 */

/** Окно превью: картинка ровно в 1.4 раза шире карточки (317 → 444, высота 296 при 3:2). */
const PREVIEW_W = Math.round(CARD_W * 1.4);
/** 0 — окно прилипает к краю картинки вплотную, как просил пользователь. */
const PREVIEW_GAP = 0;
/** Минимальный отступ от краёв экрана, чтобы окно не липло к границе вьюпорта. */
const VIEWPORT_EDGE = 8;
const PREVIEW_CLOSE_MS = 200;
/** Доля вьюпорта под прокручиваемое окно превью. */
const PREVIEW_MAX_H_RATIO = 0.72;

/** fisher-обложки лежат в /gen-styles/fisher/, HQ-версии — в /gen-styles/fisher/big/. */
const FISHER_COVER_DIR = "/gen-styles/fisher/";

/** Как показывать стили: по одному в ряд (как было) или сеткой по три. */
type StyleView = "list" | "grid";

/** Рамка превью: уже готовые координаты, window читаем только в обработчиках (SSR). */
type PreviewBox = { left: number; top: number; width: number; maxHeight: number };
type HoverState = { id: string; box: PreviewBox };
type PanelBox = { left: number; top: number; width: number; height: number };

/** Категория выбранного стиля — чтобы окно открывалось на нужном месте. */
function positiveCatFor(styleId: string): string | null {
  if (!styleId) return null;
  const cat = INSPIRATION_CATEGORIES.find((c) => c.styles.some((s) => s.id === styleId));
  return cat?.id ?? null;
}

/** Обложки, которые пользователь уже сгенерировал в помощнике (genAssistant.styleArt.<id>). */
function readArtUrls(): Record<string, string> {
  const out: Record<string, string> = {};
  if (typeof window === "undefined") return out;
  try {
    for (let i = 0; i < window.localStorage.length; i += 1) {
      const key = window.localStorage.key(i);
      if (!key || !key.startsWith(INSPIRATION_ART_PREFIX)) continue;
      const value = window.localStorage.getItem(key);
      if (value) out[key.slice(INSPIRATION_ART_PREFIX.length)] = value;
    }
  } catch {
    /* приватный режим — просто без обложек */
  }
  return out;
}

/**
 * HQ-обложка для превью: у fisher-стилей HQ-версии лежат рядом, в /fisher/big/
 * (тот же файл, ширины хватает на окно 444 px). У core-стилей путь другой
 * (/gen-styles/<name>.webp) и HQ-копий нет — для них остаётся обычная обложка.
 */
function hqCoverUrl(cover?: string): string | undefined {
  if (!cover || !cover.startsWith(FISHER_COVER_DIR)) return undefined;
  return cover.replace(FISHER_COVER_DIR, `${FISHER_COVER_DIR}big/`);
}

/**
 * Что грузим в превью: сначала HQ (если есть), при ошибке — обычная обложка.
 * Пользовательская обложка из localStorage уже «как есть», её не подменяем.
 */
function previewCoverFor(
  style: GenStyleDef,
  artUrl?: string,
): { src?: string; fallback?: string } {
  const normal = artUrl ?? style.cover;
  if (!normal) return {};
  const big = artUrl ? undefined : hqCoverUrl(normal);
  return big ? { src: big, fallback: normal } : { src: normal };
}

/** Рамка окна превью: вплотную к правому краю карточки, иначе к левому; зажата во вьюпорт. */
function previewBoxFor(rect: DOMRect): PreviewBox {
  const vw = window.innerWidth;
  const vh = window.innerHeight;
  const width = PREVIEW_W;
  const maxHeight = Math.min(Math.round(vh * PREVIEW_MAX_H_RATIO), vh - VIEWPORT_EDGE * 2);

  let left = rect.right + PREVIEW_GAP;
  if (left + width > vw - VIEWPORT_EDGE) left = rect.left - PREVIEW_GAP - width;
  left = Math.min(Math.max(VIEWPORT_EDGE, left), Math.max(VIEWPORT_EDGE, vw - width - VIEWPORT_EDGE));

  const top = Math.min(
    Math.max(VIEWPORT_EDGE, rect.top),
    Math.max(VIEWPORT_EDGE, vh - maxHeight - VIEWPORT_EDGE),
  );

  return { left, top, width, maxHeight };
}

/** Картинка стиля: обложка, если есть, иначе SVG-эскиз в тон стиля. */
function StyleThumb({
  style,
  artUrl,
  className,
  children,
}: {
  style: GenStyleDef;
  artUrl?: string;
  className?: string;
  children?: ReactNode;
}) {
  const [broken, setBroken] = useState(false);
  const cover = !broken ? (artUrl ?? style.cover) : undefined;

  return (
    <div className={cn("relative overflow-hidden bg-[#16161c]", className)}>
      <div className="absolute inset-0 flex items-center justify-center">
        <div className="max-h-[78%] max-w-[78%] opacity-90">
          <GenStyleArtView art={style.art} color={style.color} />
        </div>
      </div>
      {cover ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img
          src={cover}
          alt=""
          className="absolute inset-0 h-full w-full object-cover"
          onError={() => setBroken(true)}
        />
      ) : null}
      {children}
    </div>
  );
}

/** Крупная картинка превью: HQ-версия с откатом на обычную обложку и на SVG-эскиз. */
function PreviewImage({ style, artUrl }: { style: GenStyleDef; artUrl?: string }) {
  const { src, fallback } = previewCoverFor(style, artUrl);
  const [current, setCurrent] = useState<string | undefined>(src);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    setCurrent(src);
    setFailed(false);
  }, [src]);

  return (
    <div className="relative aspect-[3/2] w-full shrink-0 overflow-hidden bg-[#0b0b0e]">
      <div className="absolute inset-0 flex items-center justify-center">
        <div className="max-h-[78%] max-w-[78%] opacity-70">
          <GenStyleArtView art={style.art} color={style.color} />
        </div>
      </div>
      {current && !failed ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img
          src={current}
          alt={style.name}
          className="absolute inset-0 h-full w-full object-cover"
          onError={() => {
            if (fallback && current !== fallback) setCurrent(fallback);
            else setFailed(true);
          }}
        />
      ) : null}
      <div className="pointer-events-none absolute inset-x-0 bottom-0 h-14 bg-gradient-to-t from-black/60 to-transparent" />
    </div>
  );
}

/**
 * Всплывающее окно стиля вплотную к карточке. Внутри одна прокрутка:
 * сверху картинка, ниже категория/название/описание/теги/промпт.
 */
function StylePreview({
  style,
  artUrl,
  categoryName,
  selected,
  box,
  previewRef,
  onEnter,
  onLeave,
  onPick,
}: {
  style: GenStyleDef;
  artUrl?: string;
  categoryName: string;
  selected: boolean;
  box: PreviewBox;
  previewRef: RefObject<HTMLDivElement | null>;
  onEnter: () => void;
  onLeave: () => void;
  onPick: () => void;
}) {
  return (
    <div
      ref={previewRef}
      data-testid="inspiration-detail"
      role="dialog"
      aria-label={`Превью стиля «${style.name}»`}
      style={{
        left: box.left,
        top: box.top,
        width: box.width,
        maxHeight: box.maxHeight,
      }}
      onMouseEnter={onEnter}
      onMouseLeave={onLeave}
      onPointerDown={(e) => e.stopPropagation()}
      className="fixed z-[124] flex flex-col overflow-y-auto overscroll-contain rounded-2xl border border-white/15 bg-[#121216]/98 shadow-[0_25px_70px_rgba(0,0,0,0.85)] ring-1 ring-white/10 backdrop-blur-2xl"
    >
      <PreviewImage style={style} artUrl={artUrl} />

      <div className="flex flex-col gap-1.5 p-3">
        <div className="flex items-center gap-1.5">
          <span className="rounded bg-[#2dd4bf]/15 px-1.5 py-0.5 text-[9.5px] font-semibold tracking-[0.08em] text-[#2dd4bf] uppercase">
            {categoryName || "Стиль"}
          </span>
          {selected ? (
            <span className="flex items-center gap-0.5 rounded bg-[#2dd4bf] px-1.5 py-0.5 text-[9.5px] font-bold text-black">
              <Check className="h-2.5 w-2.5" /> выбран
            </span>
          ) : null}
        </div>

        <div data-testid="inspiration-style-name" className="text-[14px] font-bold text-white">
          {style.name}
        </div>
        <div className="text-[11.5px] leading-relaxed text-white/65">{style.desc}</div>

        {style.tags?.length ? (
          <div className="flex flex-wrap gap-1">
            {style.tags.slice(0, 8).map((t) => (
              <span
                key={t}
                className="rounded bg-white/[0.06] px-1.5 py-0.5 text-[9.5px] text-white/55"
              >
                {t}
              </span>
            ))}
          </div>
        ) : null}

        <div className="mt-0.5 text-[9.5px] font-semibold tracking-[0.12em] text-white/35 uppercase">
          Промпт
        </div>
        <div
          data-testid="inspiration-style-prompt"
          className="rounded-lg border border-white/8 bg-black/30 p-2 text-[10.5px] leading-relaxed whitespace-pre-wrap text-white/70"
        >
          {style.promptCore}
        </div>

        {style.negativePrompt ? (
          <>
            <div className="mt-0.5 text-[9.5px] font-semibold tracking-[0.12em] text-white/35 uppercase">
              Негатив
            </div>
            <div className="rounded-lg border border-red-400/15 bg-black/30 p-2 text-[10.5px] leading-relaxed whitespace-pre-wrap text-white/55">
              {style.negativePrompt}
            </div>
          </>
        ) : null}

        <button
          type="button"
          data-testid="inspiration-apply"
          onClick={onPick}
          className={cn(
            "mt-1 flex shrink-0 items-center justify-center gap-1.5 rounded-xl px-3 py-2 text-[12px] font-bold transition",
            selected
              ? "bg-[#2dd4bf]/15 text-[#2dd4bf] ring-1 ring-[#2dd4bf]/50"
              : "bg-gradient-to-r from-[#2dd4bf] to-[#0d9488] text-black hover:brightness-110",
          )}
        >
          {selected ? (
            <>
              <Check className="h-3.5 w-3.5" /> Выбран
            </>
          ) : (
            "Выбрать стиль"
          )}
        </button>
      </div>
    </div>
  );
}

export function InspirationMenu({
  value,
  onChange,
  className,
}: {
  value: string;
  onChange: (id: string) => void;
  className?: string;
}) {
  const [open, setOpen] = useState(false);
  const [artUrls, setArtUrls] = useState<Record<string, string>>({});
  const [catId, setCatId] = useState<string>(INSPIRATION_CATEGORIES[0]?.id ?? "");
  /** Поиск по всем стилям: в категории их бывает много, глазами не найти. */
  const [query, setQuery] = useState("");
  /** Список (как раньше) или сетка по три в ряд — кнопки слева от крестика. */
  const [view, setView] = useState<StyleView>("list");
  /** Карточка под курсором и готовая рамка окна превью (позиция считается в обработчике). */
  const [hover, setHover] = useState<HoverState | null>(null);
  /** Координаты панели каталога — по getBoundingClientRect кнопки-триггера. */
  const [panelBox, setPanelBox] = useState<PanelBox | null>(null);

  const buttonRef = useRef<HTMLButtonElement | null>(null);
  const panelRef = useRef<HTMLDivElement | null>(null);
  const previewRef = useRef<HTMLDivElement | null>(null);
  const openTimer = useRef<number | null>(null);
  const closeTimer = useRef<number | null>(null);
  const hoverRef = useRef<HoverState | null>(null);
  const valueRef = useRef(value);
  valueRef.current = value;

  const active = value ? inspirationStyle(value) : null;
  const category = useMemo(
    () => INSPIRATION_CATEGORIES.find((c) => c.id === catId) ?? INSPIRATION_CATEGORIES[0] ?? null,
    [catId],
  );
  const hoverStyle = hover ? inspirationStyle(hover.id) : null;

  /** Ширина колонки стилей и всей панели: в сетке панель шире, карточки того же размера. */
  const stylesColW = view === "grid" ? GRID_W : CARD_W;
  const panelW = CAT_W + stylesColW;

  const needle = query.trim().toLowerCase();
  const visibleStyles = useMemo(() => {
    if (!needle) return category?.styles ?? [];
    return INSPIRATION_STYLES.filter((s) =>
      `${s.name} ${s.desc} ${s.id} ${(s.tags ?? []).join(" ")}`.toLowerCase().includes(needle),
    );
  }, [needle, category]);

  const categoryNameOf = useCallback((styleId: string) => {
    return INSPIRATION_CATEGORIES.find((c) => c.styles.some((s) => s.id === styleId))?.name ?? "";
  }, []);

  const clearOpenTimer = useCallback(() => {
    if (openTimer.current !== null) {
      window.clearTimeout(openTimer.current);
      openTimer.current = null;
    }
  }, []);

  const clearCloseTimer = useCallback(() => {
    if (closeTimer.current !== null) {
      window.clearTimeout(closeTimer.current);
      closeTimer.current = null;
    }
  }, []);

  useEffect(() => {
    hoverRef.current = hover;
  }, [hover]);

  /**
   * Позиция панели: считаем от кнопки (portal + position: fixed), прижимаем к вьюпорту.
   * Открываем вверх: кнопка живёт в доке внизу экрана.
   */
  const measurePanel = useCallback(() => {
    const btn = buttonRef.current;
    if (!btn) return;
    const rect = btn.getBoundingClientRect();
    const vw = window.innerWidth;
    const vh = window.innerHeight;
    const width = panelW;
    const height = Math.min(PANEL_MAX_H, Math.round(vh * 0.82));
    const left = Math.min(Math.max(8, rect.left - 20), Math.max(8, vw - width - 8));
    const top = Math.min(Math.max(8, rect.top - 12 - height), Math.max(8, vh - height - 8));
    setPanelBox({ left, top, width, height });
  }, [panelW]);

  useEffect(() => {
    if (!open) {
      setPanelBox(null);
      return;
    }
    measurePanel();
    const onResize = () => {
      measurePanel();
      setHover(null);
    };
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, [open, measurePanel]);

  /** Превью привязано к координатам карточки — при прокрутке каталога закрываем его. */
  useEffect(() => {
    if (!hover) return;
    const onScroll = (e: Event) => {
      const target = e.target;
      if (target instanceof Node && previewRef.current?.contains(target)) return;
      setHover(null);
    };
    window.addEventListener("scroll", onScroll, true);
    return () => window.removeEventListener("scroll", onScroll, true);
  }, [hover]);

  useEffect(
    () => () => {
      clearOpenTimer();
      clearCloseTimer();
    },
    [clearOpenTimer, clearCloseTimer],
  );

  useEffect(() => {
    if (!open) {
      setHover(null);
      clearOpenTimer();
      clearCloseTimer();
      return;
    }

    setArtUrls(readArtUrls());
    setQuery("");
    // Открываем на категории выбранного стиля, иначе на сохранённой, иначе на первой.
    let saved = "";
    try {
      saved = window.localStorage.getItem(INSPIRATION_LS_CATEGORY) ?? "";
    } catch {
      /* ignore */
    }
    const target = positiveCatFor(valueRef.current) ?? saved;
    if (target && INSPIRATION_CATEGORIES.some((c) => c.id === target)) setCatId(target);

    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      // Сначала закрываем превью, повторный Escape — сам каталог.
      if (hoverRef.current) {
        setHover(null);
        return;
      }
      setOpen(false);
    };
    const onDown = (e: MouseEvent) => {
      const node = e.target as Node;
      if (
        panelRef.current?.contains(node) ||
        buttonRef.current?.contains(node) ||
        previewRef.current?.contains(node)
      ) {
        return;
      }
      setOpen(false);
    };
    window.addEventListener("keydown", onKey);
    window.addEventListener("mousedown", onDown);
    return () => {
      window.removeEventListener("keydown", onKey);
      window.removeEventListener("mousedown", onDown);
    };
  }, [open, clearOpenTimer, clearCloseTimer]);

  const select = useCallback(
    (style: GenStyleDef, cat?: string) => {
      try {
        window.localStorage.setItem(INSPIRATION_LS_STYLE, style.id);
        if (cat) window.localStorage.setItem(INSPIRATION_LS_CATEGORY, cat);
      } catch {
        /* ignore */
      }
      onChange(style.id);
    },
    [onChange],
  );

  const pick = useCallback(
    (style: GenStyleDef, cat?: string) => {
      select(style, cat);
      setHover(null);
      setOpen(false);
      toast.success(`Стиль «${style.name}» выбран`);
    },
    [select],
  );

  const reset = useCallback(() => {
    try {
      window.localStorage.setItem(INSPIRATION_LS_STYLE, "");
    } catch {
      /* ignore */
    }
    onChange("");
    setHover(null);
    setOpen(false);
  }, [onChange]);

  /** Клик по карточке открывает превью (и не выбирает стиль); повторный клик — закрывает. */
  const openPreview = useCallback(
    (styleId: string, el: HTMLElement) => {
      clearOpenTimer();
      clearCloseTimer();
      const rect = el.getBoundingClientRect();
      if (rect.width === 0 && rect.height === 0) return;
      setHover({ id: styleId, box: previewBoxFor(rect) });
    },
    [clearOpenTimer, clearCloseTimer],
  );

  /** При открытом превью курсор перешёл на другую карточку — окно переключается на неё. */
  const followPreview = useCallback(
    (styleId: string, el: HTMLElement) => {
      if (!hoverRef.current || hoverRef.current.id === styleId) return;
      clearOpenTimer();
      clearCloseTimer();
      const rect = el.getBoundingClientRect();
      if (rect.width === 0 && rect.height === 0) return;
      setHover({ id: styleId, box: previewBoxFor(rect) });
    },
    [clearOpenTimer, clearCloseTimer],
  );

  /** Курсор ушёл с карточки: 200 мс форы, чтобы дойти до окна; вход в окно отменяет таймер. */
  const previewCloseSoon = useCallback(() => {
    clearOpenTimer();
    clearCloseTimer();
    closeTimer.current = window.setTimeout(() => {
      closeTimer.current = null;
      setHover(null);
    }, PREVIEW_CLOSE_MS);
  }, [clearOpenTimer, clearCloseTimer]);

  const previewStay = useCallback(() => {
    clearCloseTimer();
  }, [clearCloseTimer]);

  const closeHover = useCallback(() => {
    clearOpenTimer();
    clearCloseTimer();
    setHover(null);
  }, [clearOpenTimer, clearCloseTimer]);

  return (
    <>
      <button
        ref={buttonRef}
        type="button"
        data-testid="inspiration-button"
        aria-label="Каталог стилей"
        aria-pressed={open}
        title={active ? `Каталог стилей. Выбран «${active.name}»` : "Каталог стилей"}
        onClick={() => setOpen((o) => !o)}
        className={cn(
          "relative flex h-[54px] w-[77px] shrink-0 items-center justify-center rounded-xl border p-0 transition-all duration-200",
          open || active
            ? "border-[#2dd4bf] bg-[#2dd4bf]/15 text-[#2dd4bf] shadow-[0_0_18px_rgba(45,212,191,0.25)]"
            : "border-white/10 bg-[#16161b]/90 text-white/45 hover:border-white/20 hover:bg-[#1e1e24] hover:text-white",
          className,
        )}
      >
        <Library className="h-[22px] w-[22px]" />
        {active ? (
          <span className="absolute top-1 right-1 h-1.5 w-1.5 rounded-full bg-[#2dd4bf] shadow-[0_0_6px_#2dd4bf]" />
        ) : null}
      </button>

      {/* Панель каталога — порталом в body, иначе оверлеи дока её перекрывают. */}
      {open && panelBox && typeof document !== "undefined"
        ? createPortal(
            <div
              ref={panelRef}
              data-testid="inspiration-menu"
              role="dialog"
              aria-label="Каталог стилей"
              style={{
                left: panelBox.left,
                top: panelBox.top,
                width: panelBox.width,
                height: panelBox.height,
                maxWidth: "calc(100vw - 16px)",
              }}
              onPointerDown={(e) => e.stopPropagation()}
              className="fixed z-[120] flex flex-col overflow-hidden rounded-2xl border border-white/15 bg-[#121216]/95 shadow-[0_25px_70px_rgba(0,0,0,0.85)] ring-1 ring-white/10 backdrop-blur-2xl"
            >
              {/* Шапка */}
              <div className="flex shrink-0 items-center justify-between gap-3 border-b border-white/[0.08] bg-[#16161b]/95 px-3 py-2.5">
                <div className="flex min-w-0 items-center gap-2">
                  <Library className="h-3.5 w-3.5 shrink-0 text-[#2dd4bf]" />
                  <span
                    data-testid="inspiration-title"
                    className="text-[13px] font-bold tracking-tight text-white/90"
                  >
                    Каталог стилей
                  </span>
                  <span className="rounded-full bg-white/10 px-2 py-0.5 font-mono text-[10px] font-semibold text-[#2dd4bf]">
                    {INSPIRATION_CATEGORIES.length} кат. · {INSPIRATION_STYLES.length} стилей
                  </span>
                  {active ? (
                    <span className="truncate text-[10.5px] text-white/40">
                      выбран «{active.name}»
                    </span>
                  ) : null}
                </div>
                <div className="flex shrink-0 items-center gap-2">
                  {/* Переключатель вида: списком (как было) или сеткой 3 в ряд */}
                  <div className="flex items-center gap-0.5 rounded-lg border border-white/10 bg-white/[0.04] p-0.5">
                    <button
                      type="button"
                      data-testid="inspiration-view-list"
                      aria-pressed={view === "list"}
                      aria-label="Показывать стили списком"
                      title="Списком"
                      onClick={() => {
                        setView("list");
                        closeHover();
                      }}
                      className={cn(
                        "rounded-md p-1 transition",
                        view === "list" ? "bg-[#2dd4bf] text-black" : "text-white/45 hover:text-white",
                      )}
                    >
                      <List className="h-3.5 w-3.5" />
                    </button>
                    <button
                      type="button"
                      data-testid="inspiration-view-grid"
                      aria-pressed={view === "grid"}
                      aria-label="Показывать стили сеткой по три"
                      title="Сетка 3 в ряд"
                      onClick={() => {
                        setView("grid");
                        closeHover();
                      }}
                      className={cn(
                        "rounded-md p-1 transition",
                        view === "grid" ? "bg-[#2dd4bf] text-black" : "text-white/45 hover:text-white",
                      )}
                    >
                      <Grid3x3 className="h-3.5 w-3.5" />
                    </button>
                  </div>
                  {active ? (
                    <button
                      type="button"
                      onClick={reset}
                      className="rounded-lg border border-white/12 px-2.5 py-1 text-[11px] text-white/60 transition hover:border-[#2dd4bf]/50 hover:text-white"
                    >
                      Без стиля
                    </button>
                  ) : null}
                  <button
                    type="button"
                    onClick={() => setOpen(false)}
                    aria-label="Закрыть каталог"
                    className="rounded-lg border border-white/10 p-1 text-white/50 transition hover:bg-white/10 hover:text-white"
                  >
                    <X className="h-3.5 w-3.5" />
                  </button>
                </div>
              </div>

              {/* Слева категории · в центре стили · превью открывается отдельным окном у карточки */}
              <div className="flex min-h-0 flex-1">
                <div
                  data-testid="inspiration-categories"
                  style={{ width: CAT_W }}
                  className="shrink-0 overflow-y-auto border-r border-white/[0.08] p-2"
                  role="tablist"
                  aria-label="Категории стилей"
                >
                  <p className="mb-1.5 px-1 text-[9px] font-bold tracking-[0.14em] text-white/30 uppercase">
                    Категории
                  </p>
                  {INSPIRATION_CATEGORIES.map((c) => {
                    const isActive = c.id === category?.id;
                    const coverStyle = c.styles.find((s) => artUrls[s.id] ?? s.cover) ?? c.styles[0];
                    const hasSelected = c.styles.some((s) => s.id === value);
                    return (
                      <button
                        key={c.id}
                        type="button"
                        role="tab"
                        aria-selected={isActive}
                        data-testid={`inspiration-category-${c.id}`}
                        onClick={() => {
                          setCatId(c.id);
                          closeHover();
                        }}
                        className={cn(
                          "mb-1 flex w-full items-center gap-2 rounded-xl border p-1.5 text-left transition",
                          isActive
                            ? "border-[#2dd4bf] bg-[#2dd4bf]/12 shadow-[0_0_18px_rgba(45,212,191,0.18)]"
                            : "border-white/[0.08] bg-white/[0.03] hover:border-white/20 hover:bg-white/[0.06]",
                        )}
                      >
                        <StyleThumb
                          style={coverStyle}
                          artUrl={artUrls[coverStyle.id]}
                          className="h-[36px] w-[36px] shrink-0 rounded-lg"
                        />
                        <span className="min-w-0 flex-1">
                          <span
                            className={cn(
                              "block truncate text-[12px] font-semibold",
                              isActive ? "text-[#2dd4bf]" : "text-white/90",
                            )}
                          >
                            {c.name}
                          </span>
                          <span className="mt-0.5 flex items-center gap-1 text-[10px] text-white/40">
                            {c.styles.length} стилей
                            {hasSelected ? <Check className="h-2.5 w-2.5 text-[#2dd4bf]" /> : null}
                          </span>
                        </span>
                      </button>
                    );
                  })}
                </div>

                <div
                  data-testid="inspiration-styles"
                  data-view={view}
                  style={{ width: stylesColW }}
                  className="shrink-0 overflow-y-auto p-2"
                >
                  <div className="relative mb-1.5 px-1">
                    <Search className="pointer-events-none absolute top-1/2 left-2.5 h-3 w-3 -translate-y-1/2 text-white/35" />
                    <input
                      data-testid="inspiration-search"
                      value={query}
                      onChange={(e) => {
                        setQuery(e.target.value);
                        closeHover();
                      }}
                      placeholder="Поиск по всем стилям"
                      className="w-full rounded-lg border border-white/10 bg-white/[0.04] py-1 pr-[22px] pl-[26px] text-[10.5px] text-white/85 placeholder:text-white/30 focus:border-[#2dd4bf]/60 focus:outline-none"
                    />
                    {query ? (
                      <button
                        type="button"
                        onClick={() => {
                          setQuery("");
                          closeHover();
                        }}
                        aria-label="Очистить поиск"
                        className="absolute top-1/2 right-1.5 -translate-y-1/2 rounded p-0.5 text-white/40 transition hover:text-white"
                      >
                        <X className="h-2.5 w-2.5" />
                      </button>
                    ) : null}
                  </div>
                  <p className="mb-1.5 px-1 text-[9px] font-bold tracking-[0.14em] text-white/30 uppercase">
                    {needle ? `Найдено · ${visibleStyles.length}` : `Стили · ${visibleStyles.length}`}
                  </p>
                  <div
                    className={cn(view === "grid" && "grid grid-cols-3")}
                    style={view === "grid" ? { gap: GRID_GAP } : undefined}
                  >
                    {visibleStyles.map((s) => {
                      const isHover = s.id === hover?.id;
                      const caption = needle ? categoryNameOf(s.id) : s.desc;
                      return (
                        <button
                          key={s.id}
                          type="button"
                          data-testid={`inspiration-style-${s.id}`}
                          data-style-id={s.id}
                          aria-pressed={s.id === value}
                          onMouseEnter={(e) => followPreview(s.id, e.currentTarget)}
                          onMouseLeave={previewCloseSoon}
                          onClick={(e) => {
                            // Превью открывается кликом и не выбирает стиль;
                            // выбор — только кнопкой «Выбрать стиль» в окне.
                            if (hover?.id === s.id) closeHover();
                            else openPreview(s.id, e.currentTarget);
                          }}
                          title={s.desc}
                          className={cn(
                            "group relative block w-full overflow-hidden rounded-xl border text-left transition",
                            view === "list" && "mb-2",
                            isHover
                              ? "border-[#2dd4bf] ring-2 ring-[#2dd4bf]/40"
                              : s.id === value
                                ? "border-[#2dd4bf]/50"
                                : "border-white/10 hover:border-white/30",
                          )}
                        >
                          {/* Кадр 3:2 — как исходные обложки, поэтому не режется по высоте */}
                          <StyleThumb style={s} artUrl={artUrls[s.id]} className="aspect-[3/2] w-full" />
                          {/* Подпись всегда одна и та же — в сетке карточка не мельчает */}
                          <div className="pointer-events-none absolute inset-x-0 bottom-0 bg-gradient-to-t from-black/95 via-black/60 to-transparent px-2.5 pt-10 pb-2">
                            <div className="line-clamp-1 text-[13px] font-bold text-white">{s.name}</div>
                            <div className="line-clamp-1 text-[10.5px] text-white/55">{caption}</div>
                          </div>
                          {s.id === value ? (
                            <span className="absolute top-1 right-1 flex items-center gap-0.5 rounded bg-[#2dd4bf] px-1 py-0.5 text-[9px] font-bold text-black">
                              <Check className="h-2.5 w-2.5" /> выбран
                            </span>
                          ) : null}
                        </button>
                      );
                    })}
                  </div>
                  {visibleStyles.length === 0 ? (
                    <p className="px-1 py-3 text-[10.5px] leading-relaxed text-white/40">
                      Ничего не нашлось. Попробуй короче: «аниме», «нуар», «бумага», «киберпанк».
                    </p>
                  ) : null}
                </div>
              </div>
            </div>,
            document.body,
          )
        : null}

      {/* Всплывающее окно стиля: отдельно от панели, вплотную к карточке под курсором. */}
      {open && hover && hoverStyle && typeof document !== "undefined"
        ? createPortal(
            <StylePreview
              style={hoverStyle}
              artUrl={artUrls[hoverStyle.id]}
              categoryName={categoryNameOf(hoverStyle.id)}
              selected={hoverStyle.id === value}
              box={hover.box}
              previewRef={previewRef}
              onEnter={previewStay}
              onLeave={previewCloseSoon}
              onPick={() => pick(hoverStyle, positiveCatFor(hoverStyle.id) ?? category?.id)}
            />,
            document.body,
          )
        : null}
    </>
  );
}
