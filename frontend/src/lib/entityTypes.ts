/**
 * Fuente única de verdad para la representación visual de cada `entity_type`.
 *
 * Antes, la lista de categorías estaba duplicada y divergente entre
 * `FindingsTable` (8 entradas) y `DigitalMapGraph` (6). Esa duplicación fue la
 * causa de que `image_match`, `google_account` y `academic_profile` —tipos que
 * el backend ya emitía— no se pudieran filtrar en ninguna de las dos vistas y se
 * dibujaran con el icono genérico gris, indistinguibles entre sí.
 *
 * Al añadir un `entity_type` nuevo en el backend basta con registrarlo aquí:
 * la tabla de hallazgos, el mapa digital y la línea de tiempo lo recogen solos.
 */

import {
  AlertTriangle,
  AtSign,
  BookOpen,
  Briefcase,
  Camera,
  Code2,
  Globe,
  GraduationCap,
  IdCard,
  KeyRound,
  Mail,
  MessageCircle,
  Music,
  Phone,
  Search,
  Server,
  Share2,
  ShoppingBag,
  Skull,
  EyeOff,
  User,
  Video,
  type LucideIcon,
} from "lucide-react";

export interface EntityTypeMeta {
  /** Etiqueta para los filtros y la leyenda. */
  label: string;
  /** Explicación breve; se usa como `title`. */
  description: string;
  Icon: LucideIcon;
  /** Clase de color del icono y del acento. */
  accent: string;
  /** Clases del nodo en el mapa digital (borde + fondo). */
  node: string;
  /** Clases del badge en la tabla de hallazgos. */
  badge: string;
}

const FALLBACK: EntityTypeMeta = {
  label: "Otro hallazgo",
  description: "Hallazgo sin categoría específica.",
  Icon: Globe,
  accent: "text-slate-400",
  node: "border-[#2c3d59] bg-[#111722]",
  badge: "bg-slate-800/60 text-slate-300 border-slate-700",
};

/**
 * Registro de tipos. El orden define el de los filtros.
 * `query` es el nodo raíz de la consulta y no aparece como filtro.
 */
export const ENTITY_TYPES: Record<string, EntityTypeMeta> = {
  social_account: {
    label: "Redes y Cuentas",
    description: "Perfil o cuenta activa detectada en una plataforma.",
    Icon: Share2,
    accent: "text-sky-400",
    node: "border-[#2c3d59] bg-[#111722] hover:border-sky-500/50",
    badge: "bg-sky-500/10 text-sky-300 border-sky-500/25",
  },
  email: {
    label: "Correos",
    description: "Dirección de correo observada en una fuente.",
    Icon: Mail,
    accent: "text-amber-400",
    node: "border-amber-500/40 bg-[#1c1710]",
    badge: "bg-amber-500/10 text-amber-300 border-amber-500/25",
  },
  breach: {
    label: "Filtraciones",
    description: "Aparición del identificador en una brecha de datos pública.",
    Icon: AlertTriangle,
    accent: "text-rose-400",
    node: "border-rose-500/70 bg-[#210d14] ring-1 ring-rose-500/20",
    badge: "bg-rose-500/10 text-rose-300 border-rose-500/30",
  },
  sensitive_account: {
    label: "Contenido Sensible",
    description:
      "Cuenta observada en una plataforma de contenido adulto. Revise la fuente y sus conexiones antes de extraer conclusiones.",
    Icon: EyeOff,
    accent: "text-fuchsia-400",
    node: "border-fuchsia-500/70 bg-[#1e0d1e] ring-1 ring-fuchsia-500/25",
    badge: "bg-fuchsia-500/10 text-fuchsia-300 border-fuchsia-500/35",
  },
  infostealer: {
    label: "Infostealer",
    description:
      "Credenciales robadas por malware desde un equipo infectado. Más grave que una filtración: implica una máquina comprometida.",
    Icon: Skull,
    accent: "text-red-400",
    node: "border-red-500 bg-[#2a0a0a] ring-2 ring-red-500/30",
    badge: "bg-red-500/15 text-red-300 border-red-500/40",
  },
  phone: {
    label: "Telefonía",
    description: "Número telefónico y su huella asociada.",
    Icon: Phone,
    accent: "text-violet-400",
    node: "border-violet-500/50 bg-[#161224]",
    badge: "bg-violet-500/10 text-violet-300 border-violet-500/25",
  },
  academic: {
    label: "Producción Académica",
    description: "Publicación, artículo o coautoría detectada.",
    Icon: GraduationCap,
    accent: "text-emerald-400",
    node: "border-emerald-500/40 bg-[#0f1b1a]",
    badge: "bg-emerald-500/10 text-emerald-300 border-emerald-500/25",
  },
  academic_profile: {
    label: "Perfil Académico",
    description: "Perfil de autor en un repositorio académico (Scholar, OpenAlex, ORCID).",
    Icon: BookOpen,
    accent: "text-teal-300",
    node: "border-teal-500/45 bg-[#0d1a1c]",
    badge: "bg-teal-500/10 text-teal-300 border-teal-500/25",
  },
  google_account: {
    label: "Cuenta Google",
    description:
      "Cuenta del ecosistema Google observada. Puede contener enlaces públicos hacia otros servicios.",
    Icon: KeyRound,
    accent: "text-orange-300",
    node: "border-orange-500/50 bg-[#201509]",
    badge: "bg-orange-500/10 text-orange-300 border-orange-500/25",
  },
  image_match: {
    label: "Coincidencia Visual",
    description:
      "Otra página de la web abierta que reutiliza una imagen de perfil. Es una conexión visual a revisar.",
    Icon: Camera,
    accent: "text-fuchsia-400",
    node: "border-fuchsia-500/50 bg-[#1c0f21]",
    badge: "bg-fuchsia-500/10 text-fuchsia-300 border-fuchsia-500/25",
  },
  search_mention: {
    label: "Menciones y Dorks",
    description: "Mención pública encontrada mediante búsqueda avanzada.",
    Icon: Search,
    accent: "text-cyan-300",
    node: "border-cyan-500/35 bg-[#0d1a1f]",
    badge: "bg-cyan-500/10 text-cyan-300 border-cyan-500/25",
  },
  document: {
    label: "Documentos",
    description: "Documento de identidad o registro oficial público.",
    Icon: IdCard,
    accent: "text-indigo-300",
    node: "border-indigo-500/45 bg-[#131426]",
    badge: "bg-indigo-500/10 text-indigo-300 border-indigo-500/25",
  },
  domain: {
    label: "Infraestructura",
    description: "Dominio o subdominio observado durante la consulta.",
    Icon: Server,
    accent: "text-lime-300",
    node: "border-lime-500/40 bg-[#141a0d]",
    badge: "bg-lime-500/10 text-lime-300 border-lime-500/25",
  },
  person: {
    label: "Identidad Objetivo",
    description: "Nodo raíz: la persona investigada.",
    Icon: User,
    accent: "text-sky-300",
    node: "border-sky-400 bg-[#152033]",
    badge: "bg-sky-500/15 text-sky-200 border-sky-400/40",
  },
};

export function getEntityTypeMeta(entityType?: string | null): EntityTypeMeta {
  if (!entityType) return FALLBACK;
  return ENTITY_TYPES[entityType] ?? FALLBACK;
}

// ---------------------------------------------------------------------
// Iconos por plataforma
// ---------------------------------------------------------------------

/**
 * lucide-react 1.x ya no incluye iconos de marca, así que se usan iconos
 * genéricos que transmiten la naturaleza del servicio. El orden importa: se
 * devuelve la primera clave contenida en el nombre de la plataforma.
 */
const PLATFORM_ICONS: Array<[string, LucideIcon]> = [
  ["github", Code2],
  ["gitlab", Code2],
  ["bitbucket", Code2],
  ["stackoverflow", Code2],
  ["dockerhub", Server],
  ["linkedin", Briefcase],
  ["instagram", Camera],
  ["pinterest", Camera],
  ["flickr", Camera],
  ["twitter", AtSign],
  ["x_twitter", AtSign],
  ["mastodon", AtSign],
  ["telegram", MessageCircle],
  ["discord", MessageCircle],
  ["reddit", MessageCircle],
  ["quora", MessageCircle],
  ["whatsapp", MessageCircle],
  ["youtube", Video],
  ["twitch", Video],
  ["vimeo", Video],
  ["tiktok", Video],
  ["spotify", Music],
  ["soundcloud", Music],
  ["scholar", BookOpen],
  ["openalex", GraduationCap],
  ["orcid", GraduationCap],
  ["wikipedia", BookOpen],
  ["keybase", KeyRound],
  ["gravatar", User],
  ["google", KeyRound],
  ["amazon", ShoppingBag],
  ["etsy", ShoppingBag],
  ["steam", Globe],
  ["telephony", Phone],
  ["data_leak", AlertTriangle],
];

/**
 * Icono de un hallazgo.
 *
 * Los tipos con semántica propia (brecha, infostealer, coincidencia visual...)
 * mandan sobre la plataforma: en un hallazgo de infostealer alojado en GitHub
 * interesa mucho más comunicar el riesgo que el servicio.
 */
const TYPE_WINS_OVER_PLATFORM = new Set([
  "breach",
  "infostealer",
  // El icono del sitio da igual aquí: lo que hay que comunicar es la categoría.
  "sensitive_account",
  "image_match",
  "document",
  "phone",
]);

export function getFindingIcon(
  platform?: string | null,
  entityType?: string | null
): LucideIcon {
  if (entityType && TYPE_WINS_OVER_PLATFORM.has(entityType)) {
    return getEntityTypeMeta(entityType).Icon;
  }

  const p = (platform || "").toLowerCase();
  if (p) {
    for (const [needle, Icon] of PLATFORM_ICONS) {
      if (p.includes(needle)) return Icon;
    }
  }

  if (entityType && ENTITY_TYPES[entityType]) {
    return ENTITY_TYPES[entityType].Icon;
  }
  return FALLBACK.Icon;
}

// ---------------------------------------------------------------------
// Filtros
// ---------------------------------------------------------------------

export interface EntityFilter {
  id: string;
  label: string;
  count: number;
  description: string;
}

/**
 * Construye los filtros a partir de los tipos realmente presentes.
 *
 * Se prefiere esto a una lista fija por dos razones: no se muestran categorías
 * vacías que el usuario pulsa para no encontrar nada, y cualquier tipo nuevo del
 * backend aparece automáticamente aunque no esté registrado arriba (con el
 * aspecto genérico, pero filtrable).
 */
export function buildEntityFilters(
  entityTypes: Array<string | null | undefined>
): EntityFilter[] {
  const counts = new Map<string, number>();
  for (const t of entityTypes) {
    if (!t || t === "person") continue;
    counts.set(t, (counts.get(t) ?? 0) + 1);
  }

  const known = Object.keys(ENTITY_TYPES).filter((t) => t !== "person");
  const present = [...counts.keys()];
  // Los tipos conocidos conservan el orden del registro; los desconocidos van al final.
  const ordered = [
    ...known.filter((t) => counts.has(t)),
    ...present.filter((t) => !known.includes(t)).sort(),
  ];

  const total = [...counts.values()].reduce((a, b) => a + b, 0);

  return [
    {
      id: "all",
      label: "Todas las Capas",
      count: total,
      description: "Sin filtrar: todos los hallazgos.",
    },
    ...ordered.map((id) => {
      const meta = getEntityTypeMeta(id);
      return {
        id,
        label: meta === FALLBACK ? id : meta.label,
        count: counts.get(id) ?? 0,
        description: meta.description,
      };
    }),
  ];
}
