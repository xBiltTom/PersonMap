import type { Metadata } from "next";
import { Inter, JetBrains_Mono } from "next/font/google";
import { WorkstationProvider } from "@/context/WorkstationContext";
import { WorkstationShell } from "@/components/layout/WorkstationShell";
import "./globals.css";

const sansFont = Inter({
  subsets: ["latin"],
  variable: "--font-sans",
  display: "swap",
});

const monoFont = JetBrains_Mono({
  subsets: ["latin"],
  variable: "--font-mono",
  display: "swap",
});

export const metadata: Metadata = {
  title: "PersonMap // Forensic Intelligence Workstation",
  description:
    "Herramienta forense de fuentes abiertas (OSINT) y concientización de huella digital para estudiantes universitarios.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="es" className={`dark ${sansFont.variable} ${monoFont.variable}`}>
      <body className="min-h-screen bg-[#080c14] text-slate-100 antialiased selection:bg-sky-500 selection:text-white font-sans">
        <WorkstationProvider>
          <WorkstationShell>{children}</WorkstationShell>
        </WorkstationProvider>
      </body>
    </html>
  );
}
