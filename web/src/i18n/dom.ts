/**
 * Перевод уже отрисованного интерфейса.
 *
 * Компоненты не трогаем: слой один раз обходит DOM и подменяет текстовые узлы
 * и подписи (title/placeholder/aria-label/alt) по словарю. Дальше он следит за
 * изменениями — React перерисовал, роут сменился, пришёл ответ API — и
 * переводит новые узлы. При переключении на русский возвращает оригиналы.
 *
 * Модуль клиентский: импортируется динамически, только когда выбран не русский.
 */

import { Lang } from "./lang";
import { translateText } from "./dictionary";

const CYRILLIC = /[\u0400-\u04FF]/;

const TRANSLATED_ATTRS = ["title", "placeholder", "aria-label", "aria-description", "alt"] as const;

const SKIP_TAGS = new Set([
  "SCRIPT",
  "STYLE",
  "NOSCRIPT",
  "TEMPLATE",
  "TEXTAREA",
  "CODE",
  "PRE",
  "KBD",
  "SAMP",
  "VAR",
]);

const SKIP_SELECTOR = [
  "[data-i18n-skip]",
  '[translate="no"]',
  '[contenteditable=""]',
  '[contenteditable="true"]',
  '[contenteditable="plaintext-only"]',
].join(",");

let currentLang: Lang = "ru";
/** Полный проход: пересчитываем даже уже переведённые узлы (смена ru/en/both). */
let forcePass = false;
let observer: MutationObserver | null = null;

const originalText = new WeakMap<Text, string>();
const writtenText = new WeakMap<Text, string>();
const trackedText = new Set<Text>();

const originalAttrs = new WeakMap<Element, Record<string, string>>();
const writtenAttrs = new WeakMap<Element, Record<string, string>>();
const trackedElements = new Set<Element>();

/* ------------------------------------------------------------------ */
/* служебное                                                           */
/* ------------------------------------------------------------------ */

function skipped(el: Element | null): boolean {
  if (!el) return true;
  if (SKIP_TAGS.has(el.tagName)) return true;
  return Boolean(el.closest(SKIP_SELECTOR));
}

function translateNodeText(text: string): string {
  return translateText(text, currentLang);
}

function processTextNode(node: Text): void {
  if (!node.isConnected) return;
  const parent = node.parentElement;
  if (!parent || skipped(parent)) return;

  const value = node.data;
  const known = writtenText.get(node);
  // Наша собственная запись — не трогаем, иначе бесконечный цикл.
  if (!forcePass && known !== undefined && value === known) return;

  // Первый раз или React переписал узел — это новый оригинал.
  let original: string;
  if (known !== undefined && value !== known) original = value;
  else original = originalText.get(node) ?? value;
  originalText.set(node, original);
  trackedText.add(node);

  const out = translateNodeText(original);
  if (out && out !== value) {
    writtenText.set(node, out);
    node.data = out;
  } else {
    writtenText.delete(node);
  }
}

function processElementAttrs(el: Element): void {
  if (el.nodeType !== Node.ELEMENT_NODE) return;
  if (skipped(el)) return;
  const originals = originalAttrs.get(el) ?? {};
  const written = writtenAttrs.get(el) ?? {};
  let dirty = false;

  for (const attr of TRANSLATED_ATTRS) {
    const value = el.getAttribute(attr);
    if (value === null) continue;
    const known = written[attr];
    // Наша собственная запись — не трогаем (но при полном проходе пересчитываем).
    if (!forcePass && known !== undefined && value === known) continue;
    let original = originals[attr] ?? value;
    if (known !== undefined && value !== known) original = value; // React переписал атрибут
    if (!CYRILLIC.test(original)) continue;
    originals[attr] = original;
    const out = translateNodeText(original);
    if (out !== value) {
      written[attr] = out;
      el.setAttribute(attr, out);
      dirty = true;
    } else {
      written[attr] = value;
    }
  }

  if (dirty || Object.keys(originals).length > 0) {
    originalAttrs.set(el, originals);
    writtenAttrs.set(el, written);
    trackedElements.add(el);
  }
}

function walk(node: Node): void {
  if (node.nodeType === Node.TEXT_NODE) {
    processTextNode(node as Text);
    return;
  }
  if (node.nodeType !== Node.ELEMENT_NODE && node.nodeType !== Node.DOCUMENT_NODE && node.nodeType !== Node.DOCUMENT_FRAGMENT_NODE) return;
  const children = node.childNodes;
  if (node.nodeType === Node.ELEMENT_NODE) {
    const el = node as Element;
    if (skipped(el)) return;
    processElementAttrs(el);
  }
  for (let i = 0; i < children.length; i += 1) walk(children[i]);
}

/* ------------------------------------------------------------------ */
/* восстановление русского                                             */
/* ------------------------------------------------------------------ */

function restoreRussian(): void {
  for (const node of trackedText) {
    if (!node.isConnected) {
      trackedText.delete(node);
      continue;
    }
    const original = originalText.get(node);
    if (original !== undefined && node.data !== original) {
      writtenText.delete(node);
      node.data = original;
    }
  }
  for (const el of trackedElements) {
    if (!el.isConnected) {
      trackedElements.delete(el);
      continue;
    }
    const originals = originalAttrs.get(el);
    if (!originals) continue;
    const written = writtenAttrs.get(el) ?? {};
    for (const attrs of Object.keys(originals)) {
      const original = originals[attrs];
      if (el.getAttribute(attrs) !== original) el.setAttribute(attrs, original);
      delete written[attrs];
    }
    writtenAttrs.set(el, written);
  }
}

/* ------------------------------------------------------------------ */
/* очередь мутаций                                                     */
/* ------------------------------------------------------------------ */

let queue: Node[] = [];
let timer: ReturnType<typeof setTimeout> | null = null;
let flushing = false;

function enqueue(node: Node): void {
  queue.push(node);
  scheduleFlush();
}

function scheduleFlush(): void {
  if (timer !== null || flushing) return;
  timer = setTimeout(flush, 0);
}

function flush(): void {
  timer = null;
  if (flushing) return;
  const items = queue;
  queue = [];
  flushing = true;
  try {
    if (currentLang === "ru") {
      restoreRussian();
      return;
    }
    for (const node of items) {
      if (!node.isConnected) continue;
      walk(node);
    }
  } finally {
    flushing = false;
  }
  if (queue.length > 0) scheduleFlush();
}

function ensureObserver(): void {
  if (observer) return;
  observer = new MutationObserver((records) => {
    for (const record of records) {
      if (record.type === "childList") {
        for (let i = 0; i < record.addedNodes.length; i += 1) enqueue(record.addedNodes[i]);
      } else if (record.type === "characterData") {
        enqueue(record.target);
      } else if (record.type === "attributes") {
        enqueue(record.target);
      }
    }
  });
  observer.observe(document.documentElement, {
    subtree: true,
    childList: true,
    characterData: true,
    attributes: true,
    attributeFilter: [...TRANSLATED_ATTRS],
  });
}

/* ------------------------------------------------------------------ */
/* публичное API                                                       */
/* ------------------------------------------------------------------ */

/** Применить язык к уже отрисованному DOM. Вызывается провайдером. */
export function applyLanguage(lang: Lang): void {
  currentLang = lang;
  if (typeof document === "undefined" || !document.body) return;
  ensureObserver();

  if (lang === "ru") {
    forcePass = false;
    restoreRussian();
    return;
  }
  // Полный проход: первый запуск, переключение языка, смена роута.
  const wasFlushing = flushing;
  flushing = true;
  forcePass = true;
  try {
    walk(document.documentElement);
  } finally {
    forcePass = false;
    flushing = wasFlushing;
  }
}
