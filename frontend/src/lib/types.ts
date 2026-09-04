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
  };
  confidence: number;
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
