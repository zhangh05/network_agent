import { BrowserRouter, Navigate, NavLink, Route, Routes } from "react-router-dom";
import { useEffect, useState } from "react";
import { AppLayout } from "../layouts/AppLayout";
import { AgentWorkbench } from "../pages/AgentWorkbench/AgentWorkbench";
import { KnowledgeLibrary } from "../pages/KnowledgeLibrary/KnowledgeLibrary";
import { ArtifactCenter } from "../pages/ArtifactCenter/ArtifactCenter";
import { ReviewCenter } from "../pages/ReviewCenter/ReviewCenter";
import { CapabilityCenter } from "../pages/CapabilityCenter/CapabilityCenter";
import { RuntimeAudit } from "../pages/RuntimeAudit/RuntimeAudit";
import { Settings } from "../pages/Settings/Settings";
import { ToastHost } from "../components/ToastHost";
import { useUIStore, useSessionStore } from "../stores/session";
import { systemApi, workspacesApi } from "../api";
import { pickInitialWorkspaceId, shouldReplacePersistedWorkspace } from "../utils/workspace";
import {
  IconBook,
  IconBox,
  IconChat,
  IconCheck,
  IconChevronLeft,
  IconChevronRight,
  IconHistory,
  IconLayers,
  IconMoon,
  IconSettings,
  IconSun,
} from "../components/Icon";

const NAV_ITEMS: Array<{ to: string; label: string; testid: string; Icon: typeof IconChat }> = [
  { to: "/workbench", label: "工作台", testid: "nav-workbench", Icon: IconChat },
  { to: "/knowledge", label: "知识库", testid: "nav-knowledge", Icon: IconBook },
  { to: "/artifacts", label: "制品中心", testid: "nav-artifacts", Icon: IconBox },
  { to: "/reviews", label: "评审中心", testid: "nav-reviews", Icon: IconCheck },
  { to: "/capabilities", label: "能力矩阵", testid: "nav-capabilities", Icon: IconLayers },
  { to: "/audit", label: "运行审计", testid: "nav-audit", Icon: IconHistory },
  { to: "/settings", label: "系统设置", testid: "nav-settings", Icon: IconSettings },
];

export function App() {
  const [version, setVersion] = useState<string | null>(null);
  const theme = useUIStore((s) => s.theme);
  const setTheme = useUIStore((s) => s.setTheme);
  const inspectorOpen = useUIStore((s) => s.inspectorOpen);
  const sidebarOpen = useUIStore((s) => s.sidebarOpen);
  const toggleInspector = useUIStore((s) => s.toggleInspector);
  const toggleSidebar = useUIStore((s) => s.toggleSidebar);

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
  }, [theme]);

  // Hydrate workspaces on first mount; fail silently — page-level
  // error states handle the rest.
  useEffect(() => {
    workspacesApi
      .list()
      .then((res) => {
        const list = res.workspaces ?? [];
        useSessionStore.getState().setWorkspaces(list);
        const cur = useSessionStore.getState().currentWorkspaceId;
        if (list.length > 0 && shouldReplacePersistedWorkspace(cur, list)) {
          useSessionStore.getState().setCurrentWorkspace(pickInitialWorkspaceId(list));
        }
      })
      .catch(() => {
        /* noop */
      });
  }, []);

  useEffect(() => {
    const ctrl = new AbortController();
    systemApi
      .version(ctrl.signal)
      .then((res) => setVersion(res.version || "unknown"))
      .catch(() => setVersion(null));
    return () => ctrl.abort();
  }, []);

  return (
    <BrowserRouter future={{ v7_relativeSplatPath: true, v7_startTransition: true }}>
      <div className="app-shell">
        <header className="app-header">
          <a className="brand" href="/" aria-label="Network Agent · Operations Console">
            <span className="brand-mark" aria-hidden>
              网
            </span>
            <span className="brand-text">
              <span>Network Agent</span>
              <small>Operations Console{version ? ` · ${formatVersion(version)}` : ""}</small>
            </span>
          </a>

          <nav className="app-nav" aria-label="主导航">
            {NAV_ITEMS.map(({ to, label, testid, Icon }) => (
              <NavLink
                key={to}
                to={to}
                data-testid={testid}
                className={({ isActive }) =>
                  "app-nav-item" + (isActive ? " active" : "")
                }
              >
                <Icon size={14} />
                <span>{label}</span>
              </NavLink>
            ))}
          </nav>

          <div className="app-spacer" />

          <span className="status-pill" data-tip="后端 + 前端 + LLM">
            <span className="dot" />
            <span>本地 · 8010 / 5173</span>
          </span>

          <button
            type="button"
            className="collapse-btn"
            data-tip="切换侧栏"
            data-testid="btn-toggle-sidebar"
            aria-label="切换侧栏"
            onClick={toggleSidebar}
          >
            {sidebarOpen ? <IconChevronLeft size={14} /> : <IconChevronRight size={14} />}
          </button>

          <button
            type="button"
            className="theme-toggle"
            data-tip={theme === "dark" ? "切换浅色" : "切换深色"}
            aria-label="切换主题"
            onClick={() => setTheme(theme === "dark" ? "light" : "dark")}
          >
            {theme === "dark" ? <IconSun size={14} /> : <IconMoon size={14} />}
          </button>

          <button
            type="button"
            className="collapse-btn"
            data-tip="切换检查器"
            data-testid={inspectorOpen ? "btn-toggle-inspector" : "btn-open-inspector"}
            aria-label="切换检查器"
            onClick={toggleInspector}
          >
            {inspectorOpen ? <IconChevronRight size={14} /> : <IconChevronLeft size={14} />}
          </button>
        </header>

        <div className="app-main">
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
                <AppLayout cols={2}>
                  <ReviewCenter />
                </AppLayout>
              }
            />
            <Route
              path="/capabilities"
              element={
                <AppLayout cols={2}>
                  <CapabilityCenter />
                </AppLayout>
              }
            />
            <Route
              path="/audit"
              element={
                <AppLayout cols={2}>
                  <RuntimeAudit />
                </AppLayout>
              }
            />
            <Route
              path="/settings"
              element={
                <AppLayout cols={2}>
                  <Settings />
                </AppLayout>
              }
            />
            <Route path="/" element={<Navigate to="/workbench" replace />} />
            <Route
              path="*"
              element={
                <AppLayout cols={1}>
                  <div className="hero">
                    <div className="hero-mark">404</div>
                    <h1 className="hero-title">页面不存在</h1>
                    <p className="hero-sub">请通过顶栏导航回到工作台</p>
                  </div>
                </AppLayout>
              }
            />
          </Routes>
        </div>
      </div>
      <ToastHost />
    </BrowserRouter>
  );
}

function formatVersion(version: string): string {
  return version.startsWith("v") ? version : `v${version}`;
}
