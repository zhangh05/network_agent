/**
 * Agent Inspector Panel — v3.8 debug & monitoring panel.
 * Shows agent graph state, tool catalog, breakpoint manager, and SSE streaming status.
 * Compact slide-out panel accessible from the main workbench.
 */
import React, { useEffect, useState, useCallback } from "react";
import { graphApi, breakpointApi } from "../api";
import type { AgentGraphState } from "../types";

// ── Styles ──
const panel: React.CSSProperties = {
  position: "fixed",
  right: 0,
  top: 0,
  bottom: 0,
  width: 360,
  background: "var(--color-background-primary, #fff)",
  borderLeft: "1px solid var(--color-border-tertiary, #e0e0e0)",
  zIndex: 100,
  display: "flex",
  flexDirection: "column",
  overflow: "hidden",
  boxShadow: "-2px 0 12px rgba(0,0,0,0.08)",
};

const header: React.CSSProperties = {
  padding: "12px 16px",
  borderBottom: "1px solid var(--color-border-tertiary, #e0e0e0)",
  display: "flex",
  justifyContent: "space-between",
  alignItems: "center",
  flexShrink: 0,
};

const body: React.CSSProperties = {
  flex: 1,
  overflow: "auto",
  padding: "12px 16px",
};

const section: React.CSSProperties = {
  marginBottom: 16,
};

const sectionTitle: React.CSSProperties = {
  fontSize: 11,
  fontWeight: 500,
  textTransform: "uppercase",
  color: "var(--color-text-secondary, #888)",
  marginBottom: 8,
  letterSpacing: "0.5px",
};

const badge: React.CSSProperties = {
  display: "inline-block",
  padding: "2px 8px",
  borderRadius: 4,
  fontSize: 11,
  fontWeight: 500,
  marginRight: 4,
  marginBottom: 4,
};

const input: React.CSSProperties = {
  width: "100%",
  padding: "6px 8px",
  border: "1px solid var(--color-border-tertiary, #ddd)",
  borderRadius: 4,
  fontSize: 12,
  boxSizing: "border-box",
};

const btn: React.CSSProperties = {
  padding: "4px 12px",
  borderRadius: 4,
  border: "1px solid var(--color-border-tertiary, #ddd)",
  background: "var(--color-background-secondary, #f5f5f5)",
  cursor: "pointer",
  fontSize: 12,
  fontWeight: 500,
};

const btnPrimary: React.CSSProperties = {
  ...btn,
  background: "#378ADD",
  color: "#fff",
  border: "none",
};

// ── Tool category colors ──
const CAT_COLORS: Record<string, string> = {
  exec: "#D85A30",
  device: "#378ADD",
  workspace: "#1D9E75",
  knowledge: "#534AB7",
  memory: "#993556",
  system: "#BA7517",
  web: "#0F6E56",
  browser: "#639922",
  git: "#D4537E",
  agent: "#888780",
  config: "#185FA5",
  code: "#0C447C",
  data: "#993C1D",
};

// ── Component ──
export const AgentInspector: React.FC<{ onClose: () => void }> = ({ onClose }) => {
  const [state, setState] = useState<AgentGraphState | null>(null);
  const [breakpoints, setBreakpoints] = useState<string[]>([]);
  const [newBp, setNewBp] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const refresh = useCallback(async () => {
    try {
      setLoading(true);
      const [s, bps] = await Promise.all([
        graphApi.state(),
        breakpointApi.list(),
      ]);
      setState(s);
      setBreakpoints(bps.breakpoints || []);
      setError("");
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
    const t = setInterval(refresh, 5000);
    return () => clearInterval(t);
  }, [refresh]);

  const addBreakpoint = async () => {
    if (!newBp.trim()) return;
    const updated = [...breakpoints, newBp.trim()];
    await breakpointApi.set(updated);
    setBreakpoints(updated);
    setNewBp("");
  };

  const removeBreakpoint = async (tool: string) => {
    const updated = breakpoints.filter((b) => b !== tool);
    await breakpointApi.set(updated);
    setBreakpoints(updated);
  };

  const clearBreakpoints = async () => {
    await breakpointApi.clear();
    setBreakpoints([]);
  };

  if (loading && !state) {
    return (
      <div style={panel}>
        <div style={header}>
          <span style={{ fontWeight: 500, fontSize: 14 }}>Agent Inspector</span>
          <button style={btn} onClick={onClose}>✕</button>
        </div>
        <div style={body}>
          <span style={{ color: "#888", fontSize: 12 }}>Loading...</span>
        </div>
      </div>
    );
  }

  return (
    <div style={panel}>
      <div style={header}>
        <div>
          <span style={{ fontWeight: 500, fontSize: 14 }}>Agent Inspector</span>
          <span style={{ fontSize: 11, color: "#888", marginLeft: 8 }}>v3.8</span>
        </div>
        <div style={{ display: "flex", gap: 4 }}>
          <button style={btn} onClick={refresh} title="Refresh">↻</button>
          <button style={btn} onClick={onClose}>✕</button>
        </div>
      </div>

      <div style={body}>
        {error && (
          <div style={{ padding: 8, background: "#FCEBEB", borderRadius: 4, marginBottom: 12, fontSize: 12, color: "#A32D2D" }}>
            {error}
          </div>
        )}

        {/* Graph State */}
        <div style={section}>
          <div style={sectionTitle}>Graph State</div>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }}>
            <StateCard label="Total Tools" value={state?.total_tools} />
            <StateCard label="Core Tools" value={state?.core_tools} />
            <StateCard label="Categories" value={state?.categories?.length} />
            <StateCard label="Checkpoint" value={state?.checkpoint_backend} />
          </div>
        </div>

        {/* Categories */}
        <div style={section}>
          <div style={sectionTitle}>Categories</div>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
            {(state?.categories || []).map((cat) => (
              <span
                key={cat}
                style={{
                  ...badge,
                  background: (CAT_COLORS[cat] || "#888") + "18",
                  color: CAT_COLORS[cat] || "#888",
                  border: `1px solid ${(CAT_COLORS[cat] || "#888")}40`,
                }}
              >
                {cat}
              </span>
            ))}
          </div>
        </div>

        {/* Breakpoints */}
        <div style={section}>
          <div style={sectionTitle}>
            Breakpoints
            <span style={{ fontSize: 11, color: "#888", marginLeft: 4 }}>
              ({breakpoints.length})
            </span>
          </div>
          <div style={{ display: "flex", gap: 4, marginBottom: 8 }}>
            <input
              style={input}
              placeholder="tool_id (e.g. exec.run)"
              value={newBp}
              onChange={(e) => setNewBp(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && addBreakpoint()}
            />
            <button style={btnPrimary} onClick={addBreakpoint}>+</button>
          </div>
          {breakpoints.length > 0 ? (
            <div style={{ maxHeight: 120, overflow: "auto" }}>
              {breakpoints.map((bp) => (
                <div
                  key={bp}
                  style={{
                    display: "flex",
                    justifyContent: "space-between",
                    alignItems: "center",
                    padding: "4px 8px",
                    borderRadius: 4,
                    background: "#FCEBEB",
                    marginBottom: 4,
                    fontSize: 12,
                  }}
                >
                  <code style={{ fontSize: 11 }}>{bp}</code>
                  <button
                    style={{ ...btn, fontSize: 11, padding: "1px 6px", border: "none", background: "transparent", color: "#A32D2D" }}
                    onClick={() => removeBreakpoint(bp)}
                  >
                    ✕
                  </button>
                </div>
              ))}
              <button style={{ ...btn, fontSize: 11, marginTop: 4 }} onClick={clearBreakpoints}>
                Clear all
              </button>
            </div>
          ) : (
            <div style={{ fontSize: 12, color: "#888" }}>
              No breakpoints set. Add tool IDs to pause execution.
            </div>
          )}
        </div>

        {/* SSE Status */}
        <div style={section}>
          <div style={sectionTitle}>SSE Streaming</div>
          <div style={{ fontSize: 12, color: "#888", display: "flex", alignItems: "center", gap: 6 }}>
            <span style={{
              width: 8, height: 8, borderRadius: "50%",
              background: "#1D9E75", display: "inline-block",
            }} />
            Endpoint: /api/agent/sse/stream/:id
          </div>
        </div>

        {/* Runtime Mode */}
        <div style={section}>
          <div style={sectionTitle}>Runtime</div>
          <div style={{ fontSize: 12, color: "#888" }}>
            {localStorage.getItem("agentRuntime") || "turn_runner"} mode
            <span style={{ marginLeft: 8, fontSize: 11, color: "#1D9E75" }}>
              (set AGENT_RUNTIME env to switch)
            </span>
          </div>
        </div>
      </div>
    </div>
  );
};

// ── Helper ──
const StateCard: React.FC<{ label: string; value: unknown }> = ({ label, value }) => (
  <div
    style={{
      padding: "8px 10px",
      borderRadius: 6,
      background: "var(--color-background-secondary, #f5f5f5)",
    }}
  >
    <div style={{ fontSize: 10, color: "#888", marginBottom: 2 }}>{label}</div>
    <div style={{ fontSize: 16, fontWeight: 500 }}>
      {value !== undefined && value !== null ? String(value) : "—"}
    </div>
  </div>
);

export default AgentInspector;
