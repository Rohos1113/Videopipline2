/**
 * Публичная точка входа i18n.
 *
 *   <I18nProvider> — один раз в Providers (уже подключён);
 *   useLang()      — текущий язык в компоненте;
 *   translateText() — перевод строки вне React (toast, document.title…).
 *
 * Словарь лежит в `./dictionary.ts` и грузится лениво. Подробности — README.md.
 */

export { I18nProvider, useLang } from "./provider";
export { translateText, translator } from "./dictionary";
export { createTranslator } from "./translator";
export type { Lang, Translator } from "./translator";
export { readLang, writeLang, normalizeLang } from "./lang";
