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
 * Capa del motor híbrido de la que procede un hallazgo.
 *
 * `heuristic` es el barrido determinista; `refinement`, lo que añadió el LLM al
 * cubrir los huecos. Un hallazgo puede llevar las dos si ambas capas lo vieron.
 */
export type EngineLayer = "heuristic" | "refinement";

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
  status: string;
  summary?: string | null;
  metrics: InvestigationMetrics;
  created_at: string;
  completed_at?: string | null;
  target?: TargetData | null;
  entities?: EntityData[];
  correlation_groups?: CorrelationGroupData[];
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
  layer?: EngineLayer;
  findings_count?: number;
  error?: string;
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

// ---------------------------------------------------------------------
// Métricas comparativas (backend/app/api/v1/metrics.py)
// ---------------------------------------------------------------------

/** Los tres motores que puede reportar el backend en `engine_used`. */
export type EngineId = "rules" | "agentic" | "hybrid";

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

/**
 * Estrategias de orquestación. `hybrid` se añadió como TERCERA condición sin
 * sustituir a `rule_based` ni a `agentic`: los tres son brazos experimentales
 * independientes de la comparativa del artículo.
 */
export type Strategy = "auto" | "rule_based" | "agentic" | "hybrid";

export interface CreateInvestigationPayload {
  target: TargetInput;
  strategy: Strategy;
  /**
   * Consentimiento para las fuentes que revelan a un tercero a quién se
   * investiga (hoy, los registros de infostealer de Hudson Rock). Por defecto
   * `false`: esas herramientas fallan cerradas.
   */
  self_consent?: boolean;
}
