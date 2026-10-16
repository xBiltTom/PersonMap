import assert from "node:assert/strict";
import test from "node:test";
import { mkdtemp, readFile, writeFile, rm } from "node:fs/promises";
import { join, resolve, dirname } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import ts from "typescript";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { investigationExecution } from "../src/lib/investigationPolicy.ts";
import { fairCoverage } from "../src/lib/fairCoverage.ts";

async function component(name: string) {
  const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
  const dir = await mkdtemp(join(root, "tests/.lite-render-"));
  const text = await readFile(join(root, `src/components/investigation/${name}.tsx`), "utf8");
  const code = ts.transpileModule(text, { compilerOptions: { jsx: ts.JsxEmit.ReactJSX,
    module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 } }).outputText
    .replace('"../../lib/fairCoverage.ts"', JSON.stringify(pathToFileURL(join(root, "src/lib/fairCoverage.ts")).href));
  const file = join(dir, name + ".mjs");
  await writeFile(file, code);
  try { return (await import(pathToFileURL(file).href))[name]; }
  finally { await rm(dir, { recursive: true, force: true }); }
}

for (const scanMode of ["fast", "deep", "all"] as const) {
  test(`Lite ignores legacy ${scanMode} options and always requests Fair`, () => {
    const payload = investigationExecution("lite", { strategy: "agentic", scanMode, extract: true, enrich: true });
    assert.deepEqual(payload, { acquisition_mode: "fair", strategy: "rule_based" });
    assert.equal("maigret_plan" in payload, false);
  });
}

test("normal mode retains its existing explicit options", () => {
  assert.deepEqual(investigationExecution("normal", { strategy: "hybrid", scanMode: "all", extract: true, enrich: false }),
    { acquisition_mode: "normal", strategy: "hybrid", maigret_plan: { scan_mode: "all", options: { parse: true, enrich: false } } });
});

test("coverage distinguishes empty search results, missing inputs and timeout", async () => {
  const metrics = { fair_snapshot: { sources: {
    search_dorker: { status: "completed", findings_count: 0 },
    academic_finder: { status: "not_applicable", findings_count: 0 },
    username_finder: { status: "timeout", findings_count: 0 },
    apify_social: { status: "completed", findings_count: 2 },
  } } };
  const rows = fairCoverage(metrics);
  assert.equal(rows.find(r => r.key === "apify_social")?.count, 2);
  assert.match(rows.find(r => r.key === "academic_finder")?.note || "", /nombre completo/);
  const Coverage = await component("FairCoverage");
  const html = renderToStaticMarkup(createElement(Coverage, { metrics }));
  assert.match(html, /SearchDorker/); assert.match(html, /OpenAlex/); assert.match(html, /Apify/);
  assert.match(html, /Tiempo agotado/); assert.match(html, /2 hallazgos/);
});

test("Lite keeps infostealers and email enumeration visible with explicit coverage", async () => {
  const metrics = { fair_progress: { sources: {
    infostealer_checker: { status: "skipped", findings_count: 0, reason: "subject_consent_required" },
    email_enumerator: { status: "completed", findings_count: 3 },
    ghunt: { status: "provider_unavailable", findings_count: 0 },
  } } };
  const rows = fairCoverage(metrics);
  assert.match(rows.find(r => r.key === "infostealer_checker")?.note || "", /autorizar/);
  assert.equal(rows.find(r => r.key === "email_enumerator")?.count, 3);
  const Coverage = await component("FairCoverage");
  const html = renderToStaticMarkup(createElement(Coverage, { metrics }));
  assert.match(html, /infostealers/); assert.match(html, /Enumeración de correo/);
  assert.match(html, /Fuentes públicas de Google/); assert.match(html, /3 hallazgos/);
});

test("web progress distinguishes query count from finding count", () => {
  const rows = fairCoverage({ fair_progress: { sources: {
    search_dorker: { status: "running", findings_count: 6, queries_used: 20, query_budget: 60 },
  } } });
  assert.equal(rows.find(r => r.key === "search_dorker")?.queryProgress, "20/60 consultas web");
  assert.equal(rows.find(r => r.key === "search_dorker")?.count, 6);
});
