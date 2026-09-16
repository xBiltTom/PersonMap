/**
 * Disposición SpiderFoot radial por grupos de correlación.
 *
 *  - Centro (0, 0): Nodo de Identidad Objetivo.
 *  - Ramas radiales: Grupos de cuentas correlacionadas entre sí (mismo correo,
 *    enlaces cruzados, mismo alias, avatar, etc.).
 *  - En cada grupo: Los nodos se disponen en una constelación compacta sin solaparse,
 *    con enlaces visibles que muestran cómo se relacionan.
 *  - Hallazgos aislados: Se agrupan por tipo de entidad en sectores organizados,
 *    evitando generar cientos de sectores individuales que ralentizaban el lienzo.
 */

import { getEntityTypeMeta } from "@/lib/entityTypes";

export interface LayoutItem {
  id: string;
  label?: string;
  entityType?: string;
  platform?: string | null;
  groupId?: string | null;
  metadata?: Record<string, unknown>;
}

export interface LayoutLink {
  source: string;
  target: string;
  relationType?: string;
  supportsGroup?: boolean;
}

export interface LayoutCluster {
  id: string;
  label: string;
  hint: string;
  isCorrelated: boolean;
  color: string;
  size: number;
  bounds: {
    x: number;
    y: number;
    width: number;
    height: number;
  };
}

export interface MapLayout {
  positions: Map<string, { x: number; y: number }>;
  clusters: LayoutCluster[];
  bounds: { x: number; y: number; width: number; height: number };
}

const CARD_W = 200;
const CARD_H = 82;
const GAP_X = 24;
const GAP_Y = 20;
const DX = CARD_W + GAP_X; // 224
const DY = CARD_H + GAP_Y; // 102

const ROOT_W = 220;
const ROOT_H = 110;

class UnionFind {
  private parents = new Map<string, string>();

  add(id: string) {
    if (!this.parents.has(id)) this.parents.set(id, id);
  }

  find(id: string): string {
    const parent = this.parents.get(id);
    if (!parent || parent === id) return id;
    const root = this.find(parent);
    this.parents.set(id, root);
    return root;
  }

  join(a: string, b: string) {
    const rootA = this.find(a);
    const rootB = this.find(b);
    if (rootA !== rootB) this.parents.set(rootB, rootA);
  }
}

interface RawGroup {
  id: string;
  members: LayoutItem[];
  label: string;
  hint: string;
  isCorrelated: boolean;
  color: string;
}

function determineCorrelationLabel(
  members: LayoutItem[],
  links: LayoutLink[]
): { label: string; hint: string; color: string } {
  const memberSet = new Set(members.map((m) => m.id));
  const innerLinks = links.filter(
    (l) => memberSet.has(l.source) && memberSet.has(l.target)
  );

  const relations = new Set(innerLinks.map((l) => l.relationType));

  if (relations.has("shares_declared_email")) {
    return {
      label: "Mismo correo declarado",
      hint: "Cuentas vinculadas por el correo del objetivo",
      color: "#10b981", // Emerald
    };
  }
  if (relations.has("explicit_profile_link")) {
    return {
      label: "Perfiles vinculados",
      hint: "Cuentas que enlazan directamente entre sí",
      color: "#a855f7", // Purple
    };
  }
  if (relations.has("same_username")) {
    return {
      label: "Mismo alias de usuario",
      hint: "Coincidencia exacta de nombre de usuario",
      color: "#f59e0b", // Amber
    };
  }
  if (relations.has("similar_avatar")) {
    return {
      label: "Avatar coincidente",
      hint: "Foto de perfil idéntica o muy similar",
      color: "#f97316", // Orange
    };
  }

  // Si tiene group_id explícito
  if (members.some((m) => m.groupId)) {
    return {
      label: "Grupo de correlación",
      hint: "Evidencia compartida de identidad",
      color: "#38bdf8", // Sky
    };
  }

  return {
    label: "Cuentas correlacionadas",
    hint: `${members.length} hallazgos interconectados`,
    color: "#a855f7",
  };
}

export function layoutDigitalMap(
  rootId: string,
  items: LayoutItem[],
  links: LayoutLink[]
): MapLayout {
  const positions = new Map<string, { x: number; y: number }>();
  if (rootId) positions.set(rootId, { x: 0, y: 0 });

  if (items.length === 0) {
    return {
      positions,
      clusters: [],
      bounds: { x: -ROOT_W / 2, y: -ROOT_H / 2, width: ROOT_W, height: ROOT_H },
    };
  }

  const visible = new Set(items.map((i) => i.id));
  const sets = new UnionFind();
  const byGroupId = new Map<string, string>();

  for (const item of items) {
    sets.add(item.id);
    if (item.groupId) {
      const existing = byGroupId.get(item.groupId);
      if (existing) sets.join(existing, item.id);
      else byGroupId.set(item.groupId, item.id);
    }
  }

  // Unir nodos mediante aristas de relación entre entidades (excluyendo discovered_from)
  for (const link of links) {
    if (!visible.has(link.source) || !visible.has(link.target)) continue;
    if (link.relationType === "discovered_from") continue;
    if (link.supportsGroup !== false) {
      sets.join(link.source, link.target);
    }
  }

  // Agrupar miembros por componente conexa
  const componentMap = new Map<string, LayoutItem[]>();
  for (const item of items) {
    const root = sets.find(item.id);
    if (!componentMap.has(root)) componentMap.set(root, []);
    componentMap.get(root)!.push(item);
  }

  const correlatedGroups: RawGroup[] = [];
  const isolatedItems: LayoutItem[] = [];

  for (const [rootKey, members] of componentMap.entries()) {
    const hasExplicitGroup = members.some((m) => m.groupId);
    if (members.length >= 2 || hasExplicitGroup) {
      const { label, hint, color } = determineCorrelationLabel(members, links);
      correlatedGroups.push({
        id: `corr-${rootKey}`,
        members,
        label,
        hint,
        isCorrelated: true,
        color,
      });
    } else {
      isolatedItems.push(...members);
    }
  }

  // Ordenar grupos correlacionados por tamaño descendente
  correlatedGroups.sort((a, b) => b.members.length - a.members.length);

  // Agrupar los hallazgos aislados por su tipo de entidad para no saturar el mapa
  const categoryMap = new Map<string, LayoutItem[]>();
  for (const item of isolatedItems) {
    const cat = item.entityType || "other";
    if (!categoryMap.has(cat)) categoryMap.set(cat, []);
    categoryMap.get(cat)!.push(item);
  }

  const categoryGroups: RawGroup[] = [];
  for (const [catKey, members] of categoryMap.entries()) {
    const meta = getEntityTypeMeta(catKey);
    categoryGroups.push({
      id: `cat-${catKey}`,
      members,
      label: meta.label,
      hint: `${members.length} hallazgo(s) sin enlace directo`,
      isCorrelated: false,
      color: "#64748b",
    });
  }

  // Ordenar categorías por tamaño descendente
  categoryGroups.sort((a, b) => b.members.length - a.members.length);

  // Lista consolidada de grupos a posicionar
  // Si hay grupos correlacionados, los distribuimos radialmente con prioridad
  const allGroups = [...correlatedGroups, ...categoryGroups];
  const numGroups = allGroups.length;

  const layoutClusters: LayoutCluster[] = [];

  // Distribución radial alrededor de la Identidad Objetivo
  // Ángulo de inicio: -Math.PI / 2 (arriba), girando horario
  const angleStep = (2 * Math.PI) / Math.max(1, numGroups);

  allGroups.forEach((group, index) => {
    const angle = -Math.PI / 2 + index * angleStep;
    const K = group.members.length;

    // Determinar columnas y filas para acomodar los nodos dentro del grupo
    let cols = 1;
    if (K === 2) cols = 2;
    else if (K <= 4) cols = 2;
    else if (K <= 9) cols = 3;
    else if (K <= 16) cols = 4;
    else cols = Math.min(5, Math.ceil(Math.sqrt(K * 1.5)));

    const rows = Math.ceil(K / cols);

    const clusterWidth = cols * DX - GAP_X;
    const clusterHeight = rows * DY - GAP_Y;

    // Distancia al centro calculada para evitar colisiones con el nodo raíz central
    const halfDiag = Math.sqrt((clusterWidth / 2) ** 2 + (clusterHeight / 2) ** 2);
    // Los grupos correlacionados están más cercanos al centro; las categorías aisladas un poco más alejadas si hay grupos
    const baseDistance = group.isCorrelated ? 340 : correlatedGroups.length > 0 ? 460 : 360;
    const centerRadius = Math.max(baseDistance, halfDiag + 150);

    const cx = centerRadius * Math.cos(angle);
    const cy = centerRadius * Math.sin(angle);

    // Posicionar cada nodo miembro en una cuadrícula compacta centrada en (cx, cy)
    const startX = cx - clusterWidth / 2 + CARD_W / 2;
    const startY = cy - clusterHeight / 2 + CARD_H / 2;

    group.members.forEach((member, mIndex) => {
      const col = mIndex % cols;
      const row = Math.floor(mIndex / cols);
      const x = startX + col * DX;
      const y = startY + row * DY;
      positions.set(member.id, { x, y });
    });

    const padding = 16;
    const headerHeight = 32;

    layoutClusters.push({
      id: group.id,
      label: group.label,
      hint: group.hint,
      isCorrelated: group.isCorrelated,
      color: group.color,
      size: K,
      bounds: {
        x: cx - clusterWidth / 2 - padding,
        y: cy - clusterHeight / 2 - headerHeight - padding,
        width: clusterWidth + padding * 2,
        height: clusterHeight + headerHeight + padding * 2,
      },
    });
  });

  // Calcular los límites globales del grafo para fitView / encuadre automático
  const xs: number[] = [-ROOT_W / 2 - 40, ROOT_W / 2 + 40];
  const ys: number[] = [-ROOT_H / 2 - 40, ROOT_H / 2 + 40];

  for (const cluster of layoutClusters) {
    xs.push(cluster.bounds.x, cluster.bounds.x + cluster.bounds.width);
    ys.push(cluster.bounds.y, cluster.bounds.y + cluster.bounds.height);
  }

  const minX = Math.min(...xs);
  const maxX = Math.max(...xs);
  const minY = Math.min(...ys);
  const maxY = Math.max(...ys);

  return {
    positions,
    clusters: layoutClusters,
    bounds: {
      x: minX,
      y: minY,
      width: maxX - minX,
      height: maxY - minY,
    },
  };
}
