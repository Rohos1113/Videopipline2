/**
 * Язык интерфейса. Хранится в тех же настройках пользователя, что тема и
 * размер шрифта (`vp-user-prefs`), поэтому переключатель в профиле работает
 * без отдельного хранилища.
 */

export type Lang = "ru" | "en" | "both";

export const PREFS_KEY = "vp-user-prefs";

/** Событие «язык сменился» — его шлёт applyUserPrefs из user-panel. */
export const LANG_EVENT = "vp-lang-change";

export const DEFAULT_LANG: Lang = "ru";

export function normalizeLang(value: unknown): Lang {
  return value === "en" || value === "both" ? value : "ru";
}

/** Текущий язык из localStorage. На сервере (без window) — русский. */
export function readLang(): Lang {
  if (typeof window === "undefined") return DEFAULT_LANG;
  try {
    const raw = window.localStorage.getItem(PREFS_KEY);
    if (raw) return normalizeLang(JSON.parse(raw)?.lang);
  } catch {
    /* битые настройки — считаем, что русский */
  }
  return DEFAULT_LANG;
}

/** Записать язык в те же настройки, не затирая тему и масштаб шрифта. */
export function writeLang(lang: Lang): void {
  if (typeof window === "undefined") return;
  try {
    const raw = window.localStorage.getItem(PREFS_KEY);
    const prefs = raw ? JSON.parse(raw) : {};
    window.localStorage.setItem(PREFS_KEY, JSON.stringify({ ...prefs, lang }));
  } catch {
    /* localStorage может быть недоступен — молча пропускаем */
  }
  window.dispatchEvent(new CustomEvent(LANG_EVENT, { detail: lang }));
}
