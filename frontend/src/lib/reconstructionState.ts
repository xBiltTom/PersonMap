import type { ReconstructionBasis, ReconstructionGraph, ReconstructionGroup, ReconstructionReport,
  DigitalFootprintReconstruction } from "./types.ts";

export const GRAPH_GROUPS: Record<ReconstructionGroup, string> = {
  identity: "Identidad", accounts: "Cuentas", content: "Contenido",
  documents: "Documentos", breaches: "Brechas e infostealers", exposure: "Exposición",
};
export const GROUP_COLOR: Record<ReconstructionGroup, string> = {
  identity: "#38bdf8", accounts: "#34d399", content: "#94a3b8",
  documents: "#94a3b8", breaches: "#a855f7", exposure: "#fbbf24",
};
export const SEVERITY_COLOR = { high: "#f87171", medium: "#fbbf24", low: "#34d399", informational: "#38bdf8" };

export function filterReconstructionGraph(graph: ReconstructionGraph, groups: ReconstructionGroup[], basis?: ReconstructionBasis) {
  const nodes = graph.nodes.filter(n => n.kind === "subject" || (groups.includes(n.group) && (!basis || n.basis === basis)));
  const ids = new Set(nodes.map(n => n.id));
  return { ...graph, nodes, edges: graph.edges.filter(e => ids.has(e.source) && ids.has(e.target) && (!basis || e.basis === basis)) };
}

/** Stable ring layout is computed for the full graph, so filters don't move nodes. */
export function reconstructionPositions(graph: ReconstructionGraph) {
  const positions = new Map<string, { x: number; y: number }>();
  let priorRadius = 0;
  for (let ring = 0; ring <= 4; ring++) {
    const nodes = graph.nodes.filter(n => n.ring === ring).sort((a, b) => a.id.localeCompare(b.id));
    const radius = ring === 0 ? 0 : Math.max(priorRadius + 370, nodes.length * 240 / (2 * Math.PI));
    priorRadius = radius;
    nodes.forEach((n, index) => {
      const angle = index / Math.max(nodes.length, 1) * 2 * Math.PI - Math.PI / 2;
      positions.set(n.id, { x: Math.cos(angle) * radius - 100, y: Math.sin(angle) * radius - 38 });
    });
  }
  return positions;
}

export type GraphSelection = { kind: "node" | "edge"; id: string } | null;
export function reconstructionDetails(snapshot: DigitalFootprintReconstruction, selection: GraphSelection) {
  if (!selection) return null;
  const item = selection.kind === "node" ? snapshot.graph.nodes.find(n => n.id === selection.id) :
    snapshot.graph.edges.find(e => e.id === selection.id);
  if (!item) return null;
  return { item, evidence: item.evidence_refs.map(ref => snapshot.evidence[ref]).filter(Boolean) };
}

export function visibleReconstruction(report: ReconstructionReport | null) {
  return report && !report.stale && (report.status === "completed" || report.status === "partial") ? report.snapshot : null;
}
export function reconstructionNextStep(code?: string) {
  if (code === "review_not_finalized") return { path: "review", label: "Finalizar revisión" };
  if (code === "exposure_report_stale") return { path: "exposure", label: "Reanalizar Exposure Lens" };
  if (code === "exposure_analysis_required") return { path: "exposure", label: "Analizar Exposure Lens" };
  return null;
}
