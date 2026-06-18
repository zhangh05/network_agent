import React from "react";
import ReactDOM from "react-dom/client";
import { App } from "./app/App";
import { ErrorBoundary } from "./components/ErrorBoundary";
import "./styles/global.css";

// Theme initialization — read from localStorage or fall back to
// prefers-color-scheme. We do this BEFORE React mounts so the first
// paint uses the correct tokens and we don't get a flash of unstyled
// (or wrong-themed) content.
(function initTheme() {
  try {
    const stored = localStorage.getItem("ui.theme");
    if (stored === "light" || stored === "dark") {
      document.documentElement.setAttribute("data-theme", stored);
      return;
    }
  } catch {
    /* ignore */
  }
  const prefersDark =
    typeof window !== "undefined" &&
    window.matchMedia &&
    window.matchMedia("(prefers-color-scheme: dark)").matches;
  document.documentElement.setAttribute("data-theme", prefersDark ? "dark" : "light");
})();

const rootEl = document.getElementById("root");
if (!rootEl) {
  throw new Error("Root element #root not found in index.html");
}

ReactDOM.createRoot(rootEl).render(
  <React.StrictMode>
    <ErrorBoundary>
      <App />
    </ErrorBoundary>
  </React.StrictMode>,
);
