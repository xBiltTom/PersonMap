import assert from "node:assert/strict";
import test from "node:test";
import { applyReviewDecision } from "../src/lib/reviewState.ts";
import { decideReviewCandidate, finalizeInvestigationReview, getInvestigationReview, getReviewedFootprint } from "../src/lib/api.ts";
import type { InvestigationReviewData, ReviewCandidate } from "../src/lib/types.ts";

const candidate = (id: string, decision: ReviewCandidate["decision"] = null): ReviewCandidate => ({
  id,
  entity_type: "social_account",
  category: "account",
  platform: "instagram",
  value: `https://instagram.com/${id}`,
  username: id,
  display_name: id,
  institutions: [],
  reason: "Perfil detectado automáticamente.",
  sources: [{ name: "SearchDorker", evidence_urls: ["https://example.org/result"] }],
  evidence_urls: ["https://example.org/result"],
  provenance: { origin: "automatic", status: "discovered", subject_asserted: false,
    matches_declared_identifier: false, evidence_urls: [], needs_review: true },
  decision,
});

const review = (): InvestigationReviewData => ({
  version: 1,
  investigation_id: "investigation-1",
  review_status: "not_started",
  finalized_at: null,
  counts: { pending: 2, confirmed: 0, rejected: 0, uncertain: 0 },
  declared_seeds: [{ kind: "username", value: "pepito", platform: "instagram",
    provenance: { origin: "subject", status: "declared", subject_asserted: true,
      matches_declared_identifier: false, evidence_urls: [], needs_review: false } }],
  candidates: [candidate("pepito_alt"), candidate("pepito_other")],
  fair: { acquisition_finished: true, partial: false, sources: {}, social_sources: {} },
});

test("Confirm click projection moves the candidate into confirmed", () => {
  const next = applyReviewDecision(review(), "pepito_alt", "confirmed");
  assert.equal(next.candidates[0].decision, "confirmed");
  assert.deepEqual(next.counts, { pending: 1, confirmed: 1, rejected: 0, uncertain: 0 });
});

test("Reject and uncertain choices stay distinct", () => {
  const rejected = applyReviewDecision(review(), "pepito_alt", "rejected");
  const uncertain = applyReviewDecision(review(), "pepito_other", "uncertain");
  assert.equal(rejected.candidates[0].decision, "rejected");
  assert.equal(rejected.counts.rejected, 1);
  assert.equal(uncertain.candidates[1].decision, "uncertain");
  assert.equal(uncertain.counts.uncertain, 1);
  assert.equal(uncertain.counts.confirmed, 0);
});

test("A saved choice can be changed and opens a finalized review again", () => {
  const finalized = { ...review(), review_status: "complete" as const, finalized_at: "2026-10-16T12:00:00Z",
    candidates: [candidate("pepito_alt", "confirmed"), candidate("pepito_other")],
    counts: { pending: 1, confirmed: 1, rejected: 0, uncertain: 0 } };
  const next = applyReviewDecision(finalized, "pepito_alt", "rejected");
  assert.equal(next.review_status, "in_progress");
  assert.equal(next.finalized_at, null);
  assert.deepEqual(next.counts, { pending: 1, confirmed: 0, rejected: 1, uncertain: 0 });
});

test("Unknown candidate IDs do not change counts", () => {
  const current = review();
  const next = applyReviewDecision(current, "missing", "confirmed");
  assert.deepEqual(next.counts, current.counts);
});

test("Declared seeds stay read-only and are not promoted into review candidates", () => {
  const current = review();
  const next = applyReviewDecision(current, "pepito_alt", "confirmed");
  assert.deepEqual(next.declared_seeds, current.declared_seeds);
  assert.equal(next.candidates.some((item) => item.username === "pepito"), false);
});

test("Review API requests use stable candidate IDs and send only a decision", async () => {
  const originalFetch = globalThis.fetch;
  const requests: Array<{ url: string; init: RequestInit }> = [];
  globalThis.fetch = (async (input, init = {}) => {
    requests.push({ url: String(input), init });
    return new Response("{}", { status: 200, headers: { "Content-Type": "application/json" } });
  }) as typeof fetch;
  try {
    await getInvestigationReview("investigation-1");
    await decideReviewCandidate("investigation-1", "entity-uuid", "confirmed");
    await finalizeInvestigationReview("investigation-1");
    await getReviewedFootprint("investigation-1");
  } finally {
    globalThis.fetch = originalFetch;
  }
  assert.deepEqual(requests.map((request) => new URL(request.url).pathname), [
    "/api/v1/investigations/investigation-1/review",
    "/api/v1/investigations/investigation-1/review/entity-uuid",
    "/api/v1/investigations/investigation-1/review/finalize",
    "/api/v1/investigations/investigation-1/reviewed-footprint",
  ]);
  assert.equal(requests[1].init.method, "PATCH");
  assert.deepEqual(JSON.parse(String(requests[1].init.body)), { decision: "confirmed" });
  assert.equal(requests[2].init.method, "POST");
  assert.equal(requests[2].init.body, undefined);
});
