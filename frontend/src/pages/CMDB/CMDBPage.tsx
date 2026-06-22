import { useState, useCallback, useEffect } from "react";
import { useSessionStore } from "../../stores/session";
import { apiRequest } from "../../api/client";
import { RemoteTerminal } from "../../components/RemoteTerminal/RemoteTerminal";

interface Asset {
  asset_id: string; name: string; type: string; vendor: string;
  model: string; host: string; port: number; protocol: string;
  username: string; location: string; description: string; tags: string[];
}

const TYPE_ICONS: Record<string, string> = { switch: "🔄", router: "🌐", firewall: "🛡", server: "🖥" };
const TYPE_LABELS: Record<string, string> = { switch: "交换机", router: "路由器", firewall: "防火墙", server: "服务器" };
const VENDOR_COLORS: Record<string, string> = {
  h3c: "#00a3e0", huawei: "#cf0a2c", cisco: "#049fd9", ruijie: "#0077be",
};

function statBadge(label: string, value: number, color: string) {
  return (
    <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 2 }}>
      <span style={{ fontSize: "var(--fs-22)", fontWeight: 800, color }}>{value}</span>
      <span style={{ fontSize: "var(--fs-11)", color: "var(--text-4)", textTransform: "uppercase", letterSpacing: 0.5 }}>{label}</span>
    </div>
  );
}

export function CMDBPage() {
  const wsId = useSessionStore((s) => s.currentWorkspaceId) || "default";
  const [assets, setAssets] = useState<Asset[]>([]);
  const [showForm, setShowForm] = useState(false);
  const [termOpen, setTermOpen] = useState(false);
  const [termAsset, setTermAsset] = useState<Asset | null>(null);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [globalTermOpen, setGlobalTermOpen] = useState(false);

  const [name, setName] = useState(""); const [type, setType] = useState("switch");
  const [vendor, setVendor] = useState(""); const [model, setModel] = useState("");
  const [host, setHost] = useState(""); const [port, setPort] = useState("22");
  const [protocol, setProtocol] = useState("ssh");
  const [username, setUsername] = useState(""); const [password, setPassword] = useState("");
  const [location, setLocation] = useState(""); const [err, setErr] = useState("");

  const load = useCallback(async () => {
    try {
      const res = await apiRequest<{ ok: boolean; assets: Asset[] }>(
        { method: "GET", url: "/cmdb/assets", params: { workspace_id: wsId } });
      if (res.ok) setAssets(res.assets || []);
    } catch { /* ignore */ }
  }, [wsId]);

  useEffect(() => { load(); }, [load]);

  const doSave = async () => {
    if (!host) { setErr("请输入主机地址"); return; }
    setErr("");
    await apiRequest({ method: "POST", url: "/cmdb/assets",
      data: { workspace_id: wsId, asset_id: editingId || undefined,
        name: name || host, type, vendor, model, host,
        port: parseInt(port) || 22, protocol, username, password, location } });
    resetForm(); load();
  };

  const resetForm = () => {
    setShowForm(false); setEditingId(null);
    setName(""); setType("switch"); setVendor(""); setModel("");
    setHost(""); setPort("22"); setProtocol("ssh");
    setUsername(""); setPassword(""); setLocation(""); setErr("");
  };

  const editAsset = (a: Asset) => {
    setName(a.name); setType(a.type); setVendor(a.vendor); setModel(a.model);
    setHost(a.host); setPort(String(a.port)); setProtocol(a.protocol);
    setUsername(a.username); setLocation(a.location);
    setEditingId(a.asset_id); setShowForm(true);
  };

  const doDelete = async (aid: string) => {
    await apiRequest({ method: "DELETE", url: `/cmdb/assets/${aid}`, params: { workspace_id: wsId } });
    load();
  };

  const stats = {
    total: assets.length,
    switches: assets.filter(a => a.type === "switch").length,
    routers: assets.filter(a => a.type === "router").length,
    firewalls: assets.filter(a => a.type === "firewall").length,
  };

  const input = (ph: string, val: string, set: (v: string) => void, opts: any = {}) => (
    <input placeholder={ph} value={val} onChange={e => set(e.target.value)}
      style={{ padding: "8px 12px", fontSize: "var(--fs-13)", borderRadius: 8,
        border: "1px solid var(--line)", background: "var(--surface)", color: "var(--text)",
        outline: "none", fontFamily: "var(--font-mono)", width: "100%", boxSizing: "border-box", ...opts }} />
  );

  return (
    <div style={{ height: "100%", overflow: "auto", padding: "20px 24px" }}>
      {/* Header + Stats */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 20 }}>
        <div>
          <h2 style={{ margin: 0, fontSize: "var(--fs-22)", fontWeight: 800 }}>📋 设备资产</h2>
          <p style={{ margin: "4px 0 0", color: "var(--text-4)", fontSize: "var(--fs-12)" }}>管理你的网络设备清单，一键连接终端</p>
        </div>
        <div style={{ display: "flex", gap: 8 }}>
          <button className="btn" onClick={() => setGlobalTermOpen(true)}
            style={{ background: "var(--surface-2)", fontWeight: 600, fontSize: "var(--fs-13)", padding: "8px 16px" }}>
            ⌨️ 快速终端
          </button>
          <button className="btn primary" onClick={() => { resetForm(); setShowForm(true); }}
            style={{ fontWeight: 600, fontSize: "var(--fs-13)", padding: "8px 20px" }}>
            + 新建资产
          </button>
        </div>
      </div>

      {/* Quick stats */}
      <div style={{ display: "flex", gap: 32, marginBottom: 24, padding: "16px 20px", borderRadius: 12,
        background: "var(--surface-2)", border: "1px solid var(--line-2)" }}>
        {statBadge("全部设备", stats.total, "var(--accent)")}
        {statBadge("交换机", stats.switches, "#00a3e0")}
        {statBadge("路由器", stats.routers, "#cf0a2c")}
        {statBadge("防火墙", stats.firewalls, "#e65100")}
      </div>

      {/* Global terminal */}
      {globalTermOpen && <RemoteTerminal onClose={() => setGlobalTermOpen(false)} />}
      {termOpen && termAsset && <RemoteTerminal onClose={() => setTermOpen(false)}
        initial={{ host: termAsset.host, port: termAsset.port, protocol: termAsset.protocol,
          vendor: termAsset.vendor, username: termAsset.username, password: "" }} />}

      {/* Form */}
      {showForm && (
        <div style={{
          position: "fixed", top: 0, left: 0, right: 0, bottom: 0, zIndex: 9999,
          background: "rgba(0,0,0,0.35)", backdropFilter: "blur(4px)",
          display: "flex", alignItems: "center", justifyContent: "center",
        }}>
          <div style={{
            width: 520, background: "var(--surface)", borderRadius: 14, padding: 28,
            boxShadow: "0 12px 60px rgba(0,0,0,0.3)", display: "flex", flexDirection: "column", gap: 14,
          }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
              <span style={{ fontWeight: 700, fontSize: "var(--fs-16)" }}>
                {editingId ? "编辑资产" : "新建资产"}
              </span>
              <button className="btn sm ghost" onClick={resetForm} style={{ fontSize: "var(--fs-16)" }}>✕</button>
            </div>

            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
              {input("设备名称 *", name, setName, { gridColumn: "span 2", fontFamily: "var(--font)" })}
              <select value={type} onChange={e => setType(e.target.value)}
                style={{ padding: "8px 12px", fontSize: "var(--fs-13)", borderRadius: 8, border: "1px solid var(--line)",
                  background: "var(--surface)", color: "var(--text)", outline: "none" }}>
                {Object.entries(TYPE_LABELS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
              </select>
              <select value={vendor} onChange={e => setVendor(e.target.value)}
                style={{ padding: "8px 12px", fontSize: "var(--fs-13)", borderRadius: 8, border: "1px solid var(--line)",
                  background: "var(--surface)", color: "var(--text)", outline: "none" }}>
                <option value="">厂商 (可选)</option>
                <option value="h3c">H3C 华三</option>
                <option value="huawei">Huawei 华为</option>
                <option value="cisco">Cisco 思科</option>
                <option value="ruijie">Ruijie 锐捷</option>
              </select>
              {input("型号", model, setModel)}
              {input("位置", location, setLocation)}
              {/* Connection */}
              <div style={{ gridColumn: "span 2", borderTop: "1px solid var(--line-2)", paddingTop: 10, marginTop: 4 }}>
                <span style={{ fontSize: "var(--fs-11)", color: "var(--text-4)", fontWeight: 600, textTransform: "uppercase", letterSpacing: 0.5 }}>连接信息</span>
              </div>
              <div style={{ display: "flex", gap: 8 }}>
                <select value={protocol} onChange={e => { setProtocol(e.target.value); setPort(e.target.value === "ssh" ? "22" : "23"); }}
                  style={{ padding: "8px 12px", fontSize: "var(--fs-13)", borderRadius: 8, border: "1px solid var(--line)",
                    background: "var(--surface)", color: "var(--text)", width: 100 }}>
                  <option value="ssh">SSH</option>
                  <option value="telnet">Telnet</option>
                </select>
                {input("主机地址 *", host, setHost, { flex: 1 })}
                {input("端口", port, setPort, { width: 70, textAlign: "center" })}
              </div>
              {input("用户名", username, setUsername)}
              <input placeholder="密码" type="password" value={password}
                onChange={e => setPassword(e.target.value)}
                style={{ padding: "8px 12px", fontSize: "var(--fs-13)", borderRadius: 8, border: "1px solid var(--line)",
                  background: "var(--surface)", color: "var(--text)", outline: "none", fontFamily: "var(--font-mono)" }} />
            </div>

            {err && <div style={{ color: "var(--warn)", fontSize: "var(--fs-12)", fontWeight: 500 }}>⚠ {err}</div>}

            <div style={{ display: "flex", gap: 8, justifyContent: "flex-end", marginTop: 4 }}>
              <button className="btn" onClick={resetForm}>取消</button>
              <button className="btn primary" onClick={doSave} style={{ padding: "8px 24px" }}>
                {editingId ? "更新" : "创建"}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Asset grid */}
      {assets.length === 0 && (
        <div style={{ textAlign: "center", padding: "80px 40px", color: "var(--text-4)" }}>
          <div style={{ fontSize: "var(--fs-40)", marginBottom: 12 }}>📋</div>
          <div style={{ fontSize: "var(--fs-16)", fontWeight: 600, marginBottom: 4 }}>暂无设备资产</div>
          <div style={{ fontSize: "var(--fs-13)" }}>点击「新建资产」添加你的第一台网络设备</div>
        </div>
      )}

      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(340px, 1fr))", gap: 14 }}>
        {assets.map(a => (
          <div key={a.asset_id} style={{
            borderRadius: 14, border: "1px solid var(--line-2)",
            background: "var(--surface)", overflow: "hidden",
            transition: "box-shadow 0.15s",
          }} onMouseEnter={e => e.currentTarget.style.boxShadow = "0 4px 20px rgba(0,0,0,0.1)"}
              onMouseLeave={e => e.currentTarget.style.boxShadow = "none"}>
            {/* Top bar */}
            <div style={{
              padding: "12px 16px", borderBottom: `3px solid ${VENDOR_COLORS[a.vendor] || "var(--accent)"}`,
              display: "flex", alignItems: "center", gap: 10,
            }}>
              <span style={{ fontSize: "var(--fs-20)" }}>{TYPE_ICONS[a.type] || "📡"}</span>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontWeight: 700, fontSize: "var(--fs-14)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                  {a.name || a.host}
                </div>
                <div style={{ fontSize: "var(--fs-11)", color: "var(--text-4)" }}>
                  {TYPE_LABELS[a.type]} · {a.vendor || "—"}
                </div>
              </div>
              <div style={{ display: "flex", gap: 4 }}>
                <button className="btn sm ghost" onClick={() => editAsset(a)}
                  style={{ fontSize: "var(--fs-11)", padding: "3px 8px" }}>✏️</button>
                <button className="btn sm ghost" onClick={() => doDelete(a.asset_id)}
                  style={{ fontSize: "var(--fs-11)", padding: "3px 8px", color: "var(--text-4)" }}>🗑</button>
              </div>
            </div>

            {/* Body */}
            <div style={{ padding: "12px 16px", display: "flex", flexDirection: "column", gap: 6 }}>
              <div style={{ fontSize: "var(--fs-12)", color: "var(--text-2)", fontFamily: "var(--font-mono)" }}>
                🔗 {a.protocol.toUpperCase()} {a.host}:{a.port} · {a.username}
              </div>
              <div style={{ fontSize: "var(--fs-12)", color: "var(--text-3)", display: "flex", gap: 12 }}>
                {a.model && <span>📦 {a.model}</span>}
                {a.location && <span>📍 {a.location}</span>}
              </div>
            </div>

            {/* Footer */}
            <div style={{ padding: "10px 16px", borderTop: "1px solid var(--line-2)", display: "flex", gap: 8 }}>
              <button className="btn primary" onClick={() => openTerminal(a)}
                style={{ flex: 1, justifyContent: "center", fontWeight: 600, fontSize: "var(--fs-13)", padding: "8px 0" }}>
                🔗 连接终端
              </button>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
