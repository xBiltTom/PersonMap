"use client";

import { memo, useMemo, useState } from "react";
import { ReactFlow, Handle, Position, MarkerType, Controls, Background, type Node, type NodeProps } from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { PlatformIcon } from "../graph/PlatformIcon";
import { useWorkstation } from "@/context/WorkstationContext";
import { ReconstructionDetails } from "./ReconstructionDetails";
import { GRAPH_GROUPS, GROUP_COLOR, SEVERITY_COLOR, filterReconstructionGraph, reconstructionPositions,
  type GraphSelection } from "../../lib/reconstructionState";
import type { DigitalFootprintReconstruction, ReconstructionFact, ReconstructionGroup } from "../../lib/types";

type FootprintNode = Node<{ fact: ReconstructionFact }, "footprint">;
const LIGHT_GROUP_COLOR: Record<ReconstructionGroup, string> = {
  identity: "var(--color-accent-strong)",
  accounts: "var(--color-success)",
  content: "var(--color-ink-muted)",
  documents: "var(--color-ink-muted)",
  breaches: "var(--color-ai)",
  exposure: "var(--color-warning)",
};
const LIGHT_SEVERITY_COLOR = {
  high: "var(--color-danger)",
  medium: "var(--color-warning)",
  low: "var(--color-success)",
  informational: "var(--color-accent-strong)",
};

const FootprintNodeView = memo(function FootprintNodeView({ data, selected }: NodeProps<FootprintNode>) {
  const { theme } = useWorkstation();
  const fact = data.fact;
  const color = theme === "light"
    ? fact.kind === "exposure" && fact.severity ? LIGHT_SEVERITY_COLOR[fact.severity] : LIGHT_GROUP_COLOR[fact.group]
    : fact.kind === "exposure" && fact.severity ? SEVERITY_COLOR[fact.severity] : GROUP_COLOR[fact.group];
  return <div className="reconstruction-node" data-kind={fact.kind} data-selected={selected}
    style={{ borderColor: color }}>
    <Handle type="target" position={Position.Top} isConnectable={false} />
    <span className="reconstruction-node-type" style={{ color }}>{fact.platform || fact.kind}</span>
    <strong>{fact.kind === "account" && <PlatformIcon platform={fact.platform} className="w-4 h-4" />}{fact.label}</strong>
    <small>{fact.basis}{fact.kind === "exposure" && fact.severity ? ` · ${fact.severity}` : ""}</small>
    <Handle type="source" position={Position.Bottom} isConnectable={false} />
  </div>;
});
const nodeTypes = { footprint: FootprintNodeView };
const ALL_GROUPS = Object.keys(GRAPH_GROUPS) as ReconstructionGroup[];

export default function ReconstructionGraph({ snapshot }: { snapshot: DigitalFootprintReconstruction }) {
  const { theme } = useWorkstation();
  const [groups, setGroups] = useState<ReconstructionGroup[]>(ALL_GROUPS);
  const [selection, setSelection] = useState<GraphSelection>(null);
  const positions = useMemo(() => reconstructionPositions(snapshot.graph), [snapshot.graph]);
  const visible = useMemo(() => filterReconstructionGraph(snapshot.graph, groups), [snapshot.graph, groups]);
  const nodes = useMemo<FootprintNode[]>(() => visible.nodes.map(fact => ({
    id: fact.id, type: "footprint", position: positions.get(fact.id) || { x: 0, y: 0 },
    data: { fact }, ariaLabel: fact.label + ", " + fact.basis, selected: selection?.kind === "node" && selection.id === fact.id,
  })), [visible.nodes, positions, selection]);
  const edges = useMemo(() => visible.edges.map(relation => ({
    id: relation.id, source: relation.source, target: relation.target,
    selected: selection?.kind === "edge" && selection.id === relation.id,
    label: selection?.id === relation.id ? relation.type.replaceAll("_", " ") : undefined,
    ariaLabel: relation.type + ", " + relation.basis,
    style: { stroke: relation.type === "HAS_EXPOSURE_SIGNAL" ? (theme === "light" ? "var(--color-warning)" : "#fbbf24") : (theme === "light" ? "var(--color-ink-faint)" : "#64748b"), strokeWidth: selection?.id === relation.id ? 3 : 1.3 },
    markerEnd: { type: MarkerType.ArrowClosed, color: relation.type === "HAS_EXPOSURE_SIGNAL" ? (theme === "light" ? "var(--color-warning)" : "#fbbf24") : (theme === "light" ? "var(--color-ink-faint)" : "#64748b") },
    interactionWidth: 24,
  })), [visible.edges, selection, theme]);
  function toggle(group: ReconstructionGroup) {
    setGroups(current => current.includes(group) ? current.filter(g => g !== group) : [...current, group]);
    setSelection(null);
  }
  return <section className="reconstruction-panel" aria-labelledby="graph-title">
    <h2 id="graph-title">Cómo se conecta tu huella</h2>
    <p>Sujeto → identificadores → perfiles → artefactos → exposición. Selecciona elementos para consultar la evidencia.</p>
    <fieldset className="reconstruction-filters"><legend>Capas del grafo</legend>
      {ALL_GROUPS.map(group => <label key={group}><input type="checkbox" checked={groups.includes(group)} onChange={() => toggle(group)} />
        <span style={{ color: theme === "light" ? LIGHT_GROUP_COLOR[group] : GROUP_COLOR[group] }}>●</span> {GRAPH_GROUPS[group]}</label>)}
    </fieldset>
    <div className="reconstruction-graph-layout">
      <div className="reconstruction-canvas" role="region" aria-label="Graph V2 interactivo">
        <ReactFlow<FootprintNode> nodes={nodes} edges={edges} nodeTypes={nodeTypes} fitView
          minZoom={0.05} maxZoom={2} nodesDraggable={false} nodesConnectable={false}
          onNodeClick={(_, node) => setSelection({ kind: "node", id: node.id })}
          onEdgeClick={(_, edge) => setSelection({ kind: "edge", id: edge.id })}
          onPaneClick={() => setSelection(null)} onlyRenderVisibleElements colorMode={theme}
          proOptions={{ hideAttribution: true }}>
          <Background color="var(--color-edge)" gap={32} /><Controls showInteractive={false} />
        </ReactFlow>
      </div>
      <ReconstructionDetails snapshot={snapshot} selection={selection} />
    </div>
    <p className="reconstruction-legend">DECLARED · declarado por el sujeto / OBSERVED · explícito en la fuente / CORRELATED · relación entre hechos / INFERRED · inferencia marcada (no emitida en esta versión).</p>
    {snapshot.graph.omitted_nodes > 0 && <p role="status">Vista limitada: {snapshot.graph.omitted_nodes} nodos quedan fuera del grafo. Los totales describen el registro de hechos completo.</p>}
  </section>;
}
