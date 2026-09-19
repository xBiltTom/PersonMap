import type { GraphEdge } from "@/lib/types";

/**
 * El endpoint construye las conexiones objetivo → hallazgo con `source-*`.
 * Las relaciones persistidas entre hallazgos usan `rel-*`. Esta topología, no
 * el nombre de una relación, define si una arista es procedencia/contexto.
 */
export function isProvenanceEdge(edge: GraphEdge): boolean {
  return edge.id.startsWith("source-");
}

/** Etiquetas observacionales: describen el dato, nunca una identidad inferida. */
export function getFriendlyRelationLabel(relationType: string, customLabel?: string | null): string {
  const labels: Record<string, string> = {
    discovered_from: "hallazgo derivado",
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
