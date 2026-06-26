import { BrowserRouter, Navigate, NavLink, Route, Routes } from "react-router-dom";
import { useEffect, useState } from "react";
import { ErrorBoundary } from "../components/ErrorBoundary";
import { AppLayout } from "../layouts/AppLayout";
import { TaskWorkbench } from "../pages/AgentWorkbench/AgentWorkbench";
import { CapabilityCenter } from "../pages/CapabilityCenter/CapabilityCenter";
import { RunsPage } from "../pages/RunsPage/RunsPage";
import { Settings } from "../pages/Settings/Settings";
import { Diagnostics } from "../pages/Diagnostics/Diagnostics";
import { JobsPage } from "../pages/JobsPage/JobsPage";
import { PacketAnalysis } from "../pages/PacketAnalysis/PacketAnalysis";
import { KnowledgeLibrary } from "../pages/KnowledgeLibrary/KnowledgeLibrary";
import { ArtifactCenter } from "../pages/ArtifactCenter/ArtifactCenter";
import { MemoryPage } from "../pages/MemoryPage/MemoryPage";
import { CMDBPage } from "../pages/CMDB/CMDBPage";
import { ReviewCenter } from "../pages/ReviewCenter/ReviewCenter";
import { RuntimeAudit } from "../pages/RuntimeAudit/RuntimeAudit";
import { FileManager } from "../pages/FileManager/FileManager";
import { ToastHost } from "../components/ToastHost";
import { useUIStore } from "../stores/session";
import { systemApi } from "../api";
import {
  IconBox,
  IconChat,
  IconChevronLeft,
  IconChevronRight,
  IconHistory,
  IconLayers,
  IconMoon,
  IconSettings,
  IconSun,
  IconBolt,
  IconShield,
} from "../components/Icon";

const NAV_ITEMS: Array<{ to: string; label: string; testid: string; Icon: typeof IconChat }> = [
  { to: "/workbench", label: "工作台", testid: "nav-workbench", Icon: IconChat },
  { to: "/packet", label: "报文分析", testid: "nav-packet", Icon: IconBolt },
  { to: "/runs", label: "运行", testid: "nav-runs", Icon: IconHistory },
  { to: "/capabilities", label: "能力矩阵", testid: "nav-capabilities", Icon: IconLayers },
  { to: "/jobs", label: "作业", testid: "nav-jobs", Icon: IconBolt },
  { to: "/knowledge", label: "知识库", testid: "nav-knowledge", Icon: IconBox },
  { to: "/artifacts", label: "制品", testid: "nav-artifacts", Icon: IconBox },
  { to: "/memory", label: "记忆", testid: "nav-memory", Icon: IconBox },
  { to: "/cmdb", label: "设备资产", testid: "nav-cmdb", Icon: IconLayers },
  { to: "/diagnostics", label: "系统诊断", testid: "nav-diagnostics", Icon: IconShield },
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
                <ErrorBoundary>
                  <AppLayout cols={3}>
                    <TaskWorkbench />
                  </AppLayout>
                </ErrorBoundary>
              }
            />
            <Route
              path="/packet"
              element={
                <ErrorBoundary>
                  <AppLayout cols={2}>
                    <PacketAnalysis />
                  </AppLayout>
                </ErrorBoundary>
              }
            />
            <Route path="/knowledge" element={
                <ErrorBoundary><AppLayout cols={2}><KnowledgeLibrary /></AppLayout></ErrorBoundary>
              }
            />
            <Route path="/artifacts" element={
                <ErrorBoundary><AppLayout cols={2}><ArtifactCenter /></AppLayout></ErrorBoundary>
              }
            />
            <Route path="/memory" element={
                <ErrorBoundary><AppLayout cols={2}><MemoryPage /></AppLayout></ErrorBoundary>
              }
            />
            <Route path="/cmdb" element={
                <ErrorBoundary><AppLayout cols={2}><CMDBPage /></AppLayout></ErrorBoundary>
              }
            />
            <Route
              path="/capabilities"
              element={
                <ErrorBoundary>
                  <AppLayout cols={2}>
                    <CapabilityCenter />
                  </AppLayout>
                </ErrorBoundary>
              }
            />
            <Route
              path="/jobs"
              element={
                <ErrorBoundary>
                  <AppLayout cols={2}>
                    <JobsPage />
                  </AppLayout>
                </ErrorBoundary>
              }
            />
            <Route
              path="/diagnostics"
              element={
                <ErrorBoundary>
                  <AppLayout cols={1}>
                    <Diagnostics />
                  </AppLayout>
                </ErrorBoundary>
              }
            />
            <Route
              path="/settings"
              element={
                <ErrorBoundary>
                  <AppLayout cols={2}>
                    <Settings />
                  </AppLayout>
                </ErrorBoundary>
              }
            />
            <Route
              path="/runs"
              element={
                <ErrorBoundary>
                  <AppLayout cols={3}>
                    <RunsPage />
                  </AppLayout>
                </ErrorBoundary>
              }
            />
            <Route path="/audit" element={
                <ErrorBoundary><AppLayout cols={2}><RuntimeAudit /></AppLayout></ErrorBoundary>
              }
            />
            <Route path="/reviews" element={
                <ErrorBoundary><AppLayout cols={2}><ReviewCenter /></AppLayout></ErrorBoundary>
              }
            />
            <Route path="/files" element={
                <ErrorBoundary><AppLayout cols={2}><FileManager /></AppLayout></ErrorBoundary>
              }
            />
            <Route path="/" element={<Navigate to="/workbench" replace />} />
            <Route
              path="*"
              element={
                <ErrorBoundary>
                  <AppLayout cols={1}>
                    <div className="hero">
                      <div className="hero-mark">404</div>
                      <h1 className="hero-title">页面不存在</h1>
                      <p className="hero-sub">请通过顶栏导航回到工作台</p>
                    </div>
                  </AppLayout>
                </ErrorBoundary>
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
