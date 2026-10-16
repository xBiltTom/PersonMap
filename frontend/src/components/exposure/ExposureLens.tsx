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
  ExposureTopItem,
} from "@/lib/types";
import styles from "./ExposureLens.module.css";

const CATEGORY_LABEL: Record<ExposureCategory, string> = {
  contact_exposure: "Contacto público",
  alias_reuse: "Alias compartido",
  cross_platform_correlation: "Cuentas relacionadas",
  location_disclosure: "Ubicación",
  temporal_exposure: "Referencia temporal",
  education_work_context: "Estudio o trabajo",
  biographical_identifiers: "Identificador biográfico",
  public_documents: "Documento público",
  breach_exposure: "Exposición en brechas",
  infostealer_exposure: "Registro de infostealer",
  content_disclosure: "Contenido público",
};

const SEVERITY_LABEL: Record<ExposureSeverity, string> = {
  high: "Alta",
  medium: "Media",
  low: "Baja",
  informational: "Informativa",
};

const PARTIAL_REASON: Record<ExposurePartialReason, string> = {
  acquisition_partial: "La adquisición tuvo fuentes parciales; esto no indica ausencia de datos fuera de la cobertura observada.",
  content_limit_reached: "Se alcanzó el límite de contenido y algunos elementos quedaron fuera del análisis.",
  ai_failure: "La clasificación opcional con IA no terminó; se conservaron los hallazgos determinísticos.",
};

type AccountThread = {
  key: string;
  platform: string;
  account: string;
  posts: ExposureTopItem[];
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

function groupPosts(posts: ExposureTopItem[]): AccountThread[] {
  const grouped = new Map<string, AccountThread>();
  for (const post of posts) {
    const platform = post.platform || "Fuente pública";
    const account = post.account ? "@" + post.account.replace(/^@/, "") : "Cuenta no indicada";
    const key = `${platform.toLocaleLowerCase()}\u0000${account.toLocaleLowerCase()}`;
    const thread = grouped.get(key) ?? { key, platform, account, posts: [] };
    thread.posts.push(post);
    grouped.set(key, thread);
  }
  return Array.from(grouped.values());
}

function evidenceSummary(posts: ExposureTopItem[], threads: AccountThread[], relationshipCount: number) {
  if (posts.length === 0) {
    return relationshipCount > 0
      ? `No se priorizaron publicaciones en esta cobertura; sí hay ${relationshipCount} ${relationshipCount === 1 ? "hallazgo que relaciona" : "hallazgos que relacionan"} cuentas mediante evidencia explícita.`
      : "En esta cobertura no aparecen publicaciones con señales priorizadas ni relaciones explícitas entre cuentas. Esto no afirma que no exista otra actividad pública.";
  }
  const signals = Array.from(new Set(posts.flatMap((post) => post.reveals))).slice(0, 4);
  const signalText = signals.length ? signals.join(", ") : "señales de exposición pública";
  const relationText = relationshipCount > 0
    ? ` También se registraron ${relationshipCount} ${relationshipCount === 1 ? "relación explícita" : "relaciones explícitas"} entre cuentas.`
    : "";
  return `La reconstrucción vincula ${threads.length} ${threads.length === 1 ? "cuenta atribuida" : "cuentas atribuidas"} con ${posts.length} ${posts.length === 1 ? "publicación priorizada" : "publicaciones priorizadas"}. Los fragmentos muestran ${signalText}.${relationText} La lectura describe solo evidencia pública revisada; no infiere rasgos personales ni añade atribuciones.`;
}

function FindingLine({ finding }: { finding: ExposureFinding }) {
  return (
    <article className={styles.findingLine}>
      <div className={styles.findingMeta}>
        <span className={`${styles.severity} ${styles[`severity_${finding.severity}`]}`}>
          {SEVERITY_LABEL[finding.severity]}
        </span>
        <span>{CATEGORY_LABEL[finding.category]}</span>
        <span className={styles.findingMethod}>
          {finding.analysis_method === "ai" ? <Sparkles size={12} /> : <BookOpenCheck size={12} />}
          {finding.analysis_method === "ai" ? "Clasificado con IA" : "Detectado por regla"}
        </span>
      </div>
      <h3>{finding.title}</h3>
      <p>{finding.summary}</p>
      <p className={styles.why}>{finding.why_it_matters}</p>
      {finding.evidence.length > 0 && (
        <details className={styles.sourceDetails}>
          <summary>Fuentes observadas <span>{finding.evidence.length}</span></summary>
          <ul>
            {finding.evidence.map((item, index) => (
              <li key={`${item.source_id ?? "source"}-${index}`}>
                <span>{[item.platform, item.account && "@" + item.account.replace(/^@/, ""), item.occurred_at && formatDate(item.occurred_at)].filter(Boolean).join(" · ") || item.source_type}</span>
                {item.excerpt && <p>{item.excerpt}</p>}
                {item.url && <a href={item.url} target="_blank" rel="noreferrer">Abrir fuente <ArrowUpRight size={12} /></a>}
              </li>
            ))}
          </ul>
        </details>
      )}
      {finding.recommendations.length > 0 && (
        <details className={styles.sourceDetails}>
          <summary>Acciones defensivas <span>{finding.recommendations.length}</span></summary>
          <ul>{finding.recommendations.slice(0, 4).map((item) => <li key={item}>{item}</li>)}</ul>
        </details>
      )}
    </article>
  );
}

function AccountThreadView({ thread, findings }: { thread: AccountThread; findings: ExposureFinding[] }) {
  return (
    <section className={styles.accountThread} aria-label={`${thread.platform}, ${thread.account}`}>
      <header className={styles.accountHeader}>
        <span className={styles.accountNode} aria-hidden="true"><Globe2 size={15} /></span>
        <div>
          <span className={styles.nodeCaption}>CUENTA ATRIBUIDA</span>
          <h3>{thread.platform} <span>·</span> {thread.account}</h3>
        </div>
        <span className={styles.threadCount}>{thread.posts.length} {thread.posts.length === 1 ? "publicación priorizada" : "publicaciones priorizadas"}</span>
      </header>
      <ol className={styles.postTrail}>
        {thread.posts.map((post) => {
          const sourceId = post.evidence.find((item) => item.source_type === "content")?.source_id;
          const relatedFinding = findings.find((finding) =>
            finding.category === "content_disclosure" && sourceId && finding.source_content_ids.includes(sourceId)
          );
          const method = post.analysis_method;
          const sourceUrl = post.evidence.find((item) => item.url)?.url;
          return (
            <li className={styles.postSignal} key={post.id}>
              <div className={styles.postMeta}>
                <span className={`${styles.severity} ${styles[`severity_${post.severity}`]}`}>
                  Riesgo {SEVERITY_LABEL[post.severity].toLowerCase()}
                </span>
                <time dateTime={post.published_at ?? undefined}>{formatDate(post.published_at)}</time>
                <span className={styles.methodTag}>
                  {method === "ai" ? <Sparkles size={12} /> : <BookOpenCheck size={12} />}
                  {method === "ai" ? "IA" : "Reglas"}
                </span>
              </div>
              <blockquote>{post.excerpt}</blockquote>
              <div className={styles.revealList} aria-label="Señales observadas">
                {post.reveals.map((label) => <span key={label}>{label}</span>)}
              </div>
              <p className={styles.postExplanation}>
                <strong>Por qué destaca: </strong>{relatedFinding?.summary ?? post.why_it_matters}
                {relatedFinding?.why_it_matters && ` ${relatedFinding.why_it_matters}`}
              </p>
              <div className={styles.postActions}>
                {sourceUrl && <a href={sourceUrl} target="_blank" rel="noreferrer">Ver publicación <ArrowUpRight size={13} /></a>}
                {post.recommendations.length > 0 && (
                  <details className={styles.inlineDetails}>
                    <summary>Qué revisar</summary>
                    <p>{post.recommendations[0]}</p>
                  </details>
                )}
              </div>
            </li>
          );
        })}
      </ol>
    </section>
  );
}

export function ExposureLens({ investigationId }: { investigationId: string }) {
  const [report, setReport] = useState<ExposureReport | null>(null);
  const [loading, setLoading] = useState(true);
  const [analyzing, setAnalyzing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [reviewRequired, setReviewRequired] = useState(false);
  const aiProcessing = report?.config.ai_processing as { enabled?: boolean; processed?: number; cached?: number; failed_batches?: number } | undefined;

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
  const prioritizedPosts = current ? report?.top_exposures ?? [] : [];
  const accountThreads = groupPosts(prioritizedPosts);
  const relationshipFindings = findings.filter((finding) =>
    finding.category === "alias_reuse" || finding.category === "cross_platform_correlation"
  );
  const secondaryFindings = findings.filter((finding) => finding.category !== "content_disclosure");
  const analyzedPosts = Number(report?.config.public_post_count || 0);
  const identitySources = new Set(accountThreads.map((thread) => thread.key)).size;
  const reconstructionSummary = evidenceSummary(prioritizedPosts, accountThreads, relationshipFindings.length);

  if (loading) {
    return <main className={styles.page}><div className={styles.loading}><LoaderCircle size={17} /> Cargando huella revisada…</div></main>;
  }

  return (
    <main className={styles.page}>
      <Link href={`/investigation/${investigationId}/review`} className={styles.backLink}>
        <ArrowLeft size={14} /> Verification Gate
      </Link>

      <header className={styles.hero}>
        <div className={styles.eyebrow}><span /> FAIR MODE <i>·</i> EXPOSURE LENS</div>
        <h1>La huella que dejan las cuentas públicas</h1>
        <p>Una reconstrucción objetiva de cuentas atribuidas y publicaciones priorizadas por sus señales de exposición. Cada lectura conserva el enlace con la fuente.</p>
        <div className={styles.heroMeta}>
          <span><ShieldCheck size={13} /> Solo huella revisada</span>
          {report?.dataset_hash && <code>DATASET · {report.dataset_hash.slice(0, 12)}</code>}
          <span className={styles.scopeNote}><Fingerprint size={13} /> Sin inferir personalidad ni ownership desde un alias</span>
        </div>
      </header>

      {error && (
        <div className={styles.notice} role="alert">
          <ShieldCheck size={16} />
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
          <div><strong>La huella cambió desde este análisis.</strong><p>Vuelve a analizar la versión revisada actual para reconstruirla.</p></div>
          <button type="button" disabled={analyzing} onClick={() => void runAnalysis()}><RefreshCw size={13} /> Reanalizar</button>
        </div>
      )}

      {!reviewRequired && (
        <>
          <section className={styles.controlRow} aria-label="Estado del análisis">
            <div>
              <span className={styles.sectionKicker}>ANÁLISIS DE EXPOSICIÓN</span>
              <strong>{report?.status === "pending" ? "La huella está lista para analizar" :
                report?.status === "running" ? "El análisis está en curso" :
                  report?.status === "partial" ? "Lectura con cobertura parcial" :
                    report?.status === "failed" ? "El análisis falló" : "Lectura lista"}</strong>
              <span className={styles.controlNote}>
                {report?.generated_at ? "Generada " + formatDate(report.generated_at) : "La lectura conserva solo señales observables."}
              </span>
            </div>
            <button type="button" className={styles.analyzeButton} disabled={!canAnalyze || analyzing || (report?.status === "pending" && !report.current_dataset_hash)}
              onClick={() => void runAnalysis()}>
              {analyzing || report?.status === "running"
                ? <><LoaderCircle size={15} className={styles.spin} /> Analizando…</>
                : <><Sparkles size={15} /> {report?.status === "pending" || report?.stale ? "Analizar huella" : "Volver a analizar"}</>}
            </button>
          </section>

          {current && report && <p className={styles.analysisNote} role="status">
            {analyzedPosts} publicaciones analizadas · {prioritizedPosts.length} priorizadas por señales · {identitySources} {identitySources === 1 ? "cuenta con hallazgos" : "cuentas con hallazgos"}.
            {aiProcessing?.enabled ? ` Clasificación IA: ${aiProcessing.processed || 0} elementos procesados y ${aiProcessing.cached || 0} desde caché.` : " Clasificación local basada en reglas."}
            {analyzedPosts === 0 && " No se recuperaron publicaciones en esta cobertura; esto no describe actividad fuera de las fuentes observadas."}
          </p>}

          {current && report && ["completed", "partial"].includes(report.status) && (
            <Link href={`/investigation/${investigationId}/reconstruction`} className={styles.graphLink}>
              Abrir grafo completo de relaciones <ArrowUpRight size={14} />
            </Link>
          )}

          {report?.status === "pending" && (
            <section className={styles.emptyState}>
              <span className={styles.emptyGlyph}><Globe2 size={20} /></span>
              <h2>La fuente está delimitada.</h2>
              <p>Analiza perfiles, publicaciones y documentos presentes en la huella que finalizaste. Solo mostraremos las publicaciones con señales relevantes.</p>
              <button type="button" className={styles.analyzeButton} disabled={analyzing || !report.current_dataset_hash} onClick={() => void runAnalysis()}>
                {analyzing ? <><LoaderCircle size={15} className={styles.spin} /> Analizando…</> : <><Sparkles size={15} /> Analizar huella</>}
              </button>
            </section>
          )}

          {report?.status === "partial" && (
            <div className={styles.partialNotice} role="status">
              {report.partial_reasons.length
                ? report.partial_reasons.map((reason) => PARTIAL_REASON[reason]).join(" ")
                : "La lectura quedó guardada con cobertura parcial."}
            </div>
          )}

          {report?.status === "failed" && (
            <div className={styles.partialNotice} role="alert">No se pudo guardar el análisis. Revisa la conexión y vuelve a intentarlo.</div>
          )}

          {current && report && report.status !== "pending" && report.status !== "running" && report.status !== "failed" && (
            <>
              <section className={styles.reconstruction} aria-labelledby="reconstruction-title">
                <div className={styles.reconstructionHeading}>
                  <span className={styles.sectionKicker}>RECONSTRUCCIÓN CON EVIDENCIA</span>
                  <h2 id="reconstruction-title">Cuentas, publicaciones y señales observadas</h2>
                  <p className={styles.leadNarrative}>{reconstructionSummary}</p>
                  <p>La huella visible se reconstruye desde cuentas declaradas o confirmadas. Los fragmentos minimizan datos sensibles y enlazan con la fuente original.</p>
                </div>

                {relationshipFindings.length > 0 && (
                  <section className={styles.relationships} aria-labelledby="relationships-title">
                    <div className={styles.subheading}>
                      <span className={styles.sectionKicker}>RELACIONES EXPLÍCITAS</span>
                      <h3 id="relationships-title">Qué conecta estas cuentas</h3>
                    </div>
                    <ol>
                      {relationshipFindings.map((finding) => (
                        <li key={finding.id}>
                          <span className={`${styles.severity} ${styles[`severity_${finding.severity}`]}`}>{SEVERITY_LABEL[finding.severity]}</span>
                          <div>
                            <strong>{finding.title}</strong>
                            <p>{finding.summary} {finding.why_it_matters}</p>
                            {finding.evidence.length > 0 && (
                              <details className={styles.sourceDetails}>
                                <summary>Fuentes observadas <span>{finding.evidence.length}</span></summary>
                                <ul>{finding.evidence.slice(0, 5).map((item, index) => (
                                  <li key={`${item.source_id ?? "source"}-${index}`}>
                                    <span>{[item.platform, item.account && "@" + item.account.replace(/^@/, "")].filter(Boolean).join(" · ") || item.source_type}</span>
                                    {item.url && <a href={item.url} target="_blank" rel="noreferrer">Abrir fuente <ArrowUpRight size={12} /></a>}
                                    {item.excerpt && <p>{item.excerpt}</p>}
                                  </li>
                                ))}</ul>
                              </details>
                            )}
                          </div>
                        </li>
                      ))}
                    </ol>
                  </section>
                )}

                <section className={styles.evidenceGraph} aria-labelledby="posts-title">
                  <div className={styles.subheading}>
                    <span className={styles.sectionKicker}>PUBLICACIONES PRIORIZADAS</span>
                    <h3 id="posts-title">De la cuenta a la evidencia</h3>
                  </div>
                  {accountThreads.length > 0 ? (
                    <div className={styles.accountThreads}>
                      {accountThreads.map((thread) => <AccountThreadView key={thread.key} thread={thread} findings={findings} />)}
                    </div>
                  ) : (
                    <p className={styles.noPosts}>No hay publicaciones con señales priorizadas en las cuentas atribuidas y fuentes revisadas. El resultado describe esta cobertura, no toda la actividad pública.</p>
                  )}
                </section>
              </section>

              {secondaryFindings.length > 0 && (
                <details className={styles.allFindings}>
                  <summary><span>Ver todos los hallazgos</span><small>{secondaryFindings.length} señales · evidencia y acciones defensivas</small></summary>
                  <div className={styles.findingList}>
                    {secondaryFindings.map((finding) => <FindingLine key={finding.id} finding={finding} />)}
                  </div>
                </details>
              )}
            </>
          )}
        </>
      )}
    </main>
  );
}
