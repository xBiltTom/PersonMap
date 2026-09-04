"use client";

import { Fragment, type ReactNode } from "react";

/**
 * Renderizador del subconjunto de Markdown que produce la narrativa del informe.
 *
 * El informe se insertaba tal cual en un `<div>` con `whitespace-pre-line`, así
 * que el usuario veía los `###` y los `**` literales. Es la pantalla que se
 * imprime y se le enseña a la persona investigada — el entregable pedagógico
 * del proyecto — y salía con la sintaxis a la vista.
 *
 * Se implementa aquí en lugar de añadir una dependencia por dos motivos: el
 * texto lo escribe un LLM y conviene controlar exactamente qué se renderiza
 * (aquí solo se construyen elementos de React, nunca HTML, así que no hay vía
 * de inyección posible), y una semana antes de una sustentación no es momento
 * de tocar el lockfile.
 *
 * Cubre lo que el prompt pide al modelo: encabezados `#`/`##`/`###`, listas con
 * `-` o `*`, separadores `---`, `**negrita**`, `*cursiva*` y `` `código` ``.
 * Cualquier otra cosa cae como párrafo, que es el modo de fallo correcto: se
 * lee bien aunque pierda formato.
 */

/** Aplica el formato de línea (negrita, cursiva, código) sin usar HTML. */
function renderInline(text: string, keyPrefix: string): ReactNode[] {
  const out: ReactNode[] = [];
  // Un solo recorrido con alternancia: los grupos capturados van en posiciones
  // impares del split, así que el índice dice qué marcador casó.
  const parts = text.split(/(\*\*[^*]+\*\*|`[^`]+`|\*[^*\n]+\*)/g);

  parts.forEach((part, i) => {
    if (!part) return;
    const key = `${keyPrefix}-${i}`;

    if (part.startsWith("**") && part.endsWith("**") && part.length > 4) {
      out.push(
        <strong key={key} className="text-slate-100 font-semibold">
          {part.slice(2, -2)}
        </strong>
      );
    } else if (part.startsWith("`") && part.endsWith("`") && part.length > 2) {
      out.push(
        <code
          key={key}
          className="px-1 py-0.5 rounded bg-[#0b0f17] border border-[#1e293b] text-sky-300 font-mono text-[0.95em] print:bg-transparent print:border-slate-300 print:text-slate-900"
        >
          {part.slice(1, -1)}
        </code>
      );
    } else if (part.startsWith("*") && part.endsWith("*") && part.length > 2) {
      out.push(
        <em key={key} className="italic">
          {part.slice(1, -1)}
        </em>
      );
    } else {
      out.push(<Fragment key={key}>{part}</Fragment>);
    }
  });

  return out;
}

interface Block {
  type: "h1" | "h2" | "h3" | "hr" | "ul" | "p";
  lines: string[];
}

/** Agrupa las líneas en bloques; las listas y los párrafos absorben las suyas. */
function toBlocks(markdown: string): Block[] {
  const blocks: Block[] = [];
  const lines = markdown.replace(/\r\n/g, "\n").split("\n");

  for (const raw of lines) {
    const line = raw.trimEnd();
    const trimmed = line.trim();
    const last = blocks[blocks.length - 1];

    if (!trimmed) {
      // Una línea en blanco cierra el bloque abierto.
      if (last && (last.type === "ul" || last.type === "p")) {
        blocks.push({ type: "p", lines: [] });
      }
      continue;
    }

    if (/^---+$/.test(trimmed) || /^\*\*\*+$/.test(trimmed)) {
      blocks.push({ type: "hr", lines: [] });
      continue;
    }

    const heading = /^(#{1,6})\s+(.*)$/.exec(trimmed);
    if (heading) {
      const level = heading[1].length;
      blocks.push({
        type: level === 1 ? "h1" : level === 2 ? "h2" : "h3",
        lines: [heading[2]],
      });
      continue;
    }

    const bullet = /^[-*+]\s+(.*)$/.exec(trimmed);
    if (bullet) {
      if (last && last.type === "ul") last.lines.push(bullet[1]);
      else blocks.push({ type: "ul", lines: [bullet[1]] });
      continue;
    }

    if (last && last.type === "p" && last.lines.length > 0) last.lines.push(trimmed);
    else blocks.push({ type: "p", lines: [trimmed] });
  }

  return blocks.filter((b) => b.type === "hr" || b.lines.length > 0);
}

export function Markdown({ children }: { children: string }) {
  const blocks = toBlocks(children);

  return (
    <div className="text-slate-300 text-xs leading-relaxed font-sans space-y-3 print:text-slate-800">
      {blocks.map((block, i) => {
        const key = `b${i}`;

        switch (block.type) {
          case "h1":
            return (
              <h3
                key={key}
                className="text-sm font-bold text-slate-100 pt-2 print:text-slate-900"
              >
                {renderInline(block.lines[0], key)}
              </h3>
            );
          case "h2":
            return (
              <h4
                key={key}
                className="text-xs font-bold uppercase tracking-wide text-sky-300 pt-2 border-b border-[#1e293b] pb-1 print:text-slate-900 print:border-slate-300"
              >
                {renderInline(block.lines[0], key)}
              </h4>
            );
          case "h3":
            return (
              <h5
                key={key}
                className="text-xs font-semibold text-slate-100 pt-1 print:text-slate-900"
              >
                {renderInline(block.lines[0], key)}
              </h5>
            );
          case "hr":
            return (
              <hr key={key} className="border-[#1e293b] print:border-slate-300" />
            );
          case "ul":
            return (
              <ul key={key} className="list-disc pl-5 space-y-1">
                {block.lines.map((line, j) => (
                  <li key={`${key}-${j}`}>{renderInline(line, `${key}-${j}`)}</li>
                ))}
              </ul>
            );
          default:
            return <p key={key}>{renderInline(block.lines.join(" "), key)}</p>;
        }
      })}
    </div>
  );
}
