import assert from "node:assert/strict";
import test from "node:test";
import { readFile, writeFile, mkdtemp, rm } from "node:fs/promises";
import { dirname, resolve, join } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import ts from "typescript";
import { getReconstruction, buildReconstruction, ApiError } from "../src/lib/api.ts";
import { filterReconstructionGraph, reconstructionDetails, reconstructionPositions, visibleReconstruction,
  reconstructionNextStep } from "../src/lib/reconstructionState.ts";
import type { DigitalFootprintReconstruction, ReconstructionFact, ReconstructionRelation, ReconstructionReport } from "../src/lib/types.ts";

function fact(id: string, kind: ReconstructionFact["kind"], group: ReconstructionFact["group"], ring: number): ReconstructionFact {
  return { id, kind, group, ring, label: kind === "account" ? "instagram · @shared" : kind, basis: kind === "subject" ? "DECLARED" : "OBSERVED",
    platform: kind === "account" || kind === "post" ? "instagram" : null, url: null, safe_summary: "Fuente atribuida y minimizada.",
    ownership_basis: kind === "account" ? "subject_confirmed" : null, source_tools: [], source_entity_ids: [], source_content_ids: [],
    evidence_refs: ["evidence:1"], evidence_count: 1, evidence_types: ["reviewed_entity"], severity: kind === "exposure" ? "high" : null, date: null };
}
const nodes = [fact("subject:1", "subject", "identity", 0), fact("alias:shared", "alias", "identity", 1),
  fact("account:1", "account", "accounts", 2), fact("account:2", "account", "accounts", 2),
  fact("post:1", "post", "content", 3), fact("exposure:1", "exposure", "exposure", 4)];
const edge: ReconstructionRelation = { id: "edge:1", source: "account:1", target: "account:2", type: "SAME_ALIAS", basis: "CORRELATED",
  why: "Ambas cuentas atribuidas usan @shared. La revisión determina la atribución.", evidence_refs: ["evidence:1"],
  evidence_count: 1, evidence_types: ["reviewed_entity"], source_entity_ids: [], source_content_ids: [] };
const snapshot: DigitalFootprintReconstruction = {
  version: 1, reconstruction_version: "reconstruction-v1", investigation_id: "fixture", dataset_hash: "dataset",
  exposure_dataset_hash: "dataset", exposure_hash: "exposure", input_hash: "input", coverage: "partial", coverage_reasons: ["acquisition_partial"],
  identity: { declared: ["alias:shared"], accounts: ["account:1", "account:2"], public_identifiers: ["alias:shared"],
    academic_presence: [], documents: [], public_content: ["post:1"], breach_exposure: [] },
  facts: nodes, evidence: { "evidence:1": { id: "evidence:1", source_type: "reviewed_entity", source_entity_ids: [], source_content_ids: [],
    url: "https://example.org/profile", platform: "instagram", excerpt: "Perfil confirmado por el sujeto." } }, correlations: [edge],
  summary: [{ text: "La huella contiene dos cuentas atribuidas.", fact_ids: ["account:1", "account:2"] }], counts: { account: 2, alias: 1, post: 1, exposure: 1 },
  content_by_platform: { instagram: 1 }, exposure_summary: { high: 1, medium: 0, low: 0, informational: 0 },
  timeline: [{ id: "timeline:1", date: "2026-10-01", kind: "post", label: "Publicación pública", platform: "instagram",
    fact_ids: ["post:1"], evidence_refs: ["evidence:1"], basis: "OBSERVED" }],
  graph: { version: "graph-v2", nodes, edges: [edge], omitted_nodes: 0, omitted_by_type: {} }, generated_at: "2026-10-16T00:00:00Z",
};
const pending: ReconstructionReport = { version: 1, investigation_id: "fixture", status: "pending", stale: false,
  cache_hit: false, input_hash: null, current_input_hash: "input", snapshot: null };

// Transpile the real presentational TSX with the installed TypeScript compiler.
// No new test/runtime dependency, browser or UI implementation copy is needed.
async function component(name: string) {
  const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
  const directory = await mkdtemp(join(root, "tests/.reconstruction-render-"));
  const source = await readFile(join(root, `src/components/reconstruction/${name}.tsx`), "utf8");
  const compiled = ts.transpileModule(source, { compilerOptions: { jsx: ts.JsxEmit.ReactJSX, module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 } }).outputText
    .replace('"../../lib/reconstructionState.ts"', JSON.stringify(pathToFileURL(join(root, "src/lib/reconstructionState.ts")).href));
  const path = join(directory, `${name}.mjs`);
  await writeFile(path, compiled);
  try { return (await import(pathToFileURL(path).href))[name]; }
  finally { await rm(directory, { recursive: true, force: true }); }
}

test("pending and stale snapshots stay hidden; missing prerequisites give the correct next action", () => {
  assert.equal(visibleReconstruction(pending), null);
  assert.equal(visibleReconstruction({ ...pending, status: "completed", snapshot, stale: true }), null);
  assert.equal(visibleReconstruction({ ...pending, status: "partial", snapshot }), snapshot);
  assert.equal(reconstructionNextStep("exposure_report_stale")?.path, "exposure");
  assert.equal(reconstructionNextStep("review_not_finalized")?.path, "review");
});

test("pending build, in-progress button and stale Exposure recovery render correctly", async () => {
  const Status = await component("ReconstructionStatus");
  const props = { report: pending, error: null, building: false, investigationId: "fixture", onBuild() {} };
  const html = renderToStaticMarkup(createElement(Status, props));
  assert.match(html, /Construir reconstrucción/);
  assert.match(html, /lista para reconstruir/);
  const busy = renderToStaticMarkup(createElement(Status, { ...props, building: true }));
  assert.match(busy, /disabled/); assert.match(busy, /Construyendo/);
  const stale = renderToStaticMarkup(createElement(Status, { ...props, error: { code: "exposure_report_stale", message: "Exposure cambió" } }));
  assert.match(stale, /Reanalizar Exposure Lens/); assert.match(stale, /\/investigation\/fixture\/exposure/);
  assert.doesNotMatch(stale, /Construir reconstrucción/);
});

test("graph filters remove excluded types and all dangling edges", () => {
  const graph = filterReconstructionGraph(snapshot.graph, ["identity", "content"]);
  assert.deepEqual(graph.nodes.map(n => n.id), ["subject:1", "alias:shared", "post:1"]);
  assert.deepEqual(graph.edges, []);
  const correlated = filterReconstructionGraph(snapshot.graph, ["accounts"], "CORRELATED");
  assert.equal(correlated.nodes.length, 1);
});

test("ring layout is stable and subject stays centered", () => {
  const positions = reconstructionPositions(snapshot.graph);
  assert.deepEqual(positions.get("subject:1"), { x: -100, y: -38 });
  assert.deepEqual(positions, reconstructionPositions({ ...snapshot.graph, nodes: [...nodes].reverse() }));
});

test("node selection displays attribution and evidence; edge selection explains correlation", async () => {
  const Details = await component("ReconstructionDetails");
  const node = reconstructionDetails(snapshot, { kind: "node", id: "account:1" });
  assert.equal(node?.evidence[0].excerpt, "Perfil confirmado por el sujeto.");
  const html = renderToStaticMarkup(createElement(Details, { snapshot, selection: { kind: "node", id: "account:1" } }));
  assert.match(html, /confirmada por el sujeto/); assert.match(html, /Ver evidencia/);
  const edgeHtml = renderToStaticMarkup(createElement(Details, { snapshot, selection: { kind: "edge", id: "edge:1" } }));
  assert.match(edgeHtml, /CORRELATED/); assert.match(edgeHtml, /Ambas cuentas atribuidas/);
  assert.equal(reconstructionDetails(snapshot, { kind: "node", id: "rejected" }), null);
});

test("partial coverage, factual narrative and safe timeline appear; rejected and uncertain are absent", async () => {
  const Sections = await component("ReconstructionSections");
  const html = renderToStaticMarkup(createElement(Sections, { snapshot }));
  assert.match(html, /Cobertura parcial/); assert.match(html, /únicamente las fuentes observadas/);
  assert.match(html, /La huella contiene dos cuentas atribuidas/); assert.match(html, /2026-10-01/);
  assert.doesNotMatch(html, /rejected|uncertain|08:10|martes/);
});

test("build uses explicit POST; GET only observes; stale errors preserve the backend code", async () => {
  const original = globalThis.fetch;
  const requests: Array<{ url: string; method: string }> = [];
  globalThis.fetch = (async (url, init = {}) => {
    requests.push({ url: String(url), method: init.method || "GET" });
    if (requests.length === 3) return new Response(JSON.stringify({ detail: { code: "exposure_report_stale", message: "Reanaliza Exposure Lens" } }), { status: 409 });
    return new Response(JSON.stringify(pending), { status: 200 });
  }) as typeof fetch;
  try {
    await getReconstruction("fixture"); await buildReconstruction("fixture");
    await assert.rejects(getReconstruction("fixture"), e => e instanceof ApiError && e.code === "exposure_report_stale");
  } finally { globalThis.fetch = original; }
  assert.deepEqual(requests.slice(0, 2).map(r => [new URL(r.url).pathname, r.method]), [
    ["/api/v1/investigations/fixture/reconstruction", "GET"],
    ["/api/v1/investigations/fixture/reconstruction/build", "POST"],
  ]);
});

test("AI highlights remain factual and its fallback is explicit", async () => {
  const Sections = await component("ReconstructionSections");
  const html = renderToStaticMarkup(createElement(Sections, { snapshot: {
    ...snapshot, narrative_method: "ai_assisted", narrative_status: "completed",
    narrative_highlights: [{ text: "Publicación colaborativa observada.", fact_ids: ["post:1"] }],
  } }));
  assert.match(html, /organizada con IA/);
  assert.match(html, /Publicación colaborativa observada/);
  const fallback = renderToStaticMarkup(createElement(Sections, { snapshot: {
    ...snapshot, narrative_status: "fallback",
  } }));
  assert.match(fallback, /La IA no respondió/);
});

test("review, Exposure and reconstruction share the workstation type and panel palette", async () => {
  const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
  for (const file of ["review/VerificationGate.module.css", "exposure/ExposureLens.module.css", "reconstruction/ReconstructionView.module.css"]) {
    const css = await readFile(join(root, "src/components", file), "utf8");
    assert.doesNotMatch(css, /Georgia|Times New Roman/);
    assert.match(css, /#0d1420|var\(--panel/);
    assert.match(css, /#38bdf8/);
  }
});
