import test from "node:test";
import assert from "node:assert/strict";
import { createTranslator } from "./translator.ts";

const t = createTranslator({
  "Проекты": "Projects",
  "Сохранить": "Save",
  "Шаг {} из {}": "Step {} of {}",
  "· {} кадров": "· {} frames",
  "{} мин": "{} min",
  "Ошибка: {}": "Error: {}",
});

test("переводит точное совпадение", () => {
  assert.equal(t.translate("Проекты", "en"), "Projects");
});

test("неизвестную строку оставляет как есть", () => {
  assert.equal(t.translate("Неизвестная строка", "en"), "Неизвестная строка");
});

test("русский режим ничего не меняет", () => {
  assert.equal(t.translate("Проекты", "ru"), "Проекты");
  assert.equal(t.translate("Шаг 3 из 10", "ru"), "Шаг 3 из 10");
});

test("латиницу и цифры не трогает", () => {
  assert.equal(t.translate("GPT-5 · 4:3", "en"), "GPT-5 · 4:3");
});

test("сохраняет пробелы по краям", () => {
  assert.equal(t.translate(" Сохранить ", "en"), " Save ");
});

test("подставляет значения в {}", () => {
  assert.equal(t.translate("Шаг 3 из 10", "en"), "Step 3 of 10");
  assert.equal(t.translate("· 12 кадров", "en"), "· 12 frames");
  assert.equal(t.translate("5 мин", "en"), "5 min");
});

test("шаблон с числом и подписью", () => {
  // Переводится только литеральная часть, данные пользователя остаются как есть.
  assert.equal(t.translate("Ошибка: файл не найден", "en"), "Error: файл не найден");
  assert.equal(t.translate("Ошибка: 404", "en"), "Error: 404");
});

test("двойное написание показывает обе формы", () => {
  assert.equal(t.translate("Проекты", "both"), "Проекты · Projects");
  assert.equal(t.translate("Шаг 3 из 10", "both"), "Шаг 3 из 10 · Step 3 of 10");
});

test("более специфичный шаблон выигрывает", () => {
  const specific = createTranslator({
    "{} мин": "{} min",
    "{} мин назад": "{} min ago",
  });
  assert.equal(specific.translate("5 мин назад", "en"), "5 min ago");
});
