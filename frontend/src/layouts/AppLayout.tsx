import type { ReactNode } from "react";
import { useUIStore } from "../stores/session";
import { Sidebar } from "./Sidebar";
import { Inspector } from "./Inspector";

interface AppLayoutProps {
  cols: 1 | 2 | 3;
  children: ReactNode;
}

/**
 * Multi-column app layout using CSS grid.
 * - Sidebar: 280px, collapsible
 * - Main: flex-1, scrollable
 * - Inspector: 380px slide-in drawer (hidden by default)
 *
 * The workbench page uses cols=3 for inspector support.
 */
export function AppLayout({ cols, children }: AppLayoutProps) {
  const sidebarOpen = useUIStore((s) => s.sidebarOpen);
  const inspectorOpen = useUIStore((s) => s.inspectorOpen);

  const rootClasses = [
    "app-root",
    !sidebarOpen ? "no-sidebar" : "",
    cols === 3 && inspectorOpen ? "with-inspector" : "",
  ].filter(Boolean).join(" ");

  return (
    <div className={rootClasses}>
      <aside
        className={"app-sidebar" + (sidebarOpen ? "" : " collapsed")}
        data-testid="layout-left"
        aria-label="侧栏"
      >
        {sidebarOpen && <Sidebar />}
      </aside>

      <section className="app-main" data-testid="layout-center">
        {children}
      </section>

      {cols === 3 && (
        <aside
          className={"app-inspector" + (inspectorOpen ? " open" : "")}
          data-testid="layout-right"
          aria-label="检查器"
        >
          {inspectorOpen && <Inspector />}
        </aside>
      )}
    </div>
  );
}
