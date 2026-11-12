import assert from "node:assert/strict";
import { test } from "node:test";

import {
  assignExcelGptSlots,
  declaredExcelGptSlot,
  EXCEL_GPT_MAX_SLOTS,
  type ExcelGptSlotNode,
} from "./excel-gpt-slots.ts";

/**
 * Слот ноды «ИИ-редактор сцен» — её связь с шагом DAG, а НЕ место на
 * холсте. Раньше номера считались по позиции X, и перетаскивание ноды 2
 * левее ноды 1 меняло её слот на 1 — нода работала под статусом чужого
 * слота (дефект E аудита).
 */

function node(
  id: string,
  opts: { slot?: number; x?: number; sdAgent?: string; overflow?: boolean } = {},
): ExcelGptSlotNode {
  const data: Record<string, unknown> = { label: "ИИ-редактор сцен" };
  if (opts.slot !== undefined) data.slotIndex = opts.slot;
  if (opts.sdAgent !== undefined) data.sd_agent = opts.sdAgent;
  if (opts.overflow !== undefined) data.slotOverflow = opts.overflow;
  return {
    id,
    type: "excel_gpt",
    position: { x: opts.x ?? 0, y: 0 },
    data,
  };
}

test("явный слот сохраняется при перестановке нод на холсте", () => {
  const nodes = [
    node("n_excel_gpt_2", { slot: 2, x: 100 }),
    node("n_excel_gpt_1", { slot: 1, x: 2000 }),
  ];
  const slots = assignExcelGptSlots(nodes);
  assert.equal(slots.get("n_excel_gpt_2"), 2);
  assert.equal(slots.get("n_excel_gpt_1"), 1);
});

test("нода без слота получает свободный слот", () => {
  const nodes = [node("n_a", { slot: 1, x: 2000 }), node("n_b", { x: 100 })];
  const slots = assignExcelGptSlots(nodes);
  assert.equal(slots.get("n_a"), 1);
  assert.equal(slots.get("n_b"), 2);
});

test("дубль явного слота не перенумеровывается молча", () => {
  // Молчаливая починка означала бы, что нода 2 тихо становится нодой 1.
  // Дубль должен дойти до серверной валидации (HTTP 400 «перенумеруйте ноды»).
  const nodes = [node("n_a", { slot: 2, x: 100 }), node("n_b", { slot: 2, x: 2000 })];
  const slots = assignExcelGptSlots(nodes);
  assert.equal(slots.get("n_a"), 2);
  assert.equal(slots.get("n_b"), 2);
});

test("слотов сверх пяти не хватает — лишние ноды без слота", () => {
  const nodes = Array.from({ length: 6 }, (_, i) => node(`n_${i + 1}`, { x: i * 100 }));
  const slots = assignExcelGptSlots(nodes);
  const used = [...slots.values()].sort((a, b) => a - b);
  assert.deepEqual(used, [1, 2, 3, 4, 5]);
  assert.equal(slots.size, EXCEL_GPT_MAX_SLOTS);
  assert.equal(slots.has("n_6"), false);
});

test("агенты веера и закреплённые overflow-ноды слоты не занимают", () => {
  const nodes = [
    node("n_agent", { sdAgent: "characters", slot: 2, x: 100 }),
    node("n_over", { overflow: true, slot: 2, x: 200 }),
    node("n_a", { slot: 1, x: 300 }),
  ];
  const slots = assignExcelGptSlots(nodes);
  assert.equal(slots.has("n_agent"), false);
  assert.equal(slots.has("n_over"), false);
  assert.equal(slots.get("n_a"), 1);
});

test("явный слот читается и из строки", () => {
  assert.equal(declaredExcelGptSlot({ id: "x", type: "excel_gpt", data: { slotIndex: "2" } }), 2);
  assert.equal(declaredExcelGptSlot({ id: "x", type: "excel_gpt", data: { slotIndex: 2 } }), 2);
  // Вне 1..5 и мусор — слот не заявлен (не тихий «слот 1»).
  assert.equal(declaredExcelGptSlot({ id: "x", type: "excel_gpt", data: { slotIndex: 0 } }), undefined);
  assert.equal(declaredExcelGptSlot({ id: "x", type: "excel_gpt", data: { slotIndex: 99 } }), undefined);
  assert.equal(declaredExcelGptSlot({ id: "x", type: "excel_gpt", data: { slotIndex: "abc" } }), undefined);
  assert.equal(declaredExcelGptSlot({ id: "x", type: "excel_gpt", data: {} }), undefined);
});
