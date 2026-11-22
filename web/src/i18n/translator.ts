/**
 * Чистое ядро переводчика: словарь RU → EN + подстановка `{}`.
 *
 * Здесь нет ни DOM, ни JSON: модуль специально без зависимостей, чтобы его
 * можно было тестировать в node без сборки.
 */

export type Lang = "ru" | "en" | "both";

/** Плоский словарь: русская строка (как в разметке) → английский вариант. */
export type Entries = Record<string, string>;

export type Translator = {
  /** Сколько строк в словаре (точные + шаблоны). */
  size: number;
  /** Перевести текст. `ru` — вернуть как есть. */
  translate(text: string, lang: Lang): string;
};

const CYRILLIC = /[\u0400-\u04FF]/;
const PLACEHOLDER = "{}";

type Wildcard = { re: RegExp; en: string; score: number };

function collapse(s: string): string {
  return s
    .replace(/\u00a0/g, " ")
    .replace(/[ \t\r\n\f\v]+/g, " ")
    .trim();
}

function escapeRegExp(s: string): string {
  return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function splitWs(text: string): { lead: string; core: string; trail: string } {
  const lead = /^\s*/.exec(text)?.[0] ?? "";
  const trail = /\s*$/.exec(text)?.[0] ?? "";
  return { lead, trail, core: collapse(text) };
}

export function createTranslator(entries: Entries): Translator {
  const exact = new Map<string, string>();
  const wildcards: Wildcard[] = [];

  for (const [rawRu, rawEn] of Object.entries(entries)) {
    if (typeof rawEn !== "string") continue;
    const en = rawEn.replace(/\u00a0/g, " ").trim();
    const ru = collapse(rawRu);
    if (!ru || !en) continue;
    if (ru.includes(PLACEHOLDER)) {
      const parts = ru.split(PLACEHOLDER);
      const src = parts.map(escapeRegExp).join("([\\s\\S]+?)");
      let score = 0;
      for (const p of parts) score += p.trim().length;
      wildcards.push({ re: new RegExp("^" + src + "$"), en, score });
    } else {
      exact.set(ru, en);
    }
  }

  // Более специфичный шаблон (больше литеральных символов) матчится первым.
  wildcards.sort((a, b) => b.score - a.score);

  function lookup(core: string): string | null {
    const hit = exact.get(core);
    if (hit !== undefined) return hit;
    for (const w of wildcards) {
      const m = w.re.exec(core);
      if (!m) continue;
      let i = 1;
      return w.en.replace(/\{\}/g, () => (m[i++] ?? "").trim());
    }
    return null;
  }

  function translate(text: string, lang: Lang): string {
    if (lang === "ru" || !text || !CYRILLIC.test(text)) return text;
    const { lead, core, trail } = splitWs(text);
    if (!core) return text;
    const en = lookup(core);
    if (en === null) return text;
    if (lang === "en") return lead + en + trail;
    // "both": двойное написание — русское и английское рядом.
    return lead + core + " · " + en + trail;
  }

  return { size: exact.size + wildcards.length, translate };
}
