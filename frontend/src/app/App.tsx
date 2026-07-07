import { BrowserRouter, Navigate, NavLink, Route, Routes, useLocation } from "react-router-dom";
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
  IconChevronLeft,
  IconChevronRight,
  IconMoon,
  IconSun,
  IconMenu,
} from "../components/Icon";
import { NAV_ITEMS } from "../config/nav";

function formatVersion(version: string): string {
  return version.startsWith("v") ? version : `v${version}`;
}

function AppShell() {
  const [version, setVersion] = useState<string | null>(null);
  const theme = useUIStore((s) => s.theme);
  const setTheme = useUIStore((s) => s.setTheme);
  const sidebarOpen = useUIStore((s) => s.sidebarOpen);
  const toggleSidebar = useUIStore((s) => s.toggleSidebar);
  const mobileNavOpen = useUIStore((s) => s.mobileNavOpen);
  const toggleMobileNav = useUIStore((s) => s.toggleMobileNav);
  const setMobileNavOpen = useUIStore((s) => s.setMobileNavOpen);

  const location = useLocation();

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

  // Close the off-canvas drawer whenever the route changes.
  useEffect(() => {
    setMobileNavOpen(false);
  }, [location.pathname, setMobileNavOpen]);

  return (
    <div className="app-shell">
      <header className="app-header">
        <button
          type="button"
          className="nav-toggle"
          data-testid="btn-mobile-nav"
          aria-label={mobileNavOpen ? "关闭导航" : "打开导航"}
          aria-expanded={mobileNavOpen}
          aria-controls="layout-left"
          onClick={toggleMobileNav}
        >
          {mobileNavOpen ? <IconChevronLeft size={16} /> : <IconMenu size={16} />}
        </button>

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
          aria-expanded={sidebarOpen}
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
      </header>

      <div className="app-main">
        <Routes>
          <Route
            path="/workbench"
            element={
              <ErrorBoundary>
                <AppLayout>
                  <TaskWorkbench />
                </AppLayout>
              </ErrorBoundary>
            }
          />
          <Route
            path="/packet"
            element={
              <ErrorBoundary>
                <AppLayout>
                  <PacketAnalysis />
                </AppLayout>
              </ErrorBoundary>
            }
          />
          <Route path="/knowledge" element={
              <ErrorBoundary><AppLayout><KnowledgeLibrary /></AppLayout></ErrorBoundary>
            }
          />
          <Route path="/artifacts" element={
              <ErrorBoundary><AppLayout><ArtifactCenter /></AppLayout></ErrorBoundary>
            }
          />
          <Route path="/memory" element={
              <ErrorBoundary><AppLayout><MemoryPage /></AppLayout></ErrorBoundary>
            }
          />
          <Route path="/cmdb" element={
            <ErrorBoundary><AppLayout><CMDBPage /></AppLayout></ErrorBoundary>
          }
          />
          <Route
            path="/capabilities"
            element={
              <ErrorBoundary>
                <AppLayout>
                  <CapabilityCenter />
                </AppLayout>
              </ErrorBoundary>
            }
          />
          <Route
            path="/jobs"
            element={
              <ErrorBoundary>
                <AppLayout>
                  <JobsPage />
                </AppLayout>
              </ErrorBoundary>
            }
          />
          <Route
            path="/diagnostics"
            element={
              <ErrorBoundary>
                <AppLayout>
                  <Diagnostics />
                </AppLayout>
              </ErrorBoundary>
            }
          />
          <Route
            path="/settings"
            element={
              <ErrorBoundary>
                <AppLayout>
                  <Settings />
                </AppLayout>
              </ErrorBoundary>
            }
          />
          <Route
            path="/runs"
            element={
              <ErrorBoundary>
                <AppLayout>
                  <RunsPage />
                </AppLayout>
              </ErrorBoundary>
            }
          />
          <Route path="/audit" element={
              <ErrorBoundary><AppLayout><RuntimeAudit /></AppLayout></ErrorBoundary>
            }
          />
          <Route path="/reviews" element={
              <ErrorBoundary><AppLayout><ReviewCenter /></AppLayout></ErrorBoundary>
            }
          />
          <Route path="/files" element={
              <ErrorBoundary><AppLayout><FileManager /></AppLayout></ErrorBoundary>
            }
          />
          <Route path="/" element={<Navigate to="/workbench" replace />} />
          <Route
            path="*"
            element={
              <ErrorBoundary>
                <AppLayout>
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
      <ToastHost />
    </div>
  );
}

export function App() {
  return (
    <BrowserRouter future={{ v7_relativeSplatPath: true, v7_startTransition: true }}>
      <AppShell />
    </BrowserRouter>
  );
}
