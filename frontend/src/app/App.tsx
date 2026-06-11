import { BrowserRouter, Navigate, NavLink, Route, Routes } from "react-router-dom";
import { useEffect } from "react";
import { AppLayout } from "../layouts/AppLayout";
import { AgentWorkbench } from "../pages/AgentWorkbench/AgentWorkbench";
import { KnowledgeLibrary } from "../pages/KnowledgeLibrary/KnowledgeLibrary";
import { ArtifactCenter } from "../pages/ArtifactCenter/ArtifactCenter";
import { ReviewCenter } from "../pages/ReviewCenter/ReviewCenter";
import { CapabilityCenter } from "../pages/CapabilityCenter/CapabilityCenter";
import { RuntimeAudit } from "../pages/RuntimeAudit/RuntimeAudit";
import { Settings } from "../pages/Settings/Settings";
import { ToastHost } from "../components/ToastHost";
import { useUIStore } from "../stores/session";
import { useSessionStore } from "../stores/session";
import { workspacesApi } from "../api";

const NAV_ITEMS: Array<{ to: string; label: string; testid: string }> = [
  { to: "/workbench", label: "Agent", testid: "nav-workbench" },
  { to: "/knowledge", label: "Knowledge", testid: "nav-knowledge" },
  { to: "/artifacts", label: "Artifacts", testid: "nav-artifacts" },
  { to: "/reviews", label: "Reviews", testid: "nav-reviews" },
  { to: "/capabilities", label: "Capabilities", testid: "nav-capabilities" },
  { to: "/audit", label: "Runtime Audit", testid: "nav-audit" },
  { to: "/settings", label: "Settings", testid: "nav-settings" },
];

export function App() {
  const theme = useUIStore((s) => s.theme);

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
  }, [theme]);

  // Hydrate workspaces/session on first mount. Failure is silent
  // — pages render the error state themselves.
  useEffect(() => {
    workspacesApi
      .list()
      .then((res) => {
        const list = res.workspaces ?? [];
        useSessionStore.getState().setWorkspaces(list);
        const cur = useSessionStore.getState().currentWorkspaceId;
        if (!cur && list.length > 0) {
          useSessionStore.getState().setCurrentWorkspace(list[0].workspace_id);
        }
      })
      .catch(() => {
        /* page-level error states handle the rest */
      });
  }, []);

  return (
    <BrowserRouter>
      <div className="app">
        <header className="app-topbar">
          <span className="brand">Network Agent</span>
          <span className="version">v1.0.0 · Workbench</span>
          <nav>
            {NAV_ITEMS.map((n) => (
              <NavLink
                key={n.to}
                to={n.to}
                className={({ isActive }) => (isActive ? "active" : "")}
                data-testid={n.testid}
              >
                {n.label}
              </NavLink>
            ))}
          </nav>
          <div className="actions" />
        </header>
        <Routes>
          <Route
            path="/workbench"
            element={
              <AppLayout cols={3}>
                <AgentWorkbench />
              </AppLayout>
            }
          />
          <Route
            path="/knowledge"
            element={
              <AppLayout cols={2}>
                <KnowledgeLibrary />
              </AppLayout>
            }
          />
          <Route
            path="/artifacts"
            element={
              <AppLayout cols={2}>
                <ArtifactCenter />
              </AppLayout>
            }
          />
          <Route
            path="/reviews"
            element={
              <AppLayout cols={1}>
                <ReviewCenter />
              </AppLayout>
            }
          />
          <Route
            path="/capabilities"
            element={
              <AppLayout cols={1}>
                <CapabilityCenter />
              </AppLayout>
            }
          />
          <Route
            path="/audit"
            element={
              <AppLayout cols={1}>
                <RuntimeAudit />
              </AppLayout>
            }
          />
          <Route
            path="/settings"
            element={
              <AppLayout cols={1}>
                <Settings />
              </AppLayout>
            }
          />
          <Route path="/" element={<Navigate to="/workbench" replace />} />
          <Route
            path="*"
            element={
              <AppLayout cols={1}>
                <div className="state">
                  <div className="icon">404</div>
                  <div className="text">页面不存在</div>
                </div>
              </AppLayout>
            }
          />
        </Routes>
      </div>
      <ToastHost />
    </BrowserRouter>
  );
}
