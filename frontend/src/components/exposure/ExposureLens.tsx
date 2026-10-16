"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import {
  ArrowLeft,
  ArrowUpRight,
  BookOpenCheck,
  Fingerprint,
  Globe2,
  LoaderCircle,
  MapPin,
  RefreshCw,
  ShieldCheck,
  Sparkles,
} from "lucide-react";
import { analyzeExposure, ApiError, getExposureReport } from "@/lib/api";
import type {
  ExposureCategory,
  ExposureFinding,
  ExposurePartialReason,
  ExposureReport,
  ExposureSeverity,
} from "@/lib/types";
import styles from "./ExposureLens.module.css";

const CATEGORY_LABEL: Record<ExposureCategory, string> = {
  contact_exposure: "Contacto",
  alias_reuse: "Alias",
  cross_platform_correlation: "Plataformas",
  location_disclosure: "Ubicación",
  temporal_exposure: "Tiempo y eventos",
  education_work_context: "Estudio y trabajo",
  biographical_identifiers: "Biografía",
  public_documents: "Documentos",
  breach_exposure: "Brechas",
  infostealer_exposure: "Infostealers",
  content_disclosure: "Contenido público",
};

const CATEGORY_ORDER = Object.keys(CATEGORY_LABEL) as ExposureCategory[];
const SEVERITY_LABEL: Record<ExposureSeverity, string> = {
  high: "Alta",
  medium: "Media",
  low: "Baja",
  informational: "Informativa",
};
const PARTIAL_REASON: Record<ExposurePartialReason, string> = {
  acquisition_partial: "Fair tuvo fuentes parciales; esto no indica ausencia de datos fuera de la cobertura observada.",
  content_limit_reached: "Se alcanzó el límite de contenido; parte de la huella quedó sin analizar.",
  ai_failure: "La clasificación opcional con IA no terminó; se conservaron los hallazgos determinísticos.",
};

function formatDate(value?: string | null) {
  if (!value) return "Fecha no registrada";
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? value.slice(0, 10)
    : new Intl.DateTimeFormat("es-PE", { day: "2-digit", month: "short", year: "numeric" }).format(date);
}

function requiresFinalReview(cause: unknown) {
  return cause instanceof ApiError && cause.code === "review_not_finalized";
}

function FindingCard({ finding }: { finding: ExposureFinding }) {
  return (
    <article className={styles.finding}>
      <div className={styles.findingTop}>
        <span className={styles["severity_" + finding.severity]}>
          <span className={styles.severity}>{SEVERITY_LABEL[finding.severity]}</span>
        </span>
        <span className={styles.category}>{CATEGORY_LABEL[finding.category]}</span>
        <span className={styles.method}>
          {finding.analysis_method === "ai" ? <Sparkles size={12} /> : <BookOpenCheck size={12} />}
          {finding.analysis_method === "ai" ? "Clasificado con IA" : "Detectado por regla"}
        </span>
      </div>
      <h3>{finding.title}</h3>
      <p className={styles.findingSummary}>{finding.summary}</p>
      <div className={styles.explanation}>
        <span>¿Por qué apareció?</span>
        <p>{finding.why_it_matters}</p>
      </div>
      {finding.signals.length > 0 && (
        <div className={styles.signalList} aria-label="Señales observadas">
          {finding.signals.slice(0, 5).map((signal) => <span key={signal}>{signal.replaceAll("_", " ")}</span>)}
        </div>
      )}
      {finding.evidence.length > 0 && (
        <details className={styles.evidence}>
          <summary>Ver evidencia <span>{finding.evidence.length} {finding.evidence.length === 1 ? "fuente" : "fuentes"}</span></summary>
          <div className={styles.evidenceList}>
            {finding.evidence.map((item, index) => (
              <div className={styles.evidenceItem} key={item.source_type + ":" + (item.source_id ?? index) + ":" + index}>
                <div className={styles.evidenceMeta}>
                  <span>{item.platform || item.source_type}</span>
                  {item.account && <span>{item.account.startsWith("@") ? item.account : "@" + item.account}</span>}
                  {item.occurred_at && <time dateTime={item.occurred_at}>{formatDate(item.occurred_at)}</time>}
                  {item.url && <a href={item.url} target="_blank" rel="noreferrer">Abrir fuente <ArrowUpRight size={12} /></a>}
                </div>
                {item.excerpt && <p>{item.excerpt}</p>}
              </div>
            ))}
          </div>
          <span className={styles.basis}>Base: {finding.basis === "observed" ? "observado explícitamente" : "inferencia marcada"}</span>
        </details>
      )}
      {finding.recommendations.length > 0 && (
        <ul className={styles.recommendations}>
          {finding.recommendations.slice(0, 4).map((item) => <li key={item}>{item}</li>)}
        </ul>
      )}
    </article>
  );
}

export function ExposureLens({ investigationId }: { investigationId: string }) {
  const [report, setReport] = useState<ExposureReport | null>(null);
  const [loading, setLoading] = useState(true);
  const [analyzing, setAnalyzing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [reviewRequired, setReviewRequired] = useState(false);

  useEffect(() => {
    let cancelled = false;
    getExposureReport(investigationId).then((next) => {
      if (!cancelled) {
        setReport(next);
        setReviewRequired(false);
        setError(null);
      }
    }).catch((cause: unknown) => {
      if (!cancelled) {
        setError(cause instanceof Error ? cause.message : "No se pudo cargar el informe.");
        setReviewRequired(requiresFinalReview(cause));
      }
    }).finally(() => {
      if (!cancelled) setLoading(false);
    });
    return () => { cancelled = true; };
  }, [investigationId]);

  const runAnalysis = async () => {
    setAnalyzing(true);
    setError(null);
    try {
      setReport(await analyzeExposure(investigationId));
      setReviewRequired(false);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "El análisis no pudo completarse.");
      setReviewRequired(requiresFinalReview(cause));
    } finally {
      setAnalyzing(false);
    }
  };

  const current = Boolean(report && !report.stale);
  const canAnalyze = Boolean(report && report.status !== "running");
  const findings = current ? report?.findings ?? [] : [];

  if (loading) {
    return <main className={styles.page}><div className={styles.loading}><LoaderCircle size={17} /> Cargando huella revisada…</div></main>;
  }

  return (
    <main className={styles.page}>
      <Link href={`/investigation/${investigationId}/review`} className={styles.backLink}>
        <ArrowLeft size={14} /> Verification Gate
      </Link>

      <header className={styles.hero}>
        <div className={styles.heroCopy}>
          <div className={styles.eyebrow}><span /> FAIR MODE <i>·</i> EXPOSURE LENS</div>
          <h1>Esto es lo que tu<br />huella pública revela.</h1>
          <p>Una lectura explicable de datos que tú declaraste o confirmaste. Cada señal enlaza con su fuente y termina en una acción defensiva.</p>
          <div className={styles.heroMeta}>
            <span><ShieldCheck size={13} /> Huella revisada</span>
            {report?.dataset_hash && <code>DATASET · {report.dataset_hash.slice(0, 12)}</code>}
          </div>
        </div>
        <aside className={styles.scopeCard} aria-label="Límite del análisis">
          <div className={styles.scopeHeader}><Fingerprint size={15} /><span>LÍMITE DE ATRIBUCIÓN</span></div>
          <div className={styles.scopeFlow}>
            <span>Declarado<br />o confirmado</span><i aria-hidden="true" />
            <span>Fuente<br />pública</span><i aria-hidden="true" />
            <span>Acción<br />defensiva</span>
          </div>
          <p>Los perfiles rechazados o dudosos quedan fuera. No se estima personalidad ni probabilidad de daño.</p>
        </aside>
      </header>

      {error && (
        <div className={styles.notice} role="alert">
          <MapPin size={16} />
          <div>
            <strong>{reviewRequired ? "Finaliza la revisión para continuar" : "No se pudo completar la solicitud"}</strong>
            <p>{reviewRequired ? "Exposure Lens solo analiza una huella cerrada en Verification Gate." : error}</p>
          </div>
          {reviewRequired && <Link href={`/investigation/${investigationId}/review`}>Abrir revisión <ArrowUpRight size={13} /></Link>}
        </div>
      )}

      {report?.stale && (
        <div className={styles.staleNotice} role="status">
          <RefreshCw size={16} />
          <div><strong>La huella cambió desde este análisis.</strong><p>Este informe anterior está oculto hasta que vuelvas a analizar la versión revisada actual.</p></div>
          <button type="button" disabled={analyzing} onClick={() => void runAnalysis()}><RefreshCw size={13} /> Reanalizar</button>
        </div>
      )}

      {!reviewRequired && (
        <>
          <section className={styles.controlRow} aria-label="Estado del análisis">
            <div>
              <span className={styles.sectionKicker}>LECTURA DE EXPOSICIÓN</span>
              <strong>{report?.status === "pending" ? "La huella está lista para analizar" :
                report?.status === "running" ? "El análisis está en curso" :
                  report?.status === "partial" ? "Informe parcial" :
                    report?.status === "failed" ? "El análisis falló" : "Informe explicable"}</strong>
              <span className={styles.controlNote}>
                {report?.generated_at ? "Generado " + formatDate(report.generated_at) : "Sin puntaje global ni probabilidades."}
              </span>
            </div>
            <button type="button" className={styles.analyzeButton} disabled={!canAnalyze || analyzing || (report?.status === "pending" && !report.current_dataset_hash)}
              onClick={() => void runAnalysis()}>
              {analyzing || report?.status === "running"
                ? <><LoaderCircle size={15} className={styles.spin} /> Analizando…</>
                : <><Sparkles size={15} /> {report?.status === "pending" || report?.stale ? "Analizar exposición" : "Volver a analizar"}</>}
            </button>
          </section>

          {current && report && ["completed", "partial"].includes(report.status) && (
            <Link href={`/investigation/${investigationId}/reconstruction`} className={styles.sourceLink}>
              Reconstruir mi huella pública <ArrowUpRight size={14} />
            </Link>
          )}

          {report?.status === "pending" && (
            <section className={styles.emptyState}>
              <span className={styles.emptyGlyph}><Globe2 size={20} /></span>
              <h2>La fuente ya está delimitada.</h2>
              <p>El análisis comenzará solo sobre perfiles, documentos, brechas y publicaciones presentes en la huella que finalizaste.</p>
              <button type="button" className={styles.analyzeButton} disabled={analyzing || !report.current_dataset_hash} onClick={() => void runAnalysis()}>
                {analyzing ? <><LoaderCircle size={15} className={styles.spin} /> Analizando…</> : <><Sparkles size={15} /> Analizar exposición</>}
              </button>
            </section>
          )}

          {report?.status === "partial" && (
            <div className={styles.partialNotice} role="status">
              {report.partial_reasons.length
                ? report.partial_reasons.map((reason) => PARTIAL_REASON[reason]).join(" ")
                : "El análisis determinístico quedó guardado con cobertura parcial."}
            </div>
          )}

          {report?.status === "failed" && (
            <div className={styles.partialNotice} role="alert">
              No se pudo guardar el análisis. Revisa la conexión y vuelve a intentarlo.
            </div>
          )}

          {current && report && report.status !== "pending" && report.status !== "running" && report.status !== "failed" && (
            <>
              <section className={styles.summaryGrid} aria-label="Hallazgos por severidad">
                {(["high", "medium", "low", "informational"] as ExposureSeverity[]).map((severity) => (
                  <article className={styles.summaryCard} data-severity={severity} key={severity}>
                    <span>{SEVERITY_LABEL[severity]}</span>
                    <strong>{report.summary[severity] ?? 0}</strong>
                    <small>impacto potencial de exposición</small>
                  </article>
                ))}
              </section>

              <section className={styles.categoryPanel} aria-labelledby="category-title">
                <div className={styles.sectionHeading}>
                  <div><span className={styles.sectionKicker}>MAPA DE CATEGORÍAS</span><h2 id="category-title">Dónde aparece exposición</h2></div>
                  <span>{findings.length} hallazgos explicables</span>
                </div>
                <div className={styles.categoryGrid}>
                  {CATEGORY_ORDER.map((category) => (
                    <div className={styles.categoryTile} key={category}>
                      <span>{CATEGORY_LABEL[category]}</span>
                      <strong>{report.categories[category] ?? 0}</strong>
                    </div>
                  ))}
                </div>
              </section>

              {report.top_exposures.length > 0 && (
                <section className={styles.topSection} aria-labelledby="top-title">
                  <div className={styles.sectionHeading}>
                    <div><span className={styles.sectionKicker}>CONTENIDO ATRIBUIDO</span><h2 id="top-title">Publicaciones con mayor exposición</h2></div>
                    <span>{report.analyzed_content_count} elementos analizados</span>
                  </div>
                  <div className={styles.topGrid}>
                    {report.top_exposures.map((item) => (
                      <article className={styles.topCard} key={item.id}>
                        <div className={styles.topMeta}>
                          <span>{item.platform || "Perfil público"}{item.account ? " · @" + item.account.replace(/^@/, "") : ""}</span>
                          <span className={styles["severity_" + item.severity]}><span className={styles.severity}>{SEVERITY_LABEL[item.severity]}</span></span>
                        </div>
                        <time>{formatDate(item.published_at)}</time>
                        <blockquote>{item.excerpt}</blockquote>
                        <div className={styles.reveals}>{item.reveals.map((label) => <span key={label}>{label}</span>)}</div>
                        <p>{item.why_it_matters}</p>
                        {item.evidence[0]?.url && <a className={styles.sourceLink} href={item.evidence[0].url} target="_blank" rel="noreferrer">Ver publicación <ArrowUpRight size={13} /></a>}
                        <ul className={styles.topAdvice}>{item.recommendations.slice(0, 2).map((recommendation) => <li key={recommendation}>{recommendation}</li>)}</ul>
                      </article>
                    ))}
                  </div>
                </section>
              )}

              <section className={styles.findingsSection} aria-labelledby="findings-title">
                <div className={styles.sectionHeading}>
                  <div><span className={styles.sectionKicker}>EVIDENCIA Y ACCIONES</span><h2 id="findings-title">Hallazgos</h2></div>
                  <span>OBSERVED / EXPLICABLE</span>
                </div>
                {findings.length > 0 ? (
                  <div className={styles.findingGrid}>{findings.map((finding) => <FindingCard key={finding.id} finding={finding} />)}</div>
                ) : (
                  <div className={styles.emptyState}><h2>No hay señales en las categorías cubiertas.</h2><p>El resultado describe este conjunto revisado; no afirma que no exista otra información pública.</p></div>
                )}
              </section>
            </>
          )}
        </>
      )}
    </main>
  );
}
