#!/usr/bin/env node
// Поиск русских строк интерфейса, которых нет в словаре.
//
//   node web/src/i18n/tools/extract.mjs            # все найденные строки (TSV)
//   node web/src/i18n/tools/extract.mjs --missing  # только отсутствующие в словаре
//
// Формат TSV: <русский текст>\t<вид>\t<файл:строка>
// Вид: jsx-text — текст в разметке, exact — строковый литерал, template — шаблон с {}.
//
// Нужен только для разработки: в сборку не попадает, typecheck его не видит.

import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const ts = require("typescript");

const here = path.dirname(fileURLToPath(import.meta.url));
const SRC = path.resolve(here, "../..");
const MESSAGES = path.resolve(here, "..", "messages");

const CYR = /[\u0400-\u04FF]/;
const MAX_LEN = 300;
const SKIP_FILES = new Set(["lib/orchestratorDomPurify.ts"]);

function normalize(text) {
  return text.replace(/\u00a0/g, " ").replace(/\s+/g, " ").trim();
}

function collectFiles(dir, out) {
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      if (entry.name === "node_modules" || entry.name === ".next" || entry.name === "messages" || entry.name === "tools") continue;
      collectFiles(full, out);
    } else if (/\.tsx?$/.test(entry.name) && !/\.test\.tsx?$/.test(entry.name) && !/\.d\.ts$/.test(entry.name)) {
      out.push(full);
    }
  }
  return out;
}

function dictionaryKeys() {
  const keys = new Set();
  for (const file of fs.readdirSync(MESSAGES)) {
    if (!file.endsWith(".json")) continue;
    for (const key of Object.keys(JSON.parse(fs.readFileSync(path.join(MESSAGES, file), "utf8")))) {
      keys.add(normalize(key));
    }
  }
  return keys;
}

function scan() {
  const rows = [];
  for (const full of collectFiles(SRC, [])) {
    const rel = path.relative(SRC, full).split(path.sep).join("/");
    if (SKIP_FILES.has(rel)) continue;
    const code = fs.readFileSync(full, "utf8");
    const sf = ts.createSourceFile(full, code, ts.ScriptTarget.ES2022, true, full.endsWith(".tsx") ? ts.ScriptKind.TSX : ts.ScriptKind.TS);
    const lineOf = (node) => sf.getLineAndCharacterOfPosition(node.getStart(sf)).line + 1;
    const add = (text, kind, node) => {
      const value = normalize(text);
      if (!value || !CYR.test(value) || value.length > MAX_LEN) return;
      rows.push({ text: value, kind, where: `${rel}:${lineOf(node)}` });
    };
    const visit = (node) => {
      if (ts.isJsxText(node)) add(node.text, "jsx-text", node);
      if (ts.isStringLiteral(node) || ts.isNoSubstitutionTemplateLiteral(node)) {
        const parent = node.parent;
        const skipped =
          !parent ||
          ts.isImportDeclaration(parent) ||
          ts.isExportDeclaration(parent) ||
          ts.isImportSpecifier(parent) ||
          (ts.isPropertyAssignment(parent) && parent.name === node) ||
          (ts.isPropertyAccessExpression(parent) && parent.name === node) ||
          (ts.isCallExpression(parent) && /^(console\.|logger\.|log\.)/.test(parent.expression.getText(sf)));
        if (!skipped) add(node.text, "exact", node);
      }
      if (ts.isTemplateExpression(node)) {
        let out = node.head.text;
        for (const span of node.templateSpans) out += "{}" + span.literal.text;
        if (CYR.test(out)) add(out, "template", node);
      }
      ts.forEachChild(node, visit);
    };
    visit(sf);
  }
  // дедуп: первое вхождение, счётчик
  const map = new Map();
  for (const row of rows) {
    const seen = map.get(row.text);
    if (seen) seen.count += 1;
    else map.set(row.text, { ...row, count: 1 });
  }
  return [...map.values()].sort((a, b) => b.count - a.count || a.text.localeCompare(b.text, "ru"));
}

const onlyMissing = process.argv.includes("--missing");
const keys = onlyMissing ? dictionaryKeys() : null;
const rows = scan().filter((row) => (onlyMissing ? !keys.has(row.text) : true));

for (const row of rows) process.stdout.write(`${row.text}\t${row.kind}\t${row.where}\t${row.count}\n`);
process.stderr.write(`\nстрок: ${rows.length}${onlyMissing ? " (нет в словаре)" : ""}\n`);
