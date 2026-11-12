/**
 * Слоты нод «Работа с GPT» (excel_gpt): раздача 1..5.
 *
 * Слот — это СВЯЗЬ ноды с шагом DAG, а не её место на холсте. Раньше номера
 * считались по позиции X, и перетаскивание ноды «ИИ-редактор сцен 2» левее
 * ноды 1 меняло её слот на 1 — нода работала под статусом чужого слота
 * (дефект E аудита).
 *
 * Правила (те же, что на бэкенде, `app/services/excel_gpt_node.py`):
 * - явный валидный слот (1..5) СОХРАНЯЕТСЯ;
 * - ноды без слота получают свободные слоты;
 * - дубль явного слота НЕ перенумеровывается молча — его ловит серверная
 *   валидация графа (HTTP 400 «перенумеруйте ноды»);
 * - слотов всего 5: лишние ноды — overflow (`slotOverflow`, без `slotIndex`);
 * - агенты веера (`sd_agent`) и закреплённые overflow-ноды слоты не занимают.
 *
 * Модуль намеренно без алиасов `@/…` — чтобы его можно было тестировать
 * штатным `npm run test:unit` (node --experimental-strip-types).
 */

export const EXCEL_GPT_MAX_SLOTS = 5;

export type ExcelGptSlotNode = {
  id: string;
  type: string;
  position?: { x?: number; y?: number };
  data?: Record<string, unknown>;
};

/** Слот, заявленный нодой явно (1..5), или undefined. */
export function declaredExcelGptSlot(node: ExcelGptSlotNode): number | undefined {
  const raw = node.data?.slotIndex;
  if (typeof raw === "number" && Number.isInteger(raw) && raw >= 1 && raw <= EXCEL_GPT_MAX_SLOTS) {
    return raw;
  }
  if (typeof raw === "string" && /^\d+$/.test(raw.trim())) {
    const parsed = Number.parseInt(raw.trim(), 10);
    if (parsed >= 1 && parsed <= EXCEL_GPT_MAX_SLOTS) return parsed;
  }
  return undefined;
}

/** Агент веера сцены — слоты enrich не занимает. */
function isSceneAgent(node: ExcelGptSlotNode): boolean {
  const data = node.data ?? {};
  return typeof data.sd_agent === "string" || typeof data.agent === "string";
}

/** Нода, закреплённая вне слотов (проверки scene-веера). */
function isOverflowPinned(node: ExcelGptSlotNode): boolean {
  return node.data?.slotOverflow === true;
}

export function isExcelGptSlotNode(node: ExcelGptSlotNode): boolean {
  return node.type === "excel_gpt" && !isSceneAgent(node) && !isOverflowPinned(node);
}

/**
 * Раздать слоты 1..5 между нодами «Работа с GPT».
 *
 * Возвращает карту `node id → слот`. Ноды, которым слот не достался
 * (слотов меньше, чем нод), в карте отсутствуют — их кладут в overflow.
 */
export function assignExcelGptSlots(
  nodes: ExcelGptSlotNode[],
): Map<string, number> {
  const slotById = new Map<string, number>();
  const taken = new Set<number>();
  const excel = nodes.filter(isExcelGptSlotNode);

  // Сначала явные слоты — они источник истины.
  for (const n of excel) {
    const slot = declaredExcelGptSlot(n);
    if (slot === undefined) continue;
    slotById.set(n.id, slot);
    taken.add(slot);
  }

  // Ноды без слота — по свободным слотам, в порядке позиции на холсте.
  const free = Array.from({ length: EXCEL_GPT_MAX_SLOTS }, (_, i) => i + 1).filter(
    (s) => !taken.has(s),
  );
  const withoutSlot = excel
    .filter((n) => !slotById.has(n.id))
    .sort((a, b) => (a.position?.x ?? 0) - (b.position?.x ?? 0));
  withoutSlot.forEach((n, i) => {
    const slot = free[i];
    if (slot === undefined) return; // слотов не хватило — нода уйдёт в overflow
    slotById.set(n.id, slot);
  });

  return slotById;
}
