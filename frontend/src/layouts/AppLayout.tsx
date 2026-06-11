import type { ReactNode } from "react";
import { useUIStore } from "../stores/session";
import { Sidebar } from "./Sidebar";
import { Inspector } from "./Inspector";

interface AppLayoutProps {
  cols: 1 | 2 | 3;
  children: ReactNode;
}

/**
 * Three-column app layout. Column 1 is always the sidebar.
 * Column 3 is the inspector (used by AgentWorkbench). Other pages
 * skip column 3 by passing `cols={2}` or `cols={1}`.
 */
export function AppLayout({ cols, children }: AppLayoutProps) {
  const { sidebarOpen, inspectorOpen, toggleSidebar, toggleInspector } =
    useUIStore();

  const className =
    "app-body" +
    (cols === 1 ? " cols-1" : cols === 2 ? " cols-2" : "");

  return (
    <main className={className} data-testid="app-layout" data-cols={cols}>
      {cols >= 1 && sidebarOpen && (
        <aside className="col left" data-testid="layout-left">
          <div className="col-header">
            <span>Workspace · Sessions · Runs</span>
            <button
              onClick={toggleSidebar}
              className="btn ghost sm"
              data-testid="btn-toggle-sidebar"
              type="button"
            >
              «
            </button>
          </div>
          <div className="col-body">
            <Sidebar />
          </div>
        </aside>
      )}

      <section className="col" data-testid="layout-center">
        {!sidebarOpen && (
          <button
            onClick={toggleSidebar}
            className="btn ghost sm"
            style={{
              position: "absolute",
              top: 56,
              left: 8,
              zIndex: 10,
            }}
            data-testid="btn-open-sidebar"
            type="button"
          >
            »
          </button>
        )}
        {children}
      </section>

      {cols === 3 && inspectorOpen && (
        <aside className="col right" data-testid="layout-right">
          <div className="col-header">
            <span>Turn Inspector</span>
            <button
              onClick={toggleInspector}
              className="btn ghost sm"
              data-testid="btn-toggle-inspector"
              type="button"
            >
              »
            </button>
          </div>
          <div className="col-body">
            <Inspector />
          </div>
        </aside>
      )}

      {cols === 3 && !inspectorOpen && (
        <button
          onClick={toggleInspector}
          className="btn ghost sm"
          style={{
            position: "absolute",
            top: 56,
            right: 8,
            zIndex: 10,
          }}
          data-testid="btn-open-inspector"
          type="button"
        >
          «
        </button>
      )}
    </main>
  );
}
