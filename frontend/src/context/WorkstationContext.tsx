"use client";

import React, { createContext, useContext, useState, useCallback, useEffect } from "react";
import { usePathname } from "next/navigation";

export interface ActiveInvestigationSummary {
  id: string;
  code: string;
  targetName: string;
  status: "pending" | "running" | "completed" | "failed" | string;
  findingsCount?: number;
  strategy?: string;
  created_at?: string;
}

interface WorkstationContextType {
  theme: "dark" | "light";
  toggleTheme: () => void;
  activeInvestigation: ActiveInvestigationSummary | null;
  setActiveInvestigation: (inv: ActiveInvestigationSummary | null) => void;
  activeTab: string;
  setActiveTab: (tab: string) => void;
  isCommandPaletteOpen: boolean;
  setIsCommandPaletteOpen: (open: boolean) => void;
  toggleCommandPalette: () => void;
  isSidebarOpen: boolean;
  setIsSidebarOpen: (open: boolean) => void;
  toggleSidebar: () => void;
}

const WorkstationContext = createContext<WorkstationContextType | null>(null);
const THEME_STORAGE_KEY = "personmap-theme";

export function WorkstationProvider({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const [theme, setTheme] = useState<"dark" | "light">("dark");
  const [themeLoaded, setThemeLoaded] = useState(false);
  const [activeInvestigation, setActiveInvestigation] = useState<ActiveInvestigationSummary | null>(null);
  const [activeTab, setActiveTab] = useState<string>("graph");
  const [isCommandPaletteOpen, setIsCommandPaletteOpen] = useState(false);
  const [isSidebarOpen, setIsSidebarOpen] = useState(false);

  useEffect(() => {
    try {
      const savedTheme = window.localStorage.getItem(THEME_STORAGE_KEY);
      if (savedTheme === "light" || savedTheme === "dark") {
        setTheme(savedTheme);
        document.documentElement.dataset.theme = savedTheme;
      }
    } catch {
      // La preferencia visual sigue disponible durante la sesión aunque el
      // navegador bloquee el almacenamiento local.
    }
    setThemeLoaded(true);
  }, []);

  useEffect(() => {
    if (!themeLoaded) return;
    document.documentElement.dataset.theme = theme;
    try {
      window.localStorage.setItem(THEME_STORAGE_KEY, theme);
    } catch {
      // El tema activo permanece aplicado al documento durante esta sesión.
    }
  }, [theme, themeLoaded]);

  const toggleTheme = useCallback(() => {
    setTheme((current) => current === "dark" ? "light" : "dark");
  }, []);

  // Cerrar command palette y sidebar móvil al cambiar de ruta
  const [prevPathname, setPrevPathname] = useState(pathname);
  if (prevPathname !== pathname) {
    setPrevPathname(pathname);
    setIsCommandPaletteOpen(false);
    setIsSidebarOpen(false);
  }

  const toggleCommandPalette = useCallback(() => {
    setIsCommandPaletteOpen((prev) => !prev);
  }, []);

  const toggleSidebar = useCallback(() => {
    setIsSidebarOpen((prev) => !prev);
  }, []);

  return (
    <WorkstationContext.Provider
      value={{
        theme,
        toggleTheme,
        activeInvestigation,
        setActiveInvestigation,
        activeTab,
        setActiveTab,
        isCommandPaletteOpen,
        setIsCommandPaletteOpen,
        toggleCommandPalette,
        isSidebarOpen,
        setIsSidebarOpen,
        toggleSidebar,
      }}
    >
      {children}
    </WorkstationContext.Provider>
  );
}

export function useWorkstation() {
  const context = useContext(WorkstationContext);
  if (!context) {
    throw new Error("useWorkstation must be used within a WorkstationProvider");
  }
  return context;
}
