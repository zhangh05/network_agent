import { useState, useRef, useEffect, useCallback } from "react";
import { useSessionStore } from "../../stores/session";
import { apiRequest } from "../../api/client";
import "@xterm/xterm/css/xterm.css";

interface SavedDevice {
  device_id: string; name: string; host: string; port: number;
  protocol: string; vendor: string; username: string;
}

interface VendorDef {
  key: string; vendor: string;
}

export function RemoteTerminal({ onClose, initial }: {
  onClose: () => void;
  initial?: { asset_id?: string; host: string; port: number; protocol: string; vendor: string; username: string; password?: string };
}) {
  const wsId = useSessionStore((s) => s.currentWorkspaceId);
  const termRef = useRef<HTMLDivElement>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const xtermRef = useRef<any>(null);
  const fitRef = useRef<any>(null);
  const resizeObserverRef = useRef<ResizeObserver | null>(null);
  // FIX 2: Ref to hold syncResize so cleanup can always access the latest
  // reference even if initTerm hasn't finished assigning it yet.
  const syncResizeRef = useRef<(() => void) | null>(null);
  // FIX 4: Ref to hold the connection timeout timer ID for cleanup.
  const connectTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Form state
  const [protocol, setProtocol] = useState(initial?.protocol || "ssh");
  const [host, setHost] = useState(initial?.host || "");
  const [port, setPort] = useState(String(initial?.port || "22"));
  const [vendor, setVendor] = useState(initial?.vendor || "");
  const [username, setUsername] = useState(initial?.username || "");
  const [password, setPassword] = useState(initial?.password || "");
  const [assetId, setAssetId] = useState(initial?.asset_id || "");
  const [deviceId, setDeviceId] = useState("");

  // Connection state
  const [sessionId, setSessionId] = useState("");
  const sessionIdRef = useRef("");
  const [connected, setConnected] = useState(false);
  const [connecting, setConnecting] = useState(false);
  const connectingRef = useRef(false);
  const [error, setError] = useState("");
  const [devices, setDevices] = useState<SavedDevice[]>([]);
  const [vendors, setVendors] = useState<VendorDef[]>([]);
  const [showDevices, setShowDevices] = useState(false);
  const [showSave, setShowSave] = useState(false);
  const [deviceName, setDeviceName] = useState("");

  // Auto-connect: when opened from a CMDB asset card, skip the form and connect directly.
  const autoConnect = !!(initial?.host && initial?.protocol);
  const xtermReadyRef = useRef(false);

  const loadDevices = useCallback(async () => {
    try {
      const res = await apiRequest<{ ok: boolean; devices: SavedDevice[] }>(
        { method: "GET", url: "/remote/devices", params: { workspace_id: wsId } }
      );
      if (res.ok) setDevices(res.devices || []);
    } catch { /* ignore */ }
  }, [wsId]);

  const loadVendors = useCallback(async () => {
    try {
      const res = await apiRequest<{ ok: boolean; vendors: VendorDef[] }>(
        { method: "GET", url: "/remote/vendors" }
      );
      if (res.ok) setVendors(res.vendors || []);
    } catch { /* ignore */ }
  }, []);

  useEffect(() => { loadDevices(); loadVendors(); }, [loadDevices, loadVendors]);

  // Init xterm
  useEffect(() => {
    let disposed = false;
    let syncResize: (() => void) | null = null;
    const initTerm = async () => {
      const { Terminal } = await import("@xterm/xterm");
      const { FitAddon } = await import("@xterm/addon-fit");
      if (disposed || !termRef.current) return;

      const term = new Terminal({
        theme: { background: "#1e1e2e", foreground: "#cdd6f4", cursor: "#f5e0dc" },
        fontSize: 13, fontFamily: "'JetBrains Mono', 'Fira Code', monospace",
        cursorBlink: true, allowProposedApi: true, convertEol: true, scrollback: 5000,
      });
      const fit = new FitAddon();
      term.loadAddon(fit);
      term.open(termRef.current);
      term.writeln(autoConnect ? "Connecting..." : "Ready. Fill connection settings and click Connect.");
      xtermRef.current = term;
      fitRef.current = fit;

      syncResize = () => {
        if (!termRef.current || disposed) return;
        try {
          fit.fit();
          const ws = wsRef.current;
          const sid = sessionIdRef.current;
          if (ws && ws.readyState === WebSocket.OPEN && sid) {
            ws.send(JSON.stringify({
              type: "resize",
              session_id: sid,
              cols: term.cols,
              rows: term.rows,
            }));
          }
        } catch { /* ignore transient layout races */ }
      };
      // FIX 2: Store syncResize in a ref so cleanup can remove the listener
      // even if the reference hasn't been captured in the closure directly.
      syncResizeRef.current = syncResize;
      resizeObserverRef.current = new ResizeObserver(() => {
        if (syncResizeRef.current) window.requestAnimationFrame(syncResizeRef.current);
      });
      resizeObserverRef.current.observe(termRef.current);
      window.addEventListener("resize", syncResize);
      window.requestAnimationFrame(() => {
        syncResize?.();
        term.focus();
      });

      term.onData((data: string) => {
        const ws = wsRef.current;
        const sid = sessionIdRef.current;
        if (ws && ws.readyState === WebSocket.OPEN && sid) {
          ws.send(JSON.stringify({ type: "input", session_id: sid, data }));
        }
      });

      // Mark xterm fully ready — auto-connect if opened from CMDB asset card
      xtermReadyRef.current = true;
    };
    initTerm();
    return () => {
      disposed = true;
      // FIX 2: Use syncResizeRef.current instead of the local syncResize
      // variable — the local may still be null at cleanup time if it
      // hasn't been assigned yet in the async closure.
      if (syncResizeRef.current) window.removeEventListener("resize", syncResizeRef.current);
      resizeObserverRef.current?.disconnect();
      resizeObserverRef.current = null;
      xtermRef.current?.dispose();
    };
  }, []);

  // Cleanup WebSocket + connection timeout on unmount (FIX 4)
  useEffect(() => {
    return () => {
      // FIX 4: Clear any pending connection timeout timer.
      if (connectTimeoutRef.current) { clearTimeout(connectTimeoutRef.current); connectTimeoutRef.current = null; }
      const ws = wsRef.current;
      if (ws && ws.readyState === WebSocket.OPEN) {
        ws.close();
      }
      wsRef.current = null;
    };
  }, []);

  // Auto-connect: when opened from a CMDB asset card, connect immediately
  // once xterm is ready — skip the manual "连接" button.
  const autoConnectedRef = useRef(false);
  useEffect(() => {
    if (!autoConnect || autoConnectedRef.current || connected || connectingRef.current) return;
    // Poll until xtermRef is ready (import("xterm") is async)
    const interval = setInterval(() => {
      if (xtermReadyRef.current && !autoConnectedRef.current) {
        autoConnectedRef.current = true;
        clearInterval(interval);
        doConnect();
      }
    }, 100);
    // Timeout: give up after 3s (xterm import should be fast)
    const timeout = setTimeout(() => clearInterval(interval), 3000);
    return () => { clearInterval(interval); clearTimeout(timeout); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const doConnect = async () => {
    if (!wsId) { setError("未选择工作区"); return; }
    if (!host) { setError("请输入主机地址"); return; }
    setError(""); setConnecting(true); connectingRef.current = true;
    const term = xtermRef.current;
    if (term) { term.clear(); term.writeln(`Connecting to ${host}:${port}...`); }

    const wsProto = window.location.protocol === "https:" ? "wss:" : "ws:";
    const wsUrl = `${wsProto}//${window.location.host}/ws/remote/terminal`;
    const ws = new WebSocket(wsUrl);
    wsRef.current = ws;

    ws.onopen = () => {
      try { fitRef.current?.fit(); } catch { /* ignore */ }
      const cols = xtermRef.current?.cols || 160;
      const rows = xtermRef.current?.rows || 40;
      ws.send(JSON.stringify({ type: "connect", workspace_id: wsId, host,
        port: parseInt(port) || 22, protocol, username, password, vendor,
        asset_id: assetId, device_id: deviceId, cols, rows }));
    };
    ws.onmessage = (e) => {
      let msg: any;
      try { msg = JSON.parse(e.data); } catch { return; }
      if (msg.type === "connected") {
        sessionIdRef.current = msg.session_id;
        setSessionId(msg.session_id); setConnected(true); setConnecting(false); connectingRef.current = false;
        if (term) { term.clear(); }
        try {
          fitRef.current?.fit();
          ws.send(JSON.stringify({
            type: "resize",
            session_id: msg.session_id,
            cols: term?.cols || 160,
            rows: term?.rows || 40,
          }));
        } catch { /* ignore */ }
        // Wait for banner or display "Connected."
        setTimeout(() => {
          if (term) {
            term.writeln("\x1b[32m═══ 已连接 " + msg.host + " ═══\x1b[0m");
            if (msg.banner) term.write(msg.banner);
            term.focus();
          }
        }, 200);
      } else if (msg.type === "output") {
        if (term) {
          term.write(msg.text);
          term.focus();
        }
      } else if (msg.type === "error") {
        setError(msg.message || "连接失败"); setConnecting(false); connectingRef.current = false;
        if (term) term.writeln(`\r\nError: ${msg.message}`);
      } else if (msg.type === "disconnected") {
        setConnected(false); setSessionId("");
        if (term) term.writeln("\r\nDisconnected.");
      }
    };
    ws.onclose = () => { setConnected(false); setConnecting(false); connectingRef.current = false; };
    ws.onerror = () => {
      setError("WebSocket 连接失败 — 请确认后端已启动 (python3 backend/main.py)");
      setConnecting(false); connectingRef.current = false;
      if (term) term.writeln("\r\n\u26a0\ufe0f WebSocket 连接失败");
    };

    // FIX 4: Connection timeout (15s) — store timer ID so it can be
    // cleared on disconnect or unmount.
    connectTimeoutRef.current = setTimeout(() => {
      connectTimeoutRef.current = null;
      if (ws.readyState !== WebSocket.OPEN && connectingRef.current) {
        ws.close();
        setError("连接超时 — 请检查设备地址和端口是否可达");
        setConnecting(false); connectingRef.current = false;
      }
    }, 15000);
  };

  const doDisconnect = () => {
    // FIX 4: Clear connection timeout timer on manual disconnect.
    if (connectTimeoutRef.current) { clearTimeout(connectTimeoutRef.current); connectTimeoutRef.current = null; }
    const ws = wsRef.current;
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ type: "disconnect", session_id: sessionId }));
      ws.close();
    }
    wsRef.current = null;
    setConnected(false); setSessionId(""); setError("");
    sessionIdRef.current = "";
    xtermRef.current?.writeln("\r\n\u23ed Disconnected.");
  };

  const loadDevice = (d: SavedDevice) => {
    setHost(d.host); setPort(String(d.port)); setProtocol(d.protocol);
    setVendor(d.vendor); setUsername(d.username); setPassword("");
    setAssetId(""); setDeviceId(d.device_id);
    setShowDevices(false);
  };

  const doSaveDevice = async () => {
    try {
      await apiRequest({ method: "POST", url: "/remote/devices",
        data: { workspace_id: wsId, name: deviceName || host, host,
          port: parseInt(port) || 22, protocol, vendor, username, password } });
      setShowSave(false); loadDevices();
    } catch { setError("设备保存失败"); }
  };

  const doDeleteDevice = async (did: string) => {
    try {
      await apiRequest({ method: "DELETE", url: `/remote/devices/${did}`, params: { workspace_id: wsId } });
      loadDevices();
    } catch { setError("设备删除失败"); }
  };

  const inputStyle: React.CSSProperties = {
    padding: "6px 10px", fontSize: "var(--fs-13)", borderRadius: 6,
    border: "1px solid var(--line)", background: "var(--surface)", color: "var(--text)",
    outline: "none", fontFamily: "var(--font-mono)",
  };
  const labelStyle: React.CSSProperties = {
    fontSize: "var(--fs-11)", color: "var(--text-4)", fontWeight: 600,
    textTransform: "uppercase", letterSpacing: "0.5px",
  };

  return (
    <div style={{
      position: "fixed", top: 0, left: 0, right: 0, bottom: 0,
      background: "rgba(0,0,0,0.45)", zIndex: 9999,
      display: "flex", alignItems: "center", justifyContent: "center",
      backdropFilter: "blur(4px)",
    }}>
      <div style={{
        width: "min(92vw, 860px)", height: "min(88vh, 620px)",
        background: "var(--surface)", borderRadius: 14,
        boxShadow: "0 12px 60px rgba(0,0,0,0.3)", display: "flex",
        flexDirection: "column", overflow: "hidden",
      }}>
        {/* Header */}
        <div style={{
          padding: "12px 20px", borderBottom: "1px solid var(--line)",
          display: "flex", alignItems: "center", gap: 10, flexShrink: 0,
          background: "var(--surface-2)",
        }}>
          <span style={{ fontSize: "var(--fs-15)" }}>⌨️</span>
          <span style={{ fontWeight: 700, fontSize: "var(--fs-14)" }}>远程终端</span>
          {connected && (
            <span className="status-pill" style={{ fontSize: "var(--fs-11)", marginLeft: 4 }}>
              <span className="dot ok" />{host}:{port} · {vendor || "auto"}
            </span>
          )}
          {!connected && (
            <span className="status-pill" style={{ fontSize: "var(--fs-11)", marginLeft: 4 }}>
              <span className="dot inactive" />未连接
            </span>
          )}
          <div style={{ flex: 1 }} />
          <button className="btn sm ghost" onClick={onClose} style={{ fontSize: "var(--fs-16)", padding: "2px 8px" }}>✕</button>
        </div>

        {/* Connection form — 2 rows */}
        <div style={{ padding: "10px 20px", borderBottom: "1px solid var(--line-2)", flexShrink: 0 }}>
          {error && (
            <div style={{ color: "var(--danger)", fontSize: "var(--fs-12)", marginBottom: 8 }}>
              {error}
            </div>
          )}
          {/* Row 1: Protocol + Host + Port + Vendor + Connect */}
          <div style={{ display: "flex", gap: 8, alignItems: "flex-end", marginBottom: 8 }}>
            <div style={{ display: "flex", flexDirection: "column", gap: 3, width: 72 }}>
              <span style={labelStyle}>协议</span>
              <select value={protocol} onChange={e => { setProtocol(e.target.value); setPort(e.target.value === "ssh" ? "22" : "23"); }}
                style={{ ...inputStyle, cursor: "pointer" }} disabled={connected}>
                <option value="ssh">SSH</option>
                <option value="telnet">Telnet</option>
              </select>
            </div>
            <div style={{ display: "flex", flexDirection: "column", gap: 3, flex: 2 }}>
              <span style={labelStyle}>主机地址</span>
              <input placeholder="192.168.1.1" value={host} onChange={e => setHost(e.target.value)} style={inputStyle} disabled={connected} autoComplete="off" />
            </div>
            <div style={{ display: "flex", flexDirection: "column", gap: 3, width: 72 }}>
              <span style={labelStyle}>端口</span>
              <input placeholder="22" value={port} onChange={e => setPort(e.target.value)} style={{ ...inputStyle, textAlign: "center" }} type="number" disabled={connected} />
            </div>
            <div style={{ display: "flex", flexDirection: "column", gap: 3, width: 120 }}>
              <span style={labelStyle}>厂商</span>
              <select value={vendor} onChange={e => setVendor(e.target.value)} style={{ ...inputStyle, cursor: "pointer" }} disabled={connected}>
                <option value="">自动识别</option>
                {vendors.map(v => <option key={v.key} value={v.key}>{v.vendor}</option>)}
              </select>
            </div>
            <div style={{ display: "flex", flexDirection: "column", gap: 3, width: 90, justifyContent: "flex-end" }}>
              <span style={labelStyle}>&nbsp;</span>
              {!connected ? (
                <button className="btn primary" onClick={doConnect} disabled={connecting}
                  style={{ width: "100%", fontWeight: 600, padding: "6px 0" }}>
                  {connecting ? "…" : "连接"}
                </button>
              ) : (
                <button className="btn danger" onClick={doDisconnect}
                  style={{ width: "100%", fontWeight: 600, padding: "6px 0" }}>断开</button>
              )}
            </div>
          </div>

          {/* Row 2: Username + Password + actions */}
          <div style={{ display: "flex", gap: 8, alignItems: "flex-end" }}>
            <div style={{ display: "flex", flexDirection: "column", gap: 3, flex: 1 }}>
              <span style={labelStyle}>用户名</span>
              <input
                placeholder={protocol === "telnet" ? "可留空" : "admin"}
                value={username}
                onChange={e => setUsername(e.target.value)}
                style={inputStyle}
                autoComplete="off"
                disabled={connected}
              />
            </div>
            <div style={{ display: "flex", flexDirection: "column", gap: 3, flex: 1 }}>
              <span style={labelStyle}>密码</span>
              <input
                placeholder={protocol === "telnet" ? "可留空，遇到提示可手动输入" : "••••••"}
                type="password"
                value={password}
                onChange={e => setPassword(e.target.value)}
                style={inputStyle}
                autoComplete="off"
                disabled={connected}
              />
            </div>
            <div style={{ display: "flex", gap: 6, alignItems: "flex-end" }}>
              <button className="btn sm ghost" onClick={() => { loadDevices(); setShowDevices(!showDevices); }}
                style={{ height: 34, fontSize: "var(--fs-12)" }}>
                📋 已保存{devices.length > 0 ? ` (${devices.length})` : ""}
              </button>
              {!connected && host && (
                <button className="btn sm ghost" onClick={() => { setDeviceName(host); setShowSave(true); }}
                  style={{ height: 34, fontSize: "var(--fs-12)", whiteSpace: "nowrap" }}>
                  💾 保存
                </button>
              )}
            </div>
          </div>
        </div>

        {/* Save device dialog */}
        {showSave && (
          <div style={{ padding: "8px 20px", borderBottom: "1px solid var(--line-2)", display: "flex", gap: 8, alignItems: "flex-end", flexShrink: 0 }}>
            <div style={{ display: "flex", flexDirection: "column", gap: 3, flex: 1 }}>
              <span style={labelStyle}>设备名称</span>
              <input placeholder="给设备起个名字" value={deviceName} onChange={e => setDeviceName(e.target.value)} style={inputStyle} />
            </div>
            <button className="btn primary sm" onClick={doSaveDevice} style={{ height: 34 }}>保存到列表</button>
            <button className="btn sm ghost" onClick={() => setShowSave(false)} style={{ height: 34 }}>取消</button>
          </div>
        )}

        {/* Device list */}
        {showDevices && (
          <div style={{ padding: "8px 20px", borderBottom: "1px solid var(--line-2)", maxHeight: 140, overflow: "auto", flexShrink: 0 }}>
            <div style={{ ...labelStyle, marginBottom: 6 }}>已保存设备</div>
            {devices.length === 0 && <div style={{ color: "var(--text-4)", fontSize: "var(--fs-12)", padding: "4px 0" }}>暂无已保存设备</div>}
            {devices.map(d => (
              <div key={d.device_id} style={{ display: "flex", alignItems: "center", gap: 8, padding: "4px 0", fontSize: "var(--fs-12)" }}>
                <span style={{ cursor: "pointer", flex: 1, color: "var(--accent)", fontWeight: 500 }}
                  onClick={() => { loadDevice(d); setShowDevices(false); }}>
                  {d.name || d.host} · {d.protocol.toUpperCase()} {d.host}:{d.port} · {d.vendor || "auto"}
                </span>
                <button className="btn sm ghost" onClick={() => doDeleteDevice(d.device_id)} style={{ color: "var(--text-4)", fontSize: "var(--fs-11)", padding: "2px 6px" }}>
                  删除
                </button>
              </div>
            ))}
          </div>
        )}

        {/* Terminal */}
        <div
          style={{
            flex: 1,
            background: "#1e1e2e",
            minHeight: 0,
            overflow: "hidden",
            display: "flex",
          }}
          onClick={() => xtermRef.current?.focus()}
        >
          <div
            ref={termRef}
            className="remote-terminal-host"
            style={{
              flex: 1,
              minWidth: 0,
              minHeight: 0,
              height: "100%",
              padding: "4px 8px",
              boxSizing: "border-box",
              overflow: "hidden",
            }}
          />
        </div>
      </div>
    </div>
  );
}
