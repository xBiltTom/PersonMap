"use client";

import { useState } from "react";
import {
  CalendarDays,
  Check,
  ChevronRight,
  Copy,
  ExternalLink,
  ImageOff,
  Link2,
  MapPin,
  Network,
  ScanSearch,
  Wrench,
  X,
} from "lucide-react";
import {
  buildEntityInspectorViewModel,
  buildRelationshipEvidenceFields,
  toSafeExternalUrl,
  type InspectorField,
  type InspectorImage,
  type InspectorLink,
} from "@/lib/entityInspector";
import { isProvenanceEdge } from "@/lib/graphSemantics";
import type { GraphEdge, GraphNode } from "@/lib/types";
import { PlatformIcon } from "./PlatformIcon";

interface InspectorProps {
  node: GraphNode;
  nodes: GraphNode[];
  edges: GraphEdge[];
  onClose: () => void;
  onSelectNode: (nodeId: string) => void;
  relationLabel: (edge: GraphEdge) => string;
}

const PANEL_CLASS = "absolute bottom-4 right-4 top-4 z-30 w-[min(390px,calc(100%-2rem))] overflow-y-auto rounded-xl border border-[#29415b]/80 bg-[#060d18]/95 shadow-2xl shadow-black/40 backdrop-blur-md";

function formatDate(value?: string): string | undefined {
  if (!value) return undefined;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return undefined;
  return new Intl.DateTimeFormat("es-PE", {
    day: "2-digit",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

function InspectorSection({ title, children, count }: { title: string; children: React.ReactNode; count?: number }) {
  return (
    <section className="border-t border-[#1b3046] px-4 py-3.5">
      <div className="mb-2.5 flex items-center gap-2">
        <h5 className="font-mono text-[10px] font-medium uppercase tracking-[0.12em] text-cyan-200">{title}</h5>
        {typeof count === "number" && <span className="font-mono text-[10px] text-slate-500">· {count}</span>}
      </div>
      {children}
    </section>
  );
}

function CopyButton({ value, copiedValue, onCopy }: { value: string; copiedValue: string | null; onCopy: (value: string) => void }) {
  const copied = copiedValue === value;
  return (
    <button
      type="button"
      onClick={() => onCopy(value)}
      className="rounded p-1 text-slate-500 transition-colors hover:bg-slate-800 hover:text-cyan-200 focus-visible:outline focus-visible:outline-1 focus-visible:outline-cyan-300"
      title={copied ? "Copiado" : "Copiar"}
      aria-label={copied ? "Copiado" : "Copiar"}
    >
      {copied ? <Check className="h-3.5 w-3.5 text-emerald-300" /> : <Copy className="h-3.5 w-3.5" />}
    </button>
  );
}

function ExternalAnchor({ href, children, className }: { href: string; children: React.ReactNode; className?: string }) {
  return (
    <a href={href} target="_blank" rel="noopener noreferrer" className={className}>
      {children}
    </a>
  );
}

function ObservedFields({ fields, copiedValue, onCopy }: { fields: InspectorField[]; copiedValue: string | null; onCopy: (value: string) => void }) {
  return (
    <dl className="overflow-hidden rounded-lg border border-[#1d344b] bg-[#081321]/70">
      {fields.map((field, index) => {
        const url = field.kind === "url" ? toSafeExternalUrl(field.value) : undefined;
        return (
          <div key={field.key} className={`grid grid-cols-[104px_minmax(0,1fr)_24px] items-center gap-2 px-2.5 py-2 ${index ? "border-t border-[#172b40]" : ""}`}>
            <dt className="font-mono text-[10px] text-slate-400">{field.label}</dt>
            <dd className="min-w-0 break-words font-mono text-[11px] leading-relaxed text-slate-200">
              {url ? (
                <ExternalAnchor href={url} className="inline-flex items-center gap-1 text-cyan-200 hover:text-cyan-100 hover:underline">
                  <span className="break-all">{field.value}</span><ExternalLink className="h-3 w-3 shrink-0" />
                </ExternalAnchor>
              ) : field.kind === "location" ? (
                <span className="inline-flex items-start gap-1.5"><MapPin className="mt-0.5 h-3 w-3 shrink-0 text-slate-500" />{field.value}</span>
              ) : field.value}
            </dd>
            <CopyButton value={field.value} copiedValue={copiedValue} onCopy={onCopy} />
          </div>
        );
      })}
    </dl>
  );
}

function EntityLinks({ links, copiedValue, onCopy }: { links: InspectorLink[]; copiedValue: string | null; onCopy: (value: string) => void }) {
  return (
    <div className="overflow-hidden rounded-lg border border-[#1d344b] bg-[#081321]/70">
      {links.map((link, index) => (
        <div key={`${link.kind}-${link.url}`} className={`grid grid-cols-[minmax(0,1fr)_24px] gap-2 px-2.5 py-2 ${index ? "border-t border-[#172b40]" : ""}`}>
          <ExternalAnchor href={link.url} className="group min-w-0">
            <span className="flex items-center gap-1.5 font-mono text-[10px] text-slate-300 group-hover:text-cyan-100">
              <Link2 className={`h-3 w-3 shrink-0 ${link.kind === "source" ? "text-violet-300" : "text-cyan-300"}`} />
              {link.label}
              <ExternalLink className="h-2.5 w-2.5 shrink-0 text-slate-500 group-hover:text-cyan-300" />
            </span>
            <span className="mt-0.5 block truncate font-mono text-[10px] text-slate-500 group-hover:text-slate-400">{link.url}</span>
          </ExternalAnchor>
          <CopyButton value={link.url} copiedValue={copiedValue} onCopy={onCopy} />
        </div>
      ))}
    </div>
  );
}

function ArtifactImage({ image, large = false, fallback }: { image: InspectorImage; large?: boolean; fallback?: React.ReactNode }) {
  const [failed, setFailed] = useState(false);
  if (failed) {
    if (fallback) return <>{fallback}</>;
    return large ? <div className="flex h-16 w-16 items-center justify-center rounded-lg border border-[#29415b] bg-[#081321] text-slate-600"><ImageOff className="h-4 w-4" /></div> : null;
  }
  return (
    <ExternalAnchor href={image.url} className={large ? "block h-16 w-16 shrink-0" : "group block aspect-square overflow-hidden rounded-md border border-[#29415b] bg-[#081321]"}>
      {/* External OSINT assets use a plain img: discovered hosts cannot be safely allow-listed for next/image. */}
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img
        src={image.url}
        alt={image.kind === "avatar" ? "Avatar público observado" : "Artefacto visual público observado"}
        loading="lazy"
        onError={() => setFailed(true)}
        className={large ? "h-16 w-16 rounded-lg border border-[#29415b] object-cover transition-opacity hover:opacity-80" : "h-full w-full object-cover transition-opacity group-hover:opacity-80"}
      />
    </ExternalAnchor>
  );
}

function InspectorHeader({ view, onClose }: { view: ReturnType<typeof buildEntityInspectorViewModel>; onClose: () => void }) {
  const avatar = view.images.find((image) => image.kind === "avatar");
  const platformTile = <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg border border-[#29415b] bg-[#0b1929] text-cyan-200"><PlatformIcon platform={view.platform} entityType={view.entityTypeKey} className="h-5 w-5" /></div>;
  return (
    <header className="px-4 pb-4 pt-4">
      <div className="flex items-start justify-between gap-3">
        <div className="flex min-w-0 gap-3">
          {avatar ? (
            <ArtifactImage image={avatar} large fallback={platformTile} />
          ) : (
            platformTile
          )}
          <div className="min-w-0 pt-0.5">
            <p className="font-mono text-[10px] uppercase tracking-[0.14em] text-cyan-300">{view.isRoot ? "Datos de investigación" : view.entityType}</p>
            <h4 className="mt-0.5 break-words text-base font-semibold leading-tight text-slate-100">{view.title}</h4>
            {view.subtitle && <p className="mt-1 break-all font-mono text-xs text-slate-400">{view.subtitle}</p>}
          </div>
        </div>
        <button type="button" onClick={onClose} className="rounded p-1 text-slate-500 hover:bg-slate-800 hover:text-white" aria-label="Cerrar inspector"><X className="h-4 w-4" /></button>
      </div>
      {view.primaryLink && (
        <ExternalAnchor href={view.primaryLink.url} className="mt-3 inline-flex items-center gap-2 rounded-md border border-[#2b5876] bg-[#0a1b2a] px-2.5 py-1.5 font-mono text-[10px] text-cyan-100 transition-colors hover:border-cyan-400/60 hover:bg-[#0d2638]">
          Abrir recurso original <ExternalLink className="h-3 w-3" />
        </ExternalAnchor>
      )}
    </header>
  );
}

export function EntityInspector({ node, nodes, edges, onClose, onSelectNode, relationLabel }: InspectorProps) {
  const [copiedValue, setCopiedValue] = useState<string | null>(null);
  const view = buildEntityInspectorViewModel(node, nodes, edges, relationLabel);
  const copy = (value: string) => {
    void navigator.clipboard.writeText(value).then(() => {
      setCopiedValue(value);
      window.setTimeout(() => setCopiedValue(null), 1500);
    }).catch(() => undefined);
  };

  const visibleImages = view.images.filter((image) => image.kind !== "avatar");
  const hasAdditionalContent = view.observedFields.length > 1 || view.descriptions.length || view.links.length || view.images.length || view.relationships.length || view.provenance;

  return (
    <aside className={PANEL_CLASS} aria-label="Inspector de entidad">
      <InspectorHeader view={view} onClose={onClose} />
      {view.observedFields.length > 0 && <InspectorSection title="Información observada"><ObservedFields fields={view.observedFields} copiedValue={copiedValue} onCopy={copy} /></InspectorSection>}
      {view.descriptions.length > 0 && (
        <InspectorSection title="Sobre el perfil">
          <div className="space-y-2">
            {view.descriptions.map((description) => (
              <div key={`${description.label}-${description.text.slice(0, 24)}`} className="rounded-lg border border-[#1d344b] bg-[#081321]/70 px-2.5 py-2">
                <p className="mb-1 font-mono text-[9px] uppercase tracking-wider text-slate-500">{description.label}</p>
                <p className="whitespace-pre-wrap text-[11px] leading-relaxed text-slate-300">{description.text}</p>
              </div>
            ))}
          </div>
        </InspectorSection>
      )}
      {view.links.length > 0 && <InspectorSection title="Enlaces"><EntityLinks links={view.links} copiedValue={copiedValue} onCopy={copy} /></InspectorSection>}
      {visibleImages.length > 0 && (
        <InspectorSection title="Artefactos visuales" count={view.images.length}>
          <div className="grid grid-cols-4 gap-2">{visibleImages.map((image) => <ArtifactImage key={image.url} image={image} />)}</div>
        </InspectorSection>
      )}
      {view.relationships.length > 0 && (
        <InspectorSection title="Relaciones" count={view.relationships.length}>
          <div className="overflow-hidden rounded-lg border border-[#1d344b] bg-[#081321]/70">
            {view.relationships.map(({ edge, node: related, label }, index) => (
              <button key={edge.id} type="button" onClick={() => onSelectNode(related.id)} className={`flex w-full items-center gap-2 px-2.5 py-2 text-left transition-colors hover:bg-[#102237] ${index ? "border-t border-[#172b40]" : ""}`}>
                <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded border border-[#29415b] text-cyan-200"><PlatformIcon platform={related.data.platform} entityType={related.data.entity_type} value={related.data.value} className="h-3 w-3" /></span>
                <span className="min-w-0 flex-1"><span className="block truncate font-mono text-[10px] text-slate-200">{related.data.display_name || related.data.value}</span><span className="block truncate font-mono text-[10px] text-cyan-300">{label}</span></span>
                <ChevronRight className="h-3.5 w-3.5 shrink-0 text-slate-600" />
              </button>
            ))}
          </div>
        </InspectorSection>
      )}
      {view.provenance && (
        <InspectorSection title="Procedencia">
          <dl className="overflow-hidden rounded-lg border border-[#1d344b] bg-[#081321]/70 font-mono text-[10px]">
            {view.provenance.sourceTool && <div className="grid grid-cols-[108px_minmax(0,1fr)] gap-2 px-2.5 py-2"><dt className="flex items-center gap-1.5 text-slate-500"><Wrench className="h-3 w-3" />Herramienta</dt><dd className="break-words text-slate-200">{view.provenance.sourceTool}</dd></div>}
            {formatDate(view.provenance.discoveredAt) && <div className="grid grid-cols-[108px_minmax(0,1fr)] gap-2 border-t border-[#172b40] px-2.5 py-2"><dt className="flex items-center gap-1.5 text-slate-500"><CalendarDays className="h-3 w-3" />Descubierto</dt><dd className="text-slate-200">{formatDate(view.provenance.discoveredAt)}</dd></div>}
            {view.provenance.engine && <div className="grid grid-cols-[108px_minmax(0,1fr)] gap-2 border-t border-[#172b40] px-2.5 py-2"><dt className="flex items-center gap-1.5 text-slate-500"><ScanSearch className="h-3 w-3" />Motor</dt><dd className="break-words text-slate-200">{view.provenance.engine}</dd></div>}
            {view.provenance.sourceUrl && <div className="border-t border-[#172b40] px-2.5 py-2"><ExternalAnchor href={view.provenance.sourceUrl} className="inline-flex max-w-full items-center gap-1 text-violet-200 hover:underline">Fuente original <ExternalLink className="h-3 w-3 shrink-0" /></ExternalAnchor></div>}
          </dl>
        </InspectorSection>
      )}
      {!hasAdditionalContent && <p className="border-t border-[#1b3046] px-4 py-4 text-[11px] leading-relaxed text-slate-500">No se extrajeron detalles adicionales de este hallazgo.</p>}
    </aside>
  );
}

export function RelationshipInspector({ edge, nodes, onClose, onSelectNode, relationLabel }: { edge: GraphEdge; nodes: GraphNode[]; onClose: () => void; onSelectNode: (nodeId: string) => void; relationLabel: (edge: GraphEdge) => string }) {
  const source = nodes.find((node) => node.id === edge.source);
  const target = nodes.find((node) => node.id === edge.target);
  const fields = buildRelationshipEvidenceFields(edge.evidence);
  const relation = relationLabel(edge);
  const provenance = isProvenanceEdge(edge);
  return (
    <aside className={PANEL_CLASS} aria-label="Inspector de relación">
      <header className="px-4 py-4">
        <div className="flex items-start justify-between gap-3"><div><p className={`font-mono text-[10px] uppercase tracking-[0.14em] ${provenance ? "text-slate-400" : "text-cyan-300"}`}>{provenance ? "Procedencia / contexto" : "Relación observada"}</p><h4 className="mt-1 text-sm font-semibold text-slate-100">{relation}</h4></div><button type="button" onClick={onClose} className="rounded p-1 text-slate-500 hover:bg-slate-800 hover:text-white" aria-label="Cerrar inspector"><X className="h-4 w-4" /></button></div>
        {source && target && <div className="mt-4 grid grid-cols-[minmax(0,1fr)_24px_minmax(0,1fr)] items-center gap-2 rounded-lg border border-[#1d344b] bg-[#081321]/70 p-2.5"><button type="button" onClick={() => onSelectNode(source.id)} className="truncate text-left font-mono text-[11px] text-slate-200 hover:text-cyan-200">{source.data.display_name || source.data.value}</button><Network className="h-4 w-4 text-cyan-300" /><button type="button" onClick={() => onSelectNode(target.id)} className="truncate text-right font-mono text-[11px] text-slate-200 hover:text-cyan-200">{target.data.display_name || target.data.value}</button></div>}
        <p className={`mt-3 rounded-md border px-2.5 py-2 text-[11px] leading-relaxed ${provenance ? "border-slate-700 bg-slate-900/40 text-slate-400" : "border-cyan-900/80 bg-cyan-950/20 text-slate-300"}`}>
          {provenance
            ? "Esta conexión explica cómo el hallazgo se relaciona con los datos iniciales de búsqueda. No implica que el recurso pertenezca a la persona investigada."
            : "Esta relación describe evidencia observada entre hallazgos. Requiere revisión humana y no atribuye automáticamente una identidad o propiedad."}
        </p>
      </header>
      {fields.length > 0 && <InspectorSection title="Evidencia"><ObservedFields fields={fields} copiedValue={null} onCopy={(value) => void navigator.clipboard.writeText(value)} /></InspectorSection>}
      {edge.supports_group && <InspectorSection title="Contexto"><p className="text-[11px] leading-relaxed text-slate-400">Esta relación se conserva como evidencia estructural para la revisión humana.</p></InspectorSection>}
    </aside>
  );
}
