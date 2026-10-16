// =====================================================================
// PERSON-MAP // Tipos compartidos del cliente (espejo de los schemas
// Pydantic del backend en backend/app/schemas/*).
// =====================================================================

export interface DataProvenance {
  origin: "subject" | "automatic" | "legacy";
  status: "declared" | "discovered" | "confirmed" | "rejected" | "uncertain";
  subject_asserted: boolean;
  matches_declared_identifier: boolean;
  evidence_urls: string[];
  needs_review: boolean;
}
export interface UsernameSeed { username: string; platform?: string | null }
export interface DeclaredSeed {
  kind: "name" | "email" | "username" | "phone";
  value: string;
  platform: string | null;
  provenance: DataProvenance;
}
export interface FootprintInput {
  version: 2;
  given_names: string | null;
  family_names: string | null;
  emails: string[];
  usernames: UsernameSeed[];
  phones: string[];
  declared_seeds: DeclaredSeed[];
}
export interface TargetData {
  footprint_input?: FootprintInput | null;
  id: string;
  full_name?: string | null;
  email?: string | null;
  username?: string | null;
  phone?: string | null;
  dni?: string | null;
  university?: string | null;
  description?: string | null;
  extra_data?: Record<string, unknown>;
  created_at: string;
}

/**
 * Capa del motor híbrido de la que procede un hallazgo.
 *
 * `heuristic` es el barrido determinista; `refinement`, lo que añadió el LLM al
 * cubrir los huecos. Un hallazgo puede llevar las dos si ambas capas lo vieron.
 */
export type EngineLayer = "heuristic" | "refinement";

export interface EntityData {
  provenance?: DataProvenance;
  id: string;
  investigation_id: string;
  entity_type: string;
  platform?: string | null;
  value: string;
  display_name?: string | null;
  metadata_info?: Record<string, unknown> & {
    bio?: string;
    university?: string;
    extracted_emails?: string[];
    snippet?: string;
    rationale?: string;
    engine?: string;
    /** Capa del motor híbrido que descubrió el hallazgo. */
    engine_layers?: EngineLayer[];
    /** Catálogo del que salió la comprobación de esta plataforma. */
    catalog_source?: "whatsmyname" | "maigret";
    /** Catálogo que aportó metadatos extra (regexCheck, ranking, ausencias). */
    catalog_enriched_by?: string | null;
    /** Ranking de popularidad del sitio, si el catálogo lo conoce. */
    site_rank?: number | null;
    /** Miniatura del avatar, pasiva o cosechada activamente. */
    avatar_url?: string;
    /** Proveedor del que se construyó la URL (github, telegram, gravatar...). */
    avatar_source?: string;
    /** `true` si la URL la construyó la cosecha activa, no un hallazgo pasivo. */
    avatar_harvested?: boolean;
    /** Bits de diferencia entre los dos hashes perceptuales. 0 = idénticos. */
    avatar_hamming_distance?: number;
  };
  source_tool: string;
  discovered_at: string;
}

export interface RecommendationData {
  title: string;
  impact: string;
  description: string;
  advice: string;
}

export interface InvestigationMetrics {
  acquisition_mode?: "normal" | "fair";
  entities_discovered?: number;
  execution_time_seconds?: number;
  ai_enhanced?: boolean;
  /** Estrategia pedida al crear la investigación. */
  strategy_used?: string;
  /**
   * Motor que REALMENTE se ejecutó. Difiere de `strategy_used` cuando no hay
   * LLM configurado: `auto`, `agentic` e `hybrid` acaban entonces corriendo el
   * motor de reglas, y contarlas como IA falsearía la comparativa.
   */
  engine_used?: EngineId;
  hybrid_degraded?: boolean;
  /**
   * El LLM dejó de responder durante el agente autónomo y se ejecutó el
   * barrido heurístico completo como respaldo. Si el agente no alcanzó a
   * ejecutar ninguna herramienta, `engine_used` es `rules`.
   */
  agent_fallback_to_rules?: boolean;
  agent_tools_executed?: number;
  /** El fallo del proveedor, en una frase ("el modelo de IA está saturado (503)"). */
  agent_llm_error?: string | null;
  /** Huella de la configuración con la que corrió (prefijo `config_`). */
  config_username_catalog_available?: number;
  config_username_catalog_scanned?: number;
  config_http_max_concurrency?: number;
  config_http_max_per_host?: number;
  config_username_scan_concurrency?: number;
  config_tools_registered?: number;
  config_search_engine?: string;
  config_catalog_from_whatsmyname?: number;
  config_catalog_from_maigret?: number;
  config_catalog_enriched?: number;
  config_catalog_with_regex_check?: number;
  config_maigret_commit?: string | null;
  enrichment_avatars_harvested?: number;
  hybrid_heuristic_findings?: number;
  hybrid_refinement_findings?: number;
  hybrid_refinement_calls?: number;
  hybrid_refinement_calls_skipped?: number;
  hybrid_entities_only_from_llm?: number;
  [key: string]: unknown;
}

export interface CorrelationGroupData {
  id: string;
  investigation_id: string;
  label: string;
  entity_ids: string[];
  summary?: string | null;
  evidence?: Record<string, unknown>;
  entities: EntityData[];
}

export interface InvestigationData {
  id: string;
  target_id: string;
  strategy: string;
  execution_mode?: "internal" | "external";
  revision?: number;
  status: string;
  summary?: string | null;
  metrics: InvestigationMetrics;
  created_at: string;
  completed_at?: string | null;
  target?: TargetData | null;
  entities?: EntityData[];
  correlation_groups?: CorrelationGroupData[];
  analysis_notes?: AnalysisNoteData[];
  sessions?: InvestigationSessionData[];
}

export type ReviewDecisionValue = "confirmed" | "rejected" | "uncertain";
export type ReviewStatus = "not_started" | "in_progress" | "complete";
export interface ReviewCandidateSource {
  name: string;
  evidence_urls: string[];
}
export interface ReviewCandidate {
  id: string;
  entity_type: string;
  category: "account" | "email" | "phone" | "academic_profile";
  platform?: string | null;
  value: string;
  username?: string | null;
  display_name?: string | null;
  avatar_url?: string | null;
  public_url?: string | null;
  bio?: string | null;
  institutions: string[];
  reason: string;
  sources: ReviewCandidateSource[];
  evidence_urls: string[];
  provenance: DataProvenance;
  decision: ReviewDecisionValue | null;
  decided_at?: string | null;
}
export interface ReviewCounts {
  pending: number;
  confirmed: number;
  rejected: number;
  uncertain: number;
}
export interface FairReviewSourceState {
  status: string;
  reason?: string | null;
  findings_count: number;
}
export interface FairReviewState {
  acquisition_finished: boolean;
  partial: boolean;
  warning?: string | null;
  sources: Record<string, FairReviewSourceState>;
  social_sources: Record<string, FairReviewSourceState>;
}
export interface InvestigationReviewData {
  version: 1;
  investigation_id: string;
  review_status: ReviewStatus;
  finalized_at?: string | null;
  counts: ReviewCounts;
  declared_seeds: DeclaredSeed[];
  candidates: ReviewCandidate[];
  fair: FairReviewState;
}
export interface ReviewFinalizeData {
  investigation_id: string;
  review_status: "complete";
  finalized_at: string;
  counts: ReviewCounts;
  dataset_version: 1;
}
export interface ReviewedFootprintDataset {
  version: 1;
  subject: { declared: Array<DeclaredSeed & { seed_id: string }> };
  accounts: Array<Record<string, unknown>>;
  emails: Array<Record<string, unknown>>;
  phones: Array<Record<string, unknown>>;
  academic_profiles: Array<Record<string, unknown>>;
  documents: Array<Record<string, unknown>>;
  breaches: Array<Record<string, unknown>>;
  infostealers: Array<Record<string, unknown>>;
  social_content: Array<Record<string, unknown>>;
  review: Record<ReviewDecisionValue, Array<Record<string, unknown>>>;
  evidence: Array<Record<string, unknown>>;
  execution: Record<string, unknown>;
}

export type ExposureStatus = "pending" | "running" | "completed" | "partial" | "failed";
export type ExposureSeverity = "high" | "medium" | "low" | "informational";
export type ExposurePartialReason = "acquisition_partial" | "content_limit_reached" | "ai_failure";
export type ExposureCategory =
  | "contact_exposure"
  | "alias_reuse"
  | "cross_platform_correlation"
  | "location_disclosure"
  | "temporal_exposure"
  | "education_work_context"
  | "biographical_identifiers"
  | "public_documents"
  | "breach_exposure"
  | "infostealer_exposure"
  | "content_disclosure";
export interface ExposureEvidence {
  source_type: "entity" | "content" | "breach" | "infostealer" | "document";
  source_id?: string | null;
  platform?: string | null;
  account?: string | null;
  url?: string | null;
  occurred_at?: string | null;
  excerpt: string;
}
export interface ExposureFinding {
  id: string;
  category: ExposureCategory;
  severity: ExposureSeverity;
  title: string;
  summary: string;
  why_it_matters: string;
  evidence: ExposureEvidence[];
  source_entity_ids: string[];
  source_content_ids: string[];
  recommendations: string[];
  basis: "observed" | "inferred";
  analysis_method: "deterministic" | "ai";
  signals: string[];
}
export interface ExposureTopItem {
  id: string;
  platform?: string | null;
  account?: string | null;
  published_at?: string | null;
  excerpt: string;
  severity: ExposureSeverity;
  reveals: string[];
  why_it_matters: string;
  evidence: ExposureEvidence[];
  recommendations: string[];
}
export interface ExposureReport {
  version: 1;
  investigation_id: string;
  dataset_hash?: string | null;
  current_dataset_hash?: string | null;
  analysis_version: string;
  status: ExposureStatus;
  partial_reasons: ExposurePartialReason[];
  stale: boolean;
  cache_hit: boolean;
  summary: Record<ExposureSeverity, number>;
  categories: Record<string, number>;
  findings: ExposureFinding[];
  top_exposures: ExposureTopItem[];
  analyzed_content_count: number;
  skipped_content_count: number;
  generated_at?: string | null;
  model?: string | null;
  config: Record<string, unknown>;
}

export type AnalysisNoteKind = "comment" | "summary" | "insight" | "hypothesis" | "next_step";
export interface AnalysisNotePayload {
  kind: AnalysisNoteKind;
  title: string;
  content: string;
  evidence_urls?: string[];
  entity_ids?: string[];
  execution_ids?: string[];
  details?: Record<string, unknown>;
}
export interface AnalysisNoteData extends AnalysisNotePayload {
  id: string;
  investigation_id: string;
  session_id?: string | null;
  author: string;
  author_type: "agent" | "analyst";
  created_at: string;
}
export interface InvestigationSessionData {
  id: string;
  client: string;
  model?: string | null;
  status: string;
  started_at: string;
  ended_at?: string | null;
}

// ---------------------------------------------------------------------
// Trazabilidad persistida de ejecución — no relaciones del mapa.
// ---------------------------------------------------------------------

export interface ToolExecutionData {
  id: string;
  tool_name: string;
  tool_description?: string | null;
  engine: string;
  engine_layer?: string | null;
  round_index?: number | null;
  turn_index?: number | null;
  started_at: string;
  completed_at?: string | null;
  status: string;
  findings_count: number;
  input_summary: Record<string, unknown>;
  error_summary?: string | null;
}

export interface EntityObservationData {
  id: string;
  entity_id: string;
  tool_execution_id: string;
  observed_at: string;
  source_url?: string | null;
  evidence_urls: string[];
  entity: EntityData;
}

export interface InvestigationTraceEventData {
  id: string;
  event_type: string;
  engine: string;
  engine_layer?: string | null;
  round_index?: number | null;
  turn_index?: number | null;
  created_at: string;
  data: Record<string, unknown>;
}

export interface InvestigationTraceResponse {
  investigation_id: string;
  available: boolean;
  executions: ToolExecutionData[];
  observations: EntityObservationData[];
  events: InvestigationTraceEventData[];
}

// ---------------------------------------------------------------------
// Grafo interactivo (React Flow) — espejo de backend/app/schemas/graph.py
// ---------------------------------------------------------------------

export interface GraphNodePosition {
  x: number;
  y: number;
}

export interface GraphNodeData {
  label: string;
  entity_type: string;
  platform?: string | null;
  value: string;
  display_name?: string | null;
  metadata_info?: Record<string, unknown>;
  /** Herramienta que produjo la observación, expuesta por el endpoint graph. */
  source_tool?: string | null;
  /** Momento en que se persistió el hallazgo; el target raíz no lo usa como evidencia. */
  discovered_at?: string | null;
  is_root?: boolean;
  group_id?: string | null;
  correlation?: {
    weight: number;
    level: string;
    reasons: string[];
    ownership_status: "unverified";
    placement_parent_id?: string;
    placement_relation?: string;
  };
  [key: string]: unknown;
}

export interface GraphNode {
  id: string;
  type: string;
  position: GraphNodePosition;
  data: GraphNodeData;
}

export interface GraphEdge {
  id: string;
  source: string;
  target: string;
  label?: string | null;
  relation_type: string;
  animated: boolean;
  style: Record<string, unknown>;
  evidence: unknown;
  supports_group: boolean;
  [key: string]: unknown;
}

export interface GraphResponse {
  investigation_id: string;
  nodes: GraphNode[];
  edges: GraphEdge[];
}

// ---------------------------------------------------------------------
// Consola en vivo — eventos del EventBus (backend/app/core/events.py)
// ---------------------------------------------------------------------

/**
 * Un evento del stream SSE.
 *
 * Convención del backend: los eventos de progreso viajan con `type: "log"` y
 * llevan la etapa en `phase` (`init`, `round_N`, `pivot`, `progress`,
 * `complete`, `agent_*`). Los de herramienta y de cierre usan un `type` propio
 * (`tool_start`, `tool_complete`, `tool_error`, `investigation_complete`,
 * `investigation_error`) y no traen `phase`.
 */
export interface StreamLog {
  type: string;
  message: string;
  timestamp: number;
  tool?: string;
  phase?: string;
  /**
   * Capa del motor que emitió el evento. Solo la usan las estrategias de dos
   * capas; la consola pinta el distintivo únicamente cuando ve las dos, para no
   * añadir ruido a una investigación puramente heurística.
   */
  layer?: EngineLayer | "agentic";
  findings_count?: number;
  error?: string;
  /** Duración real de una herramienta cuando el backend la conoce. */
  duration_seconds?: number;
  /** Identidad durable de la ejecución en Trazabilidad, no un id de UI. */
  tool_execution_id?: string;
  engine?: EngineId | string;
  round_index?: number | null;
  turn_index?: number | null;
  /**
   * Cifras del evento `phase: "progress"`. El backend ya lo emitía, pero solo
   * con una frase; sin `checked`/`total` no se puede dibujar una barra y el
   * evento se desperdiciaba como una línea de log más.
   */
  checked?: number;
  total?: number;
  pct?: number;
  /** Alias o identificador que se está comprobando. */
  subject?: string;
}

export type InvestigationLogMode = "original" | "reconstructed" | "legacy";

/** Respuesta histórica de consola: EventBus o una proyección transparente de Trace DB. */
export interface InvestigationLogHistory {
  mode: InvestigationLogMode;
  logs: StreamLog[];
}

// ---------------------------------------------------------------------
// Métricas comparativas (backend/app/api/v1/metrics.py)
// ---------------------------------------------------------------------

/** Los tres motores que puede reportar el backend en `engine_used`. */
export type EngineId = "rules" | "agentic" | "hybrid" | "external" | "fair";

export interface EngineMetrics {
  count: number;
  avg_execution_time: number;
  avg_entities: number;
  avg_clusters: number;
}

/**
 * Aportación específica del motor híbrido.
 *
 * `avg_entities_only_from_llm` es la cifra que decide si la tercera condición
 * experimental se justifica: cuántas entidades existen únicamente porque la capa
 * de refinamiento las encontró. `refinement_calls_skipped` mide lo contrario —
 * cuánto trabajo redundante pidió el LLM y el motor le ahorró al no repetirlo.
 */
export interface HybridContribution {
  investigations: number;
  avg_heuristic_findings: number;
  avg_refinement_findings: number;
  avg_entities_only_from_llm: number;
  refinement_calls_skipped: number;
}

export interface MetricsComparison {
  summary: {
    total_investigations: number;
    rule_based: EngineMetrics;
    agentic: EngineMetrics;
    hybrid: EngineMetrics;
    external?: EngineMetrics;
  };
  engine_labels?: Record<EngineId, string>;
  hybrid_contribution?: HybridContribution;
  latex_table: string;
  investigations_sample: Array<{
    id: string;
    strategy: string;
    engine_used?: EngineId;
    execution_time: number;
    entities_count: number;
    created_at: string;
  }>;
}

export interface HealthStatus {
  personmap_env: "normal" | "lite";
  default_acquisition_mode: "normal" | "fair";
  lite_plan: { platforms: string[]; deadline_seconds: number; apify_status: string } | null;
  status: string;
  service: string;
  ai_enabled: boolean;
  llm_model: string | null;
}

// ---------------------------------------------------------------------
// Encuesta de concientización (backend/app/api/v1/surveys.py)
// Es la variable dependiente del estudio: mide el delta de percepción de
// riesgo antes y después de ver el propio expediente.
// ---------------------------------------------------------------------

export interface SurveyPayload {
  investigation_id: string;
  /** Percepción de exposición ANTES de ver el expediente (1-5). */
  pre_awareness: number;
  /** Percepción DESPUÉS (1-5). */
  post_awareness: number;
  reused_alias: boolean;
  knew_commit_leak: boolean;
  will_change_habits: boolean;
}

export interface SurveyRead extends SurveyPayload {
  id: string;
  created_at: string;
}

export interface SurveyStats {
  total_responses: number;
  avg_pre_awareness: number;
  avg_post_awareness: number;
  delta_awareness: number;
  reused_alias_pct: number;
  /** % que NO sabía que sus commits filtran el correo. */
  ignorant_commit_leak_pct: number;
  will_change_habits_pct: number;
}

// ---------------------------------------------------------------------
// Payloads de entrada
// ---------------------------------------------------------------------

export interface TargetInput {
  input_version?: 1 | 2;
  given_names?: string | null;
  family_names?: string | null;
  emails?: string[];
  usernames?: UsernameSeed[];
  phones?: string[];
  full_name?: string | null;
  email?: string | null;
  username?: string | null;
  phone?: string | null;
  dni?: string | null;
  university?: string | null;
  description?: string | null;
  extra_data?: Record<string, unknown> | null;
  identifiers?: TypedIdentifier[];
}

export type IdentifierType = "orcid" | "steam_id" | "gaia_id" | "vk_id" | "qq_id" | "bilibili_id" |
  "yandex_public_id" | "yelp_userid" | "ok_id" | "wikimapia_uid" | "uidme_uguid";
export interface TypedIdentifier { value: string; id_type: IdentifierType }
export type MaigretScanMode = "fast" | "deep" | "all";
export type MaigretReportFormat = "json" | "ndjson" | "csv" | "txt" | "markdown" | "html" | "pdf" | "xmind" | "graph" | "neo4j";
export interface MaigretCapabilities {
  catalogue_with_variants: number;
  report_formats: MaigretReportFormat[];
  maigret_enrich: boolean;
  maigret_parse: boolean;
}

/**
 * Estrategias de orquestación. `hybrid` se añadió como TERCERA condición sin
 * sustituir a `rule_based` ni a `agentic`: los tres son brazos experimentales
 * independientes de la comparativa del artículo.
 */
export type Strategy = "auto" | "rule_based" | "agentic" | "hybrid";

export interface CreateInvestigationPayload {
  acquisition_mode?: "normal" | "fair";
  target: TargetInput;
  strategy: Strategy;
  /**
   * Consentimiento para las fuentes que revelan a un tercero a quién se
   * investiga (hoy, los registros de infostealer de Hudson Rock). Por defecto
   * `false`: esas herramientas fallan cerradas.
   */
  self_consent?: boolean;
  subject_consent?: boolean;
  maigret_plan?: { scan_mode: MaigretScanMode; options?: { parse?: boolean; enrich?: boolean; permutation_parts?: string[] } };
}

// Reviewed-only Digital Footprint Reconstruction / Graph V2.
export type ReconstructionBasis = "DECLARED" | "OBSERVED" | "CORRELATED" | "INFERRED";
export type ReconstructionGroup = "identity" | "accounts" | "content" | "documents" | "breaches" | "exposure";
export type ReconstructionKind = "subject" | "name" | "email" | "phone" | "alias" | "domain" | "url" |
  "account" | "academic_profile" | "document" | "publication" | "repository" | "post" | "breach" | "infostealer" | "exposure" | "context";
export interface ReconstructionEvidence {
  id: string;
  source_type: string;
  source_entity_ids: string[];
  source_content_ids: string[];
  platform: string | null;
  url: string | null;
  excerpt: string;
}
export interface ReconstructionFact {
  id: string;
  kind: ReconstructionKind;
  label: string;
  basis: ReconstructionBasis;
  group: ReconstructionGroup;
  ring: number;
  platform: string | null;
  url: string | null;
  safe_summary: string;
  ownership_basis: string | null;
  source_tools: string[];
  source_entity_ids: string[];
  source_content_ids: string[];
  evidence_refs: string[];
  evidence_count: number;
  evidence_types: string[];
  severity: ExposureSeverity | null;
  date: string | null;
}
export interface ReconstructionRelation {
  id: string;
  source: string;
  target: string;
  type: string;
  basis: ReconstructionBasis;
  why: string;
  source_entity_ids: string[];
  source_content_ids: string[];
  evidence_refs: string[];
  evidence_count: number;
  evidence_types: string[];
}
export interface ReconstructionGraph {
  version: "graph-v2";
  nodes: ReconstructionFact[];
  edges: ReconstructionRelation[];
  omitted_nodes: number;
  omitted_by_type: Record<string, number>;
}
export interface DigitalFootprintReconstruction {
  version: 1;
  reconstruction_version: "reconstruction-v1";
  investigation_id: string;
  dataset_hash: string;
  exposure_dataset_hash: string;
  exposure_hash: string;
  input_hash: string;
  coverage: "observed" | "partial";
  coverage_reasons: string[];
  identity: Record<"declared" | "accounts" | "public_identifiers" | "academic_presence" | "documents" | "public_content" | "breach_exposure", string[]>;
  facts: ReconstructionFact[];
  evidence: Record<string, ReconstructionEvidence>;
  correlations: ReconstructionRelation[];
  summary: Array<{ text: string; fact_ids: string[] }>;
  counts: Record<string, number>;
  content_by_platform: Record<string, number>;
  exposure_summary: Record<ExposureSeverity, number>;
  timeline: Array<{ id: string; date: string; kind: ReconstructionKind; label: string; platform: string | null;
    fact_ids: string[]; evidence_refs: string[]; basis: "OBSERVED" }>;
  graph: ReconstructionGraph;
  generated_at: string;
}
export interface ReconstructionReport {
  version: 1;
  investigation_id: string;
  status: ExposureStatus;
  stale: boolean;
  cache_hit: boolean;
  input_hash: string | null;
  current_input_hash: string | null;
  snapshot: DigitalFootprintReconstruction | null;
}
