"use client";

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
  return (
    <html lang="es">
      <body
        style={{
          backgroundColor: "#0b0f17",
          color: "#f1f5f9",
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
          <p style={{ fontSize: "0.75rem", color: "#8b9bb4", lineHeight: 1.6 }}>
            {error.message || "Fallo crítico en el layout raíz de la aplicación."}
          </p>
          <button
            type="button"
            onClick={reset}
            style={{
              marginTop: "1.25rem",
              padding: "0.5rem 1rem",
              borderRadius: "0.375rem",
              border: "1px solid #2b3a52",
              backgroundColor: "#182334",
              color: "#e2e8f0",
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
