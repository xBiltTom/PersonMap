"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { checkHealth, createInvestigation, getMaigretCapabilities } from "@/lib/api";
import type { Strategy, TypedIdentifier, MaigretScanMode } from "@/lib/types";
import {
  User,
  Mail,
  AtSign,
  Phone,
  FileText,
  GraduationCap,
  Sparkles,
  ArrowRight,
  ShieldAlert,
  Cpu,
  Workflow,
  Layers,
  Brain,
  Check,
} from "lucide-react";

interface StrategyOption {
  id: Strategy;
  label: string;
  badge: string;
  tagline: string;
  help: string;
  needsLlm: boolean;
  icon: React.ComponentType<{ className?: string }>;
}

const STRATEGY_OPTIONS: StrategyOption[] = [
  {
    id: "auto",
    label: "Automático",
    badge: "Recomendado",
    tagline: "Detección inteligente de motor",
    help: "Usa el agente IA si hay un LLM configurado en el backend; si no, degrada de forma transparente al motor heurístico.",
    needsLlm: false,
    icon: Cpu,
  },
  {
    id: "hybrid",
    label: "Híbrido (Reglas + IA)",
    badge: "Dos fases",
    tagline: "Heurística exhaustiva + Refinamiento",
    help: "Fase 1: barrido masivo determinista. Fase 2: el LLM razona sobre los vacíos sin repetir consultas ya ejecutadas.",
    needsLlm: true,
    icon: Workflow,
  },
  {
    id: "rule_based",
    label: "Reglas Estáticas",
    badge: "Control Paper",
    tagline: "0 tokens · 100% Determinista",
    help: "Barrido por reglas estáticas y pivoteo heurístico. Es la condición de control científico reproducible del experimento.",
    needsLlm: false,
    icon: Layers,
  },
  {
    id: "agentic",
    label: "Agente Autónomo",
    badge: "Experimental",
    tagline: "Planificación autónoma por LLM",
    help: "El LLM inspecciona las evidencias y planifica de manera autónoma qué herramientas despachar en cada iteración.",
    needsLlm: true,
    icon: Brain,
  },
];

const IDENTIFIER_OPTIONS: { id: TypedIdentifier["id_type"]; label: string; example: string }[] = [
  { id: "orcid", label: "ORCID", example: "0000-0002-1825-0097" },
  { id: "steam_id", label: "Steam ID", example: "76561198012345678" },
  { id: "gaia_id", label: "GAIA ID (Google)", example: "Identificador numérico" },
  { id: "vk_id", label: "VK ID", example: "123456789" },
  { id: "qq_id", label: "QQ ID", example: "Identificador numérico" },
  { id: "bilibili_id", label: "Bilibili ID", example: "Identificador numérico" },
  { id: "yandex_public_id", label: "Yandex ID público", example: "Identificador público" },
  { id: "yelp_userid", label: "Yelp ID", example: "Identificador del perfil" },
  { id: "ok_id", label: "OK ID", example: "Identificador numérico" },
  { id: "wikimapia_uid", label: "Wikimapia ID", example: "Identificador numérico" },
  { id: "uidme_uguid", label: "uID.me ID", example: "Identificador del perfil" },
];

export function InvestigationForm() {
  const router = useRouter();
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [fullName, setFullName] = useState("");
  const [email, setEmail] = useState("");
  const [username, setUsername] = useState("");
  const [phone, setPhone] = useState("");
  const [dni, setDni] = useState("");
  const [university, setUniversity] = useState("");
  const [description, setDescription] = useState("");
  const [strategy, setStrategy] = useState<Strategy>("auto");
  const [selfConsent, setSelfConsent] = useState(false);
  const [aiEnabled, setAiEnabled] = useState<boolean | null>(null);
  const [identifiers, setIdentifiers] = useState<TypedIdentifier[]>([{ value: "", id_type: "orcid" }]);
  const [scanMode, setScanMode] = useState<MaigretScanMode>("deep");
  const [enrich, setEnrich] = useState(true);
  const [extract, setExtract] = useState(true);
  const [permutationParts, setPermutationParts] = useState("");
  const [catalogueSize, setCatalogueSize] = useState<number | null>(null);

  useEffect(() => {
    let cancelled = false;
    checkHealth()
      .then((h) => {
        if (!cancelled) setAiEnabled(h.ai_enabled);
      })
      .catch(() => {
        if (!cancelled) setAiEnabled(null);
      });
    getMaigretCapabilities().then((capabilities) => {
      if (!cancelled) {
        setCatalogueSize(capabilities.catalogue_with_variants);
        setEnrich(capabilities.maigret_enrich);
        setExtract(capabilities.maigret_parse);
      }
    }).catch(() => { /* A disconnected backend keeps the form usable. */ });
    return () => {
      cancelled = true;
    };
  }, []);

  const selectedStrategy =
    STRATEGY_OPTIONS.find((s) => s.id === strategy) ?? STRATEGY_OPTIONS[0];

  const handleUsernameChange = (val: string) => {
    // Clean initial @ if user pasted it
    const cleaned = val.startsWith("@") ? val.slice(1) : val;
    setUsername(cleaned);
  };

  const handleDniChange = (val: string) => {
    // Limit to numeric characters and max 8 digits
    const numeric = val.replace(/\D/g, "").slice(0, 8);
    setDni(numeric);
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);

    const hasIdentifier =
      fullName.trim() ||
      email.trim() ||
      username.trim() ||
      phone.trim() ||
      dni.trim() || identifiers.some((item) => item.value.trim());

    if (!hasIdentifier) {
      setError(
        "Ingresa al menos un nombre, correo, usuario, teléfono, DNI o ID de perfil."
      );
      return;
    }

    const parts = permutationParts.split(",").map((part) => part.trim()).filter(Boolean);
    if (parts.length > 3) { setError("Combina como máximo tres fragmentos de usuario."); return; }

    setLoading(true);

    try {
      const inv = await createInvestigation({
        target: {
          full_name: fullName.trim() || null,
          email: email.trim() || null,
          username: username.trim() || null,
          phone: phone.trim() || null,
          dni: dni.trim() || null,
          university: university.trim() || null,
          description: description.trim() || null,
          identifiers: identifiers.filter((item) => item.value.trim()).map((item) => ({ ...item, value: item.value.trim() })),
        },
        strategy,
        self_consent: selfConsent,
        maigret_plan: { scan_mode: scanMode, options: { parse: extract, enrich: extract && enrich, permutation_parts: parts } },
      });

      router.push(`/investigation/${inv.id}`);
    } catch (err: unknown) {
      setError(
        err instanceof Error
          ? err.message
          : "Error al despachar la investigación. Comprueba que el backend esté activo."
      );
      setLoading(false);
    }
  };

  return (
    <div
      id="nueva-auditoria"
      className="panel-card p-5 sm:p-6 shadow-xl relative overflow-hidden border border-[#162234] bg-[#0d1420]"
    >
      {/* Header bar */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between pb-4 border-b border-[#162234] gap-2 mb-6">
        <div>
          <h2 className="text-sm sm:text-base font-semibold text-slate-100 flex items-center gap-2">
            <span className="w-2 h-2 rounded-full bg-sky-400 animate-pulse" />
            Consola de Despacho & Reconocimiento OSINT
          </h2>
          <p className="text-xs text-slate-400 mt-0.5">
            Ingresa los identificadores conocidos del objetivo. El motor pivotea desde al menos un dato.
          </p>
        </div>

        <div className="flex items-center gap-1.5 text-[11px] font-mono px-2.5 py-1 rounded bg-[#090f18] text-slate-300 border border-[#1a2636] shrink-0 self-start sm:self-auto">
          <span>Modo:</span>
          <span className="text-sky-400 font-semibold">{selectedStrategy.label}</span>
        </div>
      </div>

      {error && (
        <div className="mb-5 p-3 rounded-lg bg-rose-500/10 border border-rose-500/30 text-rose-300 text-xs flex items-center gap-2.5 animate-fade-in">
          <ShieldAlert className="w-4 h-4 text-rose-400 shrink-0" />
          <span>{error}</span>
        </div>
      )}

      <form onSubmit={handleSubmit} className="space-y-6">
        {/* Sector 1: Identidad Civil y Académica */}
        <div className="space-y-3">
          <div className="flex items-center justify-between">
            <h3 className="text-[11px] font-mono font-semibold uppercase tracking-wider text-sky-400 flex items-center gap-1.5">
              <User className="w-3.5 h-3.5" />
              1. Identidad Civil & Afiliación
            </h3>
            {/*<span className="text-[10px] font-mono text-slate-500">
              Desambiguación
            </span>*/}
          </div>

          <div className="grid grid-cols-1 md:grid-cols-3 gap-3.5">
            <div>
              <label className="block text-xs font-mono text-slate-300 mb-1.5 flex items-center gap-1.5">
                Nombre Completo
              </label>
              <input
                type="text"
                placeholder="Ej: Jane Doe"
                value={fullName}
                onChange={(e) => setFullName(e.target.value)}
                className="w-full bg-[#080d15] border border-[#1a2636] focus:border-sky-500 rounded-lg px-3 py-2 text-xs text-slate-200 placeholder-slate-600 outline-none transition-colors font-mono"
              />
            </div>

            <div>
              <label className="block text-xs font-mono text-slate-300 mb-1.5 flex items-center justify-between">
                <span className="flex items-center gap-1.5">
                  <FileText className="w-3.5 h-3.5 text-slate-400" />
                  DNI (Perú)
                </span>
                {dni.length > 0 && (
                  <span
                    className={`text-[10px] font-mono ${
                      dni.length === 8 ? "text-emerald-400" : "text-amber-400"
                    }`}
                  >
                    {dni.length}/8
                  </span>
                )}
              </label>
              <input
                type="text"
                placeholder="8 dígitos numéricos"
                value={dni}
                onChange={(e) => handleDniChange(e.target.value)}
                maxLength={8}
                className="w-full bg-[#080d15] border border-[#1a2636] focus:border-sky-500 rounded-lg px-3 py-2 text-xs text-slate-200 placeholder-slate-600 outline-none transition-colors font-mono"
              />
            </div>

            <div>
              <label className="block text-xs font-mono text-slate-300 mb-1.5 flex items-center gap-1.5">
                <GraduationCap className="w-3.5 h-3.5 text-slate-400" />
                Universidad / Institución
              </label>
              <input
                type="text"
                placeholder="Ej: UNMSM, UNI, PUCP..."
                value={university}
                onChange={(e) => setUniversity(e.target.value)}
                className="w-full bg-[#080d15] border border-[#1a2636] focus:border-sky-500 rounded-lg px-3 py-2 text-xs text-slate-200 placeholder-slate-600 outline-none transition-colors font-mono"
              />
            </div>
          </div>
        </div>

        {/* Sector 2: Pivotes Digitales y Comunicación */}
        <div className="space-y-3 pt-2 border-t border-[#162234]">
          <div className="flex items-center justify-between">
            <h3 className="text-[11px] font-mono font-semibold uppercase tracking-wider text-sky-400 flex items-center gap-1.5">
              <AtSign className="w-3.5 h-3.5" />
              2. Pivotes digitales y perfiles
            </h3>
            {/*<span className="text-[10px] font-mono text-slate-500">
              Sensores masivos
            </span>*/} 
          </div>

          <div className="grid grid-cols-1 md:grid-cols-3 gap-3.5">
            <div>
              <label className="block text-xs font-mono text-slate-300 mb-1.5 flex items-center gap-1.5">
                <Mail className="w-3.5 h-3.5 text-slate-400" />
                Correo Institucional o Personal
              </label>
              <input
                type="email"
                placeholder="Ej: j.doe@universidad.edu.pe o personal@gmail.com"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                className="w-full bg-[#080d15] border border-[#1a2636] focus:border-sky-500 rounded-lg px-3 py-2 text-xs text-slate-200 placeholder-slate-600 outline-none transition-colors font-mono"
              />
            </div>

            <div>
              <label className="block text-xs font-mono text-slate-300 mb-1.5 flex items-center gap-1.5">
                <AtSign className="w-3.5 h-3.5 text-slate-400" />
                Alias / Nombre de Usuario
              </label>
              <input
                type="text"
                placeholder="Ej: janedoe"
                value={username}
                onChange={(e) => handleUsernameChange(e.target.value)}
                className="w-full bg-[#080d15] border border-[#1a2636] focus:border-sky-500 rounded-lg px-3 py-2 text-xs text-slate-200 placeholder-slate-600 outline-none transition-colors font-mono"
              />
            </div>

            <div>
              <label className="block text-xs font-mono text-slate-300 mb-1.5 flex items-center gap-1.5">
                <Phone className="w-3.5 h-3.5 text-slate-400" />
                Teléfono / Móvil (Opcional)
              </label>
              <input
                type="tel"
                placeholder="Ej: +51 912345678"
                value={phone}
                onChange={(e) => setPhone(e.target.value)}
                className="w-full bg-[#080d15] border border-[#1a2636] focus:border-sky-500 rounded-lg px-3 py-2 text-xs text-slate-200 placeholder-slate-600 outline-none transition-colors font-mono"
              />
            </div>
          </div>

          <details className="rounded-lg border border-[#1a2636] bg-[#090f18] p-3.5">
            <summary className="cursor-pointer text-xs font-mono text-sky-300 focus-visible:outline focus-visible:outline-sky-400">Maigret · IDs de perfiles y alcance de búsqueda</summary>
            <div className="mt-4 space-y-4">
              <p className="text-[11px] text-slate-400">Un ID puede iniciar la investigación. Conservamos su tipo; las coincidencias se evalúan como candidatos.</p>
              {identifiers.map((item, index) => (
                <div key={index} className="grid grid-cols-1 sm:grid-cols-[1fr_2fr_auto] gap-2 items-end">
                  <div>
                    <label htmlFor={`maigret-type-${index}`} className="block text-xs text-slate-300 mb-1.5">Tipo de ID</label>
                    <select id={`maigret-type-${index}`} value={item.id_type} onChange={(event) => setIdentifiers((current) => current.map((entry, position) => position === index ? { ...entry, id_type: event.target.value as TypedIdentifier["id_type"] } : entry))} className="w-full rounded-lg border border-[#1a2636] bg-[#080d15] px-3 py-2 text-xs text-slate-200 focus:outline-none focus:border-sky-500">
                      {IDENTIFIER_OPTIONS.map((option) => <option key={option.id} value={option.id}>{option.label}</option>)}
                    </select>
                  </div>
                  <div>
                    <label htmlFor={`maigret-value-${index}`} className="block text-xs text-slate-300 mb-1.5">Identificador</label>
                    <input id={`maigret-value-${index}`} maxLength={100} value={item.value} placeholder={IDENTIFIER_OPTIONS.find((option) => option.id === item.id_type)?.example} onChange={(event) => setIdentifiers((current) => current.map((entry, position) => position === index ? { ...entry, value: event.target.value } : entry))} className="w-full rounded-lg border border-[#1a2636] bg-[#080d15] px-3 py-2 text-xs font-mono text-slate-200 placeholder:text-slate-600 focus:outline-none focus:border-sky-500" />
                  </div>
                  <button type="button" disabled={identifiers.length === 1} onClick={() => setIdentifiers((current) => current.filter((_, position) => position !== index))} aria-label={`Quitar identificador ${index + 1}`} className="rounded-lg border border-[#1a2636] px-3 py-2 text-xs text-slate-400 hover:text-rose-300 disabled:opacity-30 focus-visible:outline focus-visible:outline-sky-400">Quitar</button>
                </div>
              ))}
              <button type="button" disabled={identifiers.length >= 30} onClick={() => setIdentifiers((current) => [...current, { value: "", id_type: "orcid" }])} className="text-xs text-sky-300 hover:text-sky-200 disabled:opacity-40 focus-visible:outline focus-visible:outline-sky-400">Añadir otro ID</button>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 border-t border-[#162234] pt-4">
                <div>
                  <label htmlFor="maigret-scope" className="block text-xs text-slate-300 mb-1.5">Alcance por usuario</label>
                  <select id="maigret-scope" value={scanMode} onChange={(event) => setScanMode(event.target.value as MaigretScanMode)} className="w-full rounded-lg border border-[#1a2636] bg-[#080d15] px-3 py-2 text-xs text-slate-200 focus:outline-none focus:border-sky-500">
                    <option value="fast">Rápido · primeras plataformas</option>
                    <option value="deep">Habitual · límite configurado</option>
                    <option value="all">Completo{catalogueSize ? ` · ${catalogueSize.toLocaleString("es-PE")} recetas` : " · todo el catálogo"}</option>
                  </select>
                  <p className="mt-1.5 text-[11px] text-slate-500">El modo completo incluye recetas alternativas y tarda más. Mantiene el límite de usuarios por investigación.</p>
                </div>
                <div className="space-y-2.5 text-xs text-slate-300">
                  <label className="flex gap-2 items-center"><input type="checkbox" checked={extract} onChange={(event) => setExtract(event.target.checked)} className="accent-sky-500" />Extraer información de perfiles</label>
                  <label className="flex gap-2 items-center"><input type="checkbox" checked={enrich} disabled={!extract} onChange={(event) => setEnrich(event.target.checked)} className="accent-sky-500" />Ampliar datos y enlaces encontrados</label>
                </div>
              </div>
              <div>
                <label htmlFor="maigret-parts" className="block text-xs text-slate-300 mb-1.5">Combinar fragmentos de usuario (opcional)</label>
                <input id="maigret-parts" value={permutationParts} onChange={(event) => setPermutationParts(event.target.value)} maxLength={300} placeholder="jane, doe" className="w-full rounded-lg border border-[#1a2636] bg-[#080d15] px-3 py-2 text-xs font-mono text-slate-200 placeholder:text-slate-600 focus:outline-none focus:border-sky-500" />
                <p className="mt-1.5 text-[11px] text-slate-500">Hasta tres fragmentos separados por comas. Las variantes no demuestran pertenencia.</p>
              </div>
            </div>
          </details>

          <div>
            <label className="block text-xs font-mono text-slate-300 mb-1.5 flex items-center gap-1.5">
              <Sparkles className="w-3.5 h-3.5 text-amber-400" />
              Contexto / Observaciones Previas (Enriquecimiento para el Agente IA)
            </label>
            <input
              type="text"
              placeholder="Ej: Estudiante de Sistemas, suele publicar código en GitHub sobre seguridad y redes..."
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              className="w-full bg-[#080d15] border border-[#1a2636] focus:border-sky-500 rounded-lg px-3 py-2 text-xs text-slate-200 placeholder-slate-600 outline-none transition-colors font-mono"
            />
          </div>
        </div>

        {/* Sector 3: Matriz de Motores de Orquestación */}
        <div className="space-y-3 pt-2 border-t border-[#162234]">
          <div className="flex items-center justify-between">
            <h3 className="text-[11px] font-mono font-semibold uppercase tracking-wider text-sky-400 flex items-center gap-1.5">
              <Cpu className="w-3.5 h-3.5" />
              3. Modo de Orquestación
            </h3>
            {/*<span className="text-[10px] font-mono text-slate-500">
              Estrategia experimental
            </span>*/}
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-2.5">
            {STRATEGY_OPTIONS.map((opt) => {
              const Icon = opt.icon;
              const isSelected = strategy === opt.id;
              const hasLlmIssue = opt.needsLlm && aiEnabled === false;

              return (
                <button
                  key={opt.id}
                  type="button"
                  onClick={() => setStrategy(opt.id)}
                  className={`p-3 rounded-lg border text-left transition-all flex flex-col justify-between ${
                    isSelected
                      ? "bg-[#142032] border-sky-500/50 shadow-md shadow-sky-950/40"
                      : "bg-[#090f18] border-[#1a2636] hover:border-[#26374d] hover:bg-[#0c1420]"
                  }`}
                >
                  <div>
                    <div className="flex items-center justify-between gap-1 mb-1.5">
                      <div className="flex items-center gap-1.5">
                        <Icon
                          className={`w-3.5 h-3.5 ${
                            isSelected ? "text-sky-400" : "text-slate-400"
                          }`}
                        />
                        <span className="font-mono text-xs font-semibold text-slate-200">
                          {opt.label}
                        </span>
                      </div>
                      {isSelected && (
                        <Check className="w-3.5 h-3.5 text-sky-400 shrink-0" />
                      )}
                    </div>

                    <p className="text-[10px] font-mono text-slate-400 leading-snug">
                      {opt.tagline}
                    </p>
                  </div>

                  <div className="mt-2.5 pt-2 border-t border-[#162234]/70 flex items-center justify-between">
                    <span className="text-[9px] font-mono px-1.5 py-0.5 rounded bg-[#0d1522] border border-[#1d2c42] text-slate-400">
                      {opt.badge}
                    </span>
                    {hasLlmIssue && (
                      <span
                        title="No hay LLM configurado en el backend; correrá con reglas."
                        className="text-[9px] font-mono text-amber-400"
                      >
                        Degrada a reglas
                      </span>
                    )}
                  </div>
                </button>
              );
            })}
          </div>

          <p className="text-[11px] font-mono text-slate-400 leading-relaxed bg-[#090f18] p-2.5 rounded-lg border border-[#162234]">
            <strong className="text-slate-300">{selectedStrategy.label}:</strong>{" "}
            {selectedStrategy.help}
          </p>
        </div>

        {/* Sector 4: Marco Ético y Consentimiento para Infostealers */}
        <div className="p-3.5 rounded-lg bg-[#140d0d] border border-red-500/30">
          <label
            htmlFor="self-consent-cb"
            className="flex items-start gap-3 cursor-pointer select-none"
          >
            <input
              id="self-consent-cb"
              type="checkbox"
              checked={selfConsent}
              onChange={(e) => setSelfConsent(e.target.checked)}
              className="mt-0.5 w-4 h-4 shrink-0 accent-red-500 cursor-pointer"
            />
            <div className="min-w-0">
              <span className="text-xs font-mono font-semibold text-red-200 flex items-center gap-1.5">
                <ShieldAlert className="w-3.5 h-3.5 text-red-400 shrink-0" />
                Autorización de Auditoría de Credenciales Expuestas (Infostealers)
              </span>
              <p className="text-[11px] text-slate-400 mt-1 leading-relaxed">
                Habilita la consulta de registros en bases de datos de{" "}
                <strong className="text-slate-300">infostealers</strong> (equipos comprometidos por malware con contraseñas de sesión sustraídas). Esta consulta envía el correo o alias a un servicio externo de monitoreo y solo debe ejecutarse sobre uno mismo o con consentimiento explícito. Sin marcarla, esta fuente queda omitida.
              </p>
            </div>
          </label>
        </div>

        {/* Action Bar */}
        <div className="pt-4 flex items-center justify-end border-t border-[#162234]">
          <button
            type="submit"
            disabled={loading}
            className="w-full sm:w-auto flex items-center justify-center gap-2 px-6 py-2.5 rounded-lg bg-sky-600 hover:bg-sky-500 disabled:opacity-50 text-white text-xs font-mono font-semibold transition-all shadow-lg shadow-sky-950/50 cursor-pointer"
          >
            {loading ? (
              <>
                <span className="w-3.5 h-3.5 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                <span>Despachando...</span>
              </>
            ) : (
              <>
                <span>Desplegar Reconocimiento OSINT</span>
                <ArrowRight className="w-3.5 h-3.5" />
              </>
            )}
          </button>
        </div>
      </form>
    </div>
  );
}
