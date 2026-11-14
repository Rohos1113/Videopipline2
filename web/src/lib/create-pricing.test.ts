/**
 * Тесты цен Create: в UI только доллары с наценкой студии 25%, токенов нет.
 */

import assert from "node:assert/strict";
import test from "node:test";

import {
  catalogPriceUsdClient,
  estimateCreatePrice,
  tokensToUsdClient,
  TOKEN_USD,
} from "./create-pricing.ts";

test("create-pricing: 1 токен = $0.10 база, клиенту ×1.25", () => {
  assert.equal(TOKEN_USD, 0.1);
  assert.equal(tokensToUsdClient(4), 0.5);
  assert.equal(tokensToUsdClient(0.8), 0.1);
  assert.equal(tokensToUsdClient(14), 1.75);
});

test("create-pricing: подпись и Veo 3.1 Lite — только доллары (4 ток → $0.50)", () => {
  const est = estimateCreatePrice({ media: "video", model: "veo-3-1-lite", duration: 10 });
  assert.equal(est.tokens, 4);
  assert.equal(est.usd, 0.4);
  assert.equal(est.usdClient, 0.5);
  assert.equal(est.label, "$0.50");
  assert.ok(!/ток|кр/i.test(est.label));
});

test("create-pricing: GPT Image 2 — 2K = 0.8 ток → $0.10, 1K → $0.06", () => {
  const k2 = estimateCreatePrice({ media: "image", model: "gpt-image-2", resolution: "2K" });
  assert.equal(k2.tokens, 0.8);
  assert.equal(k2.label, "$0.10");
  const k1 = estimateCreatePrice({ media: "image", model: "gpt-image-2", resolution: "1K" });
  assert.equal(k1.label, "$0.06");
});

test("create-pricing: sora-2 учитывает длительность и размер", () => {
  assert.equal(estimateCreatePrice({ media: "video", model: "sora-2", duration: 10 }).label, "$0.10");
  assert.equal(
    estimateCreatePrice({ media: "video", model: "sora-2", duration: 15, size: "large" }).label,
    "$0.30",
  );
});

test("create-pricing: цена каталога в токенах → клиентские $ («от 3» → $0.38)", () => {
  assert.equal(catalogPriceUsdClient("от 3"), 0.375);
  assert.equal(catalogPriceUsdClient("3"), 0.375);
  assert.equal(catalogPriceUsdClient("от 0.03"), 0.0375);
  assert.equal(catalogPriceUsdClient(null), null);
  assert.equal(catalogPriceUsdClient("—"), null);
});
