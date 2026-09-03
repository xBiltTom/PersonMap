"use client";

import { useEffect, useState, useMemo, useCallback } from "react";
import {
  ReactFlow,
  Background,
  Controls,
  MiniMap,
  useNodesState,
  useEdgesState,
  NodeProps,
  Handle,
  Position,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { GraphResponse, GraphNode } from "@/lib/types";
import { getInvestigationGraph } from "@/lib/api";
import {
  User,
  Mail,
  GraduationCap,
  FileText,
  Search,
  ExternalLink,
  ShieldCheck,
  Globe,
  Code2,
  Briefcase,
  AtSign,
  Share2,
  AlertTriangle,
  Phone,
  Filter,
  Layers,
} from "lucide-react";

// Platform Icon Helper
function getPlatformIcon(platform?: string | null, type?: string) {
  const p = (platform || "").toLowerCase();
  if (type === "breach") return <AlertTriangle className="w-3.5 h-3.5 text-rose-400" />;
  if (type === "phone") return <Phone className="w-3.5 h-3.5 text-violet-400" />;
  if (p.includes("github")) return <Code2 className="w-3.5 h-3.5 text-slate-200" />;
  if (p.includes("instagram")) return <Share2 className="w-3.5 h-3.5 text-pink-400" />;
  if (p.includes("twitter") || p.includes("x_twitter")) return <AtSign className="w-3.5 h-3.5 text-sky-400" />;
  if (p.includes("linkedin")) return <Briefcase className="w-3.5 h-3.5 text-blue-400" />;
  if (p.includes("openalex") || type === "academic") return <GraduationCap className="w-3.5 h-3.5 text-emerald-400" />;
  if (type === "email") return <Mail className="w-3.5 h-3.5 text-amber-400" />;
  if (type === "document") return <FileText className="w-3.5 h-3.5 text-violet-400" />;
  if (type === "search_mention") return <Search className="w-3.5 h-3.5 text-sky-300" />;
  return <Globe className="w-3.5 h-3.5 text-slate-400" />;
}

// 1. Root Person Node Component
function PersonRootNode({ data }: { data: any }) {
  const meta = (data.metadata_info || {}) as Record<string, any>;
  return (
    <div className="px-4 py-3 rounded-lg bg-[#152033] border-2 border-sky-400 shadow-xl shadow-sky-950/50 min-w-[200px] text-center">
      <Handle type="source" position={Position.Bottom} className="!bg-sky-400 !w-2 !h-2" />
      <Handle type="target" position={Position.Top} className="!bg-sky-400 !w-2 !h-2" />
      
      <div className="w-10 h-10 rounded-full bg-sky-500/20 border border-sky-400/40 flex items-center justify-center mx-auto mb-2 text-sky-300">
        <User className="w-5 h-5" />
      </div>
      <div className="text-xs font-bold text-slate-100 font-mono tracking-tight truncate">
        {String(data.label || "")}
      </div>
      {meta.university && (
        <div className="text-[10px] text-sky-300/80 font-mono truncate mt-0.5">
          {String(meta.university)}
        </div>
      )}
      <div className="text-[9px] font-mono uppercase tracking-widest text-sky-400 mt-1 font-semibold">
        Identidad Objetivo
      </div>
    </div>
  );
}

// 2. Satellite Entity Node Component
function CustomEntityNode({ data, selected }: { data: any; selected?: boolean }) {
  const isHighConf = Number(data.confidence || 0) >= 0.70;
  const isVerified = Boolean(data.verified);
  const isBreach = data.entity_type === "breach";
  const isPhone = data.entity_type === "phone";
  const platform = String(data.platform || data.entity_type || "");

  return (
    <div
      className={`px-3 py-2.5 rounded-lg border transition-all min-w-[170px] max-w-[220px] shadow-lg ${
        selected
          ? "border-sky-400 ring-2 ring-sky-500/20 bg-[#162030]"
          : isBreach
          ? "border-rose-500/70 bg-[#210d14] ring-1 ring-rose-500/20 text-rose-200"
          : isPhone
          ? "border-violet-500/50 bg-[#161224]"
          : isVerified
          ? "border-emerald-500/50 bg-[#0f1b1a]"
          : isHighConf
          ? "border-[#2c3d59] hover:border-sky-500/50 bg-[#111722]"
          : "border-[#1e293b] bg-[#111722] opacity-85"
      }`}
    >
      <Handle type="target" position={Position.Top} className="!bg-slate-500 !w-1.5 !h-1.5" />
      <Handle type="source" position={Position.Bottom} className="!bg-slate-500 !w-1.5 !h-1.5" />

      <div className="flex items-center justify-between mb-1.5">
        <div className="flex items-center gap-1.5 truncate">
          {getPlatformIcon(data.platform, data.entity_type)}
          <span className="text-[10px] font-mono text-slate-400 uppercase tracking-wider truncate">
            {platform}
          </span>
        </div>

        <span
          className={`text-[9px] font-mono font-bold px-1.5 py-0.5 rounded ${
            isVerified
              ? "bg-emerald-500/20 text-emerald-300"
              : isHighConf
              ? "bg-sky-500/10 text-sky-400"
              : "bg-amber-500/10 text-amber-400"
          }`}
        >
          {intPercent(Number(data.confidence || 0))}
        </span>
      </div>

      <div className="text-xs font-semibold text-slate-200 truncate" title={String(data.label || "")}>
        {String(data.label || "")}
      </div>

      {data.display_name && data.display_name !== data.label && (
        <div className="text-[10px] text-slate-400 truncate mt-0.5">
          {String(data.display_name)}
        </div>
      )}
    </div>
  );
}

function intPercent(val: number): string {
  return `${Math.round((val || 0) * 100)}%`;
}

export function DigitalMapGraph({ investigationId }: { investigationId: string }) {
  const [allNodes, setAllNodes] = useState<any[]>([]);
  const [allEdges, setAllEdges] = useState<any[]>([]);
  const [nodes, setNodes, onNodesChange] = useNodesState<any>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState<any>([]);
  const [loading, setLoading] = useState(true);
  const [selectedNode, setSelectedNode] = useState<any>(null);
  const [activeCategory, setActiveCategory] = useState<string>("all");

  const nodeTypes = useMemo(
    () => ({
      personRoot: PersonRootNode,
      customEntity: CustomEntityNode,
    }),
    []
  );

  const loadGraph = useCallback(async () => {
    try {
      setLoading(true);
      const data: GraphResponse = await getInvestigationGraph(investigationId);
      setAllNodes(data.nodes);
      setAllEdges(data.edges);
      setNodes(data.nodes);
      setEdges(data.edges);
    } catch (err) {
      console.error("Error loading graph", err);
    } finally {
      setLoading(false);
    }
  }, [investigationId, setNodes, setEdges]);

  useEffect(() => {
    loadGraph();
  }, [loadGraph]);

  // Apply layer filtering
  useEffect(() => {
    if (activeCategory === "all") {
      setNodes(allNodes);
      setEdges(allEdges);
      return;
    }

    const filteredNodes = allNodes.filter(
      (n) => n.type === "personRoot" || n.data.entity_type === activeCategory
    );
    const visibleNodeIds = new Set(filteredNodes.map((n) => n.id));
    const filteredEdges = allEdges.filter(
      (e) => visibleNodeIds.has(e.source) && visibleNodeIds.has(e.target)
    );

    setNodes(filteredNodes);
    setEdges(filteredEdges);
  }, [activeCategory, allNodes, allEdges, setNodes, setEdges]);

  const onNodeClick = useCallback((_: any, node: any) => {
    setSelectedNode(node);
  }, []);

  const handleExportGraphJson = () => {
    const data = { nodes: allNodes, edges: allEdges };
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `graph-${investigationId}.json`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const categories = [
    { id: "all", label: "Todas las Capas" },
    { id: "social_account", label: "Redes Sociales" },
    { id: "email", label: "Correos" },
    { id: "breach", label: "Brechas (Leaks)" },
    { id: "phone", label: "Telefonía" },
    { id: "academic", label: "Académico" },
  ];

  return (
    <div className="h-[680px] w-full panel-card relative flex flex-col overflow-hidden border border-[#1e293b]">
      {/* Top Filter Bar */}
      <div className="px-4 py-3 bg-[#0d131f] border-b border-[#212f45] flex flex-wrap items-center justify-between gap-3 z-10">
        <div className="flex items-center gap-2 overflow-x-auto">
          <div className="flex items-center gap-1.5 text-xs font-mono font-bold text-sky-400 bg-sky-950/40 px-2.5 py-1 rounded border border-sky-500/30 shrink-0">
            <Filter className="w-3.5 h-3.5" />
            <span>FILTRAR CAPAS:</span>
          </div>
          {categories.map((cat) => (
            <button
              key={cat.id}
              onClick={() => setActiveCategory(cat.id)}
              className={`text-xs font-mono px-3 py-1 rounded-md transition-all whitespace-nowrap cursor-pointer ${
                activeCategory === cat.id
                  ? "bg-sky-500 text-white font-bold shadow-md shadow-sky-950 border border-sky-400"
                  : "bg-[#151e2c] text-slate-300 hover:text-white hover:bg-[#1e2b3e] border border-[#2b3a52]"
              }`}
            >
              {cat.label}
            </button>
          ))}
        </div>

        <div className="flex items-center gap-3">
          <span className="text-xs font-mono font-bold text-emerald-400 bg-emerald-950/40 px-2.5 py-1 rounded border border-emerald-500/30">
            {nodes.length} nodos activos
          </span>
          <button
            onClick={handleExportGraphJson}
            title="Exportar topología de grafo en JSON"
            className="text-xs font-mono px-3 py-1 rounded-md bg-[#182334] hover:bg-[#223148] text-slate-200 border border-[#2b3a52] transition-colors cursor-pointer"
          >
            Exportar Grafo (JSON)
          </button>
        </div>
      </div>

      {/* React Flow Canvas */}
      <div className="flex-1 h-full relative">
        {loading ? (
          <div className="absolute inset-0 flex items-center justify-center bg-[#0b0f17]/80 z-20 text-xs font-mono text-slate-400">
            <span className="w-4 h-4 border-2 border-sky-400/30 border-t-sky-400 rounded-full animate-spin mr-2"></span>
            Construyendo mapa de relaciones...
          </div>
        ) : null}

        <ReactFlow
          nodes={nodes}
          edges={edges}
          nodeTypes={nodeTypes}
          onNodesChange={onNodesChange}
          onEdgesChange={onEdgesChange}
          onNodeClick={onNodeClick}
          fitView
          fitViewOptions={{ padding: 0.2 }}
          minZoom={0.2}
          maxZoom={1.5}
        >
          <Background color="#1e293b" gap={20} size={1} />
          <Controls className="!bg-[#121824] !border-[#212d40] !text-slate-200" />
          <MiniMap
            className="!bg-[#0d121c] !border-[#1e293b] rounded-md"
            nodeColor={(n) => (n.type === "personRoot" ? "#38bdf8" : "#334155")}
          />
        </ReactFlow>
      </div>

      {/* Detail Slideout for Clicked Entity */}
      {selectedNode && (
        <div className="w-80 border-l border-[#1e293b] bg-[#0e131d] p-4 overflow-y-auto shrink-0 animate-in slide-in-from-right duration-200">
          <div className="flex items-center justify-between pb-3 border-b border-[#1e293b] mb-4">
            <h4 className="text-xs font-mono font-bold text-slate-200 uppercase tracking-wider">
              Detalle de Entidad
            </h4>
            <button
              onClick={() => setSelectedNode(null)}
              className="text-xs font-mono text-slate-500 hover:text-slate-300"
            >
              Cerrar ✕
            </button>
          </div>

          <div className="space-y-3 text-xs">
            <div>
              <span className="text-[10px] font-mono text-slate-500 uppercase block">Tipo y Plataforma</span>
              <span className="font-semibold text-slate-200">
                {selectedNode.data.platform || selectedNode.data.entity_type}
              </span>
            </div>

            <div>
              <span className="text-[10px] font-mono text-slate-500 uppercase block">Valor / Enlace</span>
              {selectedNode.data.value?.startsWith("http") ? (
                <a
                  href={selectedNode.data.value}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-sky-400 hover:underline flex items-center gap-1 break-all mt-0.5"
                >
                  <span className="truncate">{selectedNode.data.value}</span>
                  <ExternalLink className="w-3 h-3 shrink-0" />
                </a>
              ) : (
                <span className="font-mono text-slate-300 break-all">{selectedNode.data.value}</span>
              )}
            </div>

            <div>
              <span className="text-[10px] font-mono text-slate-500 uppercase block">Nivel de Confianza</span>
              <span className="font-mono text-emerald-400 font-bold">
                {intPercent(selectedNode.data.confidence)}
              </span>
            </div>

            {selectedNode.data.metadata_info?.bio && (
              <div>
                <span className="text-[10px] font-mono text-slate-500 uppercase block">Biografía / Snippet</span>
                <p className="text-slate-300 text-[11px] mt-0.5 bg-[#141b28] p-2 rounded border border-[#1e293b]">
                  {selectedNode.data.metadata_info.bio}
                </p>
              </div>
            )}

            {selectedNode.data.metadata_info?.extracted_emails?.length > 0 && (
              <div>
                <span className="text-[10px] font-mono text-slate-500 uppercase block">Correos Extraídos</span>
                <ul className="list-disc list-inside text-sky-400 text-[11px] mt-0.5">
                  {selectedNode.data.metadata_info.extracted_emails.map((em: string) => (
                    <li key={em}>{em}</li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
