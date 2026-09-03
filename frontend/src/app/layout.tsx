import type { Metadata } from "next";
import { Navbar } from "@/components/layout/Navbar";
import "./globals.css";

export const metadata: Metadata = {
  title: "PERSON-MAP // Plataforma OSINT de Reconstrucción de Identidad",
  description:
    "Herramienta de análisis de fuentes abiertas y concientización de huella digital para estudiantes universitarios.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="es" className="dark">
      <body className="min-h-screen flex flex-col bg-[#0b0f17] text-slate-100 antialiased selection:bg-sky-500 selection:text-white">
        <Navbar />
        <main className="flex-1 max-w-7xl w-full mx-auto px-4 sm:px-6 lg:px-8 py-8">
          {children}
        </main>
        <footer className="border-t border-[#1e293b] py-6 text-center text-xs font-mono text-slate-500">
          <div className="max-w-7xl mx-auto px-4 flex flex-col sm:flex-row items-center justify-between gap-2">
            <span>PERSON-MAP // Sistema OSINT y Concientización Digital</span>
            <span className="text-slate-600">
              Artículo de Investigación — Seguridad de la Información (Ciclo VIII)
            </span>
          </div>
        </footer>
      </body>
    </html>
  );
}
