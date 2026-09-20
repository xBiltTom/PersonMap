"use client";

import React from "react";
import { TopBar } from "./TopBar";
import { Sidebar } from "./Sidebar";
import { CommandPalette } from "./CommandPalette";
import { useWorkstation } from "@/context/WorkstationContext";

export function WorkstationShell({ children }: { children: React.ReactNode }) {
  const { isSidebarOpen, setIsSidebarOpen } = useWorkstation();

  return (
    <div className="min-h-screen flex flex-col bg-[#080c14] text-slate-100 antialiased selection:bg-sky-500 selection:text-white font-sans">
      <TopBar />
      <div className="flex-1 flex w-full relative">
        {/* Mobile backdrop for sidebar */}
        {isSidebarOpen && (
          <div
            className="fixed inset-0 z-20 bg-black/60 md:hidden backdrop-blur-xs"
            onClick={() => setIsSidebarOpen(false)}
          />
        )}
        <Sidebar />
        <main className="flex-1 min-w-0 p-4 sm:p-6 lg:p-7 overflow-x-hidden">
          {children}
        </main>
      </div>
      <CommandPalette />
    </div>
  );
}
