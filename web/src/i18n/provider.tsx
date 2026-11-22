"use client";

/**
 * Провайдер двуязычного интерфейса.
 *
 * Читает язык из настроек пользователя (`vp-user-prefs`), подхватывает
 * переключение из профиля и из соседних вкладок, и держит перевод слоя DOM
 * в актуальном состоянии. Сам словарь грузится динамически — только когда
 * выбран не русский язык, поэтому русская сборка не тяжелеет.
 */

import { createContext, useContext, useEffect, useMemo, useRef, useState } from "react";
import { DEFAULT_LANG, Lang, LANG_EVENT, PREFS_KEY, readLang } from "./lang";

type I18nContextValue = { lang: Lang };

const I18nContext = createContext<I18nContextValue>({ lang: DEFAULT_LANG });

export function I18nProvider({ children }: { children: React.ReactNode }) {
  const [lang, setLang] = useState<Lang>(DEFAULT_LANG);
  const translatedOnce = useRef(false);
  const generation = useRef(0);

  useEffect(() => {
    let cancelled = false;

    const sync = async () => {
      const next = readLang();
      setLang(next);
      if (next === "ru" && !translatedOnce.current) return;
      const myGeneration = generation.current + 1;
      generation.current = myGeneration;
      const runtime = await import("./dom");
      if (cancelled || generation.current !== myGeneration) return;
      translatedOnce.current = true;
      runtime.applyLanguage(next);
    };

    void sync();

    const onLangEvent = () => {
      void sync();
    };
    const onStorage = (event: StorageEvent) => {
      if (event.key === null || event.key === PREFS_KEY) void sync();
    };

    window.addEventListener(LANG_EVENT, onLangEvent);
    window.addEventListener("storage", onStorage);
    return () => {
      cancelled = true;
      window.removeEventListener(LANG_EVENT, onLangEvent);
      window.removeEventListener("storage", onStorage);
    };
  }, []);

  const value = useMemo<I18nContextValue>(() => ({ lang }), [lang]);
  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>;
}

/** Текущий язык интерфейса (без словаря — только состояние). */
export function useLang(): Lang {
  return useContext(I18nContext).lang;
}
