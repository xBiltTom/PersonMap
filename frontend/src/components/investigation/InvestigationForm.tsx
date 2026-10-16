"use client";

import { useEffect, useState, type FormEvent } from "react";
import { useRouter } from "next/navigation";
import { checkHealth, createInvestigation, getMaigretCapabilities } from "@/lib/api";
import type { HealthStatus, MaigretScanMode, Strategy, UsernameSeed } from "@/lib/types";
import { ArrowRight, ChevronDown, LoaderCircle, Plus, ShieldAlert, ShieldCheck, X } from "lucide-react";
import { buildFootprintTarget } from "@/lib/footprintInput";
import { investigationExecution } from "@/lib/investigationPolicy";
import { unlockDiscoverySound } from "@/lib/discoverySound";

const STRATEGY_OPTIONS: { id: Strategy; label: string; needsLlm: boolean }[] = [
  { id: "auto", label: "Automático", needsLlm: false },
  { id: "hybrid", label: "Híbrido", needsLlm: true },
  { id: "rule_based", label: "Reglas estáticas", needsLlm: false },
  { id: "agentic", label: "Agente autónomo", needsLlm: true },
];
const PLATFORM_OPTIONS = [
  "Academia.edu", "About.me", "Artstation", "Bandcamp", "beacons.ai", "Behance", "BitBucket", "Bluesky",
  "carrd.co", "Chess", "CodePen", "Dribbble", "Facebook", "GitHub", "GitLab", "HackerNews", "HuggingFace",
  "Instagram", "Kaggle", "LinkedIn", "Medium", "Pinterest", "Quora", "Reddit", "Replit", "Roblox",
  "Snapchat", "SlideShare", "SoundCloud", "Spotify", "StackOverflow", "Steam", "Telegram", "Threads",
  "TikTok", "Tumblr", "Twitch", "Twitter", "YouTube",
].sort((left, right) => left.localeCompare(right, "es"));
const OTHER_PLATFORM = "__other__";

const inputClass = "w-full border border-[#1a2636] bg-[#080d15] px-3 py-2.5 text-sm text-slate-100 outline-none transition-colors placeholder:text-slate-600 hover:border-[#2a405d] focus:border-sky-400 focus:ring-2 focus:ring-sky-500/15";
const selectClass = "w-full cursor-pointer appearance-none border border-[#243951] bg-[#0c1420] py-2.5 pl-3 pr-9 text-sm text-slate-100 outline-none transition-colors hover:border-sky-500/60 focus:border-sky-400 focus:ring-2 focus:ring-sky-500/15";
const smallButtonClass = "inline-flex min-h-9 items-center gap-1.5 border border-[#22344d] bg-[#101b2a] px-3 text-xs text-slate-300 transition-colors hover:border-sky-400/45 hover:text-sky-100 focus-visible:outline focus-visible:outline-sky-400 disabled:cursor-not-allowed disabled:opacity-40";
const removeButtonClass = "inline-flex h-10 w-10 shrink-0 items-center justify-center border border-[#1c2b3e] bg-[#0b111b] text-slate-500 transition-colors hover:border-rose-500/35 hover:bg-rose-500/10 hover:text-rose-300 focus-visible:outline focus-visible:outline-sky-400";
const fieldsetClass = "min-w-0 border-t border-[#22344d] pt-3";
const legendClass = "px-0 text-xs font-semibold text-slate-200";
const labelClass = "mb-1.5 block text-[10px] font-medium text-slate-400";

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

  useEffect(() => {
    let cancelled = false;
    checkHealth().then((health) => {
      if (cancelled) return;
      if (!health.personmap_env) throw new Error("Reinicia el backend actualizado para cargar la búsqueda.");
      setRuntime(health);
      setAiEnabled(health.ai_enabled);
      if (health.personmap_env === "normal") {
        void getMaigretCapabilities().then((capabilities) => {
          if (!cancelled) {
            setEnrich(capabilities.maigret_enrich);
            setExtract(capabilities.maigret_parse);
          }
        }).catch(() => {});
      }
    }).catch((cause: unknown) => {
      if (!cancelled) setError(cause instanceof Error ? cause.message : "No se pudo conectar con el servidor.");
    });
    return () => { cancelled = true; };
  }, []);

  const target = buildFootprintTarget({
    givenNames,
    familyNames,
    emails,
    usernames: usernames.map((item) => ({
      ...item,
      platform: item.platform === OTHER_PLATFORM ? "" : item.platform,
    })),
    phones,
  });
  const hasSearchData = Boolean(
    target.given_names || target.family_names || target.emails?.length || target.usernames?.length || target.phones?.length,
  );

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    if (!runtime) { setError("Espera a que se cargue la conexión con el servidor."); return; }
    if (!hasSearchData) { setError("Ingresa al menos un nombre, apellido, correo, alias o teléfono."); return; }
    if (!subjectConsent) { setError("Confirma que analizas tus propios datos o que tienes autorización explícita."); return; }
    setLoading(true);
    void unlockDiscoverySound();
    try {
      const investigation = await createInvestigation({
        target,
        subject_consent: subjectConsent,
        self_consent: selfConsent,
        ...investigationExecution(runtime.personmap_env, { strategy, scanMode, extract, enrich }),
      });
      router.push(`/investigation/${investigation.id}`);
    } catch (cause: unknown) {
      setError(cause instanceof Error ? cause.message : "No se pudo iniciar la auditoría. Comprueba la conexión con el servidor.");
      setLoading(false);
    }
  }

  const readinessMessage = !runtime
    ? null
    : !hasSearchData
      ? "Ingresa al menos un dato."
      : !subjectConsent
        ? "Confirma la autorización para continuar."
        : null;

  return (
    <div id="nueva-auditoria" className="overflow-hidden border border-[#162234] bg-[#0d1420]">
      <form onSubmit={handleSubmit} className="p-4 sm:p-5 lg:p-6">
        <header className="mb-4 flex flex-wrap items-start justify-between gap-x-6 gap-y-2 border-b border-[#162234] pb-3">
          <div>
            <h2 className="text-sm font-bold tracking-[-0.02em] text-slate-100">Datos de búsqueda</h2>
            <p className="mt-1 text-[11px] text-slate-500">Ingresa al menos un dato. Los demás son opcionales.</p>
          </div>
          {!runtime && !error && <p role="status" className="text-[11px] text-slate-500">Conectando con el servidor…</p>}
        </header>

        {error && (
          <div role="alert" className="mb-4 flex gap-2 border border-rose-500/30 bg-rose-500/10 p-3 text-xs leading-relaxed text-rose-200">
            <ShieldAlert className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
            <span>{error}</span>
          </div>
        )}

        <fieldset disabled={loading || !runtime} className="grid grid-cols-1 gap-x-5 gap-y-4 md:grid-cols-2 disabled:opacity-60">
          <legend className="sr-only">Datos para iniciar la auditoría</legend>

          <fieldset className={`${fieldsetClass} md:col-span-2`}>
            <legend className={legendClass}>Nombre y apellidos</legend>
            <p className="mb-2 text-[10px] leading-relaxed text-slate-500">Se usan también para contrastar publicaciones.</p>
            <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
              <label className="block">
                <span className={labelClass}>Nombres</span>
                <input id="given-names" autoComplete="given-name" maxLength={120} value={givenNames} onChange={(event) => setGivenNames(event.target.value)} className={inputClass} />
              </label>
              <label className="block">
                <span className={labelClass}>Apellidos</span>
                <input id="family-names" autoComplete="family-name" maxLength={120} value={familyNames} onChange={(event) => setFamilyNames(event.target.value)} className={inputClass} />
              </label>
            </div>
          </fieldset>

          <fieldset className={`${fieldsetClass} md:col-span-2`}>
            <legend className={legendClass}>Alias y plataforma</legend>
            <p className="mb-2 text-[10px] leading-relaxed text-slate-500">Si no conoces la plataforma, déjala sin seleccionar; el alias se buscará primero.</p>
            <div className="space-y-2">
              {usernames.map((item, index) => (
                <div key={index} className="grid grid-cols-1 items-end gap-2 sm:grid-cols-[minmax(0,1fr)_minmax(0,0.8fr)_auto]">
                  <label className="block min-w-0">
                    <span className={`${labelClass} sr-only`}>Alias {index + 1}</span>
                    <input aria-label={`Alias ${index + 1}`} maxLength={100} value={item.username} placeholder="Alias" onChange={(event) => setUsernames((current) => current.map((entry, i) => i === index ? { ...entry, username: event.target.value } : entry))} className={inputClass} />
                  </label>
                  <label className="block min-w-0">
                    <span className={`${labelClass} sr-only`}>Plataforma del alias {index + 1}</span>
                    <span className="relative block">
                      <select aria-label={`Plataforma del alias ${index + 1} (opcional)`} value={!item.platform ? "" : item.platform === OTHER_PLATFORM || !PLATFORM_OPTIONS.includes(item.platform) ? OTHER_PLATFORM : item.platform} onChange={(event) => setUsernames((current) => current.map((entry, i) => i === index ? { ...entry, platform: event.target.value } : entry))} className={`${selectClass} ${!item.platform ? "text-slate-500" : ""}`}>
                        <option className="bg-[#0c1420] text-slate-500" value="">Plataforma (opcional)</option>
                        {PLATFORM_OPTIONS.map((platform) => <option className="bg-[#0c1420] text-slate-200" key={platform} value={platform}>{platform}</option>)}
                        <option className="bg-[#0c1420] text-sky-300" value={OTHER_PLATFORM}>Otra…</option>
                      </select>
                      <ChevronDown className="pointer-events-none absolute right-3 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-sky-400" aria-hidden="true" />
                    </span>
                  </label>
                  <button type="button" aria-label={`Eliminar alias ${index + 1}`} onClick={() => setUsernames((current) => current.filter((_, i) => i !== index))} className={`${removeButtonClass} h-10 w-full sm:w-10`}>
                    <X className="h-4 w-4" aria-hidden="true" /><span className="sm:hidden">Quitar</span>
                  </button>
                  {(item.platform === OTHER_PLATFORM || (item.platform && !PLATFORM_OPTIONS.includes(item.platform))) && (
                    <label className="block min-w-0 sm:col-span-2">
                      <span className={`${labelClass} sr-only`}>Nombre de la plataforma {index + 1}</span>
                      <input aria-label={`Nombre de la plataforma ${index + 1}`} maxLength={100} value={item.platform === OTHER_PLATFORM ? "" : item.platform ?? ""} placeholder="Nombre de la plataforma" onChange={(event) => setUsernames((current) => current.map((entry, i) => i === index ? { ...entry, platform: event.target.value || OTHER_PLATFORM } : entry))} className={inputClass} />
                    </label>
                  )}
                </div>
              ))}
            </div>
            <button type="button" disabled={usernames.length >= 30} onClick={() => setUsernames((current) => [...current, { username: "", platform: "" }])} className={`${smallButtonClass} mt-2`}>
              <Plus className="h-3.5 w-3.5" aria-hidden="true" />Agregar alias
            </button>
          </fieldset>

          <fieldset className={fieldsetClass}>
            <legend className={legendClass}>Correos electrónicos</legend>
            <p className="mb-2 text-[10px] leading-relaxed text-slate-500">Se revisan fuentes de exposición y registro compatibles.</p>
            <div className="space-y-2">
              {emails.map((email, index) => (
                <div key={index} className="flex min-w-0 gap-2">
                  <label className="min-w-0 flex-1">
                    <span className="sr-only">Correo electrónico {index + 1}</span>
                    <input type="email" aria-label={`Correo electrónico ${index + 1}`} maxLength={254} value={email} placeholder="nombre@dominio.com" onChange={(event) => setEmails((current) => current.map((value, i) => i === index ? event.target.value : value))} className={inputClass} />
                  </label>
                  <button type="button" aria-label={`Eliminar correo ${index + 1}`} onClick={() => setEmails((current) => current.filter((_, i) => i !== index))} className={removeButtonClass}>
                    <X className="h-4 w-4" aria-hidden="true" />
                  </button>
                </div>
              ))}
            </div>
            <button type="button" disabled={emails.length >= 30} onClick={() => setEmails((current) => [...current, ""])} className={`${smallButtonClass} mt-2`}>
              <Plus className="h-3.5 w-3.5" aria-hidden="true" />Agregar correo
            </button>
          </fieldset>

          <fieldset className={fieldsetClass}>
            <legend className={legendClass}>Teléfonos</legend>
            <p className="mb-2 text-[10px] leading-relaxed text-slate-500">Incluye el prefijo de país; sin prefijo se interpreta como número peruano.</p>
            <div className="space-y-2">
              {phones.map((phone, index) => (
                <div key={index} className="flex min-w-0 gap-2">
                  <label className="min-w-0 flex-1">
                    <span className="sr-only">Teléfono {index + 1}</span>
                    <input type="tel" aria-label={`Teléfono ${index + 1}`} maxLength={100} value={phone} placeholder="+51 912 345 678" onChange={(event) => setPhones((current) => current.map((value, i) => i === index ? event.target.value : value))} className={inputClass} />
                  </label>
                  <button type="button" aria-label={`Eliminar teléfono ${index + 1}`} onClick={() => setPhones((current) => current.filter((_, i) => i !== index))} className={removeButtonClass}>
                    <X className="h-4 w-4" aria-hidden="true" />
                  </button>
                </div>
              ))}
            </div>
            <button type="button" disabled={phones.length >= 30} onClick={() => setPhones((current) => [...current, ""])} className={`${smallButtonClass} mt-2`}>
              <Plus className="h-3.5 w-3.5" aria-hidden="true" />Agregar teléfono
            </button>
          </fieldset>

          {runtime?.personmap_env === "normal" && (
            <fieldset className={`${fieldsetClass} md:col-span-2`}>
              <legend className={legendClass}>Opciones de búsqueda</legend>
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                <label className="block">
                  <span className={labelClass}>Motor</span>
                  <span className="relative block">
                    <select value={strategy} onChange={(event) => setStrategy(event.target.value as Strategy)} className={selectClass}>
                      {STRATEGY_OPTIONS.map((option) => (
                        <option className="bg-[#0c1420] text-slate-200" key={option.id} value={option.id}>
                          {option.label}{option.needsLlm && aiEnabled === false ? " (sin IA, usará reglas)" : ""}
                        </option>
                      ))}
                    </select>
                    <ChevronDown className="pointer-events-none absolute right-3 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-sky-400" aria-hidden="true" />
                  </span>
                </label>
                <label className="block">
                  <span className={labelClass}>Alcance de búsqueda de perfiles</span>
                  <span className="relative block">
                    <select value={scanMode} onChange={(event) => setScanMode(event.target.value as MaigretScanMode)} className={selectClass}>
                      <option className="bg-[#0c1420] text-slate-200" value="fast">Rápido</option>
                      <option className="bg-[#0c1420] text-slate-200" value="deep">Habitual</option>
                      <option className="bg-[#0c1420] text-slate-200" value="all">Completo</option>
                    </select>
                    <ChevronDown className="pointer-events-none absolute right-3 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-sky-400" aria-hidden="true" />
                  </span>
                </label>
              </div>
              <div className="mt-3 flex flex-wrap gap-x-6 gap-y-2 border-t border-[#162234] pt-3">
                <label className="flex items-center gap-2 text-[11px] text-slate-400">
                  <input type="checkbox" checked={extract} onChange={(event) => setExtract(event.target.checked)} className="h-4 w-4 accent-sky-500" />
                  Extraer datos de perfiles
                </label>
                <label className="flex items-center gap-2 text-[11px] text-slate-400">
                  <input type="checkbox" disabled={!extract} checked={enrich} onChange={(event) => setEnrich(event.target.checked)} className="h-4 w-4 accent-sky-500" />
                  Ampliar enlaces encontrados
                </label>
              </div>
            </fieldset>
          )}
        </fieldset>

        <section className="mt-5 border-t border-[#162234] pt-4" aria-labelledby="permissions-heading">
          <h3 id="permissions-heading" className="mb-3 flex items-center gap-2 text-xs font-semibold text-slate-200">
            <ShieldCheck className="h-4 w-4 text-sky-300" aria-hidden="true" />Permisos
          </h3>
          <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
            <label className="flex cursor-pointer items-start gap-2.5 border border-[#22344d] p-3 text-[11px] leading-relaxed text-slate-300">
              <input required type="checkbox" disabled={loading || !runtime} checked={subjectConsent} onChange={(event) => setSubjectConsent(event.target.checked)} className="mt-0.5 h-4 w-4 shrink-0 accent-sky-500" />
              <span><strong className="font-semibold text-slate-100">Autorización obligatoria.</strong> Confirmo que estos datos son míos o tengo permiso explícito para analizarlos.</span>
            </label>
            <label className="flex cursor-pointer items-start gap-2.5 border border-[#22344d] p-3 text-[11px] leading-relaxed text-slate-400">
              <input type="checkbox" disabled={loading || !runtime} checked={selfConsent} onChange={(event) => setSelfConsent(event.target.checked)} className="mt-0.5 h-4 w-4 shrink-0 accent-sky-500" />
              <span><strong className="font-semibold text-slate-300">Infostealers · opcional.</strong> Autorizo enviar estos correos o alias a un servicio externo para consultar sus registros.</span>
            </label>
          </div>
        </section>

        <footer className="mt-4 flex flex-col-reverse gap-3 border-t border-[#162234] pt-3 sm:flex-row sm:items-center sm:justify-between">
          <div className="min-h-4">
            {readinessMessage && <p className="text-[10px] text-slate-500">{readinessMessage}</p>}
          </div>
          <button type="submit" disabled={loading || !runtime || !subjectConsent || !hasSearchData} aria-busy={loading} className="inline-flex min-h-10 w-full items-center justify-center gap-2 border border-sky-500 bg-sky-600 px-5 text-xs font-bold tracking-[-0.01em] text-white transition-colors hover:bg-sky-500 focus-visible:outline focus-visible:outline-sky-300 disabled:cursor-not-allowed disabled:opacity-50 sm:w-auto">
            {loading ? <><LoaderCircle className="h-4 w-4 animate-spin" aria-hidden="true" />Iniciando…</> : <>Iniciar auditoría<ArrowRight className="h-4 w-4" aria-hidden="true" /></>}
          </button>
        </footer>
      </form>
    </div>
  );
}
