import type { TargetData } from "./types";

export function targetDisplayName(target?: TargetData | null): string {
  if (!target) return "Objetivo sin identificador";
  const primary = target.full_name?.trim() || target.username?.trim() || target.email?.trim() || target.phone?.trim() || target.dni?.trim();
  if (primary) return primary;
  const raw = target.extra_data?.identifiers;
  const first = Array.isArray(raw) ? raw[0] : null;
  if (first && typeof first === "object" && typeof first.value === "string" && typeof first.id_type === "string") {
    return `${first.id_type.replaceAll("_", " ").toUpperCase()}: ${first.value}`;
  }
  return "Objetivo sin identificador";
}
