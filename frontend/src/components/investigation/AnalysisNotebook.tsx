"use client";

import { useMemo, useState, type FormEvent } from "react";
import { BookOpen, ExternalLink, Plus } from "lucide-react";
import { addAnalysisNote } from "@/lib/api";
import type { AnalysisNoteKind, InvestigationData } from "@/lib/types";
import { Markdown } from "@/components/report/Markdown";

const KINDS: Record<AnalysisNoteKind, string> = {
  comment: "Comentario", summary: "Resumen", insight: "Hallazgo destacado",
  hypothesis: "Hipótesis", next_step: "Próximo paso",
};

export function AnalysisNotebook({ investigation, onSaved, readOnly = false }: {
  investigation: InvestigationData; onSaved?: () => void; readOnly?: boolean;
}) {
  const [kind, setKind] = useState<AnalysisNoteKind>("comment");
  const [filter, setFilter] = useState<string>("all");
  const [title, setTitle] = useState("");
  const [content, setContent] = useState("");
  const [sources, setSources] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const notes = useMemo(() => [...(investigation.analysis_notes ?? [])]
    .filter((note) => filter === "all" || note.kind === filter)
    .sort((a, b) => a.created_at.localeCompare(b.created_at)), [investigation.analysis_notes, filter]);

  async function save(event: FormEvent) {
    event.preventDefault();
    setSaving(true);
    setError(null);
    try {
      await addAnalysisNote(investigation.id, { kind, title, content,
        evidence_urls: sources.split(/\r?\n/).map((url) => url.trim()).filter(Boolean) });
      setTitle(""); setContent(""); setSources("");
      onSaved?.();
    } catch (err) {
      setError(err instanceof Error ? err.message : "No se pudo guardar la nota");
    } finally { setSaving(false); }
  }

  return <section className="space-y-4">
    <div className="flex flex-wrap items-center justify-between gap-3">
      <div><h3 className="flex items-center gap-2 text-sm font-semibold text-slate-100"><BookOpen className="h-4 w-4 text-amber-300" />Cuaderno de análisis</h3>
        <p className="mt-1 text-xs text-slate-400">Interpretaciones, preguntas y conclusiones del agente y del analista, con sus fuentes.</p></div>
      <select aria-label="Filtrar notas" value={filter} onChange={(event) => setFilter(event.target.value)} className="rounded-lg border border-[#24394f] bg-[#07101b] p-2 text-xs text-slate-300">
        <option value="all">Todas las notas</option>{Object.entries(KINDS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
      </select>
    </div>
    {investigation.sessions && investigation.sessions.length > 0 && <div className="flex flex-wrap gap-2 text-[10px] text-slate-400">
      {investigation.sessions.map((session) => <span key={session.id} className="rounded border border-[#24394f] bg-[#091522] px-2 py-1">{session.client}{session.model ? ` · ${session.model}` : ""} · {session.status === "active" ? "En curso" : session.status === "paused" ? "Pausada" : "Finalizada"}</span>)}
    </div>}
    {notes.length === 0 && <div className="rounded-xl border border-dashed border-[#294159] p-8 text-center text-xs text-slate-500">Las notas del agente y tus comentarios aparecerán aquí.</div>}
    <div className="space-y-3">{notes.map((note) => <article key={note.id} className="rounded-xl border border-[#24394f] bg-[#091522] p-4 print:break-inside-avoid">
      <div className="mb-3 flex flex-wrap items-center gap-2 text-[10px]"><span className={`rounded border px-2 py-0.5 ${note.kind === "hypothesis" ? "border-amber-500/30 text-amber-300" : "border-sky-500/25 text-sky-200"}`}>{KINDS[note.kind]}</span>
        <span className="text-slate-400">{note.author_type === "agent" ? "Análisis del agente" : "Nota del analista"} · {note.author}</span>
        <time className="ml-auto text-slate-500" dateTime={note.created_at}>{new Date(note.created_at).toLocaleString("es-PE")}</time></div>
      <h4 className="mb-2 text-sm font-medium text-slate-100">{note.title}</h4><Markdown>{note.content}</Markdown>
      {note.entity_ids && note.entity_ids.length > 0 && <p className="mt-3 text-[10px] text-slate-500">{note.entity_ids.length} observaciones referenciadas</p>}
      {note.evidence_urls && note.evidence_urls.length > 0 && <div className="mt-3 space-y-1 border-t border-[#1c3045] pt-3">{note.evidence_urls.map((url) => <a key={url} href={url} target="_blank" rel="noopener noreferrer" className="flex items-center gap-2 break-all text-[11px] text-sky-300 hover:underline"><ExternalLink className="h-3 w-3 shrink-0" />{url}</a>)}</div>}
      {note.details && Object.keys(note.details).length > 0 && <details className="mt-3 text-[11px] text-slate-400"><summary className="cursor-pointer">Datos adicionales del análisis</summary><pre className="mt-2 overflow-auto whitespace-pre-wrap rounded bg-[#07101b] p-3">{JSON.stringify(note.details, null, 2)}</pre></details>}
    </article>)}</div>
    {!readOnly && <form onSubmit={save} className="space-y-3 rounded-xl border border-[#24394f] bg-[#08111e] p-4 print:hidden">
      <h4 className="flex items-center gap-2 text-xs font-semibold text-slate-200"><Plus className="h-3.5 w-3.5" />Añadir nota del analista</h4>
      <div className="flex flex-wrap gap-2"><select aria-label="Tipo de nota" value={kind} onChange={(event) => setKind(event.target.value as AnalysisNoteKind)} className="rounded-lg border border-[#24394f] bg-[#07101b] p-2 text-xs text-slate-300">{Object.entries(KINDS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select>
        <input aria-label="Título de la nota" required maxLength={200} value={title} onChange={(event) => setTitle(event.target.value)} placeholder="Título" className="min-w-48 flex-1 rounded-lg border border-[#24394f] bg-[#07101b] p-2 text-xs text-slate-200" /></div>
      <textarea aria-label="Contenido de la nota" required maxLength={20000} rows={4} value={content} onChange={(event) => setContent(event.target.value)} placeholder="Tu análisis, una pregunta o el próximo paso…" className="w-full rounded-lg border border-[#24394f] bg-[#07101b] p-3 text-xs text-slate-200" />
      <textarea aria-label="Fuentes de la nota" rows={2} value={sources} onChange={(event) => setSources(event.target.value)} placeholder="Fuentes públicas: una URL por línea (opcional)" className="w-full rounded-lg border border-[#24394f] bg-[#07101b] p-3 text-xs text-slate-200" />
      {error && <p role="alert" className="text-xs text-rose-300">{error}</p>}
      <button disabled={saving} type="submit" className="rounded-lg border border-sky-500/40 bg-sky-500/10 px-4 py-2 text-xs font-medium text-sky-200 disabled:opacity-50">{saving ? "Guardando…" : "Guardar nota"}</button>
    </form>}
  </section>;
}
