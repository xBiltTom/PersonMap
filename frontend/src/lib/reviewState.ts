import type { InvestigationReviewData, ReviewDecisionValue } from "./types";

/** Immediate UI projection while the explicit decision is being persisted. */
export function applyReviewDecision(
  review: InvestigationReviewData,
  candidateId: string,
  decision: ReviewDecisionValue,
): InvestigationReviewData {
  const candidates = review.candidates.map((candidate) => candidate.id === candidateId
    ? { ...candidate, decision, decided_at: new Date().toISOString() }
    : candidate);
  return {
    ...review,
    review_status: "in_progress",
    finalized_at: null,
    candidates,
    counts: {
      pending: candidates.filter((candidate) => candidate.decision === null).length,
      confirmed: candidates.filter((candidate) => candidate.decision === "confirmed").length,
      rejected: candidates.filter((candidate) => candidate.decision === "rejected").length,
      uncertain: candidates.filter((candidate) => candidate.decision === "uncertain").length,
    },
  };
}

export function canFinalizeReview(acquisitionFinished: boolean, pendingCount: number): boolean {
  return acquisitionFinished && pendingCount === 0;
}
