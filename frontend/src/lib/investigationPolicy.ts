import type { CreateInvestigationPayload, MaigretScanMode, Strategy } from "./types.ts";

export function investigationExecution(mode: "normal" | "lite", options: {
  strategy: Strategy; scanMode: MaigretScanMode; extract: boolean; enrich: boolean;
}): Pick<CreateInvestigationPayload, "acquisition_mode" | "strategy" | "maigret_plan"> {
  if (mode === "lite") return { acquisition_mode: "fair", strategy: "rule_based" };
  return { acquisition_mode: "normal", strategy: options.strategy,
    maigret_plan: { scan_mode: options.scanMode, options: { parse: options.extract, enrich: options.extract && options.enrich } } };
}
