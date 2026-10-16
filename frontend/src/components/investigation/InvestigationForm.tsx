"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { checkHealth, createInvestigation, getMaigretCapabilities } from "@/lib/api";
import type { Strategy, MaigretScanMode, UsernameSeed, HealthStatus } from "@/lib/types";
import { ArrowRight, ShieldAlert } from "lucide-react";
import { buildFootprintTarget } from "@/lib/footprintInput";

import { investigationExecution } from "@/lib/investigationPolicy";
import { LiteSearchInfo } from "./LiteSearchInfo";

const STRATEGY_OPTIONS: { id: Strategy; label: string; help: string; needsLlm: boolean }[] = [
  { id: "auto", label: "Automático", help: "Usa el agente IA si está configurado; si no, ejecuta el motor de reglas.", needsLlm: false },
  { id: "hybrid", label: "Híbrido (Reglas + IA)", help: "Barrido heurístico completo y refinamiento de las búsquedas con IA.", needsLlm: true },
  { id: "rule_based", label: "Reglas estáticas", help: "Descubrimiento y pivoteo deterministas, sin IA.", needsLlm: false },
  { id: "agentic", label: "Agente autónomo", help: "El agente planifica las consultas a las herramientas existentes.", needsLlm: true },
];
const inputClass = "w-full bg-[#080d15] border border-[#1a2636] focus:border-sky-500 rounded-lg px-3 py-2 text-sm text-slate-200 placeholder:text-slate-600 outline-none transition-colors";
const buttonClass = "rounded-lg border border-[#1a2636] px-3 py-2 text-xs text-slate-300 hover:text-sky-300 disabled:opacity-40 focus-visible:outline focus-visible:outline-sky-400";

export function InvestigationForm() {
  const router = useRouter();
  const [runtime, setRuntime] = useState<HealthStatus | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [givenNames, setGivenNames] = useState("");
  const [familyNames, setFamilyNames] = useState("");
  const [emails, setEmails] = useState([""]);
  const [usernames, setUsernames] = useState<UsernameSeed[]>([{ username: "", platform: "" }]);
  const [phones, setPhones] = useState([""]);
  const [subjectConsent, setSubjectConsent] = useState(false);
  const [selfConsent, setSelfConsent] = useState(false);
  const [strategy, setStrategy] = useState<Strategy>("auto");
  const [aiEnabled, setAiEnabled] = useState<boolean | null>(null);
  const [scanMode, setScanMode] = useState<MaigretScanMode>("deep");
  const [enrich, setEnrich] = useState(true);
  const [extract, setExtract] = useState(true);
  const [catalogueSize, setCatalogueSize] = useState<number | null>(null);

  useEffect(() => {
    let cancelled = false;
    checkHealth().then((health) => {
      if (cancelled) return;
      if (!health.personmap_env) throw new Error("Reinicia el backend actualizado para cargar el modo de búsqueda.");
      setRuntime(health);
      setAiEnabled(health.ai_enabled);
      if (health.personmap_env === "normal") {
        void getMaigretCapabilities().then((capabilities) => {
          if (!cancelled) {
            setCatalogueSize(capabilities.catalogue_with_variants);
            setEnrich(capabilities.maigret_enrich);
            setExtract(capabilities.maigret_parse);
          }
        }).catch(() => {});
      }
    }).catch((cause: unknown) => {
      if (!cancelled) setError(cause instanceof Error ? cause.message : "No se pudo cargar la configuración del servidor.");
    });
    return () => { cancelled = true; };
  }, []);

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    setError(null);
    if (!runtime) { setError("Espera a que se cargue la configuración del servidor."); return; }
    const target = buildFootprintTarget({ givenNames, familyNames, emails, usernames, phones });
    if (!target.given_names && !target.family_names && !target.emails?.length && !target.usernames?.length && !target.phones?.length) {
      setError("Ingresa al menos un nombre, apellido, correo, alias o teléfono.");
      return;
    }
    if (!subjectConsent) {
      setError("Confirma que analizas tus propios datos o cuentas con autorización explícita.");
      return;
    }
    setLoading(true);
    try {
      const investigation = await createInvestigation({
        target, subject_consent: subjectConsent,
        self_consent: selfConsent,
        ...investigationExecution(runtime.personmap_env, { strategy, scanMode, extract, enrich }),
      });
      router.push(`/investigation/${investigation.id}`);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "No se pudo iniciar el análisis. Comprueba la conexión con el servidor.");
      setLoading(false);
    }
  }

  return (
    <div id="nueva-auditoria" className="panel-card p-5 sm:p-6 shadow-xl border border-[#162234] bg-[#0d1420]">
      <div className="pb-4 border-b border-[#162234] mb-6">
        <h2 className="text-base font-semibold text-slate-100">Explora tu huella digital pública</h2>
        <p className="text-xs text-slate-400 mt-2">Añade los datos que reconoces como tuyos. Los hallazgos automáticos se mantendrán separados de tu declaración.</p>
      </div>
      {error && <div role="alert" className="mb-5 p-3 rounded-lg bg-rose-500/10 border border-rose-500/30 text-rose-300 text-xs flex gap-2"><ShieldAlert className="w-4 h-4 shrink-0" />{error}</div>}
      {!runtime && !error && <p role="status" className="mb-4 text-xs text-slate-400">Cargando configuración de búsqueda…</p>}
      {runtime?.personmap_env === "lite" && runtime.lite_plan && <div className="mb-5"><LiteSearchInfo plan={runtime.lite_plan} /></div>}
      <form onSubmit={handleSubmit} className="space-y-6">
        <fieldset disabled={loading || !runtime} className="space-y-6 disabled:opacity-60">
          <legend className="text-xs font-semibold text-sky-300 mb-3">Datos declarados por ti</legend>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3.5">
            <div><label htmlFor="given-names" className="block text-xs text-slate-300 mb-1.5">Nombres</label><input id="given-names" autoComplete="given-name" maxLength={120} value={givenNames} onChange={(e) => setGivenNames(e.target.value)} className={inputClass} /></div>
            <div><label htmlFor="family-names" className="block text-xs text-slate-300 mb-1.5">Apellidos</label><input id="family-names" autoComplete="family-name" maxLength={120} value={familyNames} onChange={(e) => setFamilyNames(e.target.value)} className={inputClass} /></div>
          </div>
          <fieldset className="space-y-2">
            <legend className="text-xs text-slate-300 mb-1.5">Correos</legend>
            {emails.map((email, index) => <div key={index} className="flex gap-2">
              <input type="email" aria-label={`Correo ${index + 1}`} maxLength={254} value={email} placeholder="correo@gmail.com" onChange={(e) => setEmails((current) => current.map((value, i) => i === index ? e.target.value : value))} className={inputClass} />
              <button type="button" aria-label={`Eliminar correo ${index + 1}`} onClick={() => setEmails((current) => current.filter((_, i) => i !== index))} className={buttonClass}>Eliminar</button>
            </div>)}
            <button type="button" disabled={emails.length >= 30} onClick={() => setEmails((current) => [...current, ""])} className={buttonClass}>+ Agregar correo</button>
          </fieldset>
          <fieldset className="space-y-2">
            <legend className="text-xs text-slate-300 mb-1.5">Usernames / alias</legend>
            <p className="text-xs text-slate-500">La plataforma es opcional. Si declaras una cuenta con plataforma, podemos obtener su contenido público desde el inicio; otras coincidencias se revisan después.</p>
            {usernames.map((item, index) => <div key={index} className="grid grid-cols-1 sm:grid-cols-[1fr_1fr_auto] gap-2">
              <input aria-label={`Username ${index + 1}`} maxLength={100} value={item.username} placeholder="xbiltom" onChange={(e) => setUsernames((current) => current.map((entry, i) => i === index ? { ...entry, username: e.target.value } : entry))} className={inputClass} />
              <input aria-label={`Plataforma del username ${index + 1} (opcional)`} maxLength={100} list="common-platforms" value={item.platform ?? ""} placeholder="No especificada" onChange={(e) => setUsernames((current) => current.map((entry, i) => i === index ? { ...entry, platform: e.target.value } : entry))} className={inputClass} />
              <button type="button" aria-label={`Eliminar username ${index + 1}`} onClick={() => setUsernames((current) => current.filter((_, i) => i !== index))} className={buttonClass}>Eliminar</button>
            </div>)}
            <datalist id="common-platforms">{["GitHub", "Instagram", "TikTok", "Reddit", "X", "Facebook", "YouTube", "Threads"].map((platform) => <option key={platform} value={platform} />)}</datalist>
            <button type="button" disabled={usernames.length >= 30} onClick={() => setUsernames((current) => [...current, { username: "", platform: "" }])} className={buttonClass}>+ Agregar username</button>
          </fieldset>
          <fieldset className="space-y-2">
            <legend className="text-xs text-slate-300 mb-1.5">Teléfonos (opcional)</legend>
            <p className="text-xs text-slate-500">Incluye el prefijo de país. Los números sin prefijo se interpretan como peruanos.</p>
            {phones.map((phone, index) => <div key={index} className="flex gap-2">
              <input type="tel" aria-label={`Teléfono ${index + 1}`} maxLength={100} value={phone} placeholder="+51 912 345 678" onChange={(e) => setPhones((current) => current.map((value, i) => i === index ? e.target.value : value))} className={inputClass} />
              <button type="button" aria-label={`Eliminar teléfono ${index + 1}`} onClick={() => setPhones((current) => current.filter((_, i) => i !== index))} className={buttonClass}>Eliminar</button>
            </div>)}
            <button type="button" disabled={phones.length >= 30} onClick={() => setPhones((current) => [...current, ""])} className={buttonClass}>+ Agregar teléfono</button>
          </fieldset>
          {runtime?.personmap_env === "normal" && <details className="rounded-lg border border-[#1a2636] bg-[#090f18] p-3.5">
            <summary className="cursor-pointer text-xs text-sky-300 focus-visible:outline focus-visible:outline-sky-400">Opciones de ejecución existentes</summary>
            <div className="mt-4 space-y-4">
              <label className="block text-xs text-slate-300">Motor de búsqueda
                <select value={strategy} onChange={(e) => setStrategy(e.target.value as Strategy)} className={`${inputClass} mt-2`}>
                  {STRATEGY_OPTIONS.map((option) => <option key={option.id} value={option.id}>{option.label}{option.needsLlm && aiEnabled === false ? " · sin IA, usará reglas" : ""}</option>)}
                </select>
              </label>
              <p className="text-xs text-slate-400">{STRATEGY_OPTIONS.find((option) => option.id === strategy)?.help}</p>
              <label className="block text-xs text-slate-300">Alcance de Maigret
                <select value={scanMode} onChange={(e) => setScanMode(e.target.value as MaigretScanMode)} className={`${inputClass} mt-2`}>
                  <option value="fast">Rápido · primeras plataformas</option><option value="deep">Habitual · límite configurado</option><option value="all">Completo{catalogueSize ? ` · ${catalogueSize.toLocaleString("es-PE")} recetas` : ""}</option>
                </select>
              </label>
              <label className="flex gap-2 text-xs text-slate-300"><input type="checkbox" checked={extract} onChange={(e) => setExtract(e.target.checked)} className="accent-sky-500" />Extraer información de perfiles</label>
              <label className="flex gap-2 text-xs text-slate-300"><input type="checkbox" disabled={!extract} checked={enrich} onChange={(e) => setEnrich(e.target.checked)} className="accent-sky-500" />Ampliar datos y enlaces encontrados</label>
            </div>
          </details>}
          <div className="space-y-4 rounded-lg border border-[#1a2636] p-3.5">
            <label className="flex items-start gap-3 text-sm text-slate-200"><input required type="checkbox" checked={subjectConsent} onChange={(e) => setSubjectConsent(e.target.checked)} className="mt-1 accent-sky-500" />Confirmo que analizo mis propios datos o que cuento con autorización explícita para analizarlos.</label>
            <label className="flex items-start gap-3 text-xs text-slate-400"><input type="checkbox" checked={selfConsent} onChange={(e) => setSelfConsent(e.target.checked)} className="mt-0.5 accent-sky-500" />Además, autorizo consultar registros de infostealers en un servicio externo (opcional). Se enviarán los correos o alias consultados a ese servicio; sin este permiso, la fuente se omite.</label>
          </div>
        </fieldset>
        <div className="pt-4 flex justify-end border-t border-[#162234]">
          <button type="submit" disabled={loading || !runtime || !subjectConsent} className="w-full sm:w-auto flex items-center justify-center gap-2 px-6 py-2.5 rounded-lg bg-sky-600 hover:bg-sky-500 disabled:opacity-50 text-white text-sm font-semibold focus-visible:outline focus-visible:outline-sky-300">
            {loading ? "Iniciando análisis…" : "Explorar mi huella pública"}<ArrowRight className="w-4 h-4" />
          </button>
        </div>
      </form>
    </div>
  );
}
