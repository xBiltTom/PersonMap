"use client";

import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Background,
  BackgroundVariant,
  BaseEdge,
  EdgeLabelRenderer,
  getBezierPath,
  Handle,
  MiniMap,
  Panel,
  Position,
  ReactFlow,
  ReactFlowProvider,
  ViewportPortal,
  useReactFlow,
  type Edge,
  type EdgeProps,
  type Node,
  type NodeProps,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import {
  AlertTriangle,
  Braces,
  Check,
  ChevronDown,
  Eye,
  EyeOff,
  FileDown,
  Filter,
  Home,
  Image,
  Link2,
  Maximize2,
  Minimize2,
  Minus,
  Network,
  Plus,
  RotateCcw,
  Search,
  SlidersHorizontal,
  User,
} from "lucide-react";
import { getGraphmlUrl, getInvestigationGraph } from "@/lib/api";
import { buildEntityFilters, getEntityTypeMeta } from "@/lib/entityTypes";
import { layoutDigitalMap } from "@/lib/graphLayout";
import { getFriendlyRelationLabel, isProvenanceEdge } from "@/lib/graphSemantics";
import { getInspectorEvidenceFilters, getInspectorSearchText, type InspectorEvidenceFilter } from "@/lib/entityInspector";
import type { GraphEdge, GraphNode, GraphNodeData, GraphResponse } from "@/lib/types";
import { PlatformIcon } from "./PlatformIcon";
import { EntityInspector, RelationshipInspector } from "./EntityInspector";

// ---------------------------------------------------------------------
// Entity Theme Configuration (Matching img-referencia-mapa.png)
// ---------------------------------------------------------------------

interface EntityTheme {
  borderClass: string;
  glowShadow: string;
  accentText: string;
  badgeBg: string;
  dotColor: string;
}

function getEntityTheme(platform?: string | null, entityType?: string | null, value?: string | null): EntityTheme {
  const p = (platform || "").toLowerCase();
  const v = (value || "").toLowerCase();
  const t = (entityType || "").toLowerCase();

  // GitHub / Dev domain / Portfolio
  if (p.includes("github") || v.includes("github.com") || p.includes("portfolio")) {
    return {
      borderClass: "border-cyan-400",
      glowShadow: "0 0 22px rgba(6, 182, 212, 0.45)",
      accentText: "text-cyan-400",
      badgeBg: "bg-cyan-500/15 text-cyan-300 border-cyan-500/30",
      dotColor: "#22d3ee",
    };
  }

  // GitLab
  if (p.includes("gitlab") || v.includes("gitlab.com")) {
    return {
      borderClass: "border-amber-500",
      glowShadow: "0 0 22px rgba(245, 158, 11, 0.45)",
      accentText: "text-amber-400",
      badgeBg: "bg-amber-500/15 text-amber-300 border-amber-500/30",
      dotColor: "#f59e0b",
    };
  }

  // Twitter / X
  if (p.includes("twitter") || p.includes("x_twitter") || p === "x" || v.includes("x.com") || v.includes("twitter.com")) {
    return {
      borderClass: "border-cyan-300",
      glowShadow: "0 0 22px rgba(34, 211, 238, 0.45)",
      accentText: "text-cyan-300",
      badgeBg: "bg-cyan-400/15 text-cyan-200 border-cyan-400/30",
      dotColor: "#38bdf8",
    };
  }

  // Instagram
  if (p.includes("instagram") || v.includes("instagram.com")) {
    return {
      borderClass: "border-fuchsia-500",
      glowShadow: "0 0 22px rgba(217, 70, 239, 0.45)",
      accentText: "text-fuchsia-400",
      badgeBg: "bg-fuchsia-500/15 text-fuchsia-300 border-fuchsia-500/30",
      dotColor: "#d946ef",
    };
  }

  // Reddit
  if (p.includes("reddit") || v.includes("reddit.com")) {
    return {
      borderClass: "border-orange-500",
      glowShadow: "0 0 22px rgba(249, 115, 22, 0.45)",
      accentText: "text-orange-400",
      badgeBg: "bg-orange-500/15 text-orange-300 border-orange-500/30",
      dotColor: "#f97316",
    };
  }

  // LinkedIn
  if (p.includes("linkedin") || v.includes("linkedin.com")) {
    return {
      borderClass: "border-blue-500",
      glowShadow: "0 0 22px rgba(59, 130, 246, 0.45)",
      accentText: "text-blue-400",
      badgeBg: "bg-blue-500/15 text-blue-300 border-blue-500/30",
      dotColor: "#3b82f6",
    };
  }

  // Gravatar / Identity
  if (p.includes("gravatar") || v.includes("gravatar.com")) {
    return {
      borderClass: "border-sky-400",
      glowShadow: "0 0 22px rgba(56, 189, 248, 0.45)",
      accentText: "text-sky-300",
      badgeBg: "bg-sky-500/15 text-sky-300 border-sky-500/30",
      dotColor: "#38bdf8",
    };
  }

  // YouTube
  if (p.includes("youtube") || v.includes("youtube.com")) {
    return {
      borderClass: "border-rose-500",
      glowShadow: "0 0 22px rgba(244, 63, 94, 0.45)",
      accentText: "text-rose-400",
      badgeBg: "bg-rose-500/15 text-rose-300 border-rose-500/30",
      dotColor: "#f43f5e",
    };
  }

  // Discord
  if (p.includes("discord") || v.includes("discord.com")) {
    return {
      borderClass: "border-indigo-400",
      glowShadow: "0 0 22px rgba(129, 140, 248, 0.45)",
      accentText: "text-indigo-300",
      badgeBg: "bg-indigo-500/15 text-indigo-300 border-indigo-500/30",
      dotColor: "#818cf8",
    };
  }

  // Stack Overflow
  if (p.includes("stackoverflow") || p.includes("stack overflow")) {
    return {
      borderClass: "border-amber-400",
      glowShadow: "0 0 22px rgba(251, 191, 36, 0.45)",
      accentText: "text-amber-300",
      badgeBg: "bg-amber-500/15 text-amber-300 border-amber-500/30",
      dotColor: "#fbbf24",
    };
  }

  // Dev.to
  if (p.includes("dev.to") || p === "dev" || v.includes("dev.to")) {
    return {
      borderClass: "border-purple-400",
      glowShadow: "0 0 22px rgba(168, 85, 247, 0.45)",
      accentText: "text-purple-300",
      badgeBg: "bg-purple-500/15 text-purple-300 border-purple-500/30",
      dotColor: "#a855f7",
    };
  }

  // Cloudflare / Netlify
  if (p.includes("cloudflare") || p.includes("netlify") || v.includes("cloudflare") || v.includes("netlify")) {
    return {
      borderClass: "border-teal-400",
      glowShadow: "0 0 22px rgba(45, 212, 191, 0.45)",
      accentText: "text-teal-300",
      badgeBg: "bg-teal-500/15 text-teal-300 border-teal-500/30",
      dotColor: "#2dd4bf",
    };
  }

  // Email
  if (t === "email" || v.includes("@")) {
    return {
      borderClass: "border-sky-400",
      glowShadow: "0 0 22px rgba(56, 189, 248, 0.45)",
      accentText: "text-sky-300",
      badgeBg: "bg-sky-500/15 text-sky-300 border-sky-500/30",
      dotColor: "#38bdf8",
    };
  }

  // Domain / Host
  if (t === "domain") {
    return {
      borderClass: "border-sky-400",
      glowShadow: "0 0 22px rgba(56, 189, 248, 0.45)",
      accentText: "text-sky-300",
      badgeBg: "bg-sky-500/15 text-sky-300 border-sky-500/30",
      dotColor: "#0ea5e9",
    };
  }

  // File Types
  const fileExtMatch = (v || "").match(/\.(pdf|docx?|odt|rtf|txt|xlsx?|csv|tsv|pptx?|zip|rar|7z|tar|gz|json|sql|xml|py|js|ts|html|css|png|jpe?g|gif|webp|svg)$/i);
  const ext = fileExtMatch ? fileExtMatch[1].toLowerCase() : null;

  if (ext === "pdf" || t === "document" || p.includes("pdf")) {
    return {
      borderClass: "border-rose-500",
      glowShadow: "0 0 22px rgba(244, 63, 94, 0.45)",
      accentText: "text-rose-400",
      badgeBg: "bg-rose-500/15 text-rose-300 border-rose-500/30",
      dotColor: "#f43f5e",
    };
  }

  if (ext && ["docx", "doc", "odt", "rtf", "txt"].includes(ext)) {
    return {
      borderClass: "border-blue-500",
      glowShadow: "0 0 22px rgba(59, 130, 246, 0.45)",
      accentText: "text-blue-400",
      badgeBg: "bg-blue-500/15 text-blue-300 border-blue-500/30",
      dotColor: "#3b82f6",
    };
  }

  if (ext && ["xlsx", "xls", "csv", "tsv"].includes(ext)) {
    return {
      borderClass: "border-emerald-500",
      glowShadow: "0 0 22px rgba(16, 185, 129, 0.45)",
      accentText: "text-emerald-400",
      badgeBg: "bg-emerald-500/15 text-emerald-300 border-emerald-500/30",
      dotColor: "#10b981",
    };
  }

  if (ext && ["pptx", "ppt", "key"].includes(ext)) {
    return {
      borderClass: "border-orange-500",
      glowShadow: "0 0 22px rgba(249, 115, 22, 0.45)",
      accentText: "text-orange-400",
      badgeBg: "bg-orange-500/15 text-orange-300 border-orange-500/30",
      dotColor: "#f97316",
    };
  }

  if (ext && ["zip", "rar", "7z", "tar", "gz"].includes(ext)) {
    return {
      borderClass: "border-amber-500",
      glowShadow: "0 0 22px rgba(245, 158, 11, 0.45)",
      accentText: "text-amber-400",
      badgeBg: "bg-amber-500/15 text-amber-300 border-amber-500/30",
      dotColor: "#f59e0b",
    };
  }

  if (ext && ["json", "xml", "sql", "py", "js", "ts", "html", "css", "sh"].includes(ext)) {
    return {
      borderClass: "border-purple-400",
      glowShadow: "0 0 22px rgba(168, 85, 247, 0.45)",
      accentText: "text-purple-300",
      badgeBg: "bg-purple-500/15 text-purple-300 border-purple-500/30",
      dotColor: "#a855f7",
    };
  }

  if (ext && ["png", "jpg", "jpeg", "gif", "webp", "svg"].includes(ext)) {
    return {
      borderClass: "border-fuchsia-400",
      glowShadow: "0 0 22px rgba(217, 70, 239, 0.45)",
      accentText: "text-fuchsia-300",
      badgeBg: "bg-fuchsia-500/15 text-fuchsia-300 border-fuchsia-500/30",
      dotColor: "#d946ef",
    };
  }

  // Academia / University
  if (t === "academic" || p.includes("universidad") || p.includes("unt") || v.includes("unt")) {
    return {
      borderClass: "border-slate-400",
      glowShadow: "0 0 20px rgba(148, 163, 184, 0.35)",
      accentText: "text-slate-300",
      badgeBg: "bg-slate-500/15 text-slate-300 border-slate-500/30",
      dotColor: "#94a3b8",
    };
  }

  // Location
  if (p.includes("trujillo") || p.includes("location") || v.includes("trujillo")) {
    return {
      borderClass: "border-rose-500",
      glowShadow: "0 0 22px rgba(244, 63, 94, 0.45)",
      accentText: "text-rose-400",
      badgeBg: "bg-rose-500/15 text-rose-300 border-rose-500/30",
      dotColor: "#f43f5e",
    };
  }

  // Breaches / Infostealer
  if (t === "breach" || t === "infostealer") {
    return {
      borderClass: "border-red-500",
      glowShadow: "0 0 22px rgba(239, 68, 68, 0.5)",
      accentText: "text-red-400",
      badgeBg: "bg-red-500/15 text-red-300 border-red-500/30",
      dotColor: "#ef4444",
    };
  }

  // Fallback
  return {
    borderClass: "border-slate-500/60",
    glowShadow: "0 0 16px rgba(100, 116, 139, 0.3)",
    accentText: "text-slate-300",
    badgeBg: "bg-slate-700/20 text-slate-300 border-slate-600/30",
    dotColor: "#64748b",
  };
}

// ---------------------------------------------------------------------
// Text formatting helper (matching exact labels in img-referencia-mapa.png)
// ---------------------------------------------------------------------

function getNodeDisplayNames(data: GraphNodeData): { title: string; subtitle: string } {
  const p = (data.platform || "").trim();
  const v = (data.value || "").trim();
  const d = (data.display_name || "").trim();
  const t = (data.entity_type || "").trim();

  // Email
  if (t === "email" || v.includes("@")) {
    return { title: v, subtitle: "" };
  }

  // File types detection (matches "PDF" / "CV_BiltonNeva.pdf" in img-referencia-mapa.png)
  const fileExtMatch = (v || d).match(/\.(pdf|docx?|odt|rtf|txt|xlsx?|csv|tsv|pptx?|zip|rar|7z|tar|gz|json|sql|xml|py|js|ts|html|css|png|jpe?g|gif|webp|svg)$/i);
  if (t === "document" || fileExtMatch) {
    const ext = fileExtMatch ? fileExtMatch[1].toUpperCase() : "DOC";
    const filename = v.split("/").pop() || d || v;
    return { title: ext, subtitle: filename };
  }

  // Domain
  if (t === "domain") {
    const cleanDomain = v.replace(/^https?:\/\//, "").replace(/\/$/, "");
    return { title: cleanDomain, subtitle: p && p !== "domain" ? p : "" };
  }

  // Location
  if (p.toLowerCase().includes("trujillo") || p.toLowerCase().includes("location") || v.toLowerCase().includes("trujillo")) {
    return { title: d || v || "Trujillo, Perú", subtitle: "" };
  }

  // University / Academic
  if (p.toLowerCase().includes("unt") || v.toLowerCase().includes("unt") || p.toLowerCase().includes("universidad")) {
    return { title: "Universidad", subtitle: d || v || "UNT" };
  }

  // Standard Platforms
  if (p) {
    let platformFormatted = p.charAt(0).toUpperCase() + p.slice(1);
    const pLow = p.toLowerCase();
    if (pLow === "x_twitter" || pLow === "twitter" || pLow === "x") {
      platformFormatted = "X (Twitter)";
    } else if (pLow === "stackoverflow") {
      platformFormatted = "Stack Overflow";
    } else if (pLow === "dev.to" || pLow === "dev") {
      platformFormatted = "Dev.to";
    } else if (pLow === "github") {
      platformFormatted = "GitHub";
    } else if (pLow === "gitlab") {
      platformFormatted = "GitLab";
    } else if (pLow === "linkedin") {
      platformFormatted = "Linkedin";
    } else if (pLow === "youtube") {
      platformFormatted = "YouTube";
    }

    let handle = d || v;
    if (handle.startsWith("http")) {
      try {
        const url = new URL(handle);
        handle = url.pathname.replace(/^\/+/, "").replace(/\/+$/, "") || url.hostname;
      } catch {
        // keep as is
      }
    }

    if ((pLow.includes("twitter") || pLow === "x") && !handle.startsWith("@")) {
      handle = `@${handle}`;
    } else if (pLow.includes("instagram") && !handle.startsWith("@")) {
      handle = `@${handle}`;
    } else if (pLow.includes("reddit") && !handle.startsWith("u/")) {
      handle = `u/${handle}`;
    } else if (pLow.includes("gravatar") && handle.length > 12) {
      handle = `hash:${handle.slice(0, 7)}...`;
    }

    return { title: platformFormatted, subtitle: handle };
  }

  return { title: d || v, subtitle: "" };
}

type MapFocusMode = "all" | "neighbors" | "two_hops";

function getFocusNodeIds(edges: GraphEdge[], selectedNodeId: string, depth: number): Set<string> {
  const visible = new Set([selectedNodeId]);
  let frontier = new Set([selectedNodeId]);
  for (let step = 0; step < depth; step += 1) {
    const next = new Set<string>();
    for (const edge of edges) {
      if (frontier.has(edge.source) && !visible.has(edge.target)) next.add(edge.target);
      if (frontier.has(edge.target) && !visible.has(edge.source)) next.add(edge.source);
    }
    next.forEach((nodeId) => visible.add(nodeId));
    frontier = next;
  }
  return visible;
}

/** Keep a factual, connected backbone at rest; full local evidence appears on interaction. */
function getEvidenceBackbone(edges: GraphEdge[]): GraphEdge[] {
  if (edges.length <= 120) return edges;

  const ordered = [...edges].sort(
    (a, b) =>
      Number(Boolean(b.supports_group)) - Number(Boolean(a.supports_group)) ||
      a.relation_type.localeCompare(b.relation_type) ||
      a.id.localeCompare(b.id)
  );
  const parents = new Map<string, string>();
  const degree = new Map<string, number>();
  const selected: GraphEdge[] = [];
  const selectedIds = new Set<string>();

  const find = (id: string): string => {
    const parent = parents.get(id) ?? id;
    if (parent === id) {
      parents.set(id, id);
      return id;
    }
    const root = find(parent);
    parents.set(id, root);
    return root;
  };

  const add = (edge: GraphEdge) => {
    selected.push(edge);
    selectedIds.add(edge.id);
    degree.set(edge.source, (degree.get(edge.source) ?? 0) + 1);
    degree.set(edge.target, (degree.get(edge.target) ?? 0) + 1);
  };

  for (const edge of ordered) {
    const sourceRoot = find(edge.source);
    const targetRoot = find(edge.target);
    if (sourceRoot === targetRoot) continue;
    parents.set(targetRoot, sourceRoot);
    add(edge);
  }

  for (const edge of ordered) {
    if (selected.length >= 140) break;
    if (selectedIds.has(edge.id)) continue;
    if ((degree.get(edge.source) ?? 0) >= 3 || (degree.get(edge.target) ?? 0) >= 3) continue;
    add(edge);
  }

  return selected;
}

// ---------------------------------------------------------------------
// Circular Handles for Nodes (4 cardinal directions)
// ---------------------------------------------------------------------

const HANDLE_DIRS = ["e", "s", "w", "n"] as const;

function NodePerimeterHandles({
  radius,
  centerX,
  centerY,
}: {
  radius: number;
  centerX: number;
  centerY: number;
}) {
  return (
    <>
      {HANDLE_DIRS.map((dir, idx) => {
        const angle = (idx * Math.PI) / 2;
        const hx = centerX + Math.cos(angle) * radius;
        const hy = centerY + Math.sin(angle) * radius;
        return (
          <React.Fragment key={dir}>
            <Handle
              id={`source-${dir}`}
              type="source"
              position={Position.Top}
              style={{ left: `${hx}px`, top: `${hy}px` }}
              className="!h-0 !w-0 !border-0 !bg-transparent !opacity-0 pointer-events-none"
            />
            <Handle
              id={`target-${dir}`}
              type="target"
              position={Position.Top}
              style={{ left: `${hx}px`, top: `${hy}px` }}
              className="!h-0 !w-0 !border-0 !bg-transparent !opacity-0 pointer-events-none"
            />
          </React.Fragment>
        );
      })}
    </>
  );
}

// Helper to determine best handle pair between source and target centers
function getBestHandlePair(
  srcX: number,
  srcY: number,
  tgtX: number,
  tgtY: number
): { sourceHandle: string; targetHandle: string } {
  const angle = Math.atan2(tgtY - srcY, tgtX - srcX);
  let octant = Math.round(angle / (Math.PI / 2));
  if (octant < 0) octant += 4;
  octant %= 4;

  const sourceDir = HANDLE_DIRS[octant];
  const targetDir = HANDLE_DIRS[(octant + 2) % 4];

  return {
    sourceHandle: `source-${sourceDir}`,
    targetHandle: `target-${targetDir}`,
  };
}

// ---------------------------------------------------------------------
// Custom Node Components
// ---------------------------------------------------------------------

interface DisplayNodeData extends GraphNodeData {
  interaction: "idle" | "focused" | "dimmed";
  isCorrelated: boolean;
}

type DisplayNode = Node<DisplayNodeData>;
type DisplayEdge = Edge<GraphEdge>;

const PersonRootNode = React.memo(function PersonRootNode({ data, selected }: NodeProps<DisplayNode>) {
  const metadata = data.metadata_info ?? {};
  const fullName = String(metadata.full_name || data.label || "Identidad Objetivo");

  return (
    <div className="relative flex h-[140px] w-[140px] select-none items-center justify-center">
      {/* Cardinal handles along the circular orb perimeter. */}
      <NodePerimeterHandles radius={62} centerX={70} centerY={70} />

      {/* Outer faint neon ring */}
      <div className="pointer-events-none absolute inset-[2px] rounded-full border border-cyan-400/25" />

      {/* Circular Glowing Orb */}
      <div
        style={{
          boxShadow: selected
            ? "0 0 50px rgba(6, 182, 212, 0.75), inset 0 0 30px rgba(6, 182, 212, 0.4)"
            : "0 0 35px rgba(6, 182, 212, 0.55), inset 0 0 22px rgba(6, 182, 212, 0.25)",
        }}
        className={`relative flex h-[124px] w-[124px] cursor-pointer flex-col items-center justify-center rounded-full border-2 bg-[#06121f] p-2 text-center transition-colors duration-150 ${
          selected ? "border-cyan-200" : "border-cyan-400 hover:border-cyan-300"
        }`}
      >
        <User className="mb-1 h-7 w-7 shrink-0 text-cyan-400" strokeWidth={1.8} aria-hidden="true" />
        <p className="line-clamp-2 max-w-[102px] font-mono text-[11px] font-bold leading-tight tracking-tight text-white">
          {fullName}
        </p>
        <span className="mt-1 inline-flex items-center rounded-full border border-cyan-400/60 bg-cyan-950/80 px-2 py-0.5 font-mono text-[8px] font-semibold uppercase tracking-widest text-cyan-300 shadow-sm">
          OBJETIVO
        </span>
      </div>
    </div>
  );
});

const CustomEntityNode = React.memo(function CustomEntityNode({ data, selected }: NodeProps<DisplayNode>) {
  const theme = getEntityTheme(data.platform, data.entity_type, data.value);
  const { title, subtitle } = getNodeDisplayNames(data);
  const isFocused = selected || data.interaction === "focused";

  return (
    <div className="relative flex h-[92px] w-[120px] select-none flex-col items-center justify-start">
      {/* Cardinal handles along the circular orb perimeter. */}
      <NodePerimeterHandles radius={26} centerX={60} centerY={26} />

      {/* Circular Orb at Top */}
      <div
        style={{
          boxShadow: isFocused
            ? `${theme.glowShadow}, 0 0 28px rgba(255, 255, 255, 0.25)`
            : theme.glowShadow,
        }}
        className={`relative flex h-[52px] w-[52px] cursor-pointer items-center justify-center overflow-hidden rounded-full border-2 bg-[#090e18] transition-transform duration-150 ${
          theme.borderClass
        } ${isFocused ? "scale-105 border-white/90" : "hover:scale-105"}`}
      >
        <PlatformIcon
          platform={data.platform}
          entityType={data.entity_type}
          value={data.value}
          displayName={data.display_name}
          avatarUrl={typeof data.metadata_info?.avatar_url === "string" ? data.metadata_info.avatar_url : undefined}
          className={`h-5 w-5 ${theme.accentText} transition-transform duration-150`}
        />

        {data.isCorrelated && (
          <span
            className="absolute -right-0.5 -top-0.5 h-2.5 w-2.5 rounded-full border-2 border-[#090e18] bg-cyan-400 shadow-[0_0_8px_rgba(34,211,238,0.8)]"
            title="Vinculado a otros hallazgos"
          />
        )}
      </div>

      {/* Centered Label Underneath Orb */}
      <div className="pointer-events-none mt-1.5 w-[116px] text-center">
        <p className="truncate font-sans text-[11px] font-semibold leading-tight text-slate-100" title={title}>
          {title}
        </p>
        {subtitle ? (
          <p className="mt-0.5 truncate font-mono text-[9px] leading-tight text-slate-400" title={subtitle}>
            {subtitle}
          </p>
        ) : null}
      </div>
    </div>
  );
});

// ---------------------------------------------------------------------
// Background Radar & Constellation Node
// ---------------------------------------------------------------------

function RadarBackgroundNode() {
  return (
    <div className="pointer-events-none absolute left-0 top-0 -z-10 -translate-x-1/2 -translate-y-1/2 select-none">
      <svg
        width="1800"
        height="1800"
        viewBox="-900 -900 1800 1800"
        className="pointer-events-none select-none overflow-visible"
      >
        <defs>
          <radialGradient id="radarGlow" cx="0" cy="0" r="1">
            <stop offset="0%" stopColor="#22d3ee" stopOpacity="0.07" />
            <stop offset="40%" stopColor="#22d3ee" stopOpacity="0.015" />
            <stop offset="80%" stopColor="#080e1a" stopOpacity="0" />
          </radialGradient>
        </defs>

        {/* Ambient center radial bloom */}
        <circle cx="0" cy="0" r="580" fill="url(#radarGlow)" />

        {/* Concentric radar rings matching img-referencia-mapa.png */}
        <circle cx="0" cy="0" r="160" fill="none" stroke="#22d3ee" strokeOpacity="0.10" strokeWidth="1" />
        <circle cx="0" cy="0" r="290" fill="none" stroke="#22d3ee" strokeOpacity="0.07" strokeWidth="1" strokeDasharray="4 6" />
        <circle cx="0" cy="0" r="450" fill="none" stroke="#22d3ee" strokeOpacity="0.05" strokeWidth="1" />
        <circle cx="0" cy="0" r="640" fill="none" stroke="#22d3ee" strokeOpacity="0.035" strokeWidth="1" strokeDasharray="6 8" />

        {/* 8-ray radar crosshair axes */}
        <line x1="-750" y1="0" x2="750" y2="0" stroke="#22d3ee" strokeOpacity="0.04" strokeWidth="1" />
        <line x1="0" y1="-750" x2="0" y2="750" stroke="#22d3ee" strokeOpacity="0.04" strokeWidth="1" />
        <line x1="-550" y1="-550" x2="550" y2="550" stroke="#22d3ee" strokeOpacity="0.025" strokeWidth="1" strokeDasharray="2 6" />
        <line x1="-550" y1="550" x2="550" y2="-550" stroke="#22d3ee" strokeOpacity="0.025" strokeWidth="1" strokeDasharray="2 6" />

        {/* Faint distant constellation stars */}
        <g stroke="#38bdf8" strokeOpacity="0.08" strokeWidth="0.75" fill="#38bdf8" fillOpacity="0.15">
          <circle cx="-380" cy="-280" r="2" />
          <circle cx="-420" cy="-210" r="1.5" />
          <line x1="-380" y1="-280" x2="-420" y2="-210" />

          <circle cx="340" cy="-310" r="2" />
          <circle cx="410" cy="-260" r="1.5" />
          <line x1="340" y1="-310" x2="410" y2="-260" />

          <circle cx="420" cy="280" r="2" />
          <circle cx="360" cy="360" r="1.5" />
          <line x1="420" y1="280" x2="360" y2="360" />

          <circle cx="-340" cy="380" r="2" />
          <circle cx="-400" cy="320" r="1.5" />
          <line x1="-340" y1="380" x2="-400" y2="320" />
        </g>
      </svg>
    </div>
  );
}

// ---------------------------------------------------------------------
// Custom Edge with Sleek Pill Badge (Matching img-referencia-mapa.png)
// ---------------------------------------------------------------------

const CustomEvidenceEdge = React.memo(function CustomEvidenceEdge({
  id,
  sourceX,
  sourceY,
  targetX,
  targetY,
  sourcePosition,
  targetPosition,
  style = {},
  markerEnd,
  label,
  selected,
}: EdgeProps) {
  const [edgePath, labelX, labelY] = getBezierPath({
    sourceX,
    sourceY,
    sourcePosition,
    targetX,
    targetY,
    targetPosition,
    curvature: 0.16,
  });

  return (
    <>
      <BaseEdge id={id} path={edgePath} style={style} markerEnd={markerEnd} />
      {label && (
        <EdgeLabelRenderer>
          <div
            style={{
              position: "absolute",
              transform: `translate(-50%, -50%) translate(${labelX}px,${labelY}px)`,
              pointerEvents: "all",
            }}
            className="nodrag nopan"
          >
            <span
              className={`inline-flex cursor-pointer select-none items-center rounded-full px-2.5 py-0.5 font-mono text-[9px] tracking-tight transition-colors duration-100 ${
                selected
                  ? "border border-cyan-400 bg-[#0a1424] text-cyan-200"
                  : "border border-slate-700/70 bg-[#080e1a]/95 text-slate-300 hover:border-cyan-400/70 hover:bg-[#0d1829] hover:text-cyan-200"
              }`}
            >
              {label}
            </span>
          </div>
        </EdgeLabelRenderer>
      )}
    </>
  );
});

// ---------------------------------------------------------------------
// Floating Zoom & Viewport Controls Next to MiniMap
// ---------------------------------------------------------------------

function ViewportToolbar({
  onToggleFullscreen,
  isFullscreen,
}: {
  onToggleFullscreen: () => void;
  isFullscreen: boolean;
}) {
  const { zoomIn, zoomOut, fitView } = useReactFlow();

  const handleZoomIn = (e: React.MouseEvent) => {
    e.preventDefault();
    e.stopPropagation();
    void zoomIn({ duration: 250 });
  };

  const handleZoomOut = (e: React.MouseEvent) => {
    e.preventDefault();
    e.stopPropagation();
    void zoomOut({ duration: 250 });
  };

  const handleFitView = (e: React.MouseEvent) => {
    e.preventDefault();
    e.stopPropagation();
    void fitView({ padding: 0.18, duration: 350 });
  };

  const handleFullscreen = (e: React.MouseEvent) => {
    e.preventDefault();
    e.stopPropagation();
    onToggleFullscreen();
  };

  return (
    <div
      className="nopan nodrag flex flex-col items-center gap-0.5 overflow-hidden rounded-lg border border-slate-700/80 bg-[#070e1a]/95 p-1 shadow-2xl backdrop-blur-md"
      onMouseDown={(e) => e.stopPropagation()}
      onPointerDown={(e) => e.stopPropagation()}
      onClick={(e) => e.stopPropagation()}
    >
      <button
        type="button"
        onClick={handleZoomIn}
        onMouseDown={(e) => e.stopPropagation()}
        className="nopan nodrag flex h-7 w-7 items-center justify-center rounded text-slate-300 transition-colors hover:bg-cyan-500/20 hover:text-cyan-200 active:scale-95"
        title="Acercar zoom (+)"
        aria-label="Acercar zoom"
      >
        <Plus className="h-4 w-4" />
      </button>

      <button
        type="button"
        onClick={handleZoomOut}
        onMouseDown={(e) => e.stopPropagation()}
        className="nopan nodrag flex h-7 w-7 items-center justify-center rounded text-slate-300 transition-colors hover:bg-cyan-500/20 hover:text-cyan-200 active:scale-95"
        title="Alejar zoom (−)"
        aria-label="Alejar zoom"
      >
        <Minus className="h-4 w-4" />
      </button>

      <div className="my-0.5 h-px w-4 bg-slate-700/80" />

      <button
        type="button"
        onClick={handleFitView}
        onMouseDown={(e) => e.stopPropagation()}
        className="nopan nodrag flex h-7 w-7 items-center justify-center rounded text-slate-300 transition-colors hover:bg-cyan-500/20 hover:text-cyan-200 active:scale-95"
        title="Restablecer / Centrar mapa (Home)"
        aria-label="Restablecer / Centrar mapa"
      >
        <Home className="h-3.5 w-3.5" />
      </button>

      <button
        type="button"
        onClick={handleFullscreen}
        onMouseDown={(e) => e.stopPropagation()}
        className="nopan nodrag flex h-7 w-7 items-center justify-center rounded text-slate-300 transition-colors hover:bg-cyan-500/20 hover:text-cyan-200 active:scale-95"
        title={isFullscreen ? "Salir de pantalla completa (Esc o F)" : "Pantalla completa (F)"}
        aria-label={isFullscreen ? "Salir de pantalla completa" : "Pantalla completa"}
      >
        {isFullscreen ? (
          <Minimize2 className="h-3.5 w-3.5 text-cyan-400" />
        ) : (
          <Maximize2 className="h-3.5 w-3.5" />
        )}
      </button>
    </div>
  );
}

// ---------------------------------------------------------------------
// Auto-fit on layout or category changes
// ---------------------------------------------------------------------

function FitToLayout({ layoutKey }: { layoutKey: string }) {
  const { fitView } = useReactFlow();

  useEffect(() => {
    const fitTimer = window.setTimeout(() => {
      void fitView({ padding: 0.16, duration: 400, maxZoom: 1.1 });
    }, 40);
    return () => window.clearTimeout(fitTimer);
  }, [fitView, layoutKey]);

  return null;
}

// ---------------------------------------------------------------------
// Main Component: DigitalMapGraph
// ---------------------------------------------------------------------

function DigitalMapGraphInner({
  investigationId,
  refreshKey,
  graphData,
  focusNodeId,
}: {
  investigationId: string;
  refreshKey?: string;
  /** `undefined` conserva la carga autónoma; `null` indica que la página la está cargando. */
  graphData?: GraphResponse | null;
  focusNodeId?: string | null;
}) {
  const [allNodes, setAllNodes] = useState<GraphNode[]>([]);
  const [allEdges, setAllEdges] = useState<GraphEdge[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [activeCategory, setActiveCategory] = useState("all");
  const [showDiscoveryLines, setShowDiscoveryLines] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");
  const [activeRelationTypes, setActiveRelationTypes] = useState<Set<string>>(() => new Set());
  const [activeEvidenceFilters, setActiveEvidenceFilters] = useState<Set<InspectorEvidenceFilter>>(() => new Set());
  const [focusMode, setFocusMode] = useState<MapFocusMode>("all");
  const [openFilterMenu, setOpenFilterMenu] = useState<"layers" | "relations" | "evidence" | "focus" | null>(null);
  const [hoveredNodeId, setHoveredNodeId] = useState<string | null>(null);
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [selectedEdgeId, setSelectedEdgeId] = useState<string | null>(null);
  const [isFullscreen, setIsFullscreen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);
  const { fitView, setCenter } = useReactFlow();

  const handleToggleFullscreen = useCallback(async () => {
    const container = containerRef.current;
    if (!container) return;

    try {
      if (!document.fullscreenElement) {
        if (container.requestFullscreen) {
          await container.requestFullscreen();
        } else {
          const webkitContainer = container as unknown as { webkitRequestFullscreen?: () => Promise<void> };
          if (webkitContainer.webkitRequestFullscreen) {
            await webkitContainer.webkitRequestFullscreen();
          } else {
            setIsFullscreen(true);
          }
        }
      } else {
        if (document.exitFullscreen) {
          await document.exitFullscreen();
        } else {
          const webkitDoc = document as unknown as { webkitExitFullscreen?: () => Promise<void> };
          if (webkitDoc.webkitExitFullscreen) {
            await webkitDoc.webkitExitFullscreen();
          } else {
            setIsFullscreen(false);
          }
        }
      }
    } catch (err) {
      console.warn("Fullscreen toggle warning (using overlay fallback):", err);
      setIsFullscreen((prev) => !prev);
    }
  }, []);

  // Sync fullscreen state with document events (e.g. Esc pressed natively)
  useEffect(() => {
    const onFullscreenChange = () => {
      const isFs = Boolean(document.fullscreenElement);
      setIsFullscreen(isFs);
    };

    document.addEventListener("fullscreenchange", onFullscreenChange);
    document.addEventListener("webkitfullscreenchange", onFullscreenChange);

    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape" && isFullscreen && !document.fullscreenElement) {
        setIsFullscreen(false);
      }
    };
    window.addEventListener("keydown", onKeyDown);

    return () => {
      document.removeEventListener("fullscreenchange", onFullscreenChange);
      document.removeEventListener("webkitfullscreenchange", onFullscreenChange);
      window.removeEventListener("keydown", onKeyDown);
    };
  }, [isFullscreen]);

  // Keyboard shortcut: 'F' toggles fullscreen
  useEffect(() => {
    const handleGlobalKeys = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement | null;
      if (
        target &&
        (target.tagName === "INPUT" ||
          target.tagName === "TEXTAREA" ||
          target.isContentEditable)
      ) {
        return;
      }

      if (e.key === "f" || e.key === "F") {
        e.preventDefault();
        void handleToggleFullscreen();
      }
    };

    window.addEventListener("keydown", handleGlobalKeys);
    return () => window.removeEventListener("keydown", handleGlobalKeys);
  }, [handleToggleFullscreen]);

  // Smoothly fit view when toggling fullscreen
  useEffect(() => {
    const timer = window.setTimeout(() => {
      void fitView({ padding: 0.18, duration: 350 });
    }, 150);
    return () => window.clearTimeout(timer);
  }, [isFullscreen, fitView]);

  const loadGraph = useCallback(async () => {
    try {
      setLoading(true);
      const data: GraphResponse = await getInvestigationGraph(investigationId);
      setAllNodes(data.nodes || []);
      setAllEdges(data.edges || []);
      setError(null);
    } catch (loadError: unknown) {
      setError(loadError instanceof Error ? loadError.message : "No se pudo cargar el mapa digital");
    } finally {
      setLoading(false);
    }
  }, [investigationId]);

  useEffect(() => {
    if (graphData === undefined) return;
    const updateTimer = window.setTimeout(() => {
      if (!graphData) {
        setLoading(true);
        setError(null);
        return;
      }
      setAllNodes(graphData.nodes || []);
      setAllEdges(graphData.edges || []);
      setError(null);
      setLoading(false);
    }, 0);
    return () => window.clearTimeout(updateTimer);
  }, [graphData]);

  useEffect(() => {
    if (graphData !== undefined) return;
    const initialLoad = window.setTimeout(() => void loadGraph(), 0);
    return () => window.clearTimeout(initialLoad);
  }, [graphData, loadGraph, refreshKey]);

  const categories = useMemo(
    () =>
      buildEntityFilters(
        allNodes.filter((node) => node.type !== "personRoot").map((node) => node.data.entity_type)
      ),
    [allNodes]
  );

  const relationOptions = useMemo(() => {
    const types = new Set(
      allEdges
        .filter((edge) => !isProvenanceEdge(edge))
        .map((edge) => edge.relation_type)
    );
    return [...types].sort();
  }, [allEdges]);

  const toggleRelationFilter = useCallback((relationType: string) => {
    setActiveRelationTypes((current) => {
      const next = new Set(current);
      if (next.has(relationType)) next.delete(relationType);
      else next.add(relationType);
      return next;
    });
  }, []);

  const toggleEvidenceFilter = useCallback((filter: InspectorEvidenceFilter) => {
    setActiveEvidenceFilters((current) => {
      const next = new Set(current);
      if (next.has(filter)) next.delete(filter);
      else next.add(filter);
      return next;
    });
  }, []);

  const resetExplorationFilters = useCallback(() => {
    setActiveCategory("all");
    setSearchQuery("");
    setActiveRelationTypes(new Set());
    setActiveEvidenceFilters(new Set());
    setFocusMode("all");
    setOpenFilterMenu(null);
  }, []);

  // Compute Layout, Nodes, and Edges
  const baseView = useMemo(() => {
    const isRoot = (node: GraphNode) => node.type === "personRoot" || node.data.is_root;
    const root = allNodes.find(isRoot);
    const normalizedQuery = searchQuery.trim().toLocaleLowerCase();
    const relationMatches = allEdges.filter(
      (edge) => !isProvenanceEdge(edge) &&
        (activeRelationTypes.size === 0 || activeRelationTypes.has(edge.relation_type))
    );
    const relationNodeIds = new Set(relationMatches.flatMap((edge) => [edge.source, edge.target]));
    const focusNodeIds = focusMode === "all" || !selectedNodeId
      ? null
      : getFocusNodeIds(allEdges, selectedNodeId, focusMode === "neighbors" ? 1 : 2);
    const entities = allNodes.filter((node) => {
      if (isRoot(node)) return false;
      if (activeCategory !== "all" && node.data.entity_type !== activeCategory) return false;
      if (normalizedQuery && !getInspectorSearchText(node).includes(normalizedQuery)) return false;
      if (activeRelationTypes.size > 0 && !relationNodeIds.has(node.id)) return false;
      if (activeEvidenceFilters.size > 0) {
        const availableEvidence = getInspectorEvidenceFilters(node);
        if (![...activeEvidenceFilters].every((filter) => availableEvidence.has(filter))) return false;
      }
      return !focusNodeIds || focusNodeIds.has(node.id);
    });
    const visibleIds = new Set(entities.map((node) => node.id));
    if (root) visibleIds.add(root.id);

    const candidateEdges = allEdges.filter(
      (edge) => visibleIds.has(edge.source) && visibleIds.has(edge.target)
    );

    const provenanceEdges = candidateEdges.filter(isProvenanceEdge);
    const evidenceEdges = candidateEdges.filter(
      (edge) => !isProvenanceEdge(edge) &&
        (activeRelationTypes.size === 0 || activeRelationTypes.has(edge.relation_type))
    );
    const visibleEdges = showDiscoveryLines
      ? [...evidenceEdges, ...provenanceEdges]
      : evidenceEdges;

    const degree = new Map<string, number>();
    for (const edge of evidenceEdges) {
      degree.set(edge.source, (degree.get(edge.source) ?? 0) + 1);
      degree.set(edge.target, (degree.get(edge.target) ?? 0) + 1);
    }

    // Deterministic organic constellation layout
    const layout = layoutDigitalMap(
      root?.id ?? "",
      entities.map((node) => ({
        id: node.id,
        groupId: node.data.group_id,
        entityType: node.data.entity_type,
        platform: node.data.platform,
        label: node.data.label,
        value: node.data.value,
      })),
      evidenceEdges.map((edge) => ({
        source: edge.source,
        target: edge.target,
        relationType: edge.relation_type,
      }))
    );

    const nodes: DisplayNode[] = [];

    // 1. Root Target Node
    if (root) {
      nodes.push({
        ...root,
        type: "personRoot",
        position: layout.positions.get(root.id) ?? { x: 0, y: 0 },
        width: 140,
        height: 140,
        draggable: false,
        zIndex: 10,
        data: {
          ...root.data,
          interaction: "idle",
          isCorrelated: false,
        },
      });
    }

    // 2. Entity Nodes
    for (const entity of entities) {
      const position = layout.positions.get(entity.id) ?? { x: 0, y: 0 };
      nodes.push({
        ...entity,
        type: "customEntity",
        position,
        width: 120,
        height: 92,
        draggable: false,
        zIndex: 5,
        data: {
          ...entity.data,
          interaction: "idle",
          isCorrelated: (degree.get(entity.id) ?? 0) > 0 || Boolean(entity.data.group_id),
        },
      });
    }

    // 3. Keep a sparse factual backbone at rest. Full incident evidence appears on focus.
    const backboneEdges = getEvidenceBackbone(evidenceEdges);
    const idleEdges = showDiscoveryLines
      ? [...backboneEdges, ...provenanceEdges]
      : backboneEdges;
    const denseGraph = evidenceEdges.length > 120;

    const toDisplayEdge = (edge: GraphEdge): DisplayEdge => {
      const sourcePos = layout.positions.get(edge.source) ?? { x: 0, y: 0 };
      const targetPos = layout.positions.get(edge.target) ?? { x: 0, y: 0 };
      const handles = getBestHandlePair(sourcePos.x, sourcePos.y, targetPos.x, targetPos.y);
      const isProvenance = isProvenanceEdge(edge);
      const isRootEdge = root && (edge.source === root.id || edge.target === root.id);
      const strokeColor = isProvenance ? "#64748b" : (edge.style?.stroke as string) || "#38bdf8";

      return {
        ...edge,
        ...handles,
        type: "customEdge",
        data: edge,
        label: undefined,
        animated: false,
        interactionWidth: 14,
        style: {
          stroke: strokeColor,
          strokeWidth: isProvenance ? 1 : isRootEdge ? 1.2 : 1,
          strokeOpacity: isProvenance ? 0.28 : denseGraph ? 0.28 : 0.52,
          strokeDasharray: isProvenance ? "4 7" : undefined,
        },
        zIndex: isProvenance ? 1 : 2,
      };
    };

    const allDisplayEdges = visibleEdges.map(toDisplayEdge);
    const displayById = new Map(allDisplayEdges.map((edge) => [edge.id, edge]));
    const edges = idleEdges
      .map((edge) => displayById.get(edge.id))
      .filter((edge): edge is DisplayEdge => Boolean(edge));

    const layoutKey = `${activeCategory}:${searchQuery}:${[...activeRelationTypes].sort().join(",")}:${[...activeEvidenceFilters].sort().join(",")}:${focusMode}:${selectedNodeId ?? ""}:${entities.map((n) => n.id).join(",")}:${evidenceEdges.map((e) => e.id).join(",")}`;

    return {
      nodes,
      edges,
      allDisplayEdges,
      visibleEdges,
      persistentLabels: evidenceEdges.length <= 12,
      layoutKey,
    };
  }, [activeCategory, activeEvidenceFilters, activeRelationTypes, allEdges, allNodes, focusMode, searchQuery, selectedNodeId, showDiscoveryLines]);

  // Entrada desde Hallazgos: una vez que el mismo grafo ya está disponible,
  // seleccionamos y centramos el nodo sin crear un canal de selección paralelo.
  useEffect(() => {
    if (!focusNodeId) return;
    const node = baseView.nodes.find((candidate) => candidate.id === focusNodeId);
    if (!node) return;
    const focusTimer = window.setTimeout(() => {
      setSelectedNodeId(focusNodeId);
      setSelectedEdgeId(null);
      void setCenter(node.position.x + 60, node.position.y + 46, { duration: 420, zoom: 1.05 });
    }, 0);
    return () => window.clearTimeout(focusTimer);
  }, [baseView.nodes, focusNodeId, setCenter]);

  // Handle Focus & Interaction
  const view = useMemo(() => {
    const activeNodeId = hoveredNodeId ?? selectedNodeId;
    const focusedNodeIds = new Set<string>();

    if (activeNodeId) {
      focusedNodeIds.add(activeNodeId);
      for (const edge of baseView.visibleEdges) {
        if (edge.source === activeNodeId) focusedNodeIds.add(edge.target);
        if (edge.target === activeNodeId) focusedNodeIds.add(edge.source);
      }
    } else if (selectedEdgeId) {
      const selectedEdge = baseView.visibleEdges.find((edge) => edge.id === selectedEdgeId);
      if (selectedEdge) {
        focusedNodeIds.add(selectedEdge.source);
        focusedNodeIds.add(selectedEdge.target);
      }
    }

    const hasFocus = focusedNodeIds.size > 0;

    const nodes = baseView.nodes.map((node) => {
      const interaction: "idle" | "focused" | "dimmed" = !hasFocus
        ? "idle"
        : focusedNodeIds.has(node.id)
          ? "focused"
          : "dimmed";

      return {
        ...node,
        selected: node.id === selectedNodeId,
        style: {
          opacity: interaction === "dimmed" ? 0.22 : 1,
          transition: "opacity 100ms ease",
        },
        data: interaction === "focused" ? { ...node.data, interaction } : node.data,
      };
    });

    const renderedEdges = new Map(baseView.edges.map((edge) => [edge.id, edge]));
    if (activeNodeId) {
      for (const edge of baseView.allDisplayEdges) {
        if (edge.source === activeNodeId || edge.target === activeNodeId) {
          renderedEdges.set(edge.id, edge);
        }
      }
    }
    if (selectedEdgeId) {
      const selectedEdge = baseView.allDisplayEdges.find((edge) => edge.id === selectedEdgeId);
      if (selectedEdge) renderedEdges.set(selectedEdge.id, selectedEdge);
    }

    let focusedLabelCount = 0;
    const edges = [...renderedEdges.values()].map((edge) => {
      const isFocused =
        edge.id === selectedEdgeId ||
        Boolean(activeNodeId && (edge.source === activeNodeId || edge.target === activeNodeId));
      const isDimmed = hasFocus && !isFocused;
      const rawEdge = edge.data as GraphEdge;
      const isProvenance = isProvenanceEdge(rawEdge);
      const showLabel =
        edge.id === selectedEdgeId ||
        (!isProvenanceEdge(rawEdge) &&
          (baseView.persistentLabels || (isFocused && focusedLabelCount < 8)));
      if (showLabel && isFocused) focusedLabelCount += 1;

      return {
        ...edge,
        selected: edge.id === selectedEdgeId,
        label: showLabel ? getFriendlyRelationLabel(rawEdge.relation_type, rawEdge.label) : undefined,
        style: {
          ...edge.style,
          strokeOpacity: isDimmed ? 0.025 : isFocused ? isProvenance ? 0.58 : 0.9 : (edge.style?.strokeOpacity ?? 0.52),
          strokeWidth: isFocused ? isProvenance ? 1.3 : 2 : (edge.style?.strokeWidth ?? 1),
        },
        zIndex: isFocused ? isProvenance ? 5 : 6 : edge.zIndex,
      };
    });

    return { nodes, edges };
  }, [baseView, hoveredNodeId, selectedEdgeId, selectedNodeId]);

  const nodeTypes = useMemo(
    () => ({
      personRoot: PersonRootNode,
      customEntity: CustomEntityNode,
    }),
    []
  );

  const edgeTypes = useMemo(
    () => ({
      customEdge: CustomEvidenceEdge,
    }),
    []
  );

  const selectedNode = allNodes.find((node) => node.id === selectedNodeId) ?? null;
  const selectedEdgeRaw = allEdges.find((edge) => edge.id === selectedEdgeId);
  const selectedEdge = selectedEdgeRaw ?? null;

  const selectInspectorNode = useCallback((nodeId: string) => {
    setSelectedNodeId(nodeId);
    setSelectedEdgeId(null);
    const displayNode = baseView.nodes.find((node) => node.id === nodeId);
    if (displayNode) {
      const width = displayNode.width ?? 120;
      const height = displayNode.height ?? 92;
      void setCenter(displayNode.position.x + width / 2, displayNode.position.y + height / 2, {
        duration: 380,
        zoom: 1.05,
      });
    }
  }, [baseView.nodes, setCenter]);

  const entityCount = allNodes.filter(
    (node) => node.type !== "personRoot" && !node.data.is_root
  ).length;
  const evidenceCount = allEdges.filter((edge) => !isProvenanceEdge(edge)).length;
  const shownEntityCount = baseView.nodes.filter((node) => node.type !== "personRoot" && !node.data.is_root).length;
  const shownEvidenceCount = baseView.visibleEdges.filter((edge) => !isProvenanceEdge(edge)).length;
  const hasActiveExplorationFilters = Boolean(
    activeCategory !== "all" || searchQuery || activeRelationTypes.size || activeEvidenceFilters.size || focusMode !== "all"
  );

  const exportGraphJson = () => {
    const blob = new Blob([JSON.stringify({ nodes: allNodes, edges: allEdges }, null, 2)], {
      type: "application/json",
    });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `graph-${investigationId}.json`;
    link.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div
      ref={containerRef}
      className={`digital-map-canvas relative w-full overflow-hidden rounded-xl border border-[#141f2f] bg-[#030712] shadow-2xl transition-all duration-300 [&:fullscreen]:w-screen [&:fullscreen]:h-screen [&:fullscreen]:rounded-none [&:fullscreen]:border-0 ${
        isFullscreen ? "fixed inset-0 z-[9999] h-screen w-screen rounded-none border-0" : "h-[700px] sm:h-[750px]"
      }`}
    >
      {/* Top Floating Filter & Actions Bar */}
      <div className="pointer-events-none absolute inset-x-0 top-0 z-20 bg-gradient-to-b from-[#030712] via-[#030712]/90 to-transparent px-3 pb-8 pt-3 sm:px-4">
        <div className="pointer-events-auto flex flex-wrap items-center justify-between gap-2">
          <div className="flex min-w-0 flex-1 flex-wrap items-center gap-1.5">
            <label className="flex h-7 min-w-[190px] flex-1 items-center gap-1.5 rounded-md border border-slate-800 bg-[#070e1a]/90 px-2 text-slate-500 focus-within:border-cyan-400/60 focus-within:text-cyan-300 sm:max-w-[270px]">
              <Search className="h-3.5 w-3.5 shrink-0" />
              <input
                value={searchQuery}
                onChange={(event) => setSearchQuery(event.target.value)}
                placeholder="Buscar alias, correo, dominio…"
                className="min-w-0 flex-1 bg-transparent font-mono text-[10px] text-slate-200 outline-none placeholder:text-slate-600"
                aria-label="Buscar nodos del mapa"
              />
            </label>

            <div className="relative">
              <button type="button" onClick={() => setOpenFilterMenu((menu) => menu === "layers" ? null : "layers")} aria-expanded={openFilterMenu === "layers"} className={`flex h-7 items-center gap-1 rounded-md border px-2 font-mono text-[9px] ${activeCategory !== "all" ? "border-cyan-400/60 bg-cyan-500/15 text-cyan-100" : "border-slate-800 bg-[#070e1a]/90 text-slate-400 hover:text-slate-200"}`}>
                <Filter className="h-3 w-3" /> Capas <ChevronDown className="h-3 w-3" />
              </button>
              {openFilterMenu === "layers" && (
                <div className="absolute left-0 top-8 z-40 w-56 overflow-hidden rounded-lg border border-[#29415b] bg-[#07111f]/98 p-1 shadow-2xl backdrop-blur-md">
                  {categories.map((category) => {
                    const meta = getEntityTypeMeta(category.id);
                    const Icon = category.id === "all" ? Network : meta.Icon;
                    const active = activeCategory === category.id;
                    return <button key={category.id} type="button" onClick={() => { setActiveCategory(category.id); setOpenFilterMenu(null); }} className={`flex w-full items-center gap-2 rounded px-2 py-1.5 text-left font-mono text-[10px] ${active ? "bg-cyan-500/15 text-cyan-100" : "text-slate-400 hover:bg-slate-800/80 hover:text-slate-200"}`}><span className="w-3">{active && <Check className="h-3 w-3" />}</span><Icon className={`h-3 w-3 ${meta.accent}`} /><span className="flex-1">{category.label}</span><span className="text-slate-600">{category.count}</span></button>;
                  })}
                </div>
              )}
            </div>

            <div className="relative">
              <button type="button" onClick={() => setOpenFilterMenu((menu) => menu === "relations" ? null : "relations")} aria-expanded={openFilterMenu === "relations"} className={`flex h-7 items-center gap-1 rounded-md border px-2 font-mono text-[9px] ${activeRelationTypes.size ? "border-violet-400/60 bg-violet-500/15 text-violet-100" : "border-slate-800 bg-[#070e1a]/90 text-slate-400 hover:text-slate-200"}`}>
                <Link2 className="h-3 w-3" /> Relaciones {activeRelationTypes.size ? activeRelationTypes.size : ""}<ChevronDown className="h-3 w-3" />
              </button>
              {openFilterMenu === "relations" && (
                <div className="absolute left-0 top-8 z-40 w-52 overflow-hidden rounded-lg border border-[#29415b] bg-[#07111f]/98 p-1 shadow-2xl backdrop-blur-md">
                  <p className="px-2 py-1 font-mono text-[9px] uppercase tracking-wider text-slate-500">Mostrar relaciones</p>
                  {relationOptions.map((relationType) => {
                    const active = activeRelationTypes.has(relationType);
                    return <button key={relationType} type="button" onClick={() => toggleRelationFilter(relationType)} className={`flex w-full items-center gap-2 rounded px-2 py-1.5 text-left font-mono text-[10px] ${active ? "bg-violet-500/15 text-violet-100" : "text-slate-400 hover:bg-slate-800/80 hover:text-slate-200"}`}><span className={`flex h-3 w-3 items-center justify-center rounded border ${active ? "border-violet-300 bg-violet-400 text-[#07111f]" : "border-slate-600"}`}>{active && <Check className="h-2.5 w-2.5" />}</span>{getFriendlyRelationLabel(relationType)}</button>;
                  })}
                </div>
              )}
            </div>

            <div className="relative">
              <button type="button" onClick={() => setOpenFilterMenu((menu) => menu === "evidence" ? null : "evidence")} aria-expanded={openFilterMenu === "evidence"} className={`flex h-7 items-center gap-1 rounded-md border px-2 font-mono text-[9px] ${activeEvidenceFilters.size ? "border-emerald-400/60 bg-emerald-500/15 text-emerald-100" : "border-slate-800 bg-[#070e1a]/90 text-slate-400 hover:text-slate-200"}`}>
                <SlidersHorizontal className="h-3 w-3" /> Evidencia {activeEvidenceFilters.size ? activeEvidenceFilters.size : ""}<ChevronDown className="h-3 w-3" />
              </button>
              {openFilterMenu === "evidence" && (
                <div className="absolute left-0 top-8 z-40 w-48 overflow-hidden rounded-lg border border-[#29415b] bg-[#07111f]/98 p-1 shadow-2xl backdrop-blur-md">
                  {([ ["links", "Con enlaces", Link2], ["descriptions", "Con bio o texto", FileDown], ["images", "Con imagen", Image], ["provenance", "Con procedencia", Eye] ] as const).map(([filter, label, Icon]) => {
                    const active = activeEvidenceFilters.has(filter);
                    return <button key={filter} type="button" onClick={() => toggleEvidenceFilter(filter)} className={`flex w-full items-center gap-2 rounded px-2 py-1.5 text-left font-mono text-[10px] ${active ? "bg-emerald-500/15 text-emerald-100" : "text-slate-400 hover:bg-slate-800/80 hover:text-slate-200"}`}><span className={`flex h-3 w-3 items-center justify-center rounded border ${active ? "border-emerald-300 bg-emerald-400 text-[#07111f]" : "border-slate-600"}`}>{active && <Check className="h-2.5 w-2.5" />}</span><Icon className="h-3 w-3" />{label}</button>;
                  })}
                </div>
              )}
            </div>

            <div className="relative">
              <button type="button" disabled={!selectedNodeId} onClick={() => setOpenFilterMenu((menu) => menu === "focus" ? null : "focus")} aria-expanded={openFilterMenu === "focus"} className={`flex h-7 items-center gap-1 rounded-md border px-2 font-mono text-[9px] ${focusMode !== "all" ? "border-cyan-400/60 bg-cyan-500/15 text-cyan-100" : "border-slate-800 bg-[#070e1a]/90 text-slate-400 hover:text-slate-200"} disabled:cursor-not-allowed disabled:opacity-40`}>
                <Network className="h-3 w-3" /> Foco <ChevronDown className="h-3 w-3" />
              </button>
              {openFilterMenu === "focus" && selectedNodeId && (
                <div className="absolute left-0 top-8 z-40 w-44 overflow-hidden rounded-lg border border-[#29415b] bg-[#07111f]/98 p-1 shadow-2xl backdrop-blur-md">
                  {([ ["all", "Mapa completo"], ["neighbors", "Vecinos directos"], ["two_hops", "Hasta 2 saltos"] ] as const).map(([mode, label]) => <button key={mode} type="button" onClick={() => { setFocusMode(mode); setOpenFilterMenu(null); }} className={`flex w-full items-center gap-2 rounded px-2 py-1.5 text-left font-mono text-[10px] ${focusMode === mode ? "bg-cyan-500/15 text-cyan-100" : "text-slate-400 hover:bg-slate-800/80 hover:text-slate-200"}`}><span className="w-3">{focusMode === mode && <Check className="h-3 w-3" />}</span>{label}</button>)}
                </div>
              )}
            </div>
          </div>

          {/* Action buttons */}
          <div className="flex shrink-0 items-center gap-1.5">
            <span className="hidden font-mono text-[9px] text-slate-400 lg:inline">
              {shownEntityCount}/{entityCount} nodos · {shownEvidenceCount}/{evidenceCount} vínculos
            </span>
            {hasActiveExplorationFilters && <button type="button" onClick={resetExplorationFilters} className="flex h-7 items-center gap-1 rounded-md border border-slate-700 bg-[#070e1a]/90 px-2 font-mono text-[9px] text-slate-300 hover:border-cyan-400/60 hover:text-cyan-100" title="Restablecer filtros"><RotateCcw className="h-3 w-3" /> Restablecer</button>}
            <button
              type="button"
              onClick={() => setShowDiscoveryLines((visible) => !visible)}
              className={`flex items-center gap-1.5 rounded-full border px-2.5 py-1 font-mono text-[9px] transition-colors ${
                showDiscoveryLines
                  ? "border-cyan-400/50 bg-cyan-400/10 text-cyan-200"
                  : "border-slate-800 bg-[#070e1a]/85 text-slate-400 hover:text-slate-200"
              }`}
              title="Mostrar u ocultar procedencia secundaria"
              aria-pressed={showDiscoveryLines}
            >
              {showDiscoveryLines ? <Eye className="h-3 w-3" /> : <EyeOff className="h-3 w-3" />}
              Procedencia
            </button>
            <button
              type="button"
              onClick={exportGraphJson}
              className="rounded-full border border-slate-800 bg-[#070e1a]/85 p-1.5 text-slate-400 hover:border-slate-600 hover:text-cyan-200"
              title="Exportar grafo JSON"
              aria-label="Exportar grafo JSON"
            >
              <Braces className="h-3.5 w-3.5" />
            </button>
            <button
              type="button"
              onClick={() => window.open(getGraphmlUrl(investigationId), "_blank")}
              className="rounded-full border border-slate-800 bg-[#070e1a]/85 p-1.5 text-slate-400 hover:border-slate-600 hover:text-violet-200"
              title="Descargar GraphML"
              aria-label="Descargar GraphML"
            >
              <FileDown className="h-3.5 w-3.5" />
            </button>
          </div>
        </div>
      </div>

      {/* Loading overlay */}
      {loading && (
        <div role="status" className="absolute inset-0 z-40 flex items-center justify-center bg-[#030712]/90 font-mono text-xs text-slate-400">
          <span className="mr-2.5 h-4 w-4 animate-spin rounded-full border-2 border-cyan-400/20 border-t-cyan-300" />
          Trazando constelación de evidencia...
        </div>
      )}

      {/* Error overlay */}
      {!loading && error && (
        <div className="absolute inset-0 z-40 flex flex-col items-center justify-center bg-[#030712]/95 px-6 text-center">
          <AlertTriangle className="mb-2 h-7 w-7 text-rose-400" />
          <p className="font-mono text-xs font-semibold text-slate-200">No se pudo cargar el mapa</p>
          <p className="mt-1 max-w-sm text-[11px] text-slate-500">{error}</p>
          <button
            type="button"
            onClick={() => void loadGraph()}
            className="mt-3 rounded-md border border-slate-700 bg-slate-900 px-3 py-1.5 font-mono text-[10px] text-slate-200 hover:border-cyan-500/50"
          >
            Reintentar
          </button>
        </div>
      )}

      {/* Empty category state */}
      {!loading && !error && shownEntityCount === 0 && (
        <div className="absolute inset-0 z-30 flex items-center justify-center bg-[#030712]/90 font-mono text-xs text-slate-400">
          No hay nodos que coincidan con los criterios de exploración.
        </div>
      )}

      {/* React Flow Canvas */}
      <ReactFlow<DisplayNode, DisplayEdge>
        nodes={view.nodes}
        edges={view.edges}
        nodeTypes={nodeTypes}
        edgeTypes={edgeTypes}
        nodeOrigin={[0.5, 0.5]}
        nodesDraggable={false}
        nodesConnectable={false}
        minZoom={0.1}
        maxZoom={2.4}
        elevateEdgesOnSelect={false}
        onNodeMouseEnter={(_, node) => setHoveredNodeId(node.id)}
        onNodeMouseLeave={() => setHoveredNodeId(null)}
        onNodeClick={(_, node) => {
          setSelectedNodeId(node.id);
          setSelectedEdgeId(null);
        }}
        onEdgeClick={(_, edge) => {
          setSelectedEdgeId(edge.id);
          setSelectedNodeId(null);
        }}
        onPaneClick={() => {
          setSelectedNodeId(null);
          setSelectedEdgeId(null);
        }}
      >
        <Background variant={BackgroundVariant.Dots} color="#152438" gap={34} size={1} />
        <ViewportPortal>
          <RadarBackgroundNode />
        </ViewportPortal>
        <FitToLayout layoutKey={baseView.layoutKey} />

        {/* Bottom-right: MiniMap and viewport controls */}
        <Panel position="bottom-right" className="!m-4 !p-0 z-30">
          <div className="nopan nodrag flex items-end gap-2.5">
            {/* MiniMap Container */}
            <div className="h-[120px] w-[165px] overflow-hidden rounded-lg border border-slate-700/70 bg-[#070e1a]/95 shadow-2xl backdrop-blur-md">
              <MiniMap
                pannable
                zoomable
                maskColor="rgba(3, 7, 13, 0.82)"
                nodeStrokeWidth={2}
                nodeColor={(node) => {
                  if (node.type === "personRoot") return "#22d3ee";
                  const theme = getEntityTheme(
                    node.data?.platform as string | undefined,
                    node.data?.entity_type as string | undefined,
                    node.data?.value as string | undefined
                  );
                  return theme.dotColor;
                }}
                className="!relative !inset-auto !m-0 !h-full !w-full !border-0 !bg-transparent"
              />
            </div>

            {/* Viewport Toolbar */}
            <ViewportToolbar
              onToggleFullscreen={handleToggleFullscreen}
              isFullscreen={isFullscreen}
            />
          </div>
        </Panel>
      </ReactFlow>

      {/* Side OSINT inspector */}
      {selectedNode && (
        <EntityInspector
          node={selectedNode}
          nodes={allNodes}
          edges={allEdges}
          onSelectNode={selectInspectorNode}
          relationLabel={(edge) => getFriendlyRelationLabel(edge.relation_type, edge.label)}
          onClose={() => {
            setSelectedNodeId(null);
            setSelectedEdgeId(null);
          }}
        />
      )}
      {!selectedNode && selectedEdge && (
        <RelationshipInspector
          edge={selectedEdge}
          nodes={allNodes}
          onSelectNode={selectInspectorNode}
          relationLabel={(edge) => getFriendlyRelationLabel(edge.relation_type, edge.label)}
          onClose={() => {
            setSelectedNodeId(null);
            setSelectedEdgeId(null);
          }}
        />
      )}
    </div>
  );
}

export function DigitalMapGraph({
  investigationId,
  refreshKey,
  graphData,
  focusNodeId,
}: {
  investigationId: string;
  refreshKey?: string;
  graphData?: GraphResponse | null;
  focusNodeId?: string | null;
}) {
  return (
    <ReactFlowProvider>
      <DigitalMapGraphInner
        investigationId={investigationId}
        refreshKey={refreshKey}
        graphData={graphData}
        focusNodeId={focusNodeId}
      />
    </ReactFlowProvider>
  );
}
