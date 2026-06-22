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

export function CMDBPage() {
  const wsId = useSessionStore((s) => s.currentWorkspaceId) || "default";
  const [assets, setAssets] = useState<Asset[]>([]);
  const [showForm, setShowForm] = useState(false);
  const [termOpen, setTermOpen] = useState(false);
  const [termAsset, setTermAsset] = useState<Asset | null>(null);

  // Form state
  const [name, setName] = useState(""); const [type, setType] = useState("switch");
  const [vendor, setVendor] = useState(""); const [model, setModel] = useState("");
  const [host, setHost] = useState(""); const [port, setPort] = useState("22");
  const [protocol, setProtocol] = useState("ssh");
  const [username, setUsername] = useState(""); const [password, setPassword] = useState("");
  const [location, setLocation] = useState("");
  const [err, setErr] = useState("");

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
      data: { workspace_id: wsId, name: name || host, type, vendor, model, host,
        port: parseInt(port) || 22, protocol, username, password, location } });
    setShowForm(false);
    setName(""); setModel(""); setHost(""); setUsername(""); setPassword(""); setLocation("");
    load();
  };

  const doDelete = async (aid: string) => {
    await apiRequest({ method: "DELETE", url: `/cmdb/assets/${aid}`, params: { workspace_id: wsId } });
    load();
  };

  const openTerminal = (a: Asset) => {
    setTermAsset(a);
    setTermOpen(true);
  };

  const input = (placeholder: string, value: string, setter: (v: string) => void, opts: Partial<React.CSSProperties> = {}) => (
    <input placeholder={placeholder} value={value} onChange={e => setter(e.target.value)}
      style={{ padding: "6px 10px", fontSize: "var(--fs-13)", borderRadius: 6, border: "1px solid var(--line)",
        background: "var(--surface)", color: "var(--text)", outline: "none", ...opts }} />
  );

  return (
    <div style={{ height: "100%", display: "flex", flexDirection: "column", padding: 16, gap: 12 }}>
      {/* Header */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
        <h2 style={{ margin: 0, fontSize: "var(--fs-18)" }}>📋 设备资产</h2>
        <button className="btn primary" onClick={() => setShowForm(true)}>+ 新建资产</button>
      </div>

      {/* Form modal */}
      {showForm && (
        <div style={{
          position: "fixed", top: 0, left: 0, right: 0, bottom: 0, zIndex: 9999,
          background: "rgba(0,0,0,0.4)", display: "flex", alignItems: "center", justifyContent: "center",
        }}>
          <div style={{
            width: 500, background: "var(--surface)", borderRadius: 12, padding: 24,
            boxShadow: "0 8px 40px rgba(0,0,0,0.25)", display: "flex", flexDirection: "column", gap: 12,
          }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
              <span style={{ fontWeight: 700, fontSize: "var(--fs-14)" }}>新建资产</span>
              <button className="btn sm ghost" onClick={() => setShowForm(false)}>✕</button>
            </div>

            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }}>
              {input("名称 *", name, setName, { gridColumn: "span 2" })}
              <select value={type} onChange={e => setType(e.target.value)}
                style={{ padding: "6px 10px", fontSize: "var(--fs-13)", borderRadius: 6, border: "1px solid var(--line)", background: "var(--surface)", color: "var(--text)" }}>
                <option value="switch">交换机</option><option value="router">路由器</option>
                <option value="firewall">防火墙</option><option value="server">服务器</option>
              </select>
              <select value={vendor} onChange={e => setVendor(e.target.value)}
                style={{ padding: "6px 10px", fontSize: "var(--fs-13)", borderRadius: 6, border: "1px solid var(--line)", background: "var(--surface)", color: "var(--text)" }}>
                <option value="">厂商</option>
                <option value="h3c">H3C</option><option value="huawei">Huawei</option>
                <option value="cisco">Cisco</option><option value="ruijie">Ruijie</option>
              </select>
              {input("型号", model, setModel)}
              {input("主机地址 *", host, setHost)}
              {input("端口", port, setPort, { width: 80 })}
              <select value={protocol} onChange={e => { setProtocol(e.target.value); setPort(e.target.value === "ssh" ? "22" : "23"); }}
                style={{ padding: "6px 10px", fontSize: "var(--fs-13)", borderRadius: 6, border: "1px solid var(--line)", background: "var(--surface)", color: "var(--text)" }}>
                <option value="ssh">SSH</option><option value="telnet">Telnet</option>
              </select>
              {input("用户名", username, setUsername)}
              {input("密码", password, setPassword, { type: "password" })}
              {input("位置", location, setLocation)}
            </div>

            {err && <div style={{ color: "var(--warn)", fontSize: "var(--fs-12)" }}>{err}</div>}

            <div style={{ display: "flex", gap: 8, justifyContent: "flex-end" }}>
              <button className="btn" onClick={() => setShowForm(false)}>取消</button>
              <button className="btn primary" onClick={doSave}>保存</button>
            </div>
          </div>
        </div>
      )}

      {/* Terminal popup */}
      {termOpen && termAsset && <RemoteTerminal onClose={() => setTermOpen(false)}
        initial={{ host: termAsset.host, port: termAsset.port, protocol: termAsset.protocol,
          vendor: termAsset.vendor, username: termAsset.username, password: "" }} />}

      {/* Asset list */}
      <div style={{ flex: 1, overflow: "auto" }}>
        {assets.length === 0 && (
          <div style={{ textAlign: "center", padding: 60, color: "var(--text-4)" }}>
            <div style={{ fontSize: "var(--fs-28)", marginBottom: 8 }}>📋</div>
            <div>暂无设备资产，点击「新建资产」添加</div>
          </div>
        )}
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(320px, 1fr))", gap: 10 }}>
          {assets.map(a => (
            <div key={a.asset_id} style={{
              padding: 16, borderRadius: 10, border: "1px solid var(--line-2)",
              background: "var(--surface-2)", display: "flex", flexDirection: "column", gap: 8,
            }}>
              <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <span style={{ fontSize: "var(--fs-16)" }}>{TYPE_ICONS[a.type] || "📡"}</span>
                <span style={{ fontWeight: 700, fontSize: "var(--fs-14)", flex: 1 }}>{a.name || a.host}</span>
                <span className="badge" style={{ fontSize: "var(--fs-10)" }}>{a.vendor || "—"}</span>
              </div>
              <div style={{ fontSize: "var(--fs-12)", color: "var(--text-3)", display: "flex", flexDirection: "column", gap: 2 }}>
                <span>📡 {a.host}:{a.port} · {a.protocol.toUpperCase()} · {a.username}</span>
                {a.model && <span>📦 {a.model}</span>}
                {a.location && <span>📍 {a.location}</span>}
              </div>
              <div style={{ display: "flex", gap: 6, marginTop: 4 }}>
                <button className="btn primary sm" onClick={() => openTerminal(a)}>🔗 终端</button>
                <button className="btn sm ghost" onClick={() => doDelete(a.asset_id)} style={{ fontSize: "var(--fs-11)", color: "var(--text-4)" }}>删除</button>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
