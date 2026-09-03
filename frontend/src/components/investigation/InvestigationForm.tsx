"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { createInvestigation } from "@/lib/api";
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
  SlidersHorizontal,
} from "lucide-react";

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
  const [strategy, setStrategy] = useState("auto");
  const [showAdvanced, setShowAdvanced] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);

    const hasIdentifier =
      fullName.trim() ||
      email.trim() ||
      username.trim() ||
      phone.trim() ||
      dni.trim();

    if (!hasIdentifier) {
      setError("Ingresa al menos un dato identificador del objetivo (nombre, correo, usuario, teléfono o DNI).");
      return;
    }

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
        },
        strategy,
      });

      router.push(`/investigation/${inv.id}`);
    } catch (err: any) {
      setError(err.message || "Error al despachar la investigación.");
      setLoading(false);
    }
  };

  return (
    <div className="panel-card p-6 shadow-xl relative overflow-hidden">
      <div className="flex items-center justify-between pb-5 border-b border-[#1e293b] mb-6">
        <div>
          <h2 className="text-base font-semibold text-slate-100 flex items-center gap-2">
            <span className="w-2 h-2 rounded-full bg-sky-400 animate-pulse"></span>
            Iniciar Nueva Investigación
          </h2>
          <p className="text-xs text-slate-400 mt-0.5">
            Ingresa los identificadores conocidos del objetivo. El motor pivotea desde al menos 1 dato.
          </p>
        </div>

        <div className="flex items-center gap-1.5 text-[11px] font-mono px-2.5 py-1 rounded bg-[#182334] text-slate-300 border border-[#2b3a52]">
          <span>Estrategia:</span>
          <span className="text-sky-400 font-semibold uppercase">{strategy}</span>
        </div>
      </div>

      {error && (
        <div className="mb-6 p-3.5 rounded-md bg-rose-500/10 border border-rose-500/20 text-rose-300 text-xs flex items-center gap-2">
          <ShieldAlert className="w-4 h-4 text-rose-400 shrink-0" />
          <span>{error}</span>
        </div>
      )}

      <form onSubmit={handleSubmit} className="space-y-4">
        {/* Core Primary Inputs */}
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <div>
            <label className="block text-xs font-mono text-slate-300 mb-1.5 flex items-center gap-1.5">
              <User className="w-3.5 h-3.5 text-sky-400" />
              Nombre Completo
            </label>
            <input
              type="text"
              placeholder="Ej: Carlos Eduardo Mendoza"
              value={fullName}
              onChange={(e) => setFullName(e.target.value)}
              className="w-full bg-[#0b0f17] border border-[#1e293b] rounded-md px-3.5 py-2.5 text-sm text-slate-200 placeholder-slate-600 focus:outline-none focus:border-sky-500 transition-colors"
            />
          </div>

          <div>
            <label className="block text-xs font-mono text-slate-300 mb-1.5 flex items-center gap-1.5">
              <Mail className="w-3.5 h-3.5 text-sky-400" />
              Correo Institucional o Personal
            </label>
            <input
              type="email"
              placeholder="Ej: alumno@uni.edu.pe o gmail"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="w-full bg-[#0b0f17] border border-[#1e293b] rounded-md px-3.5 py-2.5 text-sm text-slate-200 placeholder-slate-600 focus:outline-none focus:border-sky-500 transition-colors"
            />
          </div>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <div>
            <label className="block text-xs font-mono text-slate-300 mb-1.5 flex items-center gap-1.5">
              <AtSign className="w-3.5 h-3.5 text-sky-400" />
              Alias / Nombre de Usuario
            </label>
            <input
              type="text"
              placeholder="Ej: cmendoza_dev"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              className="w-full bg-[#0b0f17] border border-[#1e293b] rounded-md px-3.5 py-2.5 text-sm text-slate-200 placeholder-slate-600 focus:outline-none focus:border-sky-500 transition-colors"
            />
          </div>

          <div>
            <label className="block text-xs font-mono text-slate-300 mb-1.5 flex items-center gap-1.5">
              <GraduationCap className="w-3.5 h-3.5 text-sky-400" />
              Universidad / Facultad
            </label>
            <input
              type="text"
              placeholder="Ej: UNI, UNMSM, PUCP..."
              value={university}
              onChange={(e) => setUniversity(e.target.value)}
              className="w-full bg-[#0b0f17] border border-[#1e293b] rounded-md px-3.5 py-2.5 text-sm text-slate-200 placeholder-slate-600 focus:outline-none focus:border-sky-500 transition-colors"
            />
          </div>

          <div>
            <label className="block text-xs font-mono text-slate-300 mb-1.5 flex items-center gap-1.5">
              <FileText className="w-3.5 h-3.5 text-sky-400" />
              DNI (Perú)
            </label>
            <input
              type="text"
              placeholder="8 dígitos numéricos"
              value={dni}
              onChange={(e) => setDni(e.target.value)}
              maxLength={8}
              className="w-full bg-[#0b0f17] border border-[#1e293b] rounded-md px-3.5 py-2.5 text-sm text-slate-200 placeholder-slate-600 focus:outline-none focus:border-sky-500 transition-colors"
            />
          </div>
        </div>

        {/* Toggle Advanced / Context details */}
        <div>
          <button
            type="button"
            onClick={() => setShowAdvanced(!showAdvanced)}
            className="text-xs font-mono text-slate-400 hover:text-sky-400 flex items-center gap-1.5 py-1 transition-colors"
          >
            <SlidersHorizontal className="w-3 h-3" />
            <span>{showAdvanced ? "Ocultar parámetros avanzados" : "Añadir teléfono, contexto y elegir motor"}</span>
          </button>
        </div>

        {showAdvanced && (
          <div className="p-4 rounded-md bg-[#0d121c] border border-[#1e293b] space-y-4 animate-in fade-in duration-200">
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div>
                <label className="block text-xs font-mono text-slate-300 mb-1.5 flex items-center gap-1.5">
                  <Phone className="w-3.5 h-3.5 text-sky-400" />
                  Teléfono / Móvil
                </label>
                <input
                  type="tel"
                  placeholder="Ej: +51 987654321"
                  value={phone}
                  onChange={(e) => setPhone(e.target.value)}
                  className="w-full bg-[#0b0f17] border border-[#1e293b] rounded-md px-3.5 py-2 text-sm text-slate-200 placeholder-slate-600 focus:outline-none focus:border-sky-500 transition-colors"
                />
              </div>

              <div>
                <label className="block text-xs font-mono text-slate-300 mb-1.5">
                  Modo de Orquestación
                </label>
                <select
                  value={strategy}
                  onChange={(e) => setStrategy(e.target.value)}
                  className="w-full bg-[#0b0f17] border border-[#1e293b] rounded-md px-3 py-2 text-xs text-slate-200 focus:outline-none focus:border-sky-500"
                >
                  <option value="auto">Automático (Usa IA si hay LLM configurado, o motor por reglas)</option>
                  <option value="rule_based">Reglas Estáticas (Código puro sin IA - Comparativa Paper)</option>
                  <option value="agentic">Agente Autónomo IA (Requiere LLM configurado)</option>
                </select>
              </div>
            </div>

            <div>
              <label className="block text-xs font-mono text-slate-300 mb-1.5 flex items-center gap-1.5">
                <Sparkles className="w-3.5 h-3.5 text-amber-400" />
                Descripción de Contexto (Opcional - enriquecimiento semántico del Agente IA)
              </label>
              <textarea
                rows={2}
                placeholder="Ej: Estudiante de VIII ciclo, suele subir proyectos en GitHub sobre seguridad y publica artículos de investigación en congresos."
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                className="w-full bg-[#0b0f17] border border-[#1e293b] rounded-md p-3 text-xs text-slate-200 placeholder-slate-600 focus:outline-none focus:border-sky-500 transition-colors"
              />
            </div>
          </div>
        )}

        <div className="pt-3 flex items-center justify-between">
          <p className="text-[11px] text-slate-500 font-mono">
            * Consulta exclusivamente fuentes de acceso público bajo consentimiento ético.
          </p>

          <button
            type="submit"
            disabled={loading}
            className="flex items-center gap-2 px-5 py-2.5 rounded-md bg-sky-600 hover:bg-sky-500 disabled:opacity-50 text-white text-xs font-mono font-semibold transition-all shadow-lg shadow-sky-950/50"
          >
            {loading ? (
              <>
                <span className="w-3.5 h-3.5 border-2 border-white/30 border-t-white rounded-full animate-spin"></span>
                <span>Despachando...</span>
              </>
            ) : (
              <>
                <span>Desplegar Reconocimiento</span>
                <ArrowRight className="w-3.5 h-3.5" />
              </>
            )}
          </button>
        </div>
      </form>
    </div>
  );
}
