"use client";

import { useState } from "react";
import {
  CalendarDays,
  Check,
  ChevronRight,
  Copy,
  ExternalLink,
  Fingerprint,
  ImageOff,
  Info,
  Link2,
  MapPin,
  Network,
  ScanSearch,
  Search,
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
  containerMode?: "floating" | "embedded";
}

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

function CopyButton({
  value,
  copiedValue,
  onCopy,
}: {
  value: string;
  copiedValue: string | null;
  onCopy: (value: string) => void;
}) {
  const copied = copiedValue === value;
  return (
    <button
      type="button"
      onClick={() => onCopy(value)}
      className="rounded p-1 text-slate-500 transition-colors hover:bg-slate-800 hover:text-cyan-200 focus-visible:outline focus-visible:outline-1 focus-visible:outline-cyan-300"
      title={copied ? "Copiado" : "Copiar"}
      aria-label={copied ? "Copiado" : "Copiar"}
    >
      {copied ? <Check className="h-3.5 w-3.5 text-emerald-400" /> : <Copy className="h-3.5 w-3.5" />}
    </button>
  );
}

function ExternalAnchor({
  href,
  children,
  className,
}: {
  href: string;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <a href={href} target="_blank" rel="noopener noreferrer" className={className}>
      {children}
    </a>
  );
}

function ObservedFields({
  fields,
  copiedValue,
  onCopy,
}: {
  fields: InspectorField[];
  copiedValue: string | null;
  onCopy: (value: string) => void;
}) {
  return (
    <dl className="overflow-hidden rounded-lg border border-[#1d344b] bg-[#081321]/80">
      {fields.map((field, index) => {
        const url = field.kind === "url" ? toSafeExternalUrl(field.value) : undefined;
        return (
          <div
            key={field.key}
            className={`grid grid-cols-[100px_minmax(0,1fr)_24px] items-center gap-2 px-3 py-2 ${
              index ? "border-t border-[#172b40]" : ""
            }`}
          >
            <dt className="font-mono text-[10px] text-slate-400">{field.label}</dt>
            <dd className="min-w-0 break-words font-mono text-[11px] leading-relaxed text-slate-200">
              {url ? (
                <ExternalAnchor
                  href={url}
                  className="inline-flex items-center gap-1 text-cyan-300 hover:text-cyan-200 hover:underline"
                >
                  <span className="break-all">{field.value}</span>
                  <ExternalLink className="h-3 w-3 shrink-0" />
                </ExternalAnchor>
              ) : field.kind === "location" ? (
                <span className="inline-flex items-start gap-1.5">
                  <MapPin className="mt-0.5 h-3 w-3 shrink-0 text-slate-400" />
                  {field.value}
                </span>
              ) : (
                field.value
              )}
            </dd>
            <CopyButton value={field.value} copiedValue={copiedValue} onCopy={onCopy} />
          </div>
        );
      })}
    </dl>
  );
}

function EntityLinks({
  links,
  copiedValue,
  onCopy,
}: {
  links: InspectorLink[];
  copiedValue: string | null;
  onCopy: (value: string) => void;
}) {
  return (
    <div className="overflow-hidden rounded-lg border border-[#1d344b] bg-[#081321]/80">
      {links.map((link, index) => (
        <div
          key={`${link.kind}-${link.url}`}
          className={`grid grid-cols-[minmax(0,1fr)_24px] gap-2 px-3 py-2 ${
            index ? "border-t border-[#172b40]" : ""
          }`}
        >
          <ExternalAnchor href={link.url} className="group min-w-0">
            <span className="flex items-center gap-1.5 font-mono text-[10px] text-slate-300 group-hover:text-cyan-200">
              <Link2 className={`h-3 w-3 shrink-0 ${link.kind === "source" ? "text-violet-300" : "text-cyan-300"}`} />
              {link.label}
              <ExternalLink className="h-2.5 w-2.5 shrink-0 text-slate-500 group-hover:text-cyan-300" />
            </span>
            <span className="mt-0.5 block truncate font-mono text-[10px] text-slate-400 group-hover:text-slate-300">
              {link.url}
            </span>
          </ExternalAnchor>
          <CopyButton value={link.url} copiedValue={copiedValue} onCopy={onCopy} />
        </div>
      ))}
    </div>
  );
}

function ArtifactImage({
  image,
  large = false,
  fallback,
}: {
  image: InspectorImage;
  large?: boolean;
  fallback?: React.ReactNode;
}) {
  const [failed, setFailed] = useState(false);
  if (failed) {
    if (fallback) return <>{fallback}</>;
    return large ? (
      <div className="flex h-12 w-12 items-center justify-center rounded-lg border border-[#29415b] bg-[#081321] text-slate-500">
        <ImageOff className="h-4 w-4" />
      </div>
    ) : null;
  }
  return (
    <ExternalAnchor
      href={image.url}
      className={
        large
          ? "block h-12 w-12 shrink-0"
          : "group block aspect-square overflow-hidden rounded-md border border-[#29415b] bg-[#081321]"
      }
    >
      {/* External OSINT assets use a plain img: discovered hosts cannot be safely allow-listed for next/image. */}
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img
        src={image.url}
        alt={image.kind === "avatar" ? "Avatar público observado" : "Artefacto visual observado"}
        loading="lazy"
        onError={() => setFailed(true)}
        className={
          large
            ? "h-12 w-12 rounded-lg border border-[#29415b] object-cover transition-opacity hover:opacity-85"
            : "h-full w-full object-cover transition-opacity group-hover:opacity-85"
        }
      />
    </ExternalAnchor>
  );
}

export function EntityInspector({
  node,
  nodes,
  edges,
  onClose,
  onSelectNode,
  relationLabel,
  containerMode = "floating",
}: InspectorProps) {
  const [activeTab, setActiveTab] = useState<"info" | "relations" | "provenance">("info");
  const [copiedValue, setCopiedValue] = useState<string | null>(null);
  const [pivotCopied, setPivotCopied] = useState(false);

  const view = buildEntityInspectorViewModel(node, nodes, edges, relationLabel);

  const copy = (value: string) => {
    void navigator.clipboard
      .writeText(value)
      .then(() => {
        setCopiedValue(value);
        window.setTimeout(() => setCopiedValue(null), 1500);
      })
      .catch(() => undefined);
  };

  const handlePivot = (value: string) => {
    void navigator.clipboard
      .writeText(value)
      .then(() => {
        setPivotCopied(true);
        window.setTimeout(() => setPivotCopied(false), 2000);
      })
      .catch(() => undefined);
  };

  const avatar = view.images.find((image) => image.kind === "avatar");
  const platformTile = (
    <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-lg border border-[#233852] bg-[#0b1726] text-cyan-300">
      <PlatformIcon platform={view.platform} entityType={view.entityTypeKey} className="h-5 w-5" />
    </div>
  );

  const visibleImages = view.images.filter((image) => image.kind !== "avatar");
  const pivotTarget = view.subtitle || view.title;

  const panelClasses =
    containerMode === "embedded"
      ? "relative flex h-full w-full flex-col rounded-xl border border-[#22354c] bg-[#070e19]/95 shadow-2xl shadow-black/60 backdrop-blur-sm overflow-hidden"
      : "absolute bottom-3 right-3 top-3 z-30 flex w-[min(410px,calc(100%-1.5rem))] flex-col rounded-xl border border-[#22354c] bg-[#070e19]/95 shadow-2xl shadow-black/60 backdrop-blur-sm overflow-hidden animate-slide-in-right";

  return (
    <aside className={panelClasses} aria-label="Inspector forense de entidad">
      {/* Fixed Inspector Header */}
      <header className="shrink-0 border-b border-[#1b2b3e] bg-[#081220]/90 px-4 pt-3.5 pb-3">
        <div className="flex items-start justify-between gap-2.5">
          <div className="flex min-w-0 items-center gap-3">
            {avatar ? <ArtifactImage image={avatar} large fallback={platformTile} /> : platformTile}
            <div className="min-w-0">
              <div className="flex items-center gap-1.5">
                <span className="rounded border border-sky-500/30 bg-sky-500/10 px-1.5 py-0.2 font-mono text-[9px] font-medium uppercase tracking-wider text-sky-300">
                  {view.isRoot ? "Punto de partida" : view.entityType}
                </span>
                {view.platform && (
                  <span className="font-mono text-[10px] text-slate-400">· {view.platform}</span>
                )}
              </div>
              <h4 className="mt-0.5 truncate text-sm font-semibold leading-tight text-slate-100" title={view.title}>
                {view.title}
              </h4>
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded p-1 text-slate-400 transition-colors hover:bg-slate-800 hover:text-white"
            aria-label="Cerrar inspector"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        {/* Subtitle / Primary identifier */}
        {view.subtitle && (
          <div className="mt-2 flex items-center justify-between gap-2 rounded border border-[#1b2f44] bg-[#0a1524]/80 px-2 py-1 font-mono text-[10px]">
            <span className="truncate text-slate-300">{view.subtitle}</span>
            <CopyButton value={view.subtitle} copiedValue={copiedValue} onCopy={copy} />
          </div>
        )}

        {/* Tactical Actions Row */}
        <div className="mt-2.5 flex flex-wrap items-center gap-1.5">
          {view.primaryLink && (
            <ExternalAnchor
              href={view.primaryLink.url}
              className="inline-flex items-center gap-1 rounded border border-cyan-500/30 bg-cyan-500/10 px-2 py-1 font-mono text-[10px] text-cyan-200 transition-colors hover:bg-cyan-500/20"
            >
              <span>Abrir recurso</span>
              <ExternalLink className="h-2.5 w-2.5" />
            </ExternalAnchor>
          )}

          <button
            type="button"
            onClick={() => handlePivot(pivotTarget)}
            className="inline-flex items-center gap-1 rounded border border-slate-700 bg-slate-800/70 px-2 py-1 font-mono text-[10px] text-slate-300 transition-colors hover:border-slate-600 hover:text-slate-100"
            title="Copiar identificador para una nueva búsqueda o pivote"
          >
            {pivotCopied ? (
              <>
                <Check className="h-3 w-3 text-emerald-400" />
                <span className="text-emerald-300">Copiado para pivote</span>
              </>
            ) : (
              <>
                <Search className="h-2.5 w-2.5 text-sky-400" />
                <span>Pivotar valor</span>
              </>
            )}
          </button>
        </div>
      </header>

      {/* Tab Navigation (Fase 4: 3 clear forensic tabs) */}
      <nav className="shrink-0 flex border-b border-[#1b2b3e] bg-[#070e1a] px-3">
        <button
          type="button"
          onClick={() => setActiveTab("info")}
          className={`flex items-center gap-1.5 px-3 py-2 font-mono text-[11px] font-medium transition-colors border-b-2 ${
            activeTab === "info"
              ? "border-sky-400 text-sky-300 bg-sky-500/[0.04]"
              : "border-transparent text-slate-400 hover:text-slate-200"
          }`}
        >
          <Info className="h-3.5 w-3.5" />
          <span>Información</span>
        </button>

        <button
          type="button"
          onClick={() => setActiveTab("relations")}
          className={`flex items-center gap-1.5 px-3 py-2 font-mono text-[11px] font-medium transition-colors border-b-2 ${
            activeTab === "relations"
              ? "border-sky-400 text-sky-300 bg-sky-500/[0.04]"
              : "border-transparent text-slate-400 hover:text-slate-200"
          }`}
        >
          <Network className="h-3.5 w-3.5" />
          <span>Relaciones</span>
          <span
            className={`rounded-full px-1.5 py-0.2 text-[9px] ${
              view.relationships.length > 0
                ? "bg-violet-500/20 text-violet-300 border border-violet-500/30"
                : "bg-slate-800 text-slate-500"
            }`}
          >
            {view.relationships.length}
          </span>
        </button>

        <button
          type="button"
          onClick={() => setActiveTab("provenance")}
          className={`flex items-center gap-1.5 px-3 py-2 font-mono text-[11px] font-medium transition-colors border-b-2 ${
            activeTab === "provenance"
              ? "border-sky-400 text-sky-300 bg-sky-500/[0.04]"
              : "border-transparent text-slate-400 hover:text-slate-200"
          }`}
        >
          <Fingerprint className="h-3.5 w-3.5" />
          <span>Procedencia</span>
        </button>
      </nav>

      {/* Scrollable Inspector Body */}
      <div className="flex-1 overflow-y-auto p-4 space-y-4 text-xs">
        {/* TAB 1: INFORMACIÓN */}
        {activeTab === "info" && (
          <div className="space-y-4">
            {view.observedFields.length > 0 && (
              <section>
                <h5 className="mb-2 font-mono text-[10px] font-semibold uppercase tracking-wider text-slate-400">
                  Datos observados
                </h5>
                <ObservedFields fields={view.observedFields} copiedValue={copiedValue} onCopy={copy} />
              </section>
            )}

            {view.descriptions.length > 0 && (
              <section>
                <h5 className="mb-2 font-mono text-[10px] font-semibold uppercase tracking-wider text-slate-400">
                  Resumen de perfil
                </h5>
                <div className="space-y-2">
                  {view.descriptions.map((desc) => (
                    <div
                      key={`${desc.label}-${desc.text.slice(0, 20)}`}
                      className="rounded-lg border border-[#1d344b] bg-[#081321]/80 p-3"
                    >
                      <p className="mb-1 font-mono text-[9px] uppercase tracking-wider text-slate-400">
                        {desc.label}
                      </p>
                      <p className="whitespace-pre-wrap text-[11px] leading-relaxed text-slate-300">
                        {desc.text}
                      </p>
                    </div>
                  ))}
                </div>
              </section>
            )}

            {view.links.length > 0 && (
              <section>
                <h5 className="mb-2 font-mono text-[10px] font-semibold uppercase tracking-wider text-slate-400">
                  Enlaces observados
                </h5>
                <EntityLinks links={view.links} copiedValue={copiedValue} onCopy={copy} />
              </section>
            )}

            {visibleImages.length > 0 && (
              <section>
                <div className="mb-2 flex items-center justify-between">
                  <h5 className="font-mono text-[10px] font-semibold uppercase tracking-wider text-slate-400">
                    Artefactos visuales
                  </h5>
                  <span className="font-mono text-[10px] text-slate-500">{visibleImages.length}</span>
                </div>
                <div className="grid grid-cols-4 gap-2">
                  {visibleImages.map((image) => (
                    <ArtifactImage key={image.url} image={image} />
                  ))}
                </div>
              </section>
            )}

            {view.observedFields.length === 0 &&
              view.descriptions.length === 0 &&
              view.links.length === 0 &&
              visibleImages.length === 0 && (
                <div className="rounded-lg border border-[#1b2c40] bg-[#09121f] p-4 text-center">
                  <p className="font-mono text-[11px] text-slate-400">
                    No se extrajeron campos observados adicionales para esta entidad.
                  </p>
                </div>
              )}
          </div>
        )}

        {/* TAB 2: RELACIONES */}
        {activeTab === "relations" && (
          <div className="space-y-3">
            <div className="flex items-center justify-between">
              <h5 className="font-mono text-[10px] font-semibold uppercase tracking-wider text-slate-400">
                Conexiones documentadas
              </h5>
              <span className="font-mono text-[10px] text-slate-500">
                {view.relationships.length} {view.relationships.length === 1 ? "vínculo" : "vínculos"}
              </span>
            </div>

            {view.relationships.length > 0 ? (
              <div className="overflow-hidden rounded-lg border border-[#1d344b] bg-[#081321]/80 divide-y divide-[#172b40]">
                {view.relationships.map(({ edge, node: related, label }) => (
                  <button
                    key={edge.id}
                    type="button"
                    onClick={() => onSelectNode(related.id)}
                    className="group flex w-full items-center gap-2.5 px-3 py-2.5 text-left transition-colors hover:bg-[#0e1e32]"
                  >
                    <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded border border-[#29415b] bg-[#07111e] text-cyan-300">
                      <PlatformIcon
                        platform={related.data.platform}
                        entityType={related.data.entity_type}
                        value={related.data.value}
                        className="h-3.5 w-3.5"
                      />
                    </span>
                    <div className="min-w-0 flex-1">
                      <span className="block truncate font-mono text-[11px] text-slate-200 group-hover:text-cyan-200">
                        {related.data.display_name || related.data.value}
                      </span>
                      <span className="block truncate font-mono text-[9px] text-violet-300">
                        {label}
                      </span>
                    </div>
                    <ChevronRight className="h-3.5 w-3.5 shrink-0 text-slate-600 transition-transform group-hover:translate-x-0.5 group-hover:text-cyan-300" />
                  </button>
                ))}
              </div>
            ) : (
              <div className="rounded-lg border border-[#1b2c40] bg-[#09121f] p-4 text-center">
                <p className="font-mono text-[11px] text-slate-400">
                  Sin conexiones directas documentadas con otras entidades en el grafo actual.
                </p>
              </div>
            )}
          </div>
        )}

        {/* TAB 3: PROCEDENCIA */}
        {activeTab === "provenance" && (
          <div className="space-y-4">
            <section>
              <h5 className="mb-2 font-mono text-[10px] font-semibold uppercase tracking-wider text-slate-400">
                Trazabilidad de recolección
              </h5>
              <dl className="overflow-hidden rounded-lg border border-[#1d344b] bg-[#081321]/80 font-mono text-[11px]">
                {view.provenance?.sourceTool && (
                  <div className="grid grid-cols-[100px_minmax(0,1fr)] items-center gap-2 px-3 py-2">
                    <dt className="flex items-center gap-1.5 text-slate-400">
                      <Wrench className="h-3 w-3 text-cyan-400" /> Herramienta
                    </dt>
                    <dd className="break-words font-semibold text-slate-200">
                      {view.provenance.sourceTool}
                    </dd>
                  </div>
                )}
                {view.provenance?.discoveredAt && (
                  <div className="grid grid-cols-[100px_minmax(0,1fr)] items-center gap-2 border-t border-[#172b40] px-3 py-2">
                    <dt className="flex items-center gap-1.5 text-slate-400">
                      <CalendarDays className="h-3 w-3 text-cyan-400" /> Descubierto
                    </dt>
                    <dd className="text-slate-300">
                      {formatDate(view.provenance.discoveredAt)}
                    </dd>
                  </div>
                )}
                {view.provenance?.engine && (
                  <div className="grid grid-cols-[100px_minmax(0,1fr)] items-center gap-2 border-t border-[#172b40] px-3 py-2">
                    <dt className="flex items-center gap-1.5 text-slate-400">
                      <ScanSearch className="h-3 w-3 text-cyan-400" /> Motor
                    </dt>
                    <dd className="break-words text-slate-300">
                      {view.provenance.engine}
                    </dd>
                  </div>
                )}
                {view.provenance?.sourceUrl && (
                  <div className="border-t border-[#172b40] px-3 py-2">
                    <ExternalAnchor
                      href={view.provenance.sourceUrl}
                      className="inline-flex max-w-full items-center gap-1 text-violet-300 hover:underline"
                    >
                      <span>Fuente original</span>
                      <ExternalLink className="h-3 w-3 shrink-0" />
                    </ExternalAnchor>
                  </div>
                )}
              </dl>
            </section>

            {/* Forensic methodology disclaimer */}
            <div className="rounded-lg border border-[#1b2e44] bg-[#091524]/60 p-3">
              <div className="flex items-center gap-1.5 font-mono text-[10px] font-semibold text-cyan-300">
                <Fingerprint className="h-3.5 w-3.5" />
                <span>Metodología pasiva OSINT</span>
              </div>
              <p className="mt-1.5 text-[10px] leading-relaxed text-slate-400">
                Este hallazgo fue derivado mediante fuentes públicas accesibles en línea y correlación pasiva. Su presencia en este informe técnico documenta datos observados y no constituye una atribución de identidad irrefutable sin verificación por el analista.
              </p>
            </div>
          </div>
        )}
      </div>
    </aside>
  );
}

export function RelationshipInspector({
  edge,
  nodes,
  onClose,
  onSelectNode,
  relationLabel,
}: {
  edge: GraphEdge;
  nodes: GraphNode[];
  onClose: () => void;
  onSelectNode: (nodeId: string) => void;
  relationLabel: (edge: GraphEdge) => string;
}) {
  const source = nodes.find((node) => node.id === edge.source);
  const target = nodes.find((node) => node.id === edge.target);
  const fields = buildRelationshipEvidenceFields(edge.evidence);
  const relation = relationLabel(edge);
  const provenance = isProvenanceEdge(edge);

  return (
    <aside
      className="absolute bottom-3 right-3 top-3 z-30 flex w-[min(410px,calc(100%-1.5rem))] flex-col rounded-xl border border-[#22354c] bg-[#070e19]/95 shadow-2xl shadow-black/60 backdrop-blur-sm overflow-hidden animate-slide-in-right"
      aria-label="Inspector forense de relación"
    >
      <header className="shrink-0 border-b border-[#1b2b3e] bg-[#081220]/90 px-4 pt-3.5 pb-3">
        <div className="flex items-start justify-between gap-3">
          <div>
            <p className={`font-mono text-[10px] uppercase tracking-[0.14em] ${provenance ? "text-slate-400" : "text-cyan-300"}`}>
              {provenance ? "Procedencia / contexto" : "Relación de evidencia"}
            </p>
            <h4 className="mt-1 text-sm font-semibold text-slate-100">{relation}</h4>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded p-1 text-slate-400 transition-colors hover:bg-slate-800 hover:text-white"
            aria-label="Cerrar inspector"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        {source && target && (
          <div className="mt-3 grid grid-cols-[minmax(0,1fr)_24px_minmax(0,1fr)] items-center gap-2 rounded-lg border border-[#1d344b] bg-[#081321]/80 p-2.5">
            <button
              type="button"
              onClick={() => onSelectNode(source.id)}
              className="truncate text-left font-mono text-[11px] text-slate-200 transition-colors hover:text-cyan-300"
              title={source.data.display_name || source.data.value}
            >
              {source.data.display_name || source.data.value}
            </button>
            <Network className="h-4 w-4 text-cyan-400 mx-auto" />
            <button
              type="button"
              onClick={() => onSelectNode(target.id)}
              className="truncate text-right font-mono text-[11px] text-slate-200 transition-colors hover:text-cyan-300"
              title={target.data.display_name || target.data.value}
            >
              {target.data.display_name || target.data.value}
            </button>
          </div>
        )}

        <p
          className={`mt-2.5 rounded-md border px-2.5 py-2 text-[10px] leading-relaxed ${
            provenance
              ? "border-slate-700/80 bg-slate-900/40 text-slate-400"
              : "border-cyan-900/80 bg-cyan-950/20 text-slate-300"
          }`}
        >
          {provenance
            ? "Esta conexión documenta cómo se derivó el hallazgo a partir de los datos iniciales de búsqueda."
            : "Esta relación describe evidencia técnica observada entre entidades durante la correlación OSINT."}
        </p>
      </header>

      <div className="flex-1 overflow-y-auto p-4 space-y-4 text-xs">
        {fields.length > 0 && (
          <section>
            <h5 className="mb-2 font-mono text-[10px] font-semibold uppercase tracking-wider text-slate-400">
              Evidencia observada
            </h5>
            <ObservedFields
              fields={fields}
              copiedValue={null}
              onCopy={(value) => void navigator.clipboard.writeText(value)}
            />
          </section>
        )}

        {edge.supports_group && (
          <div className="rounded-lg border border-[#1b2e44] bg-[#091524]/60 p-3">
            <p className="font-mono text-[10px] text-slate-400">
              Esta relación apoya la consolidación estructural de grupos de entidades en el grafo forense.
            </p>
          </div>
        )}
      </div>
    </aside>
  );
}
