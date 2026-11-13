"use client";

/**
 * «Вдохновение» — кнопка над результатом генерации.
 * Внутри те же стили, что в шторке «Каталог стилей» панели «Помощник»:
 * встроенные (GEN_ASSISTANT_CATEGORIES) + свои стили с диска/из localStorage.
 * Выбор стиля отдаёт наружу его ядро (promptCore) — родитель подставляет его в промпт.
 */

import { useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { ChevronDown, Search, Sparkles, X } from "lucide-react";
import { cn } from "@/lib/utils";
import {
  GEN_ASSISTANT_CATEGORIES,
  type GenStyleArt,
  type GenStyleDef,
} from "@/lib/gen-assistant-styles";
import { GenStyleArt as GenStyleArtView } from "@/components/outsee/gen-style-art";

type CustomStyle = GenStyleDef & { categoryId: string; artUrl?: string };

const ART_KEY = "genAssistant.styleArt.";
const CUSTOM_KEY = "genAssistant.customStyles";

/** Акцент плитки. В палитре окна генерации, hex — CSS-переменных `--gen-style-*` в теме нет. */
const ACCENT: Record<GenStyleDef["color"], string> = {
  red: "#ef4444",
  purple: "#a855f7",
  gray: "#9ca3af",
  orange: "#f97316",
  cyan: "#06b6d4",
  blue: "#60a5fa",
  green: "#22c55e",
  pink: "#ec4899",
  yellow: "#eab308",
};

function readArtUrls(): Record<string, string> {
  const out: Record<string, string> = {};
  if (typeof window === "undefined") return out;
  try {
    for (let i = 0; i < window.localStorage.length; i += 1) {
      const k = window.localStorage.key(i);
      if (k && k.startsWith(ART_KEY)) {
        const v = window.localStorage.getItem(k);
        if (v) out[k.slice(ART_KEY.length)] = v;
      }
    }
  } catch {
    /* ignore */
  }
  return out;
}

function readLocalCustomStyles(): CustomStyle[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = window.localStorage.getItem(CUSTOM_KEY);
    const parsed = raw ? (JSON.parse(raw) as unknown) : [];
    if (!Array.isArray(parsed)) return [];
    return parsed.filter((s): s is CustomStyle => Boolean(s && (s as CustomStyle).id));
  } catch {
    return [];
  }
}

/** Обложка плитки: своя картинка стиля → локальное превью → файл из /gen-styles. */
function tileCover(
  s: { id: string; cover?: string; artUrl?: string },
  artUrls: Record<string, string>,
): string {
  const candidates = [s.cover, s.artUrl, artUrls[s.id], `/gen-styles/${s.id}.webp`, `/gen-styles/${s.id}.png`];
  for (const raw of candidates) {
    const u = (raw || "").trim();
    if (!u) continue;
    if (u.startsWith("blob:") || u.startsWith("file:") || u.startsWith("data:")) continue;
    if (u.startsWith("http") || u.startsWith("/")) return u;
  }
  return "";
}

type Props = {
  /** Ядро стиля (promptCore) — родитель подставляет его в промпт. */
  onApply: (style: GenStyleDef, core: string) => void;
  className?: string;
};

export function InspirationMenu({ onApply, className }: Props) {
  const [open, setOpen] = useState(false);
  const [mounted, setMounted] = useState(false);
  const [search, setSearch] = useState("");
  const [cat, setCat] = useState("all");
  const [customStyles, setCustomStyles] = useState<CustomStyle[]>(readLocalCustomStyles);
  const [artUrls] = useState<Record<string, string>>(readArtUrls);
  const [diskLoaded, setDiskLoaded] = useState(false);
  const [anchor, setAnchor] = useState({ left: 12, top: 80, width: 660, maxH: 520 });

  const btnRef = useRef<HTMLButtonElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);

  useEffect(() => setMounted(true), []);

  // Свои стили с диска — тот же источник, что у шторки «Каталог стилей».
  useEffect(() => {
    if (!open || diskLoaded) return;
    let cancelled = false;
    fetch("/api/gen-assistant/custom-styles", { cache: "no-store" })
      .then((r) => (r.ok ? r.json() : null))
      .then((data: { styles?: CustomStyle[] } | null) => {
        if (cancelled) return;
        const remote = Array.isArray(data?.styles) ? data.styles : [];
        if (remote.length) {
          setCustomStyles((prev) => {
            const byId = new Map<string, CustomStyle>();
            for (const s of [...prev, ...remote]) if (s?.id) byId.set(s.id, s);
            return Array.from(byId.values());
          });
        }
        setDiskLoaded(true);
      })
      .catch(() => setDiskLoaded(true));
    return () => {
      cancelled = true;
    };
  }, [open, diskLoaded]);

  // Позиция меню под кнопкой (портал в body — выше окна генерации).
  useEffect(() => {
    if (!open) return;
    const place = () => {
      const r = btnRef.current?.getBoundingClientRect();
      if (!r) return;
      const width = Math.min(660, window.innerWidth - 24);
      const left = Math.max(12, Math.min(window.innerWidth - width - 12, r.left + r.width / 2 - width / 2));
      const top = r.bottom + 8;
      const maxH = Math.max(260, Math.min(window.innerHeight - top - 16, 560));
      setAnchor({ left, top, width, maxH });
    };
    place();
    window.addEventListener("resize", place);
    window.addEventListener("scroll", place, true);
    return () => {
      window.removeEventListener("resize", place);
      window.removeEventListener("scroll", place, true);
    };
  }, [open]);

  // Esc и клик мимо — закрыть.
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    const onDown = (e: MouseEvent) => {
      const t = e.target as Node;
      if (panelRef.current?.contains(t) || btnRef.current?.contains(t)) return;
      setOpen(false);
    };
    window.addEventListener("keydown", onKey);
    window.addEventListener("mousedown", onDown);
    return () => {
      window.removeEventListener("keydown", onKey);
      window.removeEventListener("mousedown", onDown);
    };
  }, [open]);

  const categories = useMemo(
    () =>
      GEN_ASSISTANT_CATEGORIES.map((c) => ({
        ...c,
        styles: [...c.styles, ...customStyles.filter((s) => s.categoryId === c.id)],
      })),
    [customStyles],
  );

  const orphans = useMemo(
    () =>
      customStyles.filter(
        (s) => !GEN_ASSISTANT_CATEGORIES.some((c) => c.id === s.categoryId),
      ),
    [customStyles],
  );

  const allStyles = useMemo(
    () => [
      ...categories.flatMap((c) => c.styles.map((style) => ({ style, catName: c.name }))),
      ...orphans.map((style) => ({ style, catName: "Мой стиль" })),
    ],
    [categories, orphans],
  );

  const shown = useMemo(() => {
    let list = allStyles;
    if (cat === "custom") {
      list = list.filter(({ style }) => style.id.startsWith("custom_") || customStyles.some((c) => c.id === style.id));
    } else if (cat !== "all") {
      const ids = new Set(
        (categories.find((c) => c.id === cat)?.styles ?? []).map((s) => s.id),
      );
      list = list.filter(({ style }) => ids.has(style.id));
    }
    const q = search.trim().toLowerCase();
    if (q) {
      list = list.filter(({ style }) =>
        [style.name, style.desc, style.promptCore, ...(style.tags || [])]
          .join(" ")
          .toLowerCase()
          .includes(q),
      );
    }
    return list;
  }, [allStyles, cat, customStyles, categories, search]);

  const pick = (style: GenStyleDef) => {
    const core = (style.promptCore || "").trim();
    if (!core) return;
    onApply(style, core);
    setOpen(false);
  };

  return (
    <div className={cn("relative", className)}>
      <button
        ref={btnRef}
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        data-testid="inspiration-button"
        title="Вдохновение: готовые стили — подставятся в промпт"
        className={cn(
          "inline-flex items-center gap-1.5 rounded-xl border px-3 py-1.5 text-[11px] font-semibold backdrop-blur transition",
          open
            ? "border-[#2dd4bf]/60 bg-[#2dd4bf]/15 text-[#2dd4bf] shadow-[0_0_18px_rgba(45,212,191,0.25)]"
            : "border-white/10 bg-white/[0.04] text-white/70 hover:border-[#2dd4bf]/40 hover:bg-[#2dd4bf]/10 hover:text-white",
        )}
      >
        <Sparkles className="h-3.5 w-3.5 text-[#2dd4bf]" />
        <span>Вдохновение</span>
        <ChevronDown className={cn("h-3 w-3 opacity-60 transition", open && "rotate-180")} />
      </button>

      {open && mounted && typeof document !== "undefined"
        ? createPortal(
            <div
              ref={panelRef}
              role="dialog"
              aria-label="Вдохновение — стили"
              data-testid="inspiration-menu"
              style={{ left: anchor.left, top: anchor.top, width: anchor.width, maxHeight: anchor.maxH }}
              className="fixed z-[200] flex flex-col overflow-hidden rounded-2xl border border-white/15 bg-[#0f1015]/98 text-white shadow-[0_24px_70px_rgba(0,0,0,0.85)] ring-1 ring-white/10 backdrop-blur-2xl"
            >
              <div className="flex shrink-0 items-center gap-2 border-b border-white/10 px-3.5 py-2.5">
                <Sparkles className="h-4 w-4 text-[#2dd4bf]" />
                <div className="leading-tight">
                  <div className="text-[13px] font-bold">Вдохновение</div>
                  <div className="text-[10px] text-white/45">
                    {allStyles.length} готовых стилей · выбор добавит стиль в промпт
                  </div>
                </div>
                <button
                  type="button"
                  onClick={() => setOpen(false)}
                  className="ml-auto inline-flex h-7 w-7 items-center justify-center rounded-lg border border-white/10 bg-white/[0.04] text-white/60 transition hover:bg-white/[0.1] hover:text-white"
                  title="Закрыть"
                >
                  <X className="h-3.5 w-3.5" />
                </button>
              </div>

              <div className="shrink-0 space-y-2 border-b border-white/10 bg-white/[0.015] px-3.5 py-2.5">
                <div className="relative">
                  <Search className="pointer-events-none absolute top-1/2 left-2.5 h-3.5 w-3.5 -translate-y-1/2 text-white/40" />
                  <input
                    type="text"
                    value={search}
                    onChange={(e) => setSearch(e.target.value)}
                    placeholder="Поиск по стилям, описанию, тегам…"
                    className="w-full rounded-lg border border-white/10 bg-[#16161d] py-1.5 pr-7 pl-8 text-[12px] text-white/90 placeholder-white/35 transition focus:border-[#2dd4bf]/50 focus:outline-none"
                  />
                  {search && (
                    <button
                      type="button"
                      onClick={() => setSearch("")}
                      className="absolute top-1/2 right-2 -translate-y-1/2 text-white/40 hover:text-white"
                    >
                      <X className="h-3.5 w-3.5" />
                    </button>
                  )}
                </div>
                <div className="flex flex-wrap items-center gap-1.5">
                  <button
                    type="button"
                    onClick={() => setCat("all")}
                    className={cn(
                      "rounded-full px-2.5 py-0.5 text-[10.5px] font-medium transition",
                      cat === "all"
                        ? "bg-[#2dd4bf] font-semibold text-black"
                        : "bg-white/[0.05] text-white/60 hover:bg-white/[0.08] hover:text-white",
                    )}
                  >
                    Все ({allStyles.length})
                  </button>
                  {categories.map((c) => (
                    <button
                      key={c.id}
                      type="button"
                      onClick={() => setCat(c.id)}
                      className={cn(
                        "rounded-full px-2.5 py-0.5 text-[10.5px] font-medium transition",
                        cat === c.id
                          ? "bg-[#2dd4bf] font-semibold text-black"
                          : "bg-white/[0.05] text-white/60 hover:bg-white/[0.08] hover:text-white",
                      )}
                    >
                      {c.name} ({c.styles.length})
                    </button>
                  ))}
                  {orphans.length > 0 && (
                    <button
                      type="button"
                      onClick={() => setCat("custom")}
                      className={cn(
                        "rounded-full px-2.5 py-0.5 text-[10.5px] font-medium transition",
                        cat === "custom"
                          ? "bg-[#2dd4bf] font-semibold text-black"
                          : "bg-white/[0.05] text-white/60 hover:bg-white/[0.08] hover:text-white",
                      )}
                    >
                      Мои ({orphans.length})
                    </button>
                  )}
                </div>
              </div>

              <div className="min-h-0 flex-1 overflow-y-auto p-3">
                {shown.length === 0 ? (
                  <div className="px-2 py-8 text-center text-[12px] text-white/40">
                    Ничего не нашлось по запросу «{search}»
                  </div>
                ) : (
                  <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
                    {shown.map(({ style, catName }) => {
                      const cover = tileCover(style as CustomStyle, artUrls);
                      return (
                        <button
                          key={style.id}
                          type="button"
                          onClick={() => pick(style)}
                          title={`${style.name} — ${style.desc}\n\n${style.promptCore}`}
                          className="group relative h-[104px] overflow-hidden rounded-xl border border-white/10 bg-[#16161c] text-left transition hover:border-[#2dd4bf]/60 hover:shadow-[0_10px_28px_rgba(0,0,0,0.6)]"
                        >
                          <div className="absolute inset-0 overflow-hidden transition-transform duration-500 group-hover:scale-105">
                            {cover ? (
                              // eslint-disable-next-line @next/next/no-img-element
                              <img
                                src={cover}
                                alt=""
                                loading="lazy"
                                decoding="async"
                                className="h-full w-full object-cover"
                              />
                            ) : (
                              <GenStyleArtView art={style.art as GenStyleArt} color={style.color} />
                            )}
                          </div>
                          <div className="pointer-events-none absolute inset-x-0 bottom-0 flex flex-col justify-end bg-gradient-to-t from-black/95 via-black/70 to-transparent p-2 pt-6">
                            <div className="line-clamp-1 text-[12px] font-bold text-white drop-shadow">
                              {style.name}
                            </div>
                            <div className="line-clamp-1 text-[10px] text-white/60">{style.desc}</div>
                          </div>
                          <div className="pointer-events-none absolute inset-x-0 top-0 flex items-center justify-between p-1.5">
                            <span className="rounded bg-black/65 px-1.5 py-0.5 text-[9px] font-medium text-white/85 backdrop-blur-md">
                              {catName}
                            </span>
                            <span
                              className="h-2 w-2 rounded-full shadow-[0_0_8px_currentColor]"
                              style={{ backgroundColor: ACCENT[style.color], color: ACCENT[style.color] }}
                            />
                          </div>
                        </button>
                      );
                    })}
                  </div>
                )}
              </div>
            </div>,
            document.body,
          )
        : null}
    </div>
  );
}
