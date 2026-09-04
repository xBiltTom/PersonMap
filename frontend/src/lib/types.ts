// =====================================================================
// PERSON-MAP // Tipos compartidos del cliente (espejo de los schemas
// Pydantic del backend en backend/app/schemas/*).
// =====================================================================

export interface TargetData {
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
 * Desglose del modelo Fellegi-Sunter que persiste `app/engine/persistence.py`.
 *
 * Por cada señal hay dos claves: `<señal>` con el grado de acuerdo γ ∈ [0,1] y
 * `<señal>_weight` con su peso en bits de log-verosimilitud (positivo si la
 * señal apoya la atribución, negativo si la contradice). `log_likelihood_ratio`
 * es la suma.
 */
export interface IdentityBreakdown {
  log_likelihood_ratio?: number;
  /** Cuántas señales pudieron evaluarse para este par (objetivo, hallazgo). */
  signals_evaluated?: number;
  scorer_version?: string;
  /** `<señal>`: γ ∈ [0,1] · `<señal>_weight`: bits · `<señal>_applicable`: evaluable. */
  [signal: string]: number | string | boolean | undefined;
}

export interface EntityData {
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
    identity_breakdown?: IdentityBreakdown;
    identity_score?: number;
    snippet?: string;
    rationale?: string;
    engine?: string;
  };
  /** Valor mostrado: el máximo de las dos métricas siguientes. */
  confidence: number;
  /** Certeza de DETECCIÓN de la herramienta: "esta cuenta existe". */
  existence_confidence?: number | null;
  /** Probabilidad de ATRIBUCIÓN del modelo: "es del objetivo". */
  identity_score?: number | null;
  scorer_version?: string | null;
  verified: boolean;
  verification_notes?: string | null;
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
  entities_discovered?: number;
  risk_level?: string;
  recommendations?: RecommendationData[];
  execution_time_seconds?: number;
  ai_enhanced?: boolean;
  [key: string]: unknown;
}

export interface IdentityClusterData {
  id: string;
  investigation_id: string;
  label: string;
  confidence: number;
  entity_ids: string[];
  reasoning?: string | null;
  scoring_breakdown?: Record<string, unknown>;
  entities: EntityData[];
}

export interface InvestigationData {
  id: string;
  target_id: string;
  strategy: string;
  status: string;
  risk_score: number;
  summary?: string | null;
  metrics: InvestigationMetrics;
  created_at: string;
  completed_at?: string | null;
  target?: TargetData | null;
  entities?: EntityData[];
  identity_clusters?: IdentityClusterData[];
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
  confidence: number;
  verified: boolean;
  metadata_info?: Record<string, unknown>;
  is_root?: boolean;
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
  strength: number;
  animated: boolean;
  style: Record<string, unknown>;
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
  findings_count?: number;
  error?: string;
}

// ---------------------------------------------------------------------
// Métricas comparativas (backend/app/api/v1/metrics.py)
// ---------------------------------------------------------------------

export interface EngineMetrics {
  count: number;
  avg_execution_time: number;
  avg_entities: number;
  avg_clusters: number;
  avg_risk_score: number;
}

export interface MetricsComparison {
  summary: {
    total_investigations: number;
    rule_based: EngineMetrics;
    agentic: EngineMetrics;
  };
  latex_table: string;
  investigations_sample: Array<{
    id: string;
    strategy: string;
    execution_time: number;
    entities_count: number;
    risk_score: number;
    created_at: string;
  }>;
}

export interface HealthStatus {
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
  full_name?: string | null;
  email?: string | null;
  username?: string | null;
  phone?: string | null;
  dni?: string | null;
  university?: string | null;
  description?: string | null;
  extra_data?: Record<string, unknown> | null;
}

export interface CreateInvestigationPayload {
  target: TargetInput;
  strategy: string;
}
