import type { ReactNode } from "react";
import { useUIStore } from "../stores/session";
import { Sidebar } from "./Sidebar";
import { Inspector } from "./Inspector";

interface AppLayoutProps {
  cols: 1 | 2 | 3;
  children: ReactNode;
}

/**
 * Multi-column app layout. Column 1 is the left sidebar
 * (Workspace / Sessions / Recent Runs). Column 3 is the Turn
 * Inspector (used by AgentWorkbench). Other pages opt out of column 3
 * by passing `cols={2}`; AgentWorkbench is the only one using `cols=3`.
 */
export function AppLayout({ cols, children }: AppLayoutProps) {
  const sidebarOpen = useUIStore((s) => s.sidebarOpen);
  const inspectorOpen = useUIStore((s) => s.inspectorOpen);

  return (
    <>
      <aside
        className={"app-sidebar" + (sidebarOpen ? "" : " collapsed")}
        data-testid="layout-left"
        aria-label="侧栏"
      >
        {sidebarOpen && <Sidebar />}
      </aside>

      <section className="app-content" data-testid="layout-center">
        {children}
      </section>

      {cols === 3 && (
        <aside
          className={"app-inspector" + (inspectorOpen ? "" : " collapsed")}
          data-testid="layout-right"
          aria-label="检查器"
        >
          {inspectorOpen && <Inspector />}
        </aside>
      )}
    </>
  );
}
