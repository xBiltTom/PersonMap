"use client";

import { useEffect, useState } from "react";

/**
 * Último recurso: captura errores lanzados en el propio `layout.tsx`, donde el
 * `error.tsx` de ruta ya no aplica. Debe renderizar sus propias etiquetas
 * `<html>` y `<body>` porque sustituye al layout raíz por completo.
 */
export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  const [theme, setTheme] = useState<"dark" | "light">("dark");

  useEffect(() => {
    try {
      const savedTheme = window.localStorage.getItem("personmap-theme");
      if (savedTheme === "light" || savedTheme === "dark") setTheme(savedTheme);
    } catch {
      // Se conserva la apariencia oscura si el almacenamiento está bloqueado.
    }
  }, []);

  const light = theme === "light";

  return (
    <html lang="es" data-theme={theme}>
      <body
        style={{
          backgroundColor: light ? "#f3f6fa" : "#0b0f17",
          color: light ? "#172b42" : "#f1f5f9",
          colorScheme: light ? "light" : "dark",
          fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace",
          margin: 0,
          minHeight: "100vh",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          padding: "2rem",
        }}
      >
        <div style={{ textAlign: "center", maxWidth: "32rem" }}>
          <h2 style={{ fontSize: "1rem", marginBottom: "0.5rem" }}>
            PERSON-MAP no pudo iniciarse
          </h2>
          <p style={{ fontSize: "0.75rem", color: light ? "#52657b" : "#8b9bb4", lineHeight: 1.6 }}>
            {error.message || "Fallo crítico en el layout raíz de la aplicación."}
          </p>
          <button
            type="button"
            onClick={reset}
            style={{
              marginTop: "1.25rem",
              padding: "0.5rem 1rem",
              borderRadius: "0.375rem",
              border: light ? "1px solid #a8b8c9" : "1px solid #2b3a52",
              backgroundColor: light ? "#ffffff" : "#182334",
              color: light ? "#172b42" : "#e2e8f0",
              fontSize: "0.75rem",
              cursor: "pointer",
            }}
          >
            Reintentar
          </button>
        </div>
      </body>
    </html>
  );
}
