import { useState, useRef, useEffect, useCallback } from "react";
import { useSessionStore } from "../../stores/session";
import { apiRequest } from "../../api/client";
import { Terminal } from "@xterm/xterm";
import { FitAddon } from "@xterm/addon-fit";
import "@xterm/xterm/css/xterm.css";

interface SavedDevice {
  device_id: string; name: string; host: string; port: number;
  protocol: string; vendor: string; username: string;
}

type TerminalMessage =
  | { type: "connected"; session_id: string; host: string; banner?: string }
  | { type: "output"; text: string }
  | { type: "error"; message: string }
  | { type: "disconnected" };

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
  const xtermRef = useRef<Terminal | null>(null);
  const fitRef = useRef<FitAddon | null>(null);
  const resizeObserverRef = useRef<ResizeObserver | null>(null);
  // Keep syncResize in a ref so cleanup can always access the latest
  // reference even if initTerm hasn't finished assigning it yet.
  const syncResizeRef = useRef<(() => void) | null>(null);
  // Keep the connection timeout timer in a ref for cleanup.
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
      // Store syncResize in a ref so cleanup can remove the listener
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
      // Use syncResizeRef.current instead of the local syncResize variable — the local may still be null at cleanup time if it
      // hasn't been assigned yet in the async closure.
      if (syncResizeRef.current) window.removeEventListener("resize", syncResizeRef.current);
      resizeObserverRef.current?.disconnect();
      resizeObserverRef.current = null;
      xtermRef.current?.dispose();
    };
  }, []);

  // Cleanup WebSocket and connection timeout on unmount
  useEffect(() => {
    return () => {
      // Clear any pending connection timeout timer.
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
      let msg: TerminalMessage;
      try { msg = JSON.parse(e.data) as TerminalMessage; } catch { return; }
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

    // Connection timeout (15s) — store timer ID so it can be
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
    // Clear connection timeout timer on manual disconnect.
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

  return (
    <div className="rt-overlay">
      <div className="rt-dialog">
        {/* Header */}
        <div className="rt-header">
          <span className="rt-header-icon">⌨️</span>
          <span className="rt-header-title">远程终端</span>
          {connected && (
            <span className="status-pill rt-status-pill">
              <span className="dot ok" />{host}:{port} · {vendor || "auto"}
            </span>
          )}
          {!connected && (
            <span className="status-pill rt-status-pill">
              <span className="dot inactive" />未连接
            </span>
          )}
          <div className="flex-1" />
          <button className="btn sm ghost rt-header-btn" onClick={onClose}>✕</button>
        </div>

        {/* Connection form — 2 rows */}
        <div className="rt-form-section">
          {error && (
            <div className="rt-error-text">{error}</div>
          )}
          {/* Row 1: Protocol + Host + Port + Vendor + Connect */}
          <div className="rt-row">
            <div className="rt-field rt-field-72">
              <span className="rt-label">协议</span>
              <select className="rt-select" value={protocol} onChange={e => { setProtocol(e.target.value); setPort(e.target.value === "ssh" ? "22" : "23"); }} disabled={connected}>
                <option value="ssh">SSH</option>
                <option value="telnet">Telnet</option>
              </select>
            </div>
            <div className="rt-field flex-1">
              <span className="rt-label">主机地址</span>
              <input className="rt-input" placeholder="192.168.1.1" value={host} onChange={e => setHost(e.target.value)} disabled={connected} autoComplete="off" />
            </div>
            <div className="rt-field rt-field-72">
              <span className="rt-label">端口</span>
              <input className="rt-input-number" placeholder="22" value={port} onChange={e => setPort(e.target.value)} type="number" disabled={connected} />
            </div>
            <div className="rt-field rt-field-120">
              <span className="rt-label">厂商</span>
              <select className="rt-select" value={vendor} onChange={e => setVendor(e.target.value)} disabled={connected}>
                <option value="">自动识别</option>
                {vendors.map(v => <option key={v.key} value={v.key}>{v.vendor}</option>)}
              </select>
            </div>
            <div className="rt-field rt-field-90">
              <span className="rt-label">&nbsp;</span>
              {!connected ? (
                <button className="btn primary rt-connect-btn" onClick={doConnect} disabled={connecting}>
                  {connecting ? "…" : "连接"}
                </button>
              ) : (
                <button className="btn danger rt-connect-btn" onClick={doDisconnect}>断开</button>
              )}
            </div>
          </div>

          {/* Row 2: Username + Password + actions */}
          <div className="rt-row rt-row-last">
            <div className="rt-field flex-1">
              <span className="rt-label">用户名</span>
              <input
                className="rt-input"
                placeholder={protocol === "telnet" ? "可留空" : "admin"}
                value={username}
                onChange={e => setUsername(e.target.value)}
                autoComplete="off"
                disabled={connected}
              />
            </div>
            <div className="rt-field flex-1">
              <span className="rt-label">密码</span>
              <input
                className="rt-input"
                placeholder={protocol === "telnet" ? "可留空，遇到提示可手动输入" : "••••••"}
                type="password"
                value={password}
                onChange={e => setPassword(e.target.value)}
                autoComplete="off"
                disabled={connected}
              />
            </div>
            <div className="rt-btn-row">
              <button className="btn sm ghost rt-btn-icon" onClick={() => { loadDevices(); setShowDevices(!showDevices); }}>
                📋 已保存{devices.length > 0 ? ` (${devices.length})` : ""}
              </button>
              {!connected && host && (
                <button className="btn sm ghost rt-btn-icon" onClick={() => { setDeviceName(host); setShowSave(true); }}>
                  💾 保存
                </button>
              )}
            </div>
          </div>
        </div>

        {/* Save device dialog */}
        {showSave && (
          <div className="rt-save-row">
            <div className="rt-field flex-1">
              <span className="rt-label">设备名称</span>
              <input className="rt-input" placeholder="给设备起个名字" value={deviceName} onChange={e => setDeviceName(e.target.value)} />
            </div>
            <button className="btn primary sm rt-save-btn" onClick={doSaveDevice}>保存到列表</button>
            <button className="btn sm ghost rt-save-btn" onClick={() => setShowSave(false)}>取消</button>
          </div>
        )}

        {/* Device list */}
        {showDevices && (
          <div className="rt-device-list">
            <div className="rt-device-name">已保存设备</div>
            {devices.length === 0 && <div className="rt-device-empty">暂无已保存设备</div>}
            {devices.map(d => (
              <div key={d.device_id} className="rt-device-item">
                <span className="rt-device-link"
                  onClick={() => { loadDevice(d); setShowDevices(false); }}>
                  {d.name || d.host} · {d.protocol.toUpperCase()} {d.host}:{d.port} · {d.vendor || "auto"}
                </span>
                <button className="btn sm ghost rt-device-delete" onClick={() => doDeleteDevice(d.device_id)}>
                  删除
                </button>
              </div>
            ))}
          </div>
        )}

        {/* Terminal */}
        <div
          className="rt-terminal-wrapper"
          onClick={() => xtermRef.current?.focus()}
        >
          <div
            ref={termRef}
            className="remote-terminal-host rt-terminal-host"
          />
        </div>
      </div>
    </div>
  );
}
