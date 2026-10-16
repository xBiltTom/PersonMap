"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  ArrowLeft,
  BadgeCheck,
  BookOpenCheck,
  Check,
  CircleHelp,
  Clock3,
  Download,
  ExternalLink,
  FileQuestion,
  Fingerprint,
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
  { value: "confirmed", label: "Sí soy yo", icon: Check },
  { value: "rejected", label: "No soy yo", icon: X },
  { value: "uncertain", label: "No estoy seguro", icon: CircleHelp },
];

const DECISION_LABEL: Record<ReviewDecisionValue, string> = {
  confirmed: "Confirmados",
  rejected: "No pertenecen a mí",
  uncertain: "No estoy seguro",
};

function prettyPlatform(value?: string | null) {
  if (!value) return "Perfil público";
  const labels: Record<string, string> = {
    github: "GitHub",
    instagram: "Instagram",
    tiktok: "TikTok",
    youtube: "YouTube",
    threads: "Threads",
    twitter: "X / Twitter",
    reddit: "Reddit",
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
    completed: "Completado",
    partial: "Parcial",
    timeout: "Tiempo agotado",
    provider_unavailable: "No disponible",
    failed: "Falló",
    budget_exhausted: "Límite alcanzado",
    skipped: "No ejecutado",
    not_applicable: "Sin entrada compatible",
    pending: "Pendiente",
    running: "En curso",
  };
  return labels[state.status] ?? state.status;
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
          Hallazgo automático
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

      <p className={styles.reason}><Fingerprint size={14} aria-hidden="true" />{candidate.reason}</p>

      <details className={styles.evidenceDetails}>
        <summary>¿Por qué apareció? <span>{candidate.sources.length} {candidate.sources.length === 1 ? "fuente" : "fuentes"}</span></summary>
        <div className={styles.evidenceBody}>
          {candidate.sources.map((source) => (
            <div className={styles.sourceBlock} key={source.name}>
              <strong>{source.name}</strong>
              {source.evidence_urls.length > 0 ? (
                <ul>
                  {source.evidence_urls.map((url) => (
                    <li key={url}><a href={url} target="_blank" rel="noreferrer">{url}</a></li>
                  ))}
                </ul>
              ) : <span>Observación registrada en esta investigación.</span>}
            </div>
          ))}
          {candidate.sources.length === 0 && <p>La observación quedó registrada por {candidate.provenance.origin === "automatic" ? "una fuente automática" : "el sistema"}.</p>}
        </div>
      </details>

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
          <h2 id="declared-title">Datos que nos diste</h2>
          <p>Confirmado por ti al inicio</p>
        </div>
      </div>
      <ul className={styles.seedList}>
        {seeds.map((seed, index) => <li key={`${seed.kind}:${seed.platform ?? ""}:${seed.value}:${index}`}>{seedLabel(seed)}</li>)}
      </ul>
      <p className={styles.readOnlyNote}>Estos datos son de solo lectura y nunca vuelven a revisión.</p>
    </section>
  );
}

function SourceHealth({ review }: { review: InvestigationReviewData }) {
  const sources = useMemo(() => [
    ...Object.entries(review.fair.sources).map(([name, state]) => ({ name, state })),
    ...Object.entries(review.fair.social_sources).map(([name, state]) => ({ name: prettyPlatform(name), state })),
  ], [review.fair.sources, review.fair.social_sources]);
  return (
    <details className={styles.sourceHealth}>
      <summary><span>Estado de adquisición</span><span>{sources.length} fuentes</span></summary>
      <ul>
        {sources.map(({ name, state }) => (
          <li key={`${name}:${state.status}`}>
            <span>{name}</span>
            <span className={`${styles.sourceStatus} ${state.status === "completed" ? styles.sourceComplete : styles.sourceIncomplete}`}>
              {sourceStateLabel(state)}
            </span>
            {state.reason && <small>{state.reason.replaceAll("_", " ")}</small>}
          </li>
        ))}
      </ul>
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

  const loadReview = useCallback(async () => {
    try {
      const result = await getInvestigationReview(investigationId);
      setReview(result);
      setError(null);
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : "No se pudo cargar la revisión.");
    } finally {
      setLoading(false);
    }
  }, [investigationId]);

  useEffect(() => {
    const timer = window.setTimeout(() => { void loadReview(); }, 0);
    return () => window.clearTimeout(timer);
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
    return <div className={styles.loading}><span className={styles.loader} /><p>Preparando tus hallazgos para revisión…</p></div>;
  }
  if (!review) {
    return (
      <main className={styles.page}>
        <div className={styles.errorPanel} role="alert">
          <FileQuestion size={22} aria-hidden="true" />
          <h1>No se pudo abrir la revisión</h1>
          <p>{error || "La investigación no tiene un Verification Gate disponible."}</p>
          <Link href={`/investigation/${investigationId}`} className={styles.backLink}><ArrowLeft size={15} /> Volver al expediente</Link>
        </div>
      </main>
    );
  }

  const isComplete = review.review_status === "complete";
  return (
    <main className={styles.page}>
      <Link href={`/investigation/${investigationId}`} className={styles.backLink}>
        <ArrowLeft size={15} aria-hidden="true" /> Volver al expediente
      </Link>

      <header className={styles.hero}>
        <div className={styles.heroCopy}>
          <div className={styles.eyebrow}><span /> Verification Gate <i>·</i> Fair Mode</div>
          <h1>Tu huella empieza<br className="hidden sm:block" /> con tu decisión.</h1>
          <p>Revisa perfiles e identificadores encontrados. Cada decisión queda guardada y puedes cambiarla después.</p>
        </div>
        <div className={styles.gateMark} aria-hidden="true">
          <ShieldCheck size={25} strokeWidth={1.5} />
          <span>ATRIBUCIÓN<br />HUMANA</span>
        </div>
      </header>

      {error && <div className={styles.errorBanner} role="alert">{error}</div>}

      {review.fair.partial && (
        <div className={styles.partialNotice} role="status">
          <Clock3 size={17} aria-hidden="true" />
          <div><strong>Búsqueda con fuentes incompletas</strong><p>{review.fair.warning || "Puedes revisar los resultados disponibles."}</p></div>
        </div>
      )}

      <div className={styles.countRail} aria-label="Resumen de revisión">
        <div><strong>{review.counts.pending}</strong><span>Pendientes</span></div>
        <div><strong>{review.counts.confirmed}</strong><span>Confirmados</span></div>
        <div><strong>{review.counts.rejected}</strong><span>Descartados</span></div>
        <div><strong>{review.counts.uncertain}</strong><span>Dudosos</span></div>
        <span className={`${styles.statusPill} ${isComplete ? styles.statusComplete : ""}`}>
          {isComplete ? <><BadgeCheck size={13} /> Revisión finalizada</> : <><Clock3 size={13} /> {review.review_status === "not_started" ? "Sin empezar" : "En curso"}</>}
        </span>
      </div>

      <div className={styles.layout}>
        <aside className={styles.sidebar}>
          <DeclaredSeeds seeds={review.declared_seeds} />
          <SourceHealth review={review} />
          <div className={styles.ruleNote}>
            <BookOpenCheck size={16} aria-hidden="true" />
            <p>Un alias igual en otra plataforma no confirma que la cuenta sea tuya. La falta de resultados tampoco significa que no existan en Internet.</p>
          </div>
        </aside>

        <section className={styles.reviewColumn} aria-labelledby="discoveries-title">
          <div className={styles.sectionIntro}>
            <div><span className={styles.sectionKicker}>Hallazgos para atribuir</span><h2 id="discoveries-title">Descubrimientos</h2></div>
            {review.counts.pending > 0 && <span className={styles.pendingLabel}>{review.counts.pending} por revisar</span>}
          </div>

          {groups.pending.length > 0 ? (
            <div className={styles.pendingList}>
              {groups.pending.map((candidate) => <CandidateCard key={candidate.id} candidate={candidate}
                busy={busyId !== null || finalizing} onDecision={handleDecision} />)}
            </div>
          ) : (
            <div className={styles.emptyState}>
              <span><BadgeCheck size={21} aria-hidden="true" /></span>
              <h3>{review.candidates.length ? "Todo lo revisable tiene una decisión" : "No hay identidades nuevas para revisar"}</h3>
              <p>{review.candidates.length ? "Puedes cambiar cualquiera de tus decisiones antes o después de finalizar." : "Tus datos declarados permanecen en la huella sin pedirte una segunda confirmación."}</p>
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
              <div><h3>{isComplete ? "La huella revisada está lista" : "Cuando termines, cierra la revisión"}</h3>
                <p>{isComplete
                  ? "La Fase 5 solo podrá leer datos declarados o confirmados por ti."
                  : "Los dudosos y los pendientes quedarán fuera de la huella atribuida."}</p></div>
            </div>
            <div className={styles.finalizeActions}>
              {isComplete && <button type="button" className={styles.downloadButton} onClick={() => void handleDownload()}>
                <Download size={14} aria-hidden="true" /> {downloaded ? "Descargado" : "Descargar dataset"}
              </button>}
              <button type="button" className={styles.finalizeButton}
                disabled={!canFinalizeReview(review.fair.acquisition_finished, review.counts.pending) || finalizing || busyId !== null}
                onClick={() => void handleFinalize()}>
                <ShieldCheck size={15} aria-hidden="true" />
                {finalizing ? "Guardando…" : isComplete ? "Actualizar huella" : "Finalizar revisión"}
              </button>
            </div>
          </footer>
          {review.fair.acquisition_finished && review.counts.pending > 0 && (
            <p className={styles.waitNote} role="status">
              Revisa o marca como “No estoy seguro” los {review.counts.pending} elementos pendientes.
            </p>
          )}
          {!review.fair.acquisition_finished && <p className={styles.waitNote}>Puedes revisar resultados ahora; finalizar estará disponible al terminar Fair Mode.</p>}
        </section>
      </div>
    </main>
  );
}
