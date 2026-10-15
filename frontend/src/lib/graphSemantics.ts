import type { GraphEdge } from "@/lib/types";

/**
 * El endpoint construye las conexiones objetivo → hallazgo con `source-*`.
 * Las relaciones entre hallazgos usan `rel-*`. Solo discovered_from es
 * procedencia: una coincidencia factual con el objetivo permanece visible.
 */
export function isProvenanceEdge(edge: GraphEdge): boolean {
  return edge.id.startsWith("source-") && edge.relation_type === "discovered_from";
}

/** Etiquetas observacionales: describen el dato, nunca una identidad inferida. */
export function getFriendlyRelationLabel(relationType: string, customLabel?: string | null): string {
  const labels: Record<string, string> = {
    target_email_match: "correo coincidente con el objetivo",
    target_phone_match: "teléfono coincidente con el objetivo",
    target_identifier_match: "identificador coincidente con el objetivo",
    target_context_match: "coincidencia contextual con el objetivo",
    registration_query: "señal de registro del correo consultado",
    shares_email_and_username: "correo y alias coincidentes",
    email_lookup_association: "correo asociado por consulta exacta al proveedor",
    shares_declared_phone: "teléfono declarado en común",
    shared_orcid: "ORCID observado en común",
    shared_gaia_id: "GAIA observado en común",
    name_and_affiliation: "nombre y afiliación coincidentes",
    authored_work: "autoría vinculada por identificador",
    discovered_from: "hallazgo derivado",
    publishes_phone: "teléfono publicado",
    mentions_phone: "teléfono mencionado en búsqueda",
    shares_declared_email: "correo declarado en común",
    explicit_profile_link: "enlace de perfil declarado",
    same_username: "alias coincidente observado",
    similar_avatar: "artefacto visual relacionado",
    same_name: "nombre coincidente observado",
    observed_email: "correo usado como contexto",
    mentions: "mención observada",
    same_owner: "propiedad declarada en la fuente",
    affiliation: "afiliación observada",
    possible_location: "ubicación observada",
    links_to: "enlace observado",
    same_platform: "misma plataforma observada",
  };
  return labels[relationType]
    ?? customLabel?.trim().toLocaleLowerCase()
    ?? relationType.replace(/_/g, " ").toLocaleLowerCase();
}
