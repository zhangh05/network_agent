import type { ReactNode } from "react";
import { useEffect } from "react";
import { NavLink } from "react-router-dom";
import { useUIStore } from "../stores/session";
import { Sidebar } from "./Sidebar";
import { NAV_ITEMS } from "../config/nav";

interface AppLayoutProps {
  children: ReactNode;
}

/**
 * Two-column app layout using CSS grid.
 * - Sidebar: 280px, collapsible (desktop)
 * - Main: flex-1, scrollable
 * - ≤900px: the sidebar becomes an off-canvas drawer toggled by `mobileNavOpen`
 *   (the hamburger button in the header). A backdrop closes it.
 *
 * v3.9: Inspector panel removed — diagnostics moved inline to Timeline.
 */
export function AppLayout({ children }: AppLayoutProps) {
  const sidebarOpen = useUIStore((s) => s.sidebarOpen);
  const mobileNavOpen = useUIStore((s) => s.mobileNavOpen);
  const setMobileNavOpen = useUIStore((s) => s.setMobileNavOpen);

  const rootClasses = [
    "app-root",
    !sidebarOpen ? "no-sidebar" : "",
    mobileNavOpen ? "mobile-nav-open" : "",
  ].filter(Boolean).join(" ");

  // Lock body scroll + wire Escape-to-close while the drawer is open.
  useEffect(() => {
    if (!mobileNavOpen) return;
    const prevOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setMobileNavOpen(false);
    };
    window.addEventListener("keydown", onKey);
    return () => {
      document.body.style.overflow = prevOverflow;
      window.removeEventListener("keydown", onKey);
    };
  }, [mobileNavOpen, setMobileNavOpen]);

  // Auto-close the drawer when the viewport grows back to desktop size.
  useEffect(() => {
    const mq = window.matchMedia("(min-width: 901px)");
    const onChange = () => {
      if (mq.matches && mobileNavOpen) setMobileNavOpen(false);
    };
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, [mobileNavOpen, setMobileNavOpen]);

  return (
    <div className={rootClasses}>
      <aside
        className={"app-sidebar" + (sidebarOpen ? "" : " collapsed")}
        data-testid="layout-left"
        aria-label="侧栏"
      >
        {(sidebarOpen || mobileNavOpen) && (
          <div className="sidebar-scroll">
            <nav className="mobile-nav" aria-label="页面导航">
              {NAV_ITEMS.map(({ to, label, testid, Icon }) => (
                <NavLink
                  key={to}
                  to={to}
                  data-testid={`mobile-${testid}`}
                  className={({ isActive }) =>
                    "mobile-nav-item" + (isActive ? " active" : "")
                  }
                >
                  <Icon size={15} />
                  <span>{label}</span>
                </NavLink>
              ))}
            </nav>
            <Sidebar />
          </div>
        )}
      </aside>

      {mobileNavOpen && (
        <div
          className="nav-backdrop"
          data-testid="nav-backdrop"
          onClick={() => setMobileNavOpen(false)}
          aria-hidden="true"
        />
      )}

      <section className="app-main" data-testid="layout-center">
        {children}
      </section>
    </div>
  );
}
