import type { ReactNode } from "react";
import { useUIStore } from "../stores/session";
import { Sidebar } from "./Sidebar";

interface AppLayoutProps {
  children: ReactNode;
}

/**
 * Two-column app layout using CSS grid.
 * - Sidebar: 280px, collapsible
 * - Main: flex-1, scrollable
 *
 * v3.9: Inspector panel removed — diagnostics moved inline to Timeline.
 */
export function AppLayout({ children }: AppLayoutProps) {
  const sidebarOpen = useUIStore((s) => s.sidebarOpen);

  const rootClasses = [
    "app-root",
    !sidebarOpen ? "no-sidebar" : "",
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
    </div>
  );
}
