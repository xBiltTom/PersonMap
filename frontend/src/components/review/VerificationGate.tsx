"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  ArrowLeft,
  ArrowRight,
  BadgeCheck,
  Check,
  CircleHelp,
  Clock3,
  Download,
  ExternalLink,
  FileQuestion,
  Fingerprint,
  ListChecks,
  RefreshCw,
  ShieldCheck,
  X,
} from "lucide-react";
import { AvatarThumb } from "@/components/identity/AvatarThumb";
import {
  decideReviewCandidate,
  finalizeInvestigationReview,
  getInvestigationReview,
  getReviewedFootprint,
} from "@/lib/api";
import type {
  DeclaredSeed,
  FairReviewSourceState,
  InvestigationReviewData,
  ReviewCandidate,
  ReviewDecisionValue,
} from "@/lib/types";
import { applyReviewDecision, canFinalizeReview } from "@/lib/reviewState";
import styles from "./VerificationGate.module.css";

const DECISION_OPTIONS: Array<{
  value: ReviewDecisionValue;
  label: string;
  icon: typeof Check;
}> = [
  { value: "confirmed", label: "Me pertenece", icon: Check },
  { value: "rejected", label: "No me pertenece", icon: X },
  { value: "uncertain", label: "No estoy seguro", icon: CircleHelp },
];

const DECISION_LABEL: Record<ReviewDecisionValue, string> = {
  confirmed: "Confirmados",
  rejected: "Descartados",
  uncertain: "En duda",
};

const SOURCE_LABELS: Record<string, string> = {
  ghunt: "Perfiles y actividad pública de Google",
  dni_lookup: "Búsqueda por documento de identidad",
  apify_social: "Perfiles públicos de redes sociales",
  phone_lookup: "Búsqueda por teléfono",
  domain_finder: "Sitios web y dominios asociados",
  email_checker: "Servicios asociados al correo",
  gravatar_deep: "Imagen pública asociada al correo",
  search_dorker: "Buscador web",
  breach_checker: "Avisos de filtraciones de datos",
  academic_finder: "Autores y publicaciones académicas",
  social_verifier: "Comprobación de perfiles públicos",
  username_finder: "Búsqueda de alias en plataformas",
  wikipedia_edits: "Actividad pública en Wikipedia",
  email_enumerator: "Cuentas asociadas al correo",
  keybase_resolver: "Perfiles de Keybase",
  maigret_enricher: "Búsqueda ampliada de alias",
  github_deep_scanner: "Actividad pública en GitHub",
  infostealer_checker: "Credenciales en registros de malware",
  google_account_osint: "Perfiles públicos de Google y YouTube",
  reverse_image_search: "Coincidencias de imágenes",
  social_url_extractor: "Enlaces públicos a perfiles",
};

const EVIDENCE_SOURCE_LABELS: Record<string, string> = {
  "Apify Social": "Perfiles de redes sociales",
  "Social Verifier": "Comprobación de perfiles",
  SearchDorker: "Búsqueda web",
  "Username Finder": "Búsqueda de alias",
  Maigret: "Búsqueda ampliada de alias",
  GHunt: "Perfiles públicos de Google",
  "Google OSINT": "Perfiles públicos de Google",
  "OpenAlex / Crossref": "Autores y publicaciones académicas",
  "Email Checker": "Comprobación de correo",
  "Email Enumerator": "Cuentas asociadas al correo",
  "Phone Lookup": "Búsqueda por teléfono",
  "GitHub Scanner": "Actividad pública en GitHub",
  "URL pública": "Enlace público a un perfil",
};

const SOURCE_REASON_LABELS: Record<string, string> = {
  outside_fair_seed_scope: "La búsqueda por documento queda fuera del alcance de esta revisión.",
  secondary_source_outside_fast_preset: "Se omite en esta búsqueda rápida.",
  deep_enrichment_outside_fast_preset: "La búsqueda ampliada de alias no se ejecuta en esta revisión.",
  optional_separate_consent_not_default_fair: "Esta consulta requiere autorización específica y no se ejecuta por defecto.",
  subject_consent_required: "Hace falta autorización específica antes de consultar estos registros.",
  not_in_fair_allowlist: "Esta red queda fuera de las plataformas consultadas en esta búsqueda.",
  not_requested: "No se solicitó una consulta específica para esta plataforma.",
  no_pending_compatible_input: "No había un dato de entrada compatible para esta búsqueda.",
  deadline_or_no_applicable_work: "No se ejecutó antes de terminar la búsqueda o no había datos para usarla.",
  optional_time_budget: "El tiempo se reservó para las búsquedas principales.",
  provider_unavailable: "El servicio externo no respondió o no estaba disponible.",
  actor_access_denied: "El servicio externo no permitió completar la consulta.",
  tool_not_registered: "Esta búsqueda no está disponible en la instalación actual.",
  token_missing: "El servicio externo no está configurado.",
  session_missing: "No había una sesión disponible para consultar este servicio.",
  session_not_configured: "Este servicio no está configurado.",
  budget_exhausted: "Se alcanzó el límite de consultas de esta fuente.",
  source_invocation_budget: "Se alcanzó el límite de consultas de esta fuente.",
  wave_or_time_budget: "La búsqueda llegó a su límite de tiempo o consultas.",
  cancellation_grace_exhausted: "La fuente no terminó dentro del tiempo disponible.",
  observed: "Se encontró actividad pública para revisar.",
  run_budget_exhausted: "Se alcanzó el límite de consultas de esta fuente.",
  timeout: "La fuente no respondió dentro del tiempo disponible.",
  failed: "La consulta no pudo completarse.",
  provider_input_budget: "Se alcanzó el límite de datos revisados para esta fuente.",
  request_budget_exhausted: "Se alcanzó el límite de consultas de esta fuente.",
  profile_budget_exhausted: "Se alcanzó el límite de perfiles para esta fuente.",
  actor_budget_exhausted: "Se alcanzó el límite de consultas de esta fuente.",
  time_budget_exhausted: "Se terminó el tiempo asignado a esta fuente.",
  quota_exhausted: "El servicio externo alcanzó su límite de consultas.",
  rate_limited: "El servicio externo limitó temporalmente las consultas.",
  runtime_missing: "El servicio externo no está disponible en este entorno.",
  dependency_missing: "Falta un componente necesario para esta consulta.",
  authentication_failed: "El servicio externo no permitió completar la consulta.",
};

function prettyPlatform(value?: string | null) {
  if (!value) return "Perfil público";
  const labels: Record<string, string> = {
    github: "GitHub",
    gitlab: "GitLab",
    bitbucket: "Bitbucket",
    instagram: "Instagram",
    tiktok: "TikTok",
    youtube: "YouTube",
    threads: "Threads",
    twitter: "X / Twitter",
    x: "X",
    reddit: "Reddit",
    facebook: "Facebook",
    linkedin: "LinkedIn",
    telegram: "Telegram",
    bluesky: "Bluesky",
    twitch: "Twitch",
    snapchat: "Snapchat",
    pinterest: "Pinterest",
    tumblr: "Tumblr",
    medium: "Medium",
    quora: "Quora",
    stackoverflow: "Stack Overflow",
    stack_overflow: "Stack Overflow",
    codepen: "CodePen",
    replit: "Replit",
    kaggle: "Kaggle",
    huggingface: "Hugging Face",
    hackernews: "Hacker News",
    behance: "Behance",
    dribbble: "Dribbble",
    artstation: "ArtStation",
    soundcloud: "SoundCloud",
    spotify: "Spotify",
    bandcamp: "Bandcamp",
    steam: "Steam",
    roblox: "Roblox",
    chess: "Chess.com",
    academia_edu: "Academia.edu",
    slideshare: "SlideShare",
    about_me: "About.me",
    beacons: "Beacons",
    carrd: "Carrd",
    openalex_author: "OpenAlex",
    google_scholar: "Google Scholar",
    google: "Google",
    telephony: "Teléfono",
  };
  return labels[value.toLowerCase()] ?? value.replaceAll("_", " ");
}

function seedLabel(seed: DeclaredSeed) {
  if (seed.kind === "username") return `${seed.platform ? `${prettyPlatform(seed.platform)} ` : "Alias "}@${seed.value}`;
  if (seed.kind === "email") return `Correo · ${seed.value}`;
  if (seed.kind === "phone") return `Teléfono · ${seed.value}`;
  return `Nombre · ${seed.value}`;
}

function sourceStateLabel(state: FairReviewSourceState) {
  const labels: Record<string, string> = {
    completed: state.reason === "observed" ? "Perfil encontrado" : state.findings_count > 0 ? "Consultada" : "Sin resultados",
    partial: "Parcial",
    timeout: "Sin respuesta",
    provider_unavailable: "No disponible",
    failed: "Error de consulta",
    budget_exhausted: "Límite alcanzado",
    skipped: "No ejecutada",
    not_applicable: "No aplicaba",
    pending: "Pendiente",
    running: "En curso",
  };
  return labels[state.status] ?? "Estado no disponible";
}

function sourceStatusClass(state: FairReviewSourceState) {
  if (state.status !== "completed") return styles.sourceIncomplete;
  return state.findings_count > 0 || state.reason === "observed" ? styles.sourceComplete : styles.sourceEmpty;
}

function sourceLabel(name: string) {
  return SOURCE_LABELS[name] ?? prettyPlatform(name);
}

function evidenceSourceLabel(name: string) {
  return EVIDENCE_SOURCE_LABELS[name] ?? sourceLabel(name);
}

function sourceExplanation(state: FairReviewSourceState) {
  if (state.reason && SOURCE_REASON_LABELS[state.reason]) return SOURCE_REASON_LABELS[state.reason];
  if (state.status === "completed") {
    return state.findings_count > 0
      ? `${state.findings_count} ${state.findings_count === 1 ? "resultado encontrado" : "resultados encontrados"}. Revisa cada uno por separado.`
      : "La consulta terminó sin coincidencias; esto no descarta que haya otros datos públicos.";
  }
  if (state.status === "partial") return "La consulta devolvió información incompleta.";
  if (state.status === "timeout") return "La fuente no respondió dentro del tiempo disponible.";
  if (state.status === "provider_unavailable") return "El servicio externo no respondió o no estaba disponible.";
  if (state.status === "failed") return "La consulta no pudo completarse.";
  if (state.status === "budget_exhausted") return "Se alcanzó el límite de tiempo o consultas.";
  if (state.status === "not_applicable") return "No había datos de entrada compatibles con esta búsqueda.";
  if (state.status === "skipped") return "Esta consulta no se ejecutó en esta búsqueda.";
  if (state.status === "running") return "La consulta sigue en curso.";
  return "La consulta está pendiente.";
}

function candidateReason(candidate: ReviewCandidate) {
  if (candidate.category === "academic_profile") {
    return candidate.reason.includes("afiliación")
      ? "El nombre y la institución coinciden con un perfil académico. Revisa si reconoces el perfil y sus publicaciones."
      : "Se encontró un perfil académico con un nombre relacionado. Confirma que el perfil o sus publicaciones te pertenezcan.";
  }
  if (candidate.category === "email") return "Este correo apareció en una fuente pública, pero aún no está confirmado que te pertenezca.";
  if (candidate.category === "phone") return "Este teléfono apareció en una fuente pública, pero aún no está confirmado que te pertenezca.";
  if (candidate.reason.includes("registro asociado a un correo")) {
    return "Se encontró un servicio asociado a este correo. La cuenta puede pertenecer a otra persona.";
  }
  if (candidate.reason.includes("SearchDorker")) {
    return "La búsqueda web encontró una coincidencia exacta para este perfil. Aun así, puede pertenecer a otra persona.";
  }
  if (candidate.reason.startsWith("Encontrado al buscar el alias declarado")) {
    return "El perfil apareció al buscar un alias que declaraste. Confirma cada plataforma por separado.";
  }
  if (candidate.reason.startsWith("Perfil público detectado automáticamente")) {
    return "Se encontró un perfil público en esta plataforma. La búsqueda no confirma quién lo usa.";
  }
  if (candidate.reason.startsWith("Identidad pública relacionada por")) {
    return "Este resultado apareció en una fuente pública relacionada. Confirma que reconoces el dato.";
  }
  return candidate.reason;
}

function candidateKindLabel(candidate: ReviewCandidate) {
  if (candidate.category === "email") return "Dirección de correo";
  if (candidate.category === "phone") return "Número de teléfono";
  if (candidate.category === "academic_profile") return "Perfil académico";
  return "Perfil de plataforma";
}

function CandidateCard({
  candidate,
  busy,
  onDecision,
}: {
  candidate: ReviewCandidate;
  busy: boolean;
  onDecision: (candidate: ReviewCandidate, decision: ReviewDecisionValue) => void;
}) {
  const title = candidate.display_name || candidate.username || candidate.value;
  const initials = title.slice(0, 1).toLocaleUpperCase();
  return (
    <article className={styles.candidate} data-candidate-id={candidate.id}>
      <div className={styles.cardTopline}>
        <span className={styles.observationTag}>
          <span className={styles.observationDot} />
          {candidateKindLabel(candidate)}
        </span>
        <span className={styles.platform}>{prettyPlatform(candidate.platform)}</span>
      </div>

      <div className={styles.identityRow}>
        {candidate.avatar_url ? (
          <AvatarThumb url={candidate.avatar_url} source={prettyPlatform(candidate.platform)} size="lg" />
        ) : (
          <span className={styles.avatarFallback} aria-hidden="true">{initials}</span>
        )}
        <div className={styles.identityText}>
          <h3>{title}</h3>
          {candidate.username && <p className={styles.username}>@{candidate.username}</p>}
          {candidate.entity_type !== "social_account" && <p className={styles.rawValue}>{candidate.value}</p>}
        </div>
        {candidate.public_url && (
          <a className={styles.profileLink} href={candidate.public_url} target="_blank" rel="noreferrer">
            <span>Ver perfil</span><ExternalLink size={13} aria-hidden="true" />
          </a>
        )}
      </div>

      {candidate.bio && <p className={styles.bio}>{candidate.bio}</p>}
      {candidate.institutions.length > 0 && (
        <p className={styles.affiliations}>{candidate.institutions.join(" · ")}</p>
      )}

      <div className={styles.reason}>
        <Fingerprint size={14} aria-hidden="true" />
        <div><strong>Por qué aparece</strong><p>{candidateReason(candidate)}</p></div>
      </div>

      <details className={styles.evidenceDetails}>
        <summary>Ver fuentes y enlaces <span>{candidate.sources.length} {candidate.sources.length === 1 ? "fuente" : "fuentes"}</span></summary>
        <div className={styles.evidenceBody}>
          {candidate.sources.map((source) => (
            <div className={styles.sourceBlock} key={source.name}>
              <strong>{evidenceSourceLabel(source.name)}</strong>
              {source.evidence_urls.length > 0 ? (
                <ul>
                  {source.evidence_urls.map((url) => (
                    <li key={url}><a href={url} target="_blank" rel="noreferrer">{url}</a></li>
                  ))}
                </ul>
              ) : <span>Observación registrada en esta investigación.</span>}
            </div>
          ))}
          {candidate.sources.length === 0 && <p>No hay una fuente detallada asociada a este resultado.</p>}
        </div>
      </details>

      <p className={styles.decisionPrompt}>¿Reconoces este dato? Elige una opción.</p>
      <div className={styles.actions} aria-label={`Revisar ${title}`}>
        {DECISION_OPTIONS.map(({ value, label, icon: Icon }) => {
          const selected = candidate.decision === value;
          return (
            <button
              key={value}
              type="button"
              aria-pressed={selected}
              disabled={busy}
              onClick={() => onDecision(candidate, value)}
              className={`${styles.decisionButton} ${styles[`decision_${value}`]} ${selected ? styles.selected : ""}`}
            >
              <Icon size={14} aria-hidden="true" />
              <span>{label}</span>
              {selected && <span className={styles.savedMark}>Guardado</span>}
            </button>
          );
        })}
      </div>
    </article>
  );
}

function CandidateSection({
  title,
  candidates,
  busyId,
  onDecision,
  open = false,
}: {
  title: string;
  candidates: ReviewCandidate[];
  busyId: string | null;
  onDecision: (candidate: ReviewCandidate, decision: ReviewDecisionValue) => void;
  open?: boolean;
}) {
  if (candidates.length === 0) return null;
  return (
    <details className={styles.reviewSection} open={open}>
      <summary>
        <span>{title}</span><span className={styles.sectionCount}>{candidates.length}</span>
      </summary>
      <div className={styles.cardList}>
        {candidates.map((candidate) => (
          <CandidateCard key={candidate.id} candidate={candidate} busy={busyId !== null}
            onDecision={onDecision} />
        ))}
      </div>
    </details>
  );
}

function DeclaredSeeds({ seeds }: { seeds: DeclaredSeed[] }) {
  if (seeds.length === 0) return null;
  return (
    <section className={styles.declaredPanel} aria-labelledby="declared-title">
      <div className={styles.declaredHeading}>
        <span className={styles.declaredGlyph}><BadgeCheck size={16} aria-hidden="true" /></span>
        <div>
          <h2 id="declared-title">Datos que ingresaste</h2>
          <p>Se incluirán directamente en la huella</p>
        </div>
      </div>
      <ul className={styles.seedList}>
        {seeds.map((seed, index) => <li key={`${seed.kind}:${seed.platform ?? ""}:${seed.value}:${index}`}>{seedLabel(seed)}</li>)}
      </ul>
      <p className={styles.readOnlyNote}>No necesitas confirmarlos otra vez.</p>
    </section>
  );
}

function SourceHealth({ review }: { review: InvestigationReviewData }) {
  const sources = useMemo(() => [
    ...Object.entries(review.fair.sources).map(([name, state]) => ({ name, state })),
    ...Object.entries(review.fair.social_sources).map(([name, state]) => ({ name: prettyPlatform(name), state })),
  ], [review.fair.sources, review.fair.social_sources]);

  const completed = sources.filter(({ state }) => state.status === "completed").length;
  const partial = sources.filter(({ state }) => ["partial", "timeout", "provider_unavailable", "failed", "budget_exhausted"].includes(state.status)).length;
  const notRun = sources.filter(({ state }) => ["skipped", "not_applicable"].includes(state.status)).length;
  const inProgress = sources.filter(({ state }) => ["pending", "running"].includes(state.status)).length;

  return (
    <details className={styles.sourceHealth}>
      <summary>
        <span className={styles.sourceSummaryCopy}>
          <strong>Cobertura de búsqueda</strong>
          <small>{completed} consultadas · {partial} parciales · {notRun} no ejecutadas{inProgress > 0 ? ` · ${inProgress} en curso` : ""}</small>
        </span>
      </summary>
      <div className={styles.sourceDetails}>
        <p className={styles.sourceIntro}>Cada fuente se consulta por separado. Una coincidencia no prueba que el dato sea tuyo; una búsqueda sin resultados tampoco demuestra que no exista.</p>
        <div className={styles.sourceCounts} aria-label="Resumen de fuentes">
          <span><strong>{completed}</strong> consultadas</span>
          <span><strong>{partial}</strong> parciales</span>
          <span><strong>{notRun}</strong> no ejecutadas</span>
          {inProgress > 0 && <span><strong>{inProgress}</strong> en curso</span>}
        </div>
        <ul>
          {sources.map(({ name, state }) => (
            <li key={`${name}:${state.status}`}>
              <div className={styles.sourceCopy}>
                <strong>{sourceLabel(name)}</strong>
                <small>{sourceExplanation(state)}</small>
              </div>
              <span
                className={`${styles.sourceStatus} ${sourceStatusClass(state)}`}
                data-status={state.status}
              >
                {sourceStateLabel(state)}
                {state.findings_count > 0 && ` · ${state.findings_count} ${state.findings_count === 1 ? "resultado" : "resultados"}`}
              </span>
            </li>
          ))}
        </ul>
      </div>
    </details>
  );
}

export function VerificationGate({ investigationId }: { investigationId: string }) {
  const [review, setReview] = useState<InvestigationReviewData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [finalizing, setFinalizing] = useState(false);
  const [downloaded, setDownloaded] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const reviewRequest = useRef<Promise<void> | null>(null);

  const loadReview = useCallback(() => {
    if (reviewRequest.current) return reviewRequest.current;

    const request = (async () => {
      try {
        const result = await getInvestigationReview(investigationId);
        setReview(result);
        setError(null);
      } catch (loadError) {
        setError(loadError instanceof Error ? loadError.message : "No se pudo cargar la revisión.");
      } finally {
        setLoading(false);
        reviewRequest.current = null;
      }
    })();
    reviewRequest.current = request;
    return request;
  }, [investigationId]);

  useEffect(() => {
    const timer = window.setTimeout(() => { void loadReview(); }, 0);
    return () => window.clearTimeout(timer);
  }, [loadReview]);

  useEffect(() => {
    if (!review || review.review_status === "complete" || busyId !== null || finalizing) return;
    const timer = window.setInterval(() => {
      if (document.visibilityState === "visible") void loadReview();
    }, 15_000);
    return () => window.clearInterval(timer);
  }, [busyId, finalizing, loadReview, review?.review_status]);

  const handleRefresh = useCallback(async () => {
    setRefreshing(true);
    try {
      await loadReview();
    } finally {
      setRefreshing(false);
    }
  }, [loadReview]);

  const handleDecision = useCallback(async (candidate: ReviewCandidate, decision: ReviewDecisionValue) => {
    setBusyId(candidate.id);
    setError(null);
    try {
      setReview((current) => current ? applyReviewDecision(current, candidate.id, decision) : current);
      const result = await decideReviewCandidate(investigationId, candidate.id, decision);
      setReview(result);
    } catch (saveError) {
      setError(saveError instanceof Error ? saveError.message : "No se guardó la decisión.");
      void loadReview();
    } finally {
      setBusyId(null);
    }
  }, [investigationId, loadReview]);

  const handleFinalize = useCallback(async () => {
    setFinalizing(true);
    setError(null);
    try {
      await finalizeInvestigationReview(investigationId);
      await loadReview();
    } catch (finalizeError) {
      setError(finalizeError instanceof Error ? finalizeError.message : "No se pudo finalizar la revisión.");
    } finally {
      setFinalizing(false);
    }
  }, [investigationId, loadReview]);

  const handleDownload = useCallback(async () => {
    try {
      const dataset = await getReviewedFootprint(investigationId);
      const blob = new Blob([JSON.stringify(dataset, null, 2)], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = `person-map-reviewed-footprint-${investigationId}.json`;
      anchor.click();
      URL.revokeObjectURL(url);
      setDownloaded(true);
      window.setTimeout(() => setDownloaded(false), 2200);
    } catch (downloadError) {
      setError(downloadError instanceof Error ? downloadError.message : "No se pudo descargar la huella revisada.");
    }
  }, [investigationId]);

  const groups = useMemo(() => {
    const candidates = review?.candidates ?? [];
    return {
      pending: candidates.filter((candidate) => !candidate.decision),
      confirmed: candidates.filter((candidate) => candidate.decision === "confirmed"),
      rejected: candidates.filter((candidate) => candidate.decision === "rejected"),
      uncertain: candidates.filter((candidate) => candidate.decision === "uncertain"),
    };
  }, [review?.candidates]);

  if (loading) {
    return <div className={styles.loading}><span className={styles.loader} /><p>Cargando resultados para revisar…</p></div>;
  }
  if (!review) {
    return (
      <main className={styles.page}>
        <div className={styles.errorPanel} role="alert">
          <FileQuestion size={22} aria-hidden="true" />
          <h1>No se pudo cargar esta revisión</h1>
          <p>{error || "No hay información de revisión disponible para esta investigación."}</p>
          <Link href={`/investigation/${investigationId}`} className={styles.backLink}><ArrowLeft size={15} /> Volver al expediente</Link>
        </div>
      </main>
    );
  }

  const isComplete = review.review_status === "complete";
  const reviewedCount = review.counts.confirmed + review.counts.rejected + review.counts.uncertain;
  const totalCandidates = review.candidates.length;
  const reviewProgress = totalCandidates > 0 ? Math.round((reviewedCount / totalCandidates) * 100) : isComplete ? 100 : 0;

  return (
    <main className={styles.page}>
      <Link href={`/investigation/${investigationId}`} className={styles.backLink}>
        <ArrowLeft size={15} aria-hidden="true" /> Volver al expediente
      </Link>

      <nav className={styles.workflow} aria-label="Pasos de revisión y reconstrucción">
        <div className={styles.workflowStep} data-complete={isComplete ? "true" : "false"} aria-current={isComplete ? undefined : "step"}>
          <span className={styles.workflowNumber}>{isComplete ? <BadgeCheck size={16} aria-hidden="true" /> : "01"}</span>
          <span><strong>Revisar resultados</strong><small>{isComplete ? "Revisión guardada" : "Confirma qué datos son tuyos"}</small></span>
        </div>
        <span className={styles.workflowConnector} aria-hidden="true" />
        {isComplete ? (
          <Link href={`/investigation/${investigationId}/reconstruction`} className={styles.workflowStep} data-current="true" aria-current="step">
            <span className={styles.workflowNumber}>02</span>
            <span><strong>Reconstruir huella</strong><small>Ver datos confirmados</small></span>
            <ArrowRight size={16} aria-hidden="true" />
          </Link>
        ) : (
          <div className={styles.workflowStep} data-locked="true" aria-disabled="true">
            <span className={styles.workflowNumber}>02</span>
            <span><strong>Reconstruir huella</strong><small>Disponible al finalizar</small></span>
          </div>
        )}
      </nav>

      <header className={styles.hero}>
        <div className={styles.heroCopy}>
          <div className={styles.eyebrow}><span /> REVISIÓN DE IDENTIDAD <i>·</i> PASO 1</div>
          <h1>¿Qué resultados te pertenecen?</h1>
          <p>Revisa cada perfil o dato encontrado. Solo los que confirmes se incluirán en la reconstrucción de tu huella digital.</p>
        </div>
      </header>

      {error && <div className={styles.errorBanner} role="alert">{error}</div>}

      {review.fair.partial && (
        <div className={styles.partialNotice} role="status">
          <Clock3 size={17} aria-hidden="true" />
          <div><strong>Algunas búsquedas quedaron incompletas</strong><p>Algunas fuentes no respondieron o no tenían datos compatibles. Puedes revisar los resultados disponibles; esto no confirma ni descarta otros perfiles.</p></div>
        </div>
      )}

      <div className={styles.countRail} aria-label="Resumen de revisión">
        <div className={styles.progressHeading}>
          <div>
            <strong>{totalCandidates === 0 ? "Sin resultados nuevos" : `${reviewedCount} de ${totalCandidates}`}</strong>
            <span>{totalCandidates === 0 ? "por ahora" : totalCandidates === 1 ? "resultado revisado" : "resultados revisados"}</span>
          </div>
          <span className={`${styles.statusPill} ${isComplete ? styles.statusComplete : ""}`}>
            {isComplete ? <><BadgeCheck size={13} /> Guardado</> : <><Clock3 size={13} /> {review.fair.acquisition_finished ? "Revisión en curso" : "Búsqueda en curso"}</>}
          </span>
        </div>
        <div className={styles.progressTrack} role="progressbar" aria-label="Progreso de revisión" aria-valuenow={totalCandidates === 0 && isComplete ? 1 : reviewedCount} aria-valuemin={0} aria-valuemax={Math.max(1, totalCandidates)}>
          <span style={{ width: `${reviewProgress}%` }} />
        </div>
        <div className={styles.decisionCounts}>
          <div><strong>{review.counts.pending}</strong><span>Por revisar</span></div>
          <div><strong>{review.counts.confirmed}</strong><span>Me pertenecen</span></div>
          <div><strong>{review.counts.rejected}</strong><span>Descartados</span></div>
          <div><strong>{review.counts.uncertain}</strong><span>En duda</span></div>
        </div>
      </div>

      <div className={styles.layout}>
        <aside className={styles.sidebar}>
          <DeclaredSeeds seeds={review.declared_seeds} />
          <SourceHealth review={review} />
          <div className={styles.ruleNote}>
            <ListChecks size={16} aria-hidden="true" />
            <p>Un mismo alias puede pertenecer a distintas personas. Confirma cada perfil que reconozcas; los que marques en duda no se incluirán.</p>
          </div>
        </aside>

        <section className={styles.reviewColumn} aria-labelledby="discoveries-title">
          <div className={styles.sectionIntro}>
            <div><span className={styles.sectionKicker}>RESULTADOS DE LA BÚSQUEDA</span><h2 id="discoveries-title">Revisa cada coincidencia</h2></div>
            <div className={styles.sectionTools}>
              {review.counts.pending > 0 && <span className={styles.pendingLabel}>{review.counts.pending} por revisar</span>}
              <button type="button" className={styles.refreshButton} onClick={() => void handleRefresh()}
                disabled={refreshing || busyId !== null || finalizing} aria-label="Actualizar resultados de revisión">
                <RefreshCw size={13} className={refreshing ? styles.spinning : ""} aria-hidden="true" />
                {refreshing ? "Actualizando…" : "Actualizar"}
              </button>
            </div>
          </div>
          <p className={styles.sectionHelp}>Las decisiones se guardan automáticamente. Puedes cambiar una respuesta mientras la revisión siga abierta.</p>

          {groups.pending.length > 0 ? (
            <div className={styles.pendingList}>
              {groups.pending.map((candidate) => <CandidateCard key={candidate.id} candidate={candidate}
                busy={busyId !== null || finalizing} onDecision={handleDecision} />)}
            </div>
          ) : (
            <div className={styles.emptyState}>
              <span><BadgeCheck size={21} aria-hidden="true" /></span>
              <h3>{review.candidates.length ? "Ya revisaste todos los resultados" : "No hay resultados nuevos para revisar por ahora"}</h3>
              <p>{review.candidates.length ? "Puedes cambiar una decisión antes de continuar." : "Los datos que ingresaste al crear la investigación se conservarán en la huella."}</p>
            </div>
          )}

          <div className={styles.decidedGroups}>
            <CandidateSection title={DECISION_LABEL.confirmed} candidates={groups.confirmed}
              busyId={busyId || (finalizing ? "__finalizing__" : null)} onDecision={handleDecision} />
            <CandidateSection title={DECISION_LABEL.rejected} candidates={groups.rejected}
              busyId={busyId || (finalizing ? "__finalizing__" : null)} onDecision={handleDecision} />
            <CandidateSection title={DECISION_LABEL.uncertain} candidates={groups.uncertain}
              busyId={busyId || (finalizing ? "__finalizing__" : null)} onDecision={handleDecision} />
          </div>

          <footer className={styles.finalizePanel}>
            <div className={styles.finalizeCopy}>
              <span className={styles.finalizeIcon}><ShieldCheck size={17} aria-hidden="true" /></span>
              <div><h3>{isComplete ? "Revisión guardada" : "Finaliza para reconstruir la huella"}</h3>
                <p>{isComplete
                  ? "La siguiente vista mostrará los datos declarados y los resultados que confirmaste."
                  : "Los resultados pendientes o en duda quedarán fuera de la reconstrucción."}</p></div>
            </div>
            <div className={styles.finalizeActions}>
              {isComplete && <Link href={`/investigation/${investigationId}/reconstruction`} className={styles.finalizeButton}>
                Reconstruir huella <ArrowRight size={14} aria-hidden="true" />
              </Link>}
              {isComplete && <button type="button" className={styles.downloadButton} onClick={() => void handleDownload()}>
                <Download size={14} aria-hidden="true" /> {downloaded ? "Descargado" : "Descargar datos revisados"}
              </button>}
              {!isComplete && <button type="button" className={styles.finalizeButton}
                disabled={!canFinalizeReview(review.fair.acquisition_finished, review.counts.pending) || finalizing || busyId !== null}
                onClick={() => void handleFinalize()}>
                <ShieldCheck size={15} aria-hidden="true" />
                {finalizing ? "Guardando…" : "Finalizar revisión"}
              </button>}
            </div>
          </footer>
          {review.fair.acquisition_finished && review.counts.pending > 0 && (
            <p className={styles.waitNote} role="status">
              Revisa o marca como “No estoy seguro” los {review.counts.pending} elementos pendientes.
            </p>
          )}
          {!review.fair.acquisition_finished && <p className={styles.waitNote}>Puedes revisar estos resultados ahora. El botón para finalizar se habilitará cuando terminen las búsquedas.</p>}
        </section>
      </div>
    </main>
  );
}
