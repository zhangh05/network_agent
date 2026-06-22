import { useState, useRef, useEffect, useCallback } from "react";
import { useSessionStore } from "../../stores/session";
import { apiRequest } from "../../api/client";

interface SavedDevice {
  device_id: string; name: string; host: string; port: number;
  protocol: string; vendor: string; username: string;
}

interface VendorDef {
  key: string; vendor: string;
}

export function RemoteTerminal({ onClose }: { onClose: () => void }) {
  const wsId = useSessionStore((s) => s.currentWorkspaceId) || "default";
  const termRef = useRef<HTMLDivElement>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const xtermRef = useRef<any>(null);
  const fitRef = useRef<any>(null);

  // Form state
  const [protocol, setProtocol] = useState("ssh");
  const [host, setHost] = useState("");
  const [port, setPort] = useState("22");
  const [vendor, setVendor] = useState("");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");

  // Connection state
  const [sessionId, setSessionId] = useState("");
  const [connected, setConnected] = useState(false);
  const [connecting, setConnecting] = useState(false);
  const [error, setError] = useState("");
  const [devices, setDevices] = useState<SavedDevice[]>([]);
  const [vendors, setVendors] = useState<VendorDef[]>([]);
  const [showDevices, setShowDevices] = useState(false);
  const [showSave, setShowSave] = useState(false);
  const [deviceName, setDeviceName] = useState("");

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
    const initTerm = async () => {
      const { Terminal } = await import("xterm");
      const { FitAddon } = await import("@xterm/addon-fit");
      if (disposed || !termRef.current) return;

      const term = new Terminal({
        theme: { background: "#1e1e2e", foreground: "#cdd6f4", cursor: "#f5e0dc" },
        fontSize: 13, fontFamily: "'JetBrains Mono', 'Fira Code', monospace",
        cursorBlink: true, allowProposedApi: true,
      });
      const fit = new FitAddon();
      term.loadAddon(fit);
      term.open(termRef.current);
      fit.fit();
      term.writeln("Ready. Fill connection settings and click Connect.");
      xtermRef.current = term;
      fitRef.current = fit;

      term.onData((data: string) => {
        if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN && sessionId) {
          wsRef.current.send(JSON.stringify({ type: "input", session_id: sessionId, data }));
        }
      });
    };
    initTerm();
    return () => { disposed = true; xtermRef.current?.dispose(); };
  }, []);

  const doConnect = async () => {
    if (!host) { setError("请输入主机地址"); return; }
    setError(""); setConnecting(true);
    const term = xtermRef.current;
    if (term) { term.clear(); term.writeln(`Connecting to ${host}:${port}...`); }

    const wsUrl = `ws://${window.location.hostname}:8010/ws/remote/terminal`;
    const ws = new WebSocket(wsUrl);
    wsRef.current = ws;

    ws.onopen = () => {
      ws.send(JSON.stringify({ type: "connect", workspace_id: wsId, host,
        port: parseInt(port) || 22, protocol, username, password, vendor }));
    };
    ws.onmessage = (e) => {
      const msg = JSON.parse(e.data);
      if (msg.type === "connected") {
        setSessionId(msg.session_id); setConnected(true); setConnecting(false);
        if (term) { term.clear(); term.writeln(msg.banner || "Connected."); }
      } else if (msg.type === "output") {
        if (term) term.write(msg.text);
      } else if (msg.type === "error") {
        setError(msg.message || "连接失败"); setConnecting(false);
        if (term) term.writeln(`\r\nError: ${msg.message}`);
      } else if (msg.type === "disconnected") {
        setConnected(false); setSessionId("");
        if (term) term.writeln("\r\nDisconnected.");
      }
    };
    ws.onclose = () => { setConnected(false); setConnecting(false); };
    ws.onerror = () => { setError("WebSocket 连接失败"); setConnecting(false); };
  };

  const doDisconnect = () => {
    if (wsRef.current) {
      wsRef.current.send(JSON.stringify({ type: "disconnect", session_id: sessionId }));
      wsRef.current.close(); wsRef.current = null;
    }
    setConnected(false); setSessionId("");
    xtermRef.current?.writeln("\r\nDisconnected.");
  };

  const loadDevice = (d: SavedDevice) => {
    setHost(d.host); setPort(String(d.port)); setProtocol(d.protocol);
    setVendor(d.vendor); setUsername(d.username); setPassword("");
    setShowDevices(false);
  };

  const doSaveDevice = async () => {
    await apiRequest({ method: "POST", url: "/remote/devices",
      data: { workspace_id: wsId, name: deviceName || host, host,
        port: parseInt(port) || 22, protocol, vendor, username, password } });
    setShowSave(false); loadDevices();
  };

  const doDeleteDevice = async (did: string) => {
    await apiRequest({ method: "DELETE", url: `/remote/devices/${did}`, params: { workspace_id: wsId } });
    loadDevices();
  };

  const inputStyle: React.CSSProperties = {
    padding: "4px 8px", fontSize: "var(--fs-12)", borderRadius: 5,
    border: "1px solid var(--line)", background: "var(--surface-2)", color: "var(--text)",
    outline: "none", flex: 1,
  };

  return (
    <div style={{
      position: "fixed", top: 0, left: 0, right: 0, bottom: 0,
      background: "rgba(0,0,0,0.4)", zIndex: 9999,
      display: "flex", alignItems: "center", justifyContent: "center",
    }}>
      <div style={{
        width: "min(90vw, 800px)", height: "min(85vh, 600px)",
        background: "var(--surface)", borderRadius: 12,
        boxShadow: "0 8px 40px rgba(0,0,0,0.25)", display: "flex", flexDirection: "column",
        overflow: "hidden",
      }}>
        {/* Header */}
        <div style={{ padding: "10px 16px", borderBottom: "1px solid var(--line)", display: "flex", alignItems: "center", gap: 8, flexShrink: 0 }}>
          <span style={{ fontWeight: 700, fontSize: "var(--fs-14)" }}>远程终端</span>
          {connected && <span className="status-pill" style={{ fontSize: "var(--fs-11)" }}><span className="dot ok" />{host}</span>}
          {!connected && connected !== undefined && <span className="status-pill" style={{ fontSize: "var(--fs-11)" }}><span className="dot inactive" />未连接</span>}
          <div style={{ flex: 1 }} />
          <button className="btn sm ghost" onClick={onClose}>✕</button>
        </div>

        {/* Connection form */}
        <div style={{ padding: "8px 16px", borderBottom: "1px solid var(--line-2)", display: "flex", gap: 6, alignItems: "center", flexWrap: "wrap", flexShrink: 0 }}>
          <select value={protocol} onChange={e => { setProtocol(e.target.value); setPort(e.target.value === "ssh" ? "22" : "23"); }}
            style={{ ...inputStyle, flex: "0 0 70px" }}>
            <option value="ssh">SSH</option>
            <option value="telnet">Telnet</option>
          </select>
          <input placeholder="主机" value={host} onChange={e => setHost(e.target.value)} style={inputStyle} disabled={connected} />
          <input placeholder="端口" value={port} onChange={e => setPort(e.target.value)} style={{ ...inputStyle, flex: "0 0 60px" }} type="number" disabled={connected} />
          <select value={vendor} onChange={e => setVendor(e.target.value)} style={{ ...inputStyle, flex: "0 0 110px" }} disabled={connected}>
            <option value="">自动</option>
            {vendors.map(v => <option key={v.key} value={v.key}>{v.vendor}</option>)}
          </select>
          <input placeholder="用户名" value={username} onChange={e => setUsername(e.target.value)} style={inputStyle} autoComplete="off" disabled={connected} />
          <input placeholder="密码" type="password" value={password} onChange={e => setPassword(e.target.value)} style={{ ...inputStyle, flex: "0 0 100px" }} autoComplete="off" disabled={connected} />
          {!connected ? (
            <button className="btn primary sm" onClick={doConnect} disabled={connecting} style={{ whiteSpace: "nowrap" }}>
              {connecting ? "连接中…" : "连接"}
            </button>
          ) : (
            <button className="btn danger sm" onClick={doDisconnect} style={{ whiteSpace: "nowrap" }}>断开</button>
          )}
          <button className="btn sm ghost" onClick={() => { loadDevices(); setShowDevices(!showDevices); }} style={{ fontSize: "var(--fs-11)" }}>
            ▾ 设备
          </button>
          {!connected && host && (
            <button className="btn sm ghost" onClick={() => { setDeviceName(host); setShowSave(true); }} style={{ fontSize: "var(--fs-11)" }}>
              💾 保存
            </button>
          )}
        </div>

        {/* Save device dialog */}
        {showSave && (
          <div style={{ padding: "8px 16px", borderBottom: "1px solid var(--line-2)", display: "flex", gap: 6, alignItems: "center", flexShrink: 0 }}>
            <input placeholder="设备名称" value={deviceName} onChange={e => setDeviceName(e.target.value)} style={inputStyle} />
            <button className="btn primary sm" onClick={doSaveDevice}>保存</button>
            <button className="btn sm ghost" onClick={() => setShowSave(false)}>取消</button>
          </div>
        )}

        {/* Error */}
        {error && (
          <div style={{ padding: "4px 16px", color: "var(--warn)", fontSize: "var(--fs-12)", flexShrink: 0 }}>{error}</div>
        )}

        {/* Device list */}
        {showDevices && (
          <div style={{ padding: "4px 16px", borderBottom: "1px solid var(--line-2)", maxHeight: 120, overflow: "auto", flexShrink: 0 }}>
            {devices.length === 0 && <div style={{ color: "var(--text-4)", fontSize: "var(--fs-11)", padding: 4 }}>暂无已保存设备</div>}
            {devices.map(d => (
              <div key={d.device_id} style={{ display: "flex", alignItems: "center", gap: 8, padding: "2px 0", fontSize: "var(--fs-11)" }}>
                <span style={{ cursor: "pointer", flex: 1, color: "var(--accent)" }} onClick={() => loadDevice(d)}>
                  {d.name || d.host} ({d.protocol.toUpperCase()} {d.host}:{d.port} · {d.vendor || "auto"})
                </span>
                <button className="btn sm ghost" onClick={() => doDeleteDevice(d.device_id)} style={{ color: "var(--text-4)", fontSize: "var(--fs-10)" }}>✕</button>
              </div>
            ))}
          </div>
        )}

        {/* Terminal */}
        <div ref={termRef} style={{ flex: 1, padding: "4px 8px", background: "#1e1e2e", minHeight: 0 }} />
      </div>
    </div>
  );
}
