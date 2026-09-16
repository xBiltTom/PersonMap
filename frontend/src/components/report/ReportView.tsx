"use client";

import { InvestigationData } from "@/lib/types";
import { FileCheck, Printer, KeyRound, ArrowRight } from "lucide-react";
import Link from "next/link";
import { AwarenessSurveyForm } from "@/components/report/AwarenessSurveyForm";
import { Markdown } from "@/components/report/Markdown";

export function ReportView({ investigation }: { investigation: InvestigationData }) {
  const handlePrint = () => {
    window.print();
  };

  return (
    <div className="space-y-6 print:m-0 print:p-0">
      {/* Print Action Bar (Hidden when printing) */}
      <div className="flex items-center justify-between print:hidden">
        <div>
          <h2 className="text-sm font-bold text-slate-100 font-mono">
            EXPEDIENTE FORENSE // INFORME DE EXPOSICIÓN DIGITAL
          </h2>
          <p className="text-xs text-slate-400">
            Documento de concientización y auditoría de ciberseguridad personal.
          </p>
        </div>

        <button
          onClick={handlePrint}
          className="flex items-center gap-2 px-3.5 py-1.5 rounded-md bg-sky-600 hover:bg-sky-500 text-white text-xs font-mono font-semibold transition-colors shadow"
        >
          <Printer className="w-3.5 h-3.5" />
          <span>Imprimir / Guardar como PDF</span>
        </button>
      </div>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div className="panel-card p-5 flex flex-col justify-between">
          <div className="text-[10px] font-mono uppercase tracking-wider text-slate-400 mb-2">
            Datos de consulta
          </div>
          <div className="text-sm font-bold text-slate-200 truncate">
            {investigation.target?.full_name || investigation.target?.username || "Sin nombre registrado"}
          </div>
          <p className="text-[11px] text-slate-400 mt-2 leading-snug">
            Estos datos iniciaron la búsqueda. No determinan la pertenencia de las observaciones encontradas.
          </p>
        </div>

        <div className="panel-card p-5 flex flex-col justify-between">
          <div className="text-[10px] font-mono uppercase tracking-wider text-slate-400 mb-2">
            Observaciones registradas
          </div>
          <div>
            <div className="text-sm font-bold text-slate-200 truncate">
              {investigation.entities?.length || 0}
            </div>
            <div className="text-xs text-sky-400 font-mono mt-0.5 truncate">
              datos disponibles en el mapa
            </div>
          </div>
          <div className="text-[11px] font-mono text-slate-500 mt-2">
            Consulte sus fuentes y conexiones antes de formular conclusiones.
          </div>
        </div>

      </div>

      {/* Narrative Section */}
      <div className="panel-card p-6">
        <h3 className="text-sm font-semibold text-slate-100 flex items-center gap-2 mb-4 pb-3 border-b border-[#1e293b]">
          <FileCheck className="w-4 h-4 text-sky-400" />
          Informe de Síntesis y Concientización
        </h3>

        {investigation.summary ? (
          // La narrativa llega en Markdown y se insertaba tal cual, así que el
          // informe --la pantalla que se imprime y se le enseña a la persona
          // investigada-- mostraba los `###` y los `**` literales.
          <Markdown>{investigation.summary}</Markdown>
        ) : (
          <div className="text-xs text-slate-500 font-mono italic">
            El resumen se generará una vez culminada la fase de correlación.
          </div>
        )}
      </div>

      <PasswordInvitation
        conBrechas={(investigation.entities || []).some(
          (e) => e.entity_type === "breach" || e.entity_type === "infostealer"
        )}
      />

      {/* El cuestionario cierra el informe: se responde justo después de leer
          los hallazgos y las recomendaciones, que es cuando el cambio de
          percepción que el estudio mide acaba de producirse. */}
      <AwarenessSurveyForm investigationId={investigation.id} />
    </div>
  );
}

/**
 * El puente entre el expediente y la autodefensa.
 *
 * El informe termina diciéndole a una persona que su correo apareció en N
 * brechas, y la pregunta que le surge en ese mismo segundo es "¿y mi
 * contraseña?". Hasta ahora la respuesta estaba en otra pestaña que no tenía
 * por qué encontrar. Ofrecerla aquí no es adorno: es el único punto del
 * recorrido donde la persona ya tiene el motivo delante.
 *
 * **Lo que este bloque NO puede prometer, y por eso lo dice.** El sistema no
 * sabe cuál es su contraseña ni puede averiguarlo: ningún servicio guarda
 * contraseñas en claro, HIBP incluido, que solo indexa hashes. La comprobación
 * exige que la teclee ella. Insinuar lo contrario sería vender exactamente la
 * clase de magia que esta herramienta enseña a desconfiar.
 */
function PasswordInvitation({ conBrechas }: { conBrechas: boolean }) {
  return (
    <div className="panel-card p-5 border-l-4 border-l-amber-400 print:hidden">
      <div className="flex items-start gap-3">
        <div className="w-9 h-9 rounded-lg bg-[#151d2c] border border-[#233044] flex items-center justify-center text-amber-400 shrink-0">
          <KeyRound className="w-4.5 h-4.5" aria-hidden="true" />
        </div>

        <div className="min-w-0">
          <h3 className="text-sm font-semibold text-slate-100">
            {conBrechas
              ? "Tu correo salió en filtraciones. ¿Y tu contraseña?"
              : "¿Y tu contraseña?"}
          </h3>

          <p className="text-xs text-slate-400 mt-1.5 leading-relaxed">
            {conBrechas ? (
              <>
                Este informe dice en qué filtraciones aparece tu correo, pero no
                si la contraseña que usas está en esas listas. Son dos cosas
                distintas: lo que se vende en los foros no son direcciones, son{" "}
                <strong className="text-slate-200">pares correo + contraseña</strong>{" "}
                listos para probar en otros sitios.
              </>
            ) : (
              <>
                Aunque tu correo no haya aparecido en ninguna filtración, la
                contraseña puede estar igualmente en los diccionarios de ataque
                si es una que usa mucha gente.
              </>
            )}
          </p>

          <p className="text-xs text-slate-400 mt-2 leading-relaxed">
            PersonMap{" "}
            <strong className="text-slate-200">no sabe cuál es tu contraseña</strong>{" "}
            y no puede averiguarlo: ningún servicio guarda contraseñas en claro.
            La tienes que escribir tú, y aun así{" "}
            <strong className="text-slate-200">no sale de tu navegador</strong>.
          </p>

          <Link
            href="/seguridad"
            className="mt-3 inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md bg-amber-500/15 text-amber-200 border border-amber-500/40 text-xs font-mono font-semibold hover:bg-amber-500/25 transition-colors"
          >
            <span>Comprobar mi contraseña</span>
            <ArrowRight className="w-3.5 h-3.5" aria-hidden="true" />
          </Link>
        </div>
      </div>
    </div>
  );
}
