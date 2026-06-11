/**
 * Stores — minimal Zustand stores. Holds cross-page state only.
 * Page-local state stays in the page component.
 *
 * Rules:
 *  - No business logic.
 *  - No API calls inside stores (callers do API then setState).
 *  - Persisted state stays minimal (workspace + UI prefs only).
 */

import { create } from "zustand";
import { persist } from "zustand/middleware";
import type { Session, Workspace } from "../types";

interface SessionState {
  currentWorkspaceId: string | null;
  currentSessionId: string | null;
  workspaces: Workspace[];
  sessions: Session[];

  setCurrentWorkspace: (id: string | null) => void;
  setCurrentSession: (id: string | null) => void;
  setWorkspaces: (w: Workspace[]) => void;
  setSessions: (s: Session[]) => void;
  reset: () => void;
}

export const useSessionStore = create<SessionState>()(
  persist(
    (set) => ({
      currentWorkspaceId: null,
      currentSessionId: null,
      workspaces: [],
      sessions: [],
      setCurrentWorkspace: (id) =>
        set({ currentWorkspaceId: id, currentSessionId: null }),
      setCurrentSession: (id) => set({ currentSessionId: id }),
      setWorkspaces: (workspaces) => set({ workspaces }),
      setSessions: (sessions) => set({ sessions }),
      reset: () =>
        set({
          currentWorkspaceId: null,
          currentSessionId: null,
          workspaces: [],
          sessions: [],
        }),
    }),
    {
      name: "na_session",
      partialize: (s) => ({
        currentWorkspaceId: s.currentWorkspaceId,
        currentSessionId: s.currentSessionId,
      }),
    },
  ),
);

interface UIState {
  inspectorOpen: boolean;
  sidebarOpen: boolean;
  theme: "light" | "dark";

  toggleInspector: () => void;
  toggleSidebar: () => void;
  setTheme: (t: "light" | "dark") => void;
}

export const useUIStore = create<UIState>()(
  persist(
    (set, get) => ({
      inspectorOpen: true,
      sidebarOpen: true,
      theme: "light",
      toggleInspector: () => set({ inspectorOpen: !get().inspectorOpen }),
      toggleSidebar: () => set({ sidebarOpen: !get().sidebarOpen }),
      setTheme: (theme) => set({ theme }),
    }),
    {
      name: "na_ui",
      partialize: (s) => ({
        inspectorOpen: s.inspectorOpen,
        sidebarOpen: s.sidebarOpen,
        theme: s.theme,
      }),
    },
  ),
);
