/**
 * Deterministic force layout for the evidence map.
 *
 * Position is driven only by observed relationships and persisted correlation
 * groups. Entity category and platform affect appearance, never topology.
 */

export interface LayoutItem {
  id: string;
  groupId?: string | null;
  entityType?: string | null;
  platform?: string | null;
  label?: string | null;
  value?: string | null;
}

export interface LayoutLink {
  source: string;
  target: string;
  relationType?: string;
}

export interface MapLayout {
  positions: Map<string, { x: number; y: number }>;
  bounds: { x: number; y: number; width: number; height: number };
}

interface Particle {
  id: string;
  x: number;
  y: number;
  vx: number;
  vy: number;
}

const ROOT_SIZE = 140;
const NODE_WIDTH = 120;
const NODE_HEIGHT = 92;
const GOLDEN_ANGLE = Math.PI * (3 - Math.sqrt(5));

function hashUnit(value: string): number {
  let hash = 2166136261;
  for (let index = 0; index < value.length; index += 1) {
    hash ^= value.charCodeAt(index);
    hash = Math.imul(hash, 16777619);
  }
  return (hash >>> 0) / 4294967295;
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
      bounds: {
        x: -ROOT_SIZE / 2,
        y: -ROOT_SIZE / 2,
        width: ROOT_SIZE,
        height: ROOT_SIZE,
      },
    };
  }

  const itemIds = new Set(items.map((item) => item.id));
  const evidenceLinks = links.filter(
    (link) =>
      link.relationType !== "discovered_from" &&
      itemIds.has(link.source) &&
      itemIds.has(link.target) &&
      link.source !== link.target
  );

  const degree = new Map(items.map((item) => [item.id, 0]));
  for (const link of evidenceLinks) {
    degree.set(link.source, (degree.get(link.source) ?? 0) + 1);
    degree.set(link.target, (degree.get(link.target) ?? 0) + 1);
  }

  const ordered = [...items].sort(
    (a, b) => (degree.get(b.id) ?? 0) - (degree.get(a.id) ?? 0) || a.id.localeCompare(b.id)
  );
  const particles = new Map<string, Particle>();
  const radialStep = items.length > 80 ? 58 : items.length > 40 ? 66 : 74;

  ordered.forEach((item, index) => {
    const angle = index * GOLDEN_ANGLE + hashUnit(item.id) * 0.55;
    const radius = 205 + Math.sqrt(index) * radialStep;
    particles.set(item.id, {
      id: item.id,
      x: Math.cos(angle) * radius,
      y: Math.sin(angle) * radius * 0.72,
      vx: 0,
      vy: 0,
    });
  });

  const groups = new Map<string, Particle[]>();
  for (const item of items) {
    if (!item.groupId) continue;
    const particle = particles.get(item.id);
    if (!particle) continue;
    const members = groups.get(item.groupId) ?? [];
    members.push(particle);
    groups.set(item.groupId, members);
  }

  const particleList = [...particles.values()];
  const iterations = items.length > 120 ? 28 : 42;

  for (let iteration = 0; iteration < iterations; iteration += 1) {
    const cooling = Math.max(0.25, 1 - iteration / iterations);

    for (let first = 0; first < particleList.length; first += 1) {
      const a = particleList[first];
      for (let second = first + 1; second < particleList.length; second += 1) {
        const b = particleList[second];
        let dx = b.x - a.x;
        const dy = b.y - a.y;
        if (dx === 0 && dy === 0) dx = hashUnit(`${a.id}:${b.id}`) > 0.5 ? 0.01 : -0.01;

        const distanceSquared = dx * dx + dy * dy;
        if (distanceSquared > 360 * 360) continue;
        const distance = Math.max(1, Math.sqrt(distanceSquared));
        const force = Math.min(2.8, 9400 / Math.max(2200, distanceSquared));
        const fx = (dx / distance) * force;
        const fy = (dy / distance) * force;
        a.vx -= fx;
        a.vy -= fy;
        b.vx += fx;
        b.vy += fy;
      }
    }

    for (const link of evidenceLinks) {
      const source = particles.get(link.source);
      const target = particles.get(link.target);
      if (!source || !target) continue;

      const dx = target.x - source.x;
      const dy = target.y - source.y;
      const distance = Math.max(1, Math.sqrt(dx * dx + dy * dy));
      const normalization = Math.sqrt(
        Math.max(1, degree.get(link.source) ?? 1) * Math.max(1, degree.get(link.target) ?? 1)
      );
      const force = ((distance - 180) * 0.018) / normalization;
      const fx = (dx / distance) * force;
      const fy = (dy / distance) * force;
      source.vx += fx;
      source.vy += fy;
      target.vx -= fx;
      target.vy -= fy;
    }

    for (const members of groups.values()) {
      if (members.length < 2) continue;
      const centerX = members.reduce((sum, particle) => sum + particle.x, 0) / members.length;
      const centerY = members.reduce((sum, particle) => sum + particle.y, 0) / members.length;
      for (const particle of members) {
        particle.vx += (centerX - particle.x) * 0.002;
        particle.vy += (centerY - particle.y) * 0.002;
      }
    }

    for (const particle of particleList) {
      const rootDistance = Math.max(1, Math.sqrt(particle.x ** 2 + particle.y ** 2));
      if (rootDistance < 190) {
        const force = (190 - rootDistance) * 0.045;
        particle.vx += (particle.x / rootDistance) * force;
        particle.vy += (particle.y / rootDistance) * force;
      }

      particle.vx -= particle.x * 0.00055;
      particle.vy -= particle.y * 0.00055;
      particle.vx *= 0.7;
      particle.vy *= 0.7;
      particle.x += particle.vx * cooling;
      particle.y += particle.vy * cooling;
    }

    // Resolve label-sized rectangles after forces so dense components stay legible.
    for (let first = 0; first < particleList.length; first += 1) {
      const a = particleList[first];
      for (let second = first + 1; second < particleList.length; second += 1) {
        const b = particleList[second];
        const dx = b.x - a.x || 0.01;
        const dy = b.y - a.y || 0.01;
        const overlapX = NODE_WIDTH + 12 - Math.abs(dx);
        const overlapY = NODE_HEIGHT + 8 - Math.abs(dy);
        if (overlapX <= 0 || overlapY <= 0) continue;

        if (overlapX < overlapY) {
          const shift = (overlapX / 2 + 0.5) * Math.sign(dx);
          a.x -= shift;
          b.x += shift;
        } else {
          const shift = (overlapY / 2 + 0.5) * Math.sign(dy);
          a.y -= shift;
          b.y += shift;
        }
      }
    }
  }

  for (const particle of particleList) {
    positions.set(particle.id, { x: Math.round(particle.x), y: Math.round(particle.y) });
  }

  const left = [-ROOT_SIZE / 2];
  const right = [ROOT_SIZE / 2];
  const top = [-ROOT_SIZE / 2];
  const bottom = [ROOT_SIZE / 2];
  for (const particle of particleList) {
    left.push(particle.x - NODE_WIDTH / 2);
    right.push(particle.x + NODE_WIDTH / 2);
    top.push(particle.y - NODE_HEIGHT / 2);
    bottom.push(particle.y + NODE_HEIGHT / 2);
  }

  const padding = 70;
  const minX = Math.min(...left) - padding;
  const maxX = Math.max(...right) + padding;
  const minY = Math.min(...top) - padding;
  const maxY = Math.max(...bottom) + padding;

  return {
    positions,
    bounds: { x: minX, y: minY, width: maxX - minX, height: maxY - minY },
  };
}
