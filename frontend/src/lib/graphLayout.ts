/**
 * Disposición del mapa digital: cada eje de la posición significa algo.
 *
 *  - **El ángulo dice a qué grupo pertenece.** Los hallazgos que comparten la
 *    misma evidencia hacia la persona (misma foto de perfil, mismo correo,
 *    mismo alias...) ocupan un mismo sector del mapa.
 *  - **La distancia dice cuánto se le atribuye.** Garantía global, no por
 *    sector: cualquier nodo de una banda de certeza está más lejos del centro
 *    que TODOS los nodos de la banda anterior, estén en el grupo que estén.
 *
 * Por qué los grupos no salen solo de las aristas `relationships`: medido sobre
 * las investigaciones guardadas, el backend no crea `same_username` entre
 * resultados de una misma enumeración (serían tautológicas), así que la mayoría
 * de hallazgos no tiene ninguna arista. Y uniendo de forma transitiva las que
 * sí hay, al mostrar todas las bandas los 316 hallazgos de una investigación
 * real colapsaban en un único grupo de 294: el círculo de antes con otro nombre.
 *
 * Por eso manda la evidencia, y las aristas solo sirven para que un hallazgo
 * sin evidencia propia se una al grupo del hallazgo al que está enlazado.
 */

import type { IdentityBreakdown } from "@/lib/types";
import { getEntityTypeMeta } from "@/lib/entityTypes";

export interface LayoutItem {
  id: string;
  /** Posición en `CERTAINTY_BANDS`: 0 es la más segura. */
  band: number;
  /** Atribución, para ordenar dentro de la banda. */
  score: number;
  entityType?: string;
  breakdown?: IdentityBreakdown;
}

export interface LayoutLink {
  source: string;
  target: string;
}

export type GroupKind = "evidence" | "linked" | "type";

export interface LayoutGroup {
  id: string;
  kind: GroupKind;
  label: string;
  hint: string;
  size: number;
  startAngle: number;
  endAngle: number;
  innerRadius: number;
  outerRadius: number;
}

/** Tramo de distancias (entre centros de nodo) que ocupa una banda. */
export interface LayoutBand {
  band: number;
  innerRadius: number;
  outerRadius: number;
}

export interface MapLayout {
  /** Centro de cada nodo, con la raíz en (0, 0): va con `nodeOrigin={[0.5, 0.5]}`. */
  positions: Map<string, { x: number; y: number }>;
  groups: LayoutGroup[];
  bands: LayoutBand[];
  /**
   * Rectángulo que ocupan nodos y sectores, para `fitBounds`. Los rótulos no
   * cuentan: se dibujan a tamaño fijo en pantalla y no escalan con el mapa.
   */
  bounds: { x: number; y: number; width: number; height: number };
}

/**
 * Nombre de grupo para cada señal del modelo, con las mismas claves que
 * `SIGNAL_PHRASES` de `PlainExplanation`.
 */
const EVIDENCE_GROUPS: Record<string, { label: string; hint: string }> = {
  cryptographic_proof: {
    label: "Firma criptográfica",
    hint: "identidad demostrada criptográficamente",
  },
  email_match: { label: "Mismo correo", hint: "declaran el correo de la persona" },
  phone_match: { label: "Mismo teléfono", hint: "muestran su teléfono" },
  avatar_match: {
    label: "Misma foto de perfil",
    hint: "usan la foto de otra cuenta suya",
  },
  cross_link: { label: "Enlazan a sus perfiles", hint: "enlazan a cuentas ya atribuidas" },
  username_match: { label: "Mismo alias", hint: "declaran el alias de la persona" },
  alias_specificity: {
    label: "Alias poco común",
    hint: "solo coincide el alias, pero casi nadie más lo usa",
  },
  name_match: { label: "Mismo nombre", hint: "muestran el nombre de la persona" },
  university_match: { label: "Misma institución", hint: "mencionan su universidad" },
  semantic_bio_match: { label: "Biografía parecida", hint: "describen el mismo perfil" },
};

const MIN_EVIDENCE_BITS = 1;

/**
 * La señal que más pesa A FAVOR en la puntuación del hallazgo.
 *
 * Solo cuentan las evaluables, con acuerdo (γ > 0) y al menos 1 bit a favor:
 * una señal que no encaja no vincula el hallazgo con nadie, y un empujón
 * menor tampoco. Sin ese mínimo, los cientos de cuentas de "torvalds" (un alias
 * poco específico, +0.17 bits) formaban un grupo de "alias poco común".
 */
function dominantEvidence(breakdown?: IdentityBreakdown): string | null {
  if (!breakdown) return null;

  let best: string | null = null;
  let bestWeight = MIN_EVIDENCE_BITS;
  for (const signal of Object.keys(EVIDENCE_GROUPS)) {
    const gamma = breakdown[signal];
    const weight = breakdown[`${signal}_weight`];
    if (breakdown[`${signal}_applicable`] === false) continue;
    if (typeof gamma !== "number" || gamma <= 0) continue;
    if (typeof weight !== "number" || weight < bestWeight) continue;
    if (best !== null && weight === bestWeight) continue;
    best = signal;
    bestWeight = weight;
  }
  return best;
}

interface Group {
  id: string;
  kind: GroupKind;
  label: string;
  hint: string;
  /** Ordenados de más a menos atribución. */
  members: LayoutItem[];
}

const KIND_ORDER: Record<GroupKind, number> = { evidence: 0, linked: 1, type: 2 };

function buildGroups(items: LayoutItem[], links: LayoutLink[]): Group[] {
  const visible = new Set(items.map((i) => i.id));
  const neighbours = new Map<string, string[]>();
  for (const { source, target } of links) {
    if (!visible.has(source) || !visible.has(target)) continue;
    if (!neighbours.has(source)) neighbours.set(source, []);
    if (!neighbours.has(target)) neighbours.set(target, []);
    neighbours.get(source)!.push(target);
    neighbours.get(target)!.push(source);
  }

  // 1. Cada hallazgo con evidencia va al grupo de su evidencia dominante.
  const groupOf = new Map<string, string>();
  const withEvidence = [...items].sort((a, b) => b.score - a.score);
  const queue: string[] = [];
  for (const item of withEvidence) {
    const evidence = dominantEvidence(item.breakdown);
    if (!evidence) continue;
    groupOf.set(item.id, `evidence:${evidence}`);
    queue.push(item.id);
  }

  // 2. Los que no tienen evidencia propia heredan el grupo del hallazgo al que
  //    están enlazados. La cola arranca por los más seguros: si uno está
  //    enlazado con dos grupos, se lo queda el del vecino más fiable.
  for (let head = 0; head < queue.length; head++) {
    const id = queue[head];
    for (const next of neighbours.get(id) ?? []) {
      if (groupOf.has(next)) continue;
      groupOf.set(next, groupOf.get(id)!);
      queue.push(next);
    }
  }

  // 3. El resto no tiene nada en común con la persona salvo el tipo.
  for (const item of items) {
    if (groupOf.has(item.id)) continue;
    groupOf.set(
      item.id,
      neighbours.has(item.id) ? "linked" : `type:${item.entityType ?? "otro"}`
    );
  }

  const groups = new Map<string, Group>();
  for (const item of items) {
    const id = groupOf.get(item.id)!;
    if (!groups.has(id)) groups.set(id, describeGroup(id));
    groups.get(id)!.members.push(item);
  }

  const best = (g: Group) => Math.min(...g.members.map((m) => m.band));
  return [...groups.values()]
    .map((g) => ({ ...g, members: g.members.sort((a, b) => b.score - a.score) }))
    .sort(
      (a, b) =>
        KIND_ORDER[a.kind] - KIND_ORDER[b.kind] ||
        best(a) - best(b) ||
        b.members.length - a.members.length ||
        a.id.localeCompare(b.id)
    );
}

function describeGroup(id: string): Group {
  if (id.startsWith("evidence:")) {
    const { label, hint } = EVIDENCE_GROUPS[id.slice("evidence:".length)];
    return { id, kind: "evidence", label, hint, members: [] };
  }
  if (id === "linked") {
    return {
      id,
      kind: "linked",
      label: "Enlazados entre sí",
      hint: "sin evidencia directa hacia la persona",
      members: [],
    };
  }
  const entityType = id.slice("type:".length);
  const meta = getEntityTypeMeta(entityType);
  return {
    id,
    kind: "type",
    label: meta.label === "Otro hallazgo" ? entityType : meta.label,
    hint: "sin evidencia en común",
    members: [],
  };
}

// ---------------------------------------------------------------------
// Geometría
// ---------------------------------------------------------------------

/** Caja de `CustomEntityNode` (`max-w-[220px]`, hasta cuatro líneas). */
const NODE_W = 220;
const NODE_H = 92;
const ROOT_W = 240;
const ROOT_H = 140;
/** Separación mínima entre cajas. */
const GAP = 20;
/** Distancia mínima de la primera banda al centro. */
const MIN_FIRST_RADIUS = 200;
/** Salto mínimo de distancia entre la última fila de una banda y la siguiente. */
const BAND_STEP = 130;
/** Avance radial cuando una fila del sector ya no admite más nodos. */
const ROW_STEP = 34;
/** Resolución del barrido angular, en píxeles de arco. */
const SCAN_PX = 10;
const WEDGE_GAP = 0.1;
/** Medio ancho del hueco superior donde se rotulan las bandas. */
const RULER_HALF_WIDTH = 80;

const TWO_PI = 2 * Math.PI;

/** Rejilla de ocupación: comprobar solapes sin comparar cada par de nodos. */
class Occupancy {
  private static readonly CELL = 160;
  private cells = new Map<string, Array<[number, number, number, number]>>();

  private *keys(x: number, y: number, hw: number, hh: number) {
    const c = Occupancy.CELL;
    for (let i = Math.floor((x - hw) / c); i <= Math.floor((x + hw) / c); i++) {
      for (let j = Math.floor((y - hh) / c); j <= Math.floor((y + hh) / c); j++) {
        yield `${i},${j}`;
      }
    }
  }

  add(x: number, y: number, hw: number, hh: number) {
    for (const key of this.keys(x, y, hw, hh)) {
      if (!this.cells.has(key)) this.cells.set(key, []);
      this.cells.get(key)!.push([x, y, hw, hh]);
    }
  }

  collides(x: number, y: number, hw: number, hh: number): boolean {
    for (const key of this.keys(x, y, hw + GAP, hh + GAP)) {
      for (const [bx, by, bw, bh] of this.cells.get(key) ?? []) {
        if (Math.abs(x - bx) < hw + bw + GAP && Math.abs(y - by) < hh + bh + GAP) {
          return true;
        }
      }
    }
    return false;
  }
}

/** True si la caja entera cae dentro del sector, no solo su centro. */
function boxInsideWedge(x: number, y: number, start: number, span: number): boolean {
  for (const dx of [-NODE_W / 2, NODE_W / 2]) {
    for (const dy of [-NODE_H / 2, NODE_H / 2]) {
      const rel = (((Math.atan2(y + dy, x + dx) - start) % TWO_PI) + TWO_PI) % TWO_PI;
      if (rel > span) return false;
    }
  }
  return true;
}

/**
 * Primer hueco libre a distancia `r`, barriendo desde el centro del sector
 * hacia los lados para que cada grupo crezca simétrico y no apilado a un lado.
 */
function findSpot(
  r: number,
  start: number,
  span: number,
  occupancy: Occupancy
): { x: number; y: number } | null {
  const mid = start + span / 2;
  const step = SCAN_PX / r;
  for (let k = 0; k * step <= span / 2; k++) {
    for (const angle of k === 0 ? [mid] : [mid + k * step, mid - k * step]) {
      const x = r * Math.cos(angle);
      const y = r * Math.sin(angle);
      if (!boxInsideWedge(x, y, start, span)) continue;
      if (occupancy.collides(x, y, NODE_W / 2, NODE_H / 2)) continue;
      return { x, y };
    }
  }
  return null;
}

export function layoutDigitalMap(
  rootId: string,
  items: LayoutItem[],
  links: LayoutLink[]
): MapLayout {
  const positions = new Map([[rootId, { x: 0, y: 0 }]]);
  if (items.length === 0) {
    const bounds = { x: -ROOT_W / 2, y: -ROOT_H / 2, width: ROOT_W, height: ROOT_H };
    return { positions, groups: [], bands: [], bounds };
  }

  const groups = buildGroups(items, links);
  const count = groups.length;

  const presentBands = [...new Set(items.map((i) => i.band))].sort((a, b) => a - b);
  const perBand = groups.map((g) => {
    const counts = new Map<number, number>();
    for (const m of g.members) counts.set(m.band, (counts.get(m.band) ?? 0) + 1);
    return counts;
  });

  // Radio de la primera banda. Cada sector necesita un ángulo mínimo para que
  // quepa un nodo en su fila más interior, y esos mínimos no pueden comerse
  // más del 60 % de la circunferencia: el resto es lo que se reparte según el
  // tamaño de cada grupo. Si no llega, el mapa entero se aleja del centro. El
  // hueco de la regla y los radios estimados dependen a su vez de este radio,
  // de ahí las iteraciones hasta que se estabiliza.
  let firstRadius = MIN_FIRST_RADIUS;
  let ruler = 0;
  let gap = 0;
  let available = 0;
  // Cota inferior de la distancia a la que empezará cada banda.
  const estimatedRadius = (band: number) =>
    firstRadius + presentBands.indexOf(band) * BAND_STEP;
  const minSpanOf = (gi: number) =>
    ((NODE_W + GAP) * 1.2) / estimatedRadius(Math.min(...perBand[gi].keys()));
  for (let i = 0; i < 8; i++) {
    ruler = 2 * Math.asin(Math.min(1, RULER_HALF_WIDTH / firstRadius));
    gap = Math.min(WEDGE_GAP, ((TWO_PI - ruler) * 0.2) / count);
    available = TWO_PI - ruler - gap * (count - 1);
    const needed = groups.reduce((sum, _, gi) => sum + minSpanOf(gi), 0);
    if (needed <= available * 0.6) break;
    firstRadius *= needed / (available * 0.6);
  }

  // El ángulo que sobra se reparte según lo que pediría cada grupo para meter
  // cada banda en una sola fila. Una banda exterior tiene más circunferencia,
  // así que sus nodos piden menos ángulo que los de una interior.
  const minSpans = groups.map((_, gi) => minSpanOf(gi));
  const demand = perBand.map((counts) =>
    Math.max(...[...counts].map(([band, n]) => n / estimatedRadius(band)))
  );
  const totalDemand = demand.reduce((a, b) => a + b, 0);
  const spare = Math.max(0, available - minSpans.reduce((a, b) => a + b, 0));

  let angle = -Math.PI / 2 + ruler / 2;
  const wedges = groups.map((_, i) => {
    const span = minSpans[i] + (spare * demand[i]) / totalDemand;
    const wedge = { start: angle, span };
    angle += span + gap;
    return wedge;
  });

  const occupancy = new Occupancy();
  occupancy.add(0, 0, ROOT_W / 2, ROOT_H / 2);

  const radii = groups.map(() => ({ inner: Infinity, outer: 0 }));
  const bands: LayoutBand[] = [];
  let bandStart = firstRadius;

  for (const band of presentBands) {
    let nearest = Infinity;
    let farthest = 0;

    groups.forEach((group, gi) => {
      const { start, span } = wedges[gi];
      let r = bandStart;
      for (const member of group.members) {
        if (member.band !== band) continue;

        let spot = findSpot(r, start, span, occupancy);
        while (!spot) {
          r += ROW_STEP;
          spot = findSpot(r, start, span, occupancy);
        }

        occupancy.add(spot.x, spot.y, NODE_W / 2, NODE_H / 2);
        positions.set(member.id, spot);
        nearest = Math.min(nearest, r);
        farthest = Math.max(farthest, r);
        radii[gi].inner = Math.min(radii[gi].inner, r);
        radii[gi].outer = Math.max(radii[gi].outer, r);
      }
    });

    bands.push({ band, innerRadius: nearest, outerRadius: farthest });
    bandStart = farthest + BAND_STEP;
  }

  const padding = NODE_W / 2 - 30;
  const layoutGroups = groups.map((g, i) => ({
    id: g.id,
    kind: g.kind,
    label: g.label,
    hint: g.hint,
    size: g.members.length,
    startAngle: wedges[i].start,
    endAngle: wedges[i].start + wedges[i].span,
    innerRadius: Math.max(ROOT_H / 2 + 10, radii[i].inner - padding),
    outerRadius: radii[i].outer + padding,
  }));

  // Límites calculados aquí y no medidos por React Flow: su `fitView` ignora
  // los nodos que aún no tienen tamaño, y justo después de activar una banda
  // son la mitad del mapa.
  const xs: number[] = [-ROOT_W / 2, ROOT_W / 2];
  const ys: number[] = [-ROOT_H / 2, ROOT_H / 2];
  for (const { x, y } of positions.values()) {
    xs.push(x - NODE_W / 2, x + NODE_W / 2);
    ys.push(y - NODE_H / 2, y + NODE_H / 2);
  }
  // La regla de certeza vive en el hueco superior, donde no llega ningún sector.
  ys.push(-bands[bands.length - 1].outerRadius);
  for (const g of layoutGroups) {
    for (let k = 0; k <= 8; k++) {
      const a = g.startAngle + ((g.endAngle - g.startAngle) * k) / 8;
      xs.push(g.outerRadius * Math.cos(a));
      ys.push(g.outerRadius * Math.sin(a));
    }
  }
  const minX = Math.min(...xs);
  const minY = Math.min(...ys);

  return {
    positions,
    bands,
    groups: layoutGroups,
    bounds: {
      x: minX,
      y: minY,
      width: Math.max(...xs) - minX,
      height: Math.max(...ys) - minY,
    },
  };
}
