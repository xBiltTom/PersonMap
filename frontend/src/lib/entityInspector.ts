import type { GraphEdge, GraphNode } from "@/lib/types";

export type InspectorFieldKind = "text" | "email" | "url" | "location" | "date";
export type InspectorLinkKind = "profile" | "website" | "social" | "repository" | "source" | "other";
export type InspectorImageKind = "avatar" | "profile" | "thumbnail" | "other";
export type InspectorEvidenceFilter = "links" | "descriptions" | "images" | "provenance";

export interface InspectorField {
  key: string;
  label: string;
  value: string;
  kind: InspectorFieldKind;
}

export interface InspectorLink {
  label: string;
  url: string;
  kind: InspectorLinkKind;
}

export interface InspectorImage {
  url: string;
  kind: InspectorImageKind;
  source?: string;
}

export interface InspectorDescription {
  label: string;
  text: string;
}

export interface InspectorRelationship {
  edge: GraphEdge;
  node: GraphNode;
  label: string;
}

export interface EntityInspectorViewModel {
  isRoot: boolean;
  title: string;
  subtitle?: string;
  platform?: string;
  entityType: string;
  entityTypeKey: string;
  primaryLink?: InspectorLink;
  observedFields: InspectorField[];
  descriptions: InspectorDescription[];
  links: InspectorLink[];
  images: InspectorImage[];
  provenance?: {
    sourceTool?: string;
    sourceUrl?: string;
    discoveredAt?: string;
    engine?: string;
  };
  relationships: InspectorRelationship[];
}

type Metadata = Record<string, unknown>;

const ENTITY_TYPE_LABELS: Record<string, string> = {
  target: "Punto de partida",
  social_account: "Cuenta",
  sensitive_account: "Cuenta sensible",
  email: "Correo",
  domain: "Dominio",
  document: "Documento",
  academic: "Hallazgo académico",
  academic_profile: "Perfil académico",
  search_mention: "Mención pública",
  image_match: "Artefacto visual",
  phone: "Teléfono",
  breach: "Brecha de datos",
};

function isRecord(value: unknown): value is Metadata {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function stringValue(value: unknown): string | undefined {
  return typeof value === "string" && value.trim() ? value.trim() : undefined;
}

function stringList(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value.flatMap((item) => {
    const text = stringValue(item);
    return text ? [text] : [];
  });
}

function numberValue(value: unknown): string | undefined {
  return typeof value === "number" && Number.isFinite(value)
    ? value.toLocaleString("es-PE")
    : undefined;
}

export function toSafeExternalUrl(value: unknown): string | undefined {
  const raw = stringValue(value);
  if (!raw) return undefined;
  try {
    const parsed = new URL(raw);
    return parsed.protocol === "https:" || parsed.protocol === "http:" ? parsed.href : undefined;
  } catch {
    return undefined;
  }
}

function humanize(value: string): string {
  return value
    .replace(/[_-]+/g, " ")
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function formatPlatform(platform?: string | null): string | undefined {
  const value = stringValue(platform);
  if (!value) return undefined;
  const aliases: Record<string, string> = {
    x_twitter: "X (Twitter)",
    twitter: "X (Twitter)",
    devto: "Dev.to",
    openalex_author: "OpenAlex",
    google_scholar: "Google Scholar",
    certificate_transparency: "Certificate Transparency",
  };
  return aliases[value.toLowerCase()] ?? humanize(value);
}

function formatTool(tool: string): string {
  const key = tool.split(":").pop() ?? tool;
  const labels: Record<string, string> = {
    github_deep_scanner: "GitHub Deep Scanner",
    gravatar_deep: "Gravatar Deep",
    social_verifier: "Verificador social",
    social_url_extractor: "Extractor de URL social",
    username_finder: "Buscador de alias",
    search_dorker: "Búsqueda avanzada",
    domain_finder: "Certificate Transparency",
    academic_finder: "Buscador académico",
    keybase_resolver: "Resolutor Keybase",
    google_account_osint: "OSINT de cuenta Google",
    reverse_image_search: "Búsqueda visual",
    email_enumerator: "Enumerador de correo",
  };
  return labels[key] ?? humanize(key);
}

function firstString(metadata: Metadata, keys: string[]): string | undefined {
  for (const key of keys) {
    const value = stringValue(metadata[key]);
    if (value) return value;
  }
  return undefined;
}

function uniqueByUrl<T extends { url: string; kind: string }>(items: T[]): T[] {
  const seen = new Set<string>();
  return items.filter((item) => {
    // Una misma URL puede ser tanto recurso observado como fuente de la
    // observación. Conservamos esa diferencia semántica, pero eliminamos los
    // repetidos dentro de cada categoría.
    const key = `${item.kind}:${item.url.toLowerCase()}`;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

function uniqueText(values: string[]): string[] {
  const seen = new Set<string>();
  return values.filter((value) => {
    const key = value.toLowerCase();
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

function linkFor(urlValue: unknown, label: string, kind: InspectorLinkKind): InspectorLink | undefined {
  const url = toSafeExternalUrl(urlValue);
  return url ? { label, url, kind } : undefined;
}

function buildLinks(node: GraphNode, metadata: Metadata): InspectorLink[] {
  const links: InspectorLink[] = [];
  const add = (value: unknown, label: string, kind: InspectorLinkKind) => {
    const link = linkFor(value, label, kind);
    if (link) links.push(link);
  };

  // URLs que identifican el recurso observado, no la fuente del hallazgo.
  add(firstString(metadata, ["profile_url", "canonical_url"]), "Perfil original", "profile");
  add(node.data.value, node.data.entity_type === "document" ? "Documento original" : "Recurso observado", "profile");
  add(metadata.url, "Recurso observado", "profile");
  add(metadata.website, "Web declarada", "website");
  add(metadata.blog, "Web declarada", "website");
  add(metadata.repository_url, "Repositorio", "repository");
  add(metadata.repo_url, "Repositorio", "repository");
  add(metadata.whatsapp_link, "WhatsApp", "social");
  add(metadata.telegram_link, "Telegram", "social");

  for (const value of stringList(metadata.linked_profiles)) add(value, "Perfil relacionado", "social");
  for (const value of stringList(metadata.links)) add(value, "Enlace declarado", "social");
  for (const item of Array.isArray(metadata.email_evidence) ? metadata.email_evidence : []) {
    if (isRecord(item)) add(item.commit_url, "Commit con correo observado", "source");
  }

  // Estas URLs explican dónde se observó el dato, por eso conservan tipo source.
  add(metadata.source_url, "Fuente original", "source");
  for (const value of stringList(metadata.evidence_urls)) add(value, "Fuente del hallazgo", "source");

  return uniqueByUrl(links);
}

function buildImages(metadata: Metadata): InspectorImage[] {
  const images: InspectorImage[] = [];
  const add = (value: unknown, kind: InspectorImageKind, source?: string) => {
    const url = toSafeExternalUrl(value);
    if (url) images.push({ url, kind, source });
  };

  add(metadata.avatar_url, "avatar", stringValue(metadata.avatar_source));
  add(metadata.profile_image, "profile");
  add(metadata.profile_image_url, "profile");
  add(metadata.thumbnail_url, "thumbnail");
  add(metadata.og_image, "thumbnail", "OpenGraph");
  add(metadata.origin_avatar_url, "other");
  for (const value of stringList(metadata.image_urls)) add(value, "other");
  for (const value of stringList(metadata.images)) add(value, "other");
  return uniqueByUrl(images);
}

/** Facetas factuales para explorar el mapa; no expresan certeza de identidad. */
export function getInspectorEvidenceFilters(node: GraphNode): Set<InspectorEvidenceFilter> {
  const metadata = isRecord(node.data.metadata_info) ? node.data.metadata_info : {};
  const filters = new Set<InspectorEvidenceFilter>();
  if (buildLinks(node, metadata).length) filters.add("links");
  if (buildDescriptions(metadata).length) filters.add("descriptions");
  if (buildImages(metadata).length) filters.add("images");
  if (stringValue(node.data.source_tool) || firstString(metadata, ["source_tool"]) || stringList(metadata.source_tools).length) {
    filters.add("provenance");
  }
  return filters;
}

/** Texto de búsqueda reducido a identificadores y datos observados conocidos. */
export function getInspectorSearchText(node: GraphNode): string {
  const metadata = isRecord(node.data.metadata_info) ? node.data.metadata_info : {};
  const scalarKeys = [
    "username", "preferred_username", "name", "full_name", "display_name",
    "email", "location", "university", "domain", "title", "doi", "orcid",
  ];
  const listKeys = ["emails", "extracted_emails", "usernames", "institutions"];
  const values = [node.data.label, node.data.display_name, node.data.value, node.data.platform, node.data.entity_type];
  for (const key of scalarKeys) values.push(stringValue(metadata[key]));
  for (const key of listKeys) values.push(...stringList(metadata[key]));
  return values.filter((value): value is string => Boolean(value)).join(" ").toLocaleLowerCase();
}

function buildObservedFields(node: GraphNode, metadata: Metadata, isRoot: boolean): InspectorField[] {
  const fields: InspectorField[] = [];
  const presentValues = new Set<string>();
  const add = (key: string, label: string, value: unknown, kind: InspectorFieldKind = "text") => {
    const text = stringValue(value);
    if (!text || presentValues.has(text.toLowerCase())) return;
    fields.push({ key, label, value: text, kind });
    presentValues.add(text.toLowerCase());
  };
  const addList = (key: string, label: string, value: unknown, kind: InspectorFieldKind = "text") => {
    const values = uniqueText(stringList(value));
    if (values.length) add(key, label, values.join(" · "), kind);
  };

  if (isRoot) add("full_name", "Nombre", metadata.full_name);
  add("username", "Usuario", firstString(metadata, ["username", "preferred_username"]));
  add("name", "Nombre", firstString(metadata, ["name", "display_name", "google_display_name", "author_name"]));
  add("email", "Email", metadata.email, "email");
  addList("emails", "Correos alternativos", metadata.emails, "email");
  addList("extracted_emails", "Correos extraídos", metadata.extracted_emails, "email");
  add("phone", "Teléfono", firstString(metadata, ["phone", "e164", "national"]));
  addList("phones", "Teléfonos alternativos", metadata.phones);
  add("location", "Ubicación", metadata.location, "location");
  add("university", "Universidad", metadata.university);
  addList("institutions", "Instituciones", metadata.institutions);
  add("organization", "Organización", firstString(metadata, ["company_university", "company"]));
  add("domain", "Dominio", metadata.domain);
  add("orcid", "ORCID", metadata.orcid);
  add("doi", "DOI", metadata.doi);
  add("title", "Título", metadata.title);
  add("og_title", "Título encontrado", metadata.og_title);
  add("publication_year", "Año de publicación", numberValue(metadata.publication_year));
  add("public_repos", "Repositorios públicos", numberValue(metadata.public_repos));
  add("works_count", "Publicaciones", numberValue(metadata.works_count));
  add("citations", "Citas", numberValue(metadata.citations));
  add("dni", "Documento", metadata.dni);
  add("identifier", "Valor observado", node.data.value, toSafeExternalUrl(node.data.value) ? "url" : "text");
  return fields;
}

function buildDescriptions(metadata: Metadata): InspectorDescription[] {
  const descriptions: InspectorDescription[] = [];
  const add = (label: string, value: unknown) => {
    const text = stringValue(value);
    if (text && !descriptions.some((entry) => entry.text === text)) descriptions.push({ label, text });
  };
  add("Bio declarada", metadata.bio);
  add("Sobre el perfil", metadata.about);
  add("Descripción", metadata.description);
  add("Resumen", metadata.summary);
  add("Extracto encontrado", metadata.snippet);
  return descriptions;
}

function buildRelationships(
  node: GraphNode,
  nodes: GraphNode[],
  edges: GraphEdge[],
  relationLabel: (edge: GraphEdge) => string
): InspectorRelationship[] {
  const nodeById = new Map(nodes.map((item) => [item.id, item]));
  return edges.flatMap((edge) => {
    if (edge.source !== node.id && edge.target !== node.id) return [];
    const related = nodeById.get(edge.source === node.id ? edge.target : edge.source);
    return related ? [{ edge, node: related, label: relationLabel(edge) }] : [];
  });
}

export function buildEntityInspectorViewModel(
  node: GraphNode,
  nodes: GraphNode[],
  edges: GraphEdge[],
  relationLabel: (edge: GraphEdge) => string
): EntityInspectorViewModel {
  const metadata = isRecord(node.data.metadata_info) ? node.data.metadata_info : {};
  const isRoot = node.type === "personRoot" || node.data.is_root === true;
  const platform = formatPlatform(node.data.platform);
  const entityType = ENTITY_TYPE_LABELS[node.data.entity_type] ?? humanize(node.data.entity_type || "hallazgo");
  const identifier = firstString(metadata, ["username", "preferred_username"])
    ?? node.data.value;
  const links = buildLinks(node, metadata);
  const primaryLink = links.find((link) => link.kind === "profile") ?? links.find((link) => link.kind === "website");
  const sourceUrl = links.find((link) => link.kind === "source")?.url;
  const sourceTools = uniqueText(stringList(metadata.source_tools));
  const rawSourceTool = firstString(metadata, ["source_tool"])
    ?? stringValue(node.data.source_tool)
    ?? (sourceTools.length ? sourceTools.join(" · ") : undefined);
  const sourceTool = rawSourceTool
    ? rawSourceTool.split(" · ").map(formatTool).join(" · ")
    : undefined;

  return {
    isRoot,
    title: platform ?? entityType,
    subtitle: identifier ? (platform && identifier === node.data.value ? undefined : identifier) : undefined,
    platform,
    entityType,
    entityTypeKey: node.data.entity_type,
    primaryLink,
    observedFields: buildObservedFields(node, metadata, isRoot),
    descriptions: buildDescriptions(metadata),
    links,
    images: buildImages(metadata),
    provenance: sourceTool || sourceUrl || node.data.discovered_at || stringValue(metadata.engine)
      ? {
          sourceTool,
          sourceUrl,
          discoveredAt: stringValue(node.data.discovered_at),
          engine: stringValue(metadata.engine),
        }
      : undefined,
    relationships: buildRelationships(node, nodes, edges, relationLabel),
  };
}

export function buildRelationshipEvidenceFields(evidence: unknown): InspectorField[] {
  if (!isRecord(evidence)) return [];
  const fields: InspectorField[] = [];
  const add = (key: string, label: string, value: unknown, kind: InspectorFieldKind = "text") => {
    const text = stringValue(value);
    if (text) fields.push({ key, label, value: text, kind });
  };
  add("email", "Correo observado", evidence.email, "email");
  add("username", "Alias observado", evidence.username);
  add("linked_profile", "Perfil enlazado", evidence.linked_profile, "url");
  add("method", "Método", evidence.method);
  add("source_tool", "Herramienta", evidence.source_tool);
  return fields;
}
