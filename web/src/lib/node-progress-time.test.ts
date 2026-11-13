import test from "node:test";
import assert from "node:assert/strict";
import { formatRelativeTime } from "./utils.ts";

test("formatRelativeTime: свежее обновление — только что", () => {
  const now = new Date();
  assert.equal(formatRelativeTime(now.toISOString()), "только что");
});

test("formatRelativeTime: секунды назад", () => {
  const past = new Date(Date.now() - 35 * 1000);
  assert.equal(formatRelativeTime(past.toISOString()), "35 сек назад");
});

test("formatRelativeTime: минуты назад", () => {
  const past = new Date(Date.now() - 3 * 60 * 1000);
  assert.equal(formatRelativeTime(past.toISOString()), "3 мин назад");
});

test("formatRelativeTime: часы назад", () => {
  const past = new Date(Date.now() - 2 * 3600 * 1000);
  assert.equal(formatRelativeTime(past.toISOString()), "2 ч назад");
});

test("formatRelativeTime: пустые и невалидные даты дают прочерк", () => {
  assert.equal(formatRelativeTime(null), "—");
  assert.equal(formatRelativeTime(undefined), "—");
  assert.equal(formatRelativeTime("not-a-date"), "—");
});
