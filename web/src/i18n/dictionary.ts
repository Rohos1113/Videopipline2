/**
 * Собранный словарь интерфейса: русские строки из разметки → английские.
 *
 * Файлы в `./messages` — плоские пары «строка в коде» : «перевод». Ключи
 * совпадают с текстом буквально (пробелы по краям не важны), `{}` — любой
 * фрагмент: `"Шаг {} из {}"` переведёт «Шаг 3 из 10» → «Step 3 of 10».
 *
 * Модуль тяжёлый (несколько тысяч строк), поэтому провайдер грузит его
 * динамически и только для не-русского языка — русская сборка не толстеет.
 */

import { createTranslator, Lang, Translator } from "./translator";
import shell from "./messages/shell.json";
import canvas1 from "./messages/canvas-1.json";
import canvas2 from "./messages/canvas-2.json";
import canvas3 from "./messages/canvas-3.json";
import canvas4 from "./messages/canvas-4.json";
import orchestrator1 from "./messages/orchestrator-1.json";
import orchestrator2 from "./messages/orchestrator-2.json";
import orchestrator3 from "./messages/orchestrator-3.json";
import orchestrator4 from "./messages/orchestrator-4.json";
import admin from "./messages/admin.json";
import studio1 from "./messages/studio-1.json";
import studio2 from "./messages/studio-2.json";
import studio3 from "./messages/studio-3.json";
import misc1 from "./messages/misc-1.json";
import misc2 from "./messages/misc-2.json";
import runtime from "./messages/runtime.json";

const PARTS: Record<string, string>[] = [
  shell as Record<string, string>,
  canvas1 as Record<string, string>,
  canvas2 as Record<string, string>,
  canvas3 as Record<string, string>,
  canvas4 as Record<string, string>,
  orchestrator1 as Record<string, string>,
  orchestrator2 as Record<string, string>,
  orchestrator3 as Record<string, string>,
  orchestrator4 as Record<string, string>,
  admin as Record<string, string>,
  studio1 as Record<string, string>,
  studio2 as Record<string, string>,
  studio3 as Record<string, string>,
  misc1 as Record<string, string>,
  misc2 as Record<string, string>,
  runtime as Record<string, string>,
];

export const MESSAGES: Record<string, string> = Object.assign({}, ...PARTS);

export const translator: Translator = createTranslator(MESSAGES);

/** Перевести одну строку. Для кода вне React (toasts, title и т.п.). */
export function translateText(text: string, lang: Lang): string {
  return translator.translate(text, lang);
}
