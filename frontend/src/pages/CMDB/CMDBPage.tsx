import { useState, useCallback, useEffect, type CSSProperties, type ReactNode } from "react";
import { useSessionStore } from "../../stores/session";
import { apiRequest } from "../../api/client";
import { RemoteTerminal } from "../../components/RemoteTerminal/RemoteTerminal";

interface Asset {
  asset_id: string; name: string; type: string; vendor: string;
  model: string; host: string; port: number; protocol: string;
  username: string; region: string; location: string; description: string; tags: string[];
}

const TYPE_LABEL: Record<string, string> = {
  switch: "交换机", router: "路由器", firewall: "防火墙", server: "服务器",
};
const VENDOR_STRIP: Record<string, string> = {
  h3c: "var(--info)", huawei: "#cf0a2c", cisco: "#049fd9", ruijie: "#0077be",
};
const REGION_PRESETS = ["华东", "华南", "华北", "华西", "核心", "汇聚", "接入"];
const REGION_TINT: Record<string, string> = {
  "华东": "var(--info-soft)", "华南": "var(--ok-soft)", "华北": "#dbeafe",
  "华西": "#f3e8ff", "核心": "#ffe4e6", "汇聚": "#fef3c7", "接入": "var(--surface-3)",
};
const REGION_TEXT: Record<string, string> = {
  "华东": "var(--info)", "华南": "var(--ok)", "华北": "#1e40af",
  "华西": "#7e22ce", "核心": "#be123c", "汇聚": "#92400e", "接入": "var(--text-3)",
};

const VENDOR_PRESETS: [string, string][] = [
  ["h3c", "H3C"], ["huawei", "Huawei"], ["cisco", "Cisco"], ["ruijie", "Ruijie"],
];

// ── tiny stat pill ──
function Stat({ label, value, color }: { label: string; value: number; color: string }) {
  return (
    <div style={{ textAlign: "center", minWidth: 64 }}>
      <div style={{ fontSize: 22, fontWeight: 700, color, lineHeight: 1.2 }}>{value}</div>
      <div style={{ fontSize: 11, color: "var(--text-4)", marginTop: 2 }}>{label}</div>
    </div>
  );
}

export function CMDBPage() {
  const wsId = useSessionStore((s) => s.currentWorkspaceId);
  const [assets, setAssets] = useState<Asset[]>([]);
  const [showForm, setShowForm] = useState(false);
  const [editingAsset, setEditingAsset] = useState<Asset | null>(null);
  const [termAsset, setTermAsset] = useState<Asset | null>(null);
  const [globalTerm, setGlobalTerm] = useState(false);
  const [regionFilter, setRegionFilter] = useState("");

  // ── form ──
  const [fv, setFv] = useState<Record<string, string>>({
    name: "", type: "switch", vendor: "", model: "", host: "", port: "22",
    protocol: "ssh", username: "", password: "", region: "", location: "", description: "", err: "",
  });
  const ufv = (k: string, v: string) => setFv((p) => ({ ...p, [k]: v }));

  // ── custom input state ──
  const [customVendor, setCustomVendor] = useState(false);
  const [customRegion, setCustomRegion] = useState(false);
  const [customVendorVal, setCustomVendorVal] = useState("");
  const [customRegionVal, setCustomRegionVal] = useState("");
  const [savedVendors, setSavedVendors] = useState<string[]>([]);
  const [savedRegions, setSavedRegions] = useState<string[]>([]);

  const load = useCallback(async () => {
    if (!wsId) return;
    try {
      const r = await apiRequest<{ ok: boolean; assets: Asset[] }>(
        { method: "GET", url: "/cmdb/assets", params: { workspace_id: wsId } });
      if (r.ok) {
        const list = r.assets || [];
        setAssets(list);
        // collect custom vendors & regions from existing assets
        const allVendors = [...new Set(list.map(a => a.vendor).filter(Boolean))] as string[];
        const allRegions = [...new Set(list.map(a => a.region).filter(Boolean))] as string[];
        setSavedVendors(allVendors.filter(v => !VENDOR_PRESETS.find(([k]) => k === v)));
        setSavedRegions(allRegions.filter(r => !REGION_PRESETS.includes(r)));
      }
    } catch { /* */ }
  }, [wsId]);

  useEffect(() => { load(); }, [load]);

  const openNew = () => {
    setEditingAsset(null);
    setFv({ name: "", type: "switch", vendor: "", model: "", host: "", port: "22",
      protocol: "ssh", username: "", password: "", region: "", location: "", description: "", err: "" });
    setCustomVendor(false); setCustomRegion(false);
    setCustomVendorVal(""); setCustomRegionVal("");
    setShowForm(true);
  };

  const openEdit = (a: Asset) => {
    setEditingAsset(a);
    setFv({
      name: a.name, type: a.type, vendor: a.vendor, model: a.model,
      host: a.host, port: String(a.port), protocol: a.protocol,
      username: a.username, password: "", region: a.region || "",
      location: a.location, description: a.description || "", err: "",
    });
    // detect if vendor/region is custom
    const isCustomV = a.vendor && !VENDOR_PRESETS.find(([k]) => k === a.vendor);
    const isCustomR = a.region && !REGION_PRESETS.includes(a.region);
    setCustomVendor(!!isCustomV); setCustomRegion(!!isCustomR);
    setCustomVendorVal(isCustomV ? a.vendor : ""); setCustomRegionVal(isCustomR ? a.region || "" : "");
    setShowForm(true);
  };

  const doSave = async () => {
    if (!fv.host) { ufv("err", "请输入主机地址"); return; }
    ufv("err", "");
    const vendor = customVendor ? (customVendorVal.trim() || "") : fv.vendor;
    const region = customRegion ? (customRegionVal.trim() || "") : fv.region;
    const payload: Record<string, unknown> = {
      workspace_id: wsId, asset_id: editingAsset?.asset_id || undefined,
      name: fv.name || fv.host, type: fv.type, vendor, model: fv.model,
      host: fv.host, port: parseInt(fv.port) || 22, protocol: fv.protocol,
      username: fv.username,
      region, location: fv.location, description: fv.description,
    };
    if (!editingAsset && fv.password) payload.password = fv.password;
    await apiRequest({
      method: "POST", url: "/cmdb/assets",
      data: payload,
    });
    setShowForm(false); load();
  };

  const doDelete = async (aid: string) => {
    await apiRequest({ method: "DELETE", url: `/cmdb/assets/${aid}`, params: { workspace_id: wsId } });
    load();
  };

  const filtered = regionFilter
    ? assets.filter(a => (a.region || "") === regionFilter)
    : assets;

  const regionSet = [...new Set(assets.map(a => a.region).filter(Boolean))];
  const stats = { total: assets.length, switch: 0, router: 0, firewall: 0 };
  assets.forEach(a => { if (a.type in stats) (stats as any)[a.type]++; });

  // ── form helpers ──
  const field = (label: string, child: ReactNode, span = 1) => (
    <div style={{ gridColumn: span > 1 ? `span ${span}` : undefined, display: "flex", flexDirection: "column", gap: 4 }}>
      {label && <span style={{ fontSize: 11, color: "var(--text-4)", fontWeight: 600 }}>{label}</span>}
      {child}
    </div>
  );
  const stl = (mono = true, w: CSSProperties = {}, suffix = false) => ({
    padding: "7px 10px", fontSize: 13, borderRadius: 6, border: "1px solid var(--line)",
    background: "var(--surface)", color: "var(--text)", outline: "none",
    fontFamily: mono ? "var(--font-mono)" : "var(--font-sans)",
    width: suffix ? "136px" : "100%", boxSizing: "border-box" as const,
    transition: "border-color .15s",
    ...w,
  });
  const inp = (ph: string, key: string, w: CSSProperties = {}, mono = true) => (
    <input
      placeholder={ph} value={fv[key] || ""} onChange={e => ufv(key, e.target.value)}
      style={stl(mono, w)}
      onFocus={e => e.currentTarget.style.borderColor = "var(--accent)"}
      onBlur={e => e.currentTarget.style.borderColor = "var(--line)"}
    />
  );
  const sel = (key: string, opts: [string, string][], onChange?: (v: string) => void) => (
    <select
      value={fv[key] || ""} onChange={e => { ufv(key, e.target.value); onChange?.(e.target.value); }}
      style={{
        padding: "7px 10px", fontSize: 13, borderRadius: 6, border: "1px solid var(--line)",
        background: "var(--surface)", color: "var(--text)", outline: "none",
        width: "100%", boxSizing: "border-box" as const, cursor: "pointer",
      }}>
      {opts.map(([k, v]) => <option key={k} value={k}>{v}</option>)}
    </select>
  );
  const customInput = (val: string, setVal: (v: string) => void, ph: string) => (
    <input
      placeholder={ph} value={val}
      onChange={e => setVal(e.target.value)}
      style={stl(false, { marginTop: 6 })}
      onFocus={e => e.currentTarget.style.borderColor = "var(--accent)"}
      onBlur={e => e.currentTarget.style.borderColor = "var(--line)"}
    />
  );

  // ── build dropdown options ──
  const typeOpts: [string, string][] = [
    ["switch", "交换机"], ["router", "路由器"], ["firewall", "防火墙"], ["server", "服务器"],
  ];
  const protocolOpts: [string, string][] = [["ssh", "SSH"], ["telnet", "Telnet"]];

  const vendorOpts: [string, string][] = [
    ["", "—"], ...VENDOR_PRESETS, ...savedVendors.map(v => [v, v] as [string, string]),
    ["__custom__", "自定义填写"],
  ];

  const regionOpts: [string, string][] = [
    ["", "—"], ...REGION_PRESETS.map(r => [r, r] as [string, string]),
    ...savedRegions.map(r => [r, r] as [string, string]),
    ["__custom__", "自定义填写"],
  ];

  return (
    <div style={{ height: "100%", overflow: "auto", background: "var(--bg)" }}>
      {/* ── 工具栏 ── */}
      <div style={{
        display: "flex", alignItems: "center", justifyContent: "space-between",
        padding: "16px 24px 12px", position: "sticky", top: 0, zIndex: 10,
        background: "var(--bg)",
      }}>
        <div>
          <h2 style={{ margin: 0, fontSize: 18, fontWeight: 700, color: "var(--text)" }}>
            设备资产
          </h2>
          <p style={{ margin: "2px 0 0", fontSize: 12, color: "var(--text-4)" }}>
            已注册 {assets.length} 台设备
          </p>
        </div>
        <div style={{ display: "flex", gap: 8 }}>
          <button className="btn" onClick={() => setGlobalTerm(true)}
            style={{ fontWeight: 600, fontSize: 13, padding: "8px 14px", background: "var(--surface-2)" }}>
            终端
          </button>
          <button className="btn primary" onClick={openNew}
            style={{ fontWeight: 600, fontSize: 13, padding: "8px 18px" }}>
            + 新增设备
          </button>
        </div>
      </div>

      <div style={{ padding: "0 24px 24px" }}>
        {/* ── 统计栏 ── */}
        <div style={{
          display: "flex", alignItems: "center", gap: 28,
          padding: "14px 20px", marginBottom: 18,
          borderRadius: 10, border: "1px solid var(--line-2)", background: "var(--surface)",
        }}>
          <Stat label="总计" value={stats.total} color="var(--accent)" />
          <div style={{ width: 1, height: 32, background: "var(--line-2)" }} />
          <Stat label="交换机" value={stats.switch} color="var(--info)" />
          <Stat label="路由器" value={stats.router} color="#cf0a2c" />
          <Stat label="防火墙" value={stats.firewall} color="#e65100" />
        </div>

        {/* ── 区域筛选 ── */}
        {regionSet.length > 0 && (
          <div style={{ display: "flex", gap: 6, marginBottom: 18, flexWrap: "wrap", alignItems: "center" }}>
            <span style={{ fontSize: 12, color: "var(--text-4)", marginRight: 4 }}>区域：</span>
            <button
              onClick={() => setRegionFilter("")}
              style={{
                padding: "3px 12px", borderRadius: "var(--r-pill)", cursor: "pointer",
                border: `1px solid ${regionFilter ? "var(--line-2)" : "var(--accent)"}`,
                background: regionFilter ? "transparent" : "var(--accent-soft)",
                color: regionFilter ? "var(--text-3)" : "var(--accent)",
                fontSize: 12, fontWeight: 600, transition: "all .15s",
              }}
            >全部</button>
            {regionSet.map(r => {
              const active = regionFilter === r;
              return (
                <button key={r} onClick={() => setRegionFilter(active ? "" : r)}
                  style={{
                    padding: "3px 12px", borderRadius: "var(--r-pill)", cursor: "pointer",
                    border: `1px solid ${active ? (REGION_TEXT[r] || "var(--text-3)") : "var(--line-2)"}`,
                    background: active ? (REGION_TINT[r] || "var(--surface-3)") : "transparent",
                    color: active ? (REGION_TEXT[r] || "var(--text)") : "var(--text-3)",
                    fontSize: 12, fontWeight: 600, transition: "all .15s",
                  }}
                >{r}</button>
              );
            })}
          </div>
        )}

        {/* ── 全局终端 ── */}
        {globalTerm && <RemoteTerminal onClose={() => setGlobalTerm(false)} />}
        {termAsset && <RemoteTerminal onClose={() => setTermAsset(null)}
          initial={{ host: termAsset.host, port: termAsset.port, protocol: termAsset.protocol,
            vendor: termAsset.vendor, username: termAsset.username, password: "" }} />}

        {/* ── 新增/编辑弹窗 ── */}
        {showForm && (
          <div style={{
            position: "fixed", inset: 0, zIndex: 9999,
            background: "var(--overlay)", backdropFilter: "blur(3px)",
            display: "flex", alignItems: "center", justifyContent: "center",
          }} onClick={() => setShowForm(false)}>
            <div
              onClick={e => e.stopPropagation()}
              style={{
                width: 540, maxHeight: "92vh", overflow: "auto",
                background: "var(--surface)", borderRadius: 12,
                boxShadow: "var(--shadow-menu)", padding: 28,
                display: "flex", flexDirection: "column",
              }}>
              {/* 标题 */}
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 20 }}>
                <span style={{ fontWeight: 700, fontSize: 16, color: "var(--text)" }}>
                  {editingAsset ? "编辑设备" : "新增设备"}
                </span>
                <button className="btn sm ghost" onClick={() => setShowForm(false)}
                  style={{ fontSize: 16, padding: "2px 6px", color: "var(--text-4)" }}>×</button>
              </div>

              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "12px 14px" }}>
                {/* 基本信息 */}
                {field("名称 *", inp("设备名称", "name", { fontFamily: "var(--font-sans)" }, false), 2)}
                {field("类型", sel("type", typeOpts))}
                <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                  <span style={{ fontSize: 11, color: "var(--text-4)", fontWeight: 600 }}>厂商</span>
                  {sel("vendor", vendorOpts, (v) => {
                    if (v === "__custom__") { setCustomVendor(true); setCustomVendorVal(""); ufv("vendor", ""); }
                    else setCustomVendor(false);
                  })}
                  {customVendor && customInput(customVendorVal, setCustomVendorVal, "输入自定义厂商...")}
                </div>
                {field("型号", inp("型号", "model", { fontFamily: "var(--font-sans)" }, false))}
                {/* 区域 & 位置 */}
                <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                  <span style={{ fontSize: 11, color: "var(--text-4)", fontWeight: 600 }}>区域</span>
                  {sel("region", regionOpts, (v) => {
                    if (v === "__custom__") { setCustomRegion(true); setCustomRegionVal(""); ufv("region", ""); }
                    else setCustomRegion(false);
                  })}
                  {customRegion && customInput(customRegionVal, setCustomRegionVal, "输入自定义区域...")}
                </div>
                {field("位置", inp("机架 / 机房", "location", { fontFamily: "var(--font-sans)" }, false))}
                {field("备注", inp("备注信息", "description", { fontFamily: "var(--font-sans)" }, false), 2)}

                {/* 连接信息分隔 */}
                <div style={{ gridColumn: "span 2", height: 1, background: "var(--line-2)", margin: "4px 0" }} />
                <div style={{ gridColumn: "span 2", fontSize: 11, color: "var(--text-4)", fontWeight: 600, marginBottom: -4 }}>
                  连接信息
                </div>

                <div style={{ display: "flex", gap: 8, gridColumn: "span 2" }}>
                  <div style={{ width: 90 }}>
                    {field("", sel("protocol", protocolOpts))}
                  </div>
                  <div style={{ flex: 1 }}>{field("主机 *", inp("192.168.1.1", "host"))}</div>
                  <div style={{ width: 72 }}>{field("端口", inp("22", "port", { textAlign: "center" }))}</div>
                </div>
                {field("用户名", inp("admin", "username"))}
                <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                  <span style={{ fontSize: 11, color: "var(--text-4)", fontWeight: 600 }}>密码</span>
                  <input
                    type="password" placeholder="······" value={fv.password}
                    onChange={e => ufv("password", e.target.value)}
                    style={{
                      padding: "7px 10px", fontSize: 13, borderRadius: 6, border: "1px solid var(--line)",
                      background: "var(--surface)", color: "var(--text)", outline: "none",
                      fontFamily: "var(--font-mono)", transition: "border-color .15s",
                    }}
                    onFocus={e => e.currentTarget.style.borderColor = "var(--accent)"}
                    onBlur={e => e.currentTarget.style.borderColor = "var(--line)"}
                  />
                </div>
              </div>

              {fv.err && (
                <div style={{ marginTop: 12, padding: "8px 12px", borderRadius: 6, background: "var(--warn-soft)", color: "var(--warn)", fontSize: 12, fontWeight: 500 }}>
                  {fv.err}
                </div>
              )}

              <div style={{ display: "flex", gap: 8, justifyContent: "flex-end", marginTop: 20 }}>
                <button className="btn" onClick={() => setShowForm(false)} style={{ padding: "7px 16px" }}>取消</button>
                <button className="btn primary" onClick={doSave} style={{ padding: "7px 22px" }}>
                  {editingAsset ? "保存更改" : "创建设备"}
                </button>
              </div>
            </div>
          </div>
        )}

        {/* ── 空状态 ── */}
        {assets.length === 0 && (
          <div style={{ textAlign: "center", padding: "80px 40px", color: "var(--text-4)" }}>
            <div style={{ fontSize: 40, marginBottom: 12, opacity: .5 }}>⊞</div>
            <div style={{ fontSize: 16, fontWeight: 600, color: "var(--text-3)", marginBottom: 4 }}>暂无设备</div>
            <div style={{ fontSize: 13 }}>点击 <b>+ 新增设备</b> 注册第一台网络设备。</div>
          </div>
        )}

        {/* ── 设备卡片 ── */}
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(360px, 1fr))", gap: 16 }}>
          {filtered.map(a => {
            const strip = VENDOR_STRIP[a.vendor] || "var(--accent)";
            const regionName = a.region || "";
            return (
              <div key={a.asset_id}
                style={{
                  borderRadius: 10, border: "1px solid var(--line-2)",
                  background: "var(--surface)", overflow: "hidden",
                  transition: "box-shadow .15s",
                }}
                onMouseEnter={e => (e.currentTarget as HTMLElement).style.boxShadow = "0 4px 16px rgba(0,0,0,.06)"}
                onMouseLeave={e => (e.currentTarget as HTMLElement).style.boxShadow = "none"}>
                {/* 顶栏 */}
                <div style={{
                  padding: "14px 16px 10px", borderBottom: `3px solid ${strip}`,
                  display: "flex", alignItems: "flex-start", gap: 12,
                }}>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ fontWeight: 700, fontSize: 14, color: "var(--text)", lineHeight: 1.3 }}>
                      {a.name || a.host}
                    </div>
                    <div style={{ marginTop: 3, display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
                      <span style={{ fontSize: 11, color: "var(--text-3)", background: "var(--surface-3)", padding: "1px 8px", borderRadius: 4 }}>
                        {TYPE_LABEL[a.type] || a.type}
                      </span>
                      {a.vendor && (
                        <span style={{ fontSize: 11, color: "var(--text-4)" }}>{a.vendor}</span>
                      )}
                      {regionName && (
                        <span style={{
                          fontSize: 11, fontWeight: 600, padding: "1px 8px", borderRadius: 4,
                          background: REGION_TINT[regionName] || "var(--surface-3)",
                          color: REGION_TEXT[regionName] || "var(--text-3)",
                        }}>{regionName}</span>
                      )}
                    </div>
                  </div>
                  <div style={{ display: "flex", gap: 4, flexShrink: 0 }}>
                    <button className="btn sm ghost" onClick={() => openEdit(a)}
                      style={{ fontSize: 11, padding: "2px 6px" }}>编辑</button>
                    <button className="btn sm ghost" onClick={() => doDelete(a.asset_id)}
                      style={{ fontSize: 11, padding: "2px 6px", color: "var(--text-4)" }}>删除</button>
                  </div>
                </div>

                {/* 信息行 */}
                <div style={{ padding: "12px 16px 8px", display: "flex", flexDirection: "column", gap: 6 }}>
                  <div style={{ fontSize: 12, fontFamily: "var(--font-mono)", color: "var(--text-2)", display: "flex", alignItems: "center", gap: 8 }}>
                    <span style={{ fontWeight: 600, fontSize: 11, color: "var(--text-4)", textTransform: "uppercase", minWidth: 28 }}>
                      {a.protocol}
                    </span>
                    <span>{a.host}:{a.port}</span>
                    {a.username && <span style={{ color: "var(--text-4)" }}>@{a.username}</span>}
                  </div>
                  {(a.model || a.location) && (
                    <div style={{ fontSize: 12, color: "var(--text-3)", display: "flex", gap: 14 }}>
                      {a.model && <span>{a.model}</span>}
                      {a.location && <span>· {a.location}</span>}
                    </div>
                  )}
                </div>

                {/* 底栏 */}
                <div style={{
                  padding: "10px 16px", borderTop: "1px solid var(--line-2)",
                  display: "flex", gap: 8,
                }}>
                  <button className="btn primary" onClick={() => setTermAsset(a)}
                    style={{ flex: 1, justifyContent: "center", fontWeight: 600, fontSize: 13, padding: "7px 0" }}>
                    连接
                  </button>
                </div>
              </div>
            );
          })}
        </div>

        {assets.length > 0 && filtered.length === 0 && (
          <div style={{ textAlign: "center", padding: "40px", color: "var(--text-4)", fontSize: 13 }}>
            该区域暂无设备。
          </div>
        )}
      </div>
    </div>
  );
}
