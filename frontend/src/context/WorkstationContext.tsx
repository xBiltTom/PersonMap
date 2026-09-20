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

export function WorkstationProvider({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const [activeInvestigation, setActiveInvestigation] = useState<ActiveInvestigationSummary | null>(null);
  const [activeTab, setActiveTab] = useState<string>("graph");
  const [isCommandPaletteOpen, setIsCommandPaletteOpen] = useState(false);
  const [isSidebarOpen, setIsSidebarOpen] = useState(false);

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

  // Global keyboard shortcut for ⌘K / Ctrl+K
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        toggleCommandPalette();
      } else if (e.key === "Escape" && isCommandPaletteOpen) {
        setIsCommandPaletteOpen(false);
      }
    };

    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [isCommandPaletteOpen, toggleCommandPalette]);

  return (
    <WorkstationContext.Provider
      value={{
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
