import { useState, useCallback, useEffect, type CSSProperties, type ReactNode } from "react";
import { useNavigate } from "react-router-dom";
import { useSessionStore } from "../../stores/session";
import { apiRequest } from "../../api/client";
import { RemoteTerminal } from "../../components/RemoteTerminal/RemoteTerminal";
import { ScriptManagerModal } from "../../components/ScriptManagerModal";

interface Asset {
  asset_id: string; name: string; type: string; vendor: string;
  model: string; host: string; port: number; protocol: string;
  username: string; region: string; location: string; description: string; tags: string[];
}

const TYPE_LABEL: Record<string, string> = {
  switch: "交换机", router: "路由器", firewall: "防火墙", server: "服务器",
  load_balancer: "负载均衡", wireless: "无线", other: "其他",
};
const VENDOR_STRIP: Record<string, string> = {
  H3C: "var(--info)", HuaWei: "#cf0a2c", Cisco: "#049fd9", Hillstone: "#0077be",
  Ruijie: "#0077be", Dipu: "#7e22ce",
};
const REGION_PRESETS = ["华东", "华南", "华北", "华西", "华东-核心", "华东-汇聚", "华东-接入",
                          "华南-核心", "华北-核心", "海外"];
const REGION_TINT: Record<string, string> = {
  "华东": "var(--info-soft)", "华南": "var(--ok-soft)", "华北": "#dbeafe",
  "华西": "#f3e8ff", "华东-核心": "#e0f2fe", "华东-汇聚": "#dbeafe", "华东-接入": "var(--surface-3)",
  "华南-核心": "#dcfce7", "华北-核心": "#dbeafe", "海外": "#fef3c7",
};
const REGION_TEXT: Record<string, string> = {
  "华东": "var(--info)", "华南": "var(--ok)", "华北": "#1e40af",
  "华西": "#7e22ce", "华东-核心": "#075985", "华东-汇聚": "#0369a1", "华东-接入": "var(--text-3)",
  "华南-核心": "#15803d", "华北-核心": "#1e40af", "海外": "#92400e",
};

// v3.9.13: vendor / region are user-typed strings. The combobox
// (``<datalist>``) lets the operator pick a preset or type anything
// for a custom entry — no more "select + extra input field" ceremony.
const VENDOR_PRESETS_LIST = [
  "H3C", "HuaWei", "Cisco", "Hillstone", "Ruijie", "Dipu",
];

// ── compact stat pill ──
function Stat({ label, value, color, sub }: { label: string; value: number | string; color: string; sub?: string }) {
  return (
    <div style={{ minWidth: 72 }}>
      <div style={{ fontSize: 22, fontWeight: 700, color, lineHeight: 1.2 }}>{value}</div>
      <div style={{ fontSize: 11, color: "var(--text-4)", marginTop: 2, whiteSpace: "nowrap" }}>{label}</div>
      {sub && <div style={{ fontSize: 10, color: "var(--text-5)", marginTop: 1, whiteSpace: "nowrap" }}>{sub}</div>}
    </div>
  );
}

export function CMDBPage() {
  const wsId = useSessionStore((s) => s.currentWorkspaceId);
  const navigate = useNavigate();
  const [assets, setAssets] = useState<Asset[]>([]);
  const [showForm, setShowForm] = useState(false);
  const [editingAsset, setEditingAsset] = useState<Asset | null>(null);
  const [termAsset, setTermAsset] = useState<Asset | null>(null);
  const [globalTerm, setGlobalTerm] = useState(false);
  const [regionFilter, setRegionFilter] = useState("");
  const [scriptManagerType, setScriptManagerType] = useState<"general" | "log" | null>(null);

  // ── form ──
  const [fv, setFv] = useState<Record<string, string>>({
    name: "", type: "switch", vendor: "", model: "", host: "", port: "22",
    protocol: "ssh", username: "", password: "", region: "", location: "", description: "", tags: "", err: "",
  });
  const ufv = (k: string, v: string) => setFv((p) => ({ ...p, [k]: v }));

  // v3.9.13: vendor / region are user-typed strings. The combobox
  // (``<datalist>``) lets the operator pick a preset or type anything
  // for a custom entry — no more "select + extra input field" ceremony.
  // We collect the union of preset + previously-typed values so the
  // combobox stays helpful as the CMDB grows.
  const [savedVendors, setSavedVendors] = useState<string[]>([...VENDOR_PRESETS_LIST]);
  const [savedRegions, setSavedRegions] = useState<string[]>([...REGION_PRESETS]);
  // v3.9.13: protocol picker shows the two primary live-terminal
  // choices (SSH / Telnet) as chips; everything else is collapsed
  // behind "其它协议".
  const [showAdvancedProtocol, setShowAdvancedProtocol] = useState(false);

  const load = useCallback(async () => {
    if (!wsId) return;
    try {
      const r = await apiRequest<{ ok: boolean; assets: Asset[] }>(
        { method: "GET", url: "/cmdb/assets", params: { workspace_id: wsId } });
      if (r.ok) {
        const list = r.assets || [];
        setAssets(list);
        const typedRegions = [...new Set(list.map(a => a.region).filter(Boolean))] as string[];
        setSavedRegions([...new Set([...REGION_PRESETS, ...typedRegions])]);
      }
    } catch { /* */ }
  }, [wsId]);

  useEffect(() => { load(); }, [load]);

  const openNew = () => {
    setEditingAsset(null);
    setFv({ name: "", type: "switch", vendor: "", model: "", host: "", port: "22",
      protocol: "ssh", username: "", password: "", region: "", location: "", description: "", tags: "", err: "" });
    setShowAdvancedProtocol(false);
    setShowForm(true);
  };

  const openEdit = (a: Asset) => {
    setEditingAsset(a);
    setFv({
      name: a.name, type: a.type, vendor: a.vendor, model: a.model,
      host: a.host, port: String(a.port), protocol: a.protocol,
      username: a.username, password: "", region: a.region || "",
      location: a.location, description: a.description || "", tags: (a.tags || []).join(", "), err: "",
    });
    // v3.9.13: SSH / Telnet live on the primary chip row; everything
    // else pops the "其它协议" disclosure.
    const adv = !["ssh", "telnet"].includes((a.protocol || "").toLowerCase());
    setShowAdvancedProtocol(adv);
    setShowForm(true);
  };

  const doSave = async () => {
    if (!fv.host) { ufv("err", "请输入主机地址"); return; }
    ufv("err", "");
    const payload: Record<string, unknown> = {
      workspace_id: wsId, asset_id: editingAsset?.asset_id || undefined,
      name: fv.name || fv.host, type: fv.type, vendor: fv.vendor, model: fv.model,
      host: fv.host, port: parseInt(fv.port) || 22, protocol: fv.protocol,
      username: fv.username,
      region: fv.region, location: fv.location, description: fv.description,
      tags: fv.tags.split(/[,，\s]+/).map(t => t.trim()).filter(Boolean),
    };
    if (fv.password) payload.password = fv.password;
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
  const activeInspectionRegion = regionFilter || (regionSet.length === 1 ? regionSet[0] : "");
  const activeInspectionRegionCount = activeInspectionRegion
    ? assets.filter(a => (a.region || "") === activeInspectionRegion).length
    : 0;
  const stats = assets.reduce((acc, a) => {
    const type = (a.type || "other").toLowerCase();
    const protocol = (a.protocol || "").toLowerCase();
    const vendor = (a.vendor || "").trim();
    const region = (a.region || "").trim();
    acc.total += 1;
    if (type === "switch") acc.switch += 1;
    else if (type === "router") acc.router += 1;
    else if (type === "firewall") acc.firewall += 1;
    else if (type === "server") acc.server += 1;
    else acc.other += 1;
    if (protocol === "ssh") acc.ssh += 1;
    if (protocol === "telnet") acc.telnet += 1;
    if (["ssh", "telnet"].includes(protocol)) acc.connectable += 1;
    if (vendor) acc.vendors.add(vendor);
    if (region) acc.regions.add(region);
    return acc;
  }, {
    total: 0, switch: 0, router: 0, firewall: 0, server: 0, other: 0,
    ssh: 0, telnet: 0, connectable: 0,
    vendors: new Set<string>(), regions: new Set<string>(),
  });

  const launchInspection = useCallback((scope: {
    region?: string; asset_ids?: string[]; label: string; source: string;
    type: "general" | "log";
  }) => {
    const region = (scope.region || "").trim();
    const assetIds = scope.asset_ids || [];
    const asset = assets.find(a => a.asset_id === assetIds[0]);
    const vendorInfo = asset?.vendor ? ` ${asset.vendor}` : "";
    const targetText = region
      ? `CMDB 区域「${region}」`
      : `CMDB 资产「${scope.label}」(${asset?.host || ""})`;

    const profileId = scope.type === "log" ? "log" : "general";
    const typeLabel = scope.type === "log" ? "日志巡检" : "通用巡检";
    const analysisHints = scope.type === "log"
      ? [
        `   - 异常告警和错误信息（CRITICAL / ERROR / WARNING 级别）`,
        `   - 重复出现的错误模式及频次`,
        `   - 接口 UP/DOWN 变更记录`,
        `   - 认证失败或安全事件`,
        `   - 时间分布规律（是否集中在某个时间窗口）`,
        ]
      : [
        `   - 是否完成、异常项、失败或跳过设备`,
        `   - 关键指标（CPU/内存/接口状态）的健康情况`,
        `   - 潜在风险或需要关注的告警`,
        `   - 下一步建议`,
        ];

    const scopeLine = region
      ? `   scope: { region: "${region}" }`
      : `   scope: { asset_ids: [${assetIds.map(id => `"${id}"`).join(", ")}] }`;

    const prompt = [
      `对 ${targetText}${vendorInfo} 发起${typeLabel}。`,
      `0. 先用 cmdb.assets 查询设备确认资产存在`,
      `1. 调用 inspection.manage action=run profile_id="${profileId}" 启动巡检${scopeLine.replace('   scope','')}`,
      `2. 记录返回的 task_id，用 action=get task_id=任务ID 每3秒轮询，直到 status=succeeded 或 partial`,
      `3. 用 action=report format=md task_id=任务ID 获取报告全文`,
      `4. 逐一读取报告中每台设备的原始命令输出，按以下维度分析：`,
      ...analysisHints,
      `输出结构化的${typeLabel}报告（不要只总结任务状态，要分析设备的具体数据）。`,
    ].join("\n");

    sessionStorage.setItem("workbench_auto_prompt", JSON.stringify({
      prompt,
      metadata: {
        intent: scope.type === "log" ? "cmdb_log_inspection" : (region ? "cmdb_region_inspection" : "cmdb_asset_inspection"),
        region,
        asset_ids: assetIds,
        source: scope.source,
      },
    }));
    navigate("/workbench");
  }, [navigate, assets]);

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
  // v3.9.13: custom input helper removed — vendor/region are
  // ``<input list="...">`` comboboxes tied to ``<datalist>``s that
  // grow with previously-saved values. No extra "select + 自定义填
  // 写" switch any more.
  const sectionTitle = (title: string, desc: string) => (
    <div style={{ gridColumn: "1 / -1", display: "flex", alignItems: "baseline", gap: 10, marginTop: 4 }}>
      <span style={{ fontSize: 13, fontWeight: 700, color: "var(--text)" }}>{title}</span>
      <span style={{ fontSize: 11, color: "var(--text-4)" }}>{desc}</span>
    </div>
  );
  const helpText = (text: string) => (
    <div style={{ fontSize: 11, color: "var(--text-4)", lineHeight: 1.45 }}>{text}</div>
  );

  // ── build dropdown options ──
  const typeOpts: [string, string][] = [
    ["switch", "交换机"], ["router", "路由器"], ["firewall", "防火墙"], ["server", "服务器"],
    ["load_balancer", "负载均衡"], ["wireless", "无线"], ["other", "其他"],
  ];

  // v3.9.13: SSH/Telnet are the *primary* live-terminal protocols and
  // render as toggle chips next to the host field. The remaining
  // protocols sit behind a collapsed "其它协议" disclosure because
  // they are non-interactive (we just persist the asset metadata).
  const terminalProtocols = [
    { value: "ssh", label: "SSH", desc: "可发起远程终端" },
    { value: "telnet", label: "Telnet", desc: "明文协议，仅在受控网络使用" },
  ];
  const passiveProtocols = [
    { value: "https", label: "HTTPS" },
    { value: "snmp", label: "SNMP" },
    { value: "netconf", label: "NETCONF" },
    { value: "restconf", label: "RESTCONF" },
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
          <button className="btn" onClick={() => setScriptManagerType("general")}
            style={{ fontWeight: 600, fontSize: 13, padding: "8px 14px", background: "var(--surface-2)" }}>
            通用脚本管理
          </button>
          <button className="btn" onClick={() => setScriptManagerType("log")}
            style={{ fontWeight: 600, fontSize: 13, padding: "8px 14px", background: "var(--surface-2)" }}>
            日志脚本管理
          </button>
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
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(86px, 1fr))",
          gap: 14,
          padding: "14px 18px", marginBottom: 18,
          borderRadius: 10, border: "1px solid var(--line-2)", background: "var(--surface)",
          alignItems: "center",
        }}>
          <Stat label="总资产" value={stats.total} color="var(--accent)" sub={`${stats.regions.size} 区域`} />
          <Stat label="可连接" value={stats.connectable} color="var(--ok)" sub={`SSH ${stats.ssh} / Telnet ${stats.telnet}`} />
          <Stat label="厂商" value={stats.vendors.size} color="#7e22ce" sub="已登记厂商" />
          <Stat label="交换机" value={stats.switch} color="var(--info)" />
          <Stat label="路由器" value={stats.router} color="#cf0a2c" />
          <Stat label="防火墙" value={stats.firewall} color="#e65100" />
          <Stat label="服务器" value={stats.server} color="#475569" />
          <Stat label="其它" value={stats.other} color="var(--text-4)" />
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
            <div style={{ flex: "1 1 160px" }} />
            <button
              type="button"
              className="btn"
              data-testid="cmdb-inspect-region-general"
              disabled={!activeInspectionRegion}
              title={activeInspectionRegion
                ? `跳转工作台，让 LLM 对 ${activeInspectionRegion} 的 ${activeInspectionRegionCount} 台设备发起通用巡检`
                : "选择区域后发起巡检"}
              onClick={() => {
                if (!activeInspectionRegion) return;
                launchInspection({
                  region: activeInspectionRegion,
                  label: activeInspectionRegion,
                  source: "cmdb_region_button",
                  type: "general",
                });
              }}
              style={{
                fontWeight: 600,
                fontSize: 13,
                padding: "7px 14px",
                opacity: activeInspectionRegion ? 1 : .55,
                whiteSpace: "nowrap",
                background: "var(--surface-2)",
              }}
            >
              通用巡检
            </button>
            <button
              type="button"
              className="btn"
              data-testid="cmdb-inspect-region-log"
              disabled={!activeInspectionRegion}
              title={activeInspectionRegion
                ? `跳转工作台，让 LLM 对 ${activeInspectionRegion} 的 ${activeInspectionRegionCount} 台设备发起日志巡检`
                : "选择区域后发起巡检"}
              onClick={() => {
                if (!activeInspectionRegion) return;
                launchInspection({
                  region: activeInspectionRegion,
                  label: activeInspectionRegion,
                  source: "cmdb_region_button",
                  type: "log",
                });
              }}
              style={{
                fontWeight: 600,
                fontSize: 13,
                padding: "7px 14px",
                opacity: activeInspectionRegion ? 1 : .55,
                whiteSpace: "nowrap",
                background: "var(--info-soft)",
                color: "var(--info)",
                border: "1px solid var(--info-soft)",
              }}
            >
              日志巡检
            </button>
          </div>
        )}

        {/* ── 全局终端 ── */}
        {globalTerm && <RemoteTerminal onClose={() => setGlobalTerm(false)} />}
        {termAsset && <RemoteTerminal onClose={() => setTermAsset(null)}
          initial={{ asset_id: termAsset.asset_id, host: termAsset.host, port: termAsset.port, protocol: termAsset.protocol,
            vendor: termAsset.vendor, username: termAsset.username, password: "" }} />}

        {/* ── 脚本管理弹窗 ── */}
        {scriptManagerType && (
          <ScriptManagerModal
            workspaceId={wsId || ""}
            scriptType={scriptManagerType}
            onClose={() => setScriptManagerType(null)}
          />
        )}

        {/* ── 新增/编辑弹窗 ── */}
        {showForm && (
          <div style={{
            position: "fixed", inset: 0, zIndex: 9999,
            background: "var(--overlay)", backdropFilter: "blur(3px)",
            display: "flex", alignItems: "center", justifyContent: "center",
            padding: 18,
          }} onClick={() => setShowForm(false)}>
            <div
              onClick={e => e.stopPropagation()}
              style={{
                width: "min(760px, 100%)", maxHeight: "92vh", overflow: "auto",
                background: "var(--surface)", borderRadius: 10,
                boxShadow: "var(--shadow-menu)", padding: 0,
                display: "flex", flexDirection: "column",
              }}>
              {/* 标题 */}
              <div style={{
                display: "flex", justifyContent: "space-between", alignItems: "flex-start",
                gap: 16, padding: "22px 24px 16px", borderBottom: "1px solid var(--line-2)",
                background: "var(--surface)",
              }}>
                <div>
                  <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                    <span style={{ fontWeight: 800, fontSize: 18, color: "var(--text)" }}>
                      {editingAsset ? "编辑设备资产" : "新增设备资产"}
                    </span>
                    {editingAsset?.asset_id && (
                      <span className="mono" style={{
                        fontSize: 11, color: "var(--text-4)", background: "var(--surface-3)",
                        border: "1px solid var(--line-2)", borderRadius: 5, padding: "2px 7px",
                      }}>{editingAsset.asset_id}</span>
                    )}
                  </div>
                  <div style={{ marginTop: 5, fontSize: 12, color: "var(--text-4)", lineHeight: 1.5 }}>
                    字段与 CMDB 后端一致；密码只会保存为服务端密钥，列表和详情不会返回明文。
                  </div>
                </div>
                <button className="btn sm ghost" onClick={() => setShowForm(false)}
                  style={{ fontSize: 18, padding: "2px 7px", color: "var(--text-4)", flexShrink: 0 }}>×</button>
              </div>

              <div style={{
                display: "grid", gridTemplateColumns: "repeat(12, minmax(0, 1fr))",
                gap: "13px 14px", padding: "18px 24px 8px",
              }}>
                {/* 基本信息 */}
                {sectionTitle("基础信息", "用于识别资产，LLM 会优先根据名称、厂商、型号和标签检索。")}
                <div style={{ gridColumn: "span 6" }}>{field("名称 *", inp("设备名称，例如：杭州核心交换机-01", "name", { fontFamily: "var(--font-sans)" }, false))}</div>
                <div style={{ gridColumn: "span 3" }}>{field("类型", sel("type", typeOpts))}</div>
                {/* v3.9.13: vendor is a combobox — pick from presets or type
                    anything for a custom entry. The datalist grows with
                    the CMDB. */}
                <div style={{ gridColumn: "span 3", display: "flex", flexDirection: "column", gap: 4 }}>
                  <span style={{ fontSize: 11, color: "var(--text-4)", fontWeight: 600 }}>厂商</span>
                  <input
                    list="cmdb-vendor-options"
                    placeholder="选择或输入，例如：H3C"
                    value={fv.vendor || ""}
                    onChange={e => ufv("vendor", e.target.value)}
                    style={stl(false)}
                    onFocus={e => e.currentTarget.style.borderColor = "var(--accent)"}
                    onBlur={e => e.currentTarget.style.borderColor = "var(--line)"}
                  />
                  <datalist id="cmdb-vendor-options">
                    {savedVendors.map(v => <option key={v} value={v} />)}
                  </datalist>
                </div>
                <div style={{ gridColumn: "span 4" }}>{field("型号", inp("型号，例如：S5735 / AR3260", "model", { fontFamily: "var(--font-sans)" }, false))}</div>
                <div style={{ gridColumn: "span 8" }}>{field("标签", inp("多个标签用逗号分隔，例如：核心, BGP, 生产", "tags", { fontFamily: "var(--font-sans)" }, false))}</div>

                {/* 区域 & 位置 */}
                {sectionTitle("区域与位置", "区域用于 LLM 分区检索和运维调度；位置用于机房、机柜、U 位等物理定位。")}
                {/* v3.9.13: region combobox — same pattern as vendor. */}
                <div style={{ gridColumn: "span 4", display: "flex", flexDirection: "column", gap: 4 }}>
                  <span style={{ fontSize: 11, color: "var(--text-4)", fontWeight: 600 }}>区域</span>
                  <input
                    list="cmdb-region-options"
                    placeholder="选择或输入，例如：华东"
                    value={fv.region || ""}
                    onChange={e => ufv("region", e.target.value)}
                    style={stl(false)}
                    onFocus={e => e.currentTarget.style.borderColor = "var(--accent)"}
                    onBlur={e => e.currentTarget.style.borderColor = "var(--line)"}
                  />
                  <datalist id="cmdb-region-options">
                    {savedRegions.map(r => <option key={r} value={r} />)}
                  </datalist>
                </div>
                <div style={{ gridColumn: "span 4" }}>{field("位置", inp("机房 / 机柜 / U 位，例如：7A-18U", "location", { fontFamily: "var(--font-sans)" }, false))}</div>
                <div style={{ gridColumn: "span 4", alignSelf: "end" }}>{helpText("示例：华东 / 杭州-A机房 / 7A-18U。区域越稳定，LLM 按区域查找越可靠。")}</div>
                <div style={{ gridColumn: "span 12" }}>{field("备注", inp("备注信息，例如用途、业务归属、维护窗口", "description", { fontFamily: "var(--font-sans)" }, false))}</div>

                {/* 连接信息分隔 */}
                {sectionTitle("连接凭据", "SSH / Telnet 可直接从资产发起远程终端；其它协议先作为资产资料保存。")}

                {/* v3.9.13: protocol picker is two-stage — primary chips
                    for SSH / Telnet (live-terminal protocols), an
                    "其它协议" disclosure for the rest. "ssh" remains
                    the default for new entries. */}
                <div style={{ gridColumn: "span 12", display: "flex", flexDirection: "column", gap: 6 }}>
                  <span style={{ fontSize: 11, color: "var(--text-4)", fontWeight: 600 }}>协议</span>
                  <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
                    {terminalProtocols.map(p => {
                      const active = (fv.protocol || "").toLowerCase() === p.value;
                      return (
                        <button
                          key={p.value}
                          type="button"
                          title={p.desc}
                          onClick={() => { ufv("protocol", p.value); setShowAdvancedProtocol(false); }}
                          style={{
                            padding: "6px 14px", borderRadius: "var(--r-pill)", cursor: "pointer",
                            border: `1px solid ${active ? "var(--accent)" : "var(--line-2)"}`,
                            background: active ? "var(--accent-soft)" : "var(--surface)",
                            color: active ? "var(--accent)" : "var(--text-3)",
                            fontSize: 13, fontWeight: 600, transition: "all .15s",
                          }}
                        >{p.label}</button>
                      );
                    })}
                    <button
                      type="button"
                      onClick={() => setShowAdvancedProtocol(v => !v)}
                      style={{
                        padding: "6px 12px", borderRadius: "var(--r-pill)", cursor: "pointer",
                        border: `1px solid ${showAdvancedProtocol ? "var(--accent)" : "var(--line)"}`,
                        background: "transparent", color: "var(--text-4)",
                        fontSize: 12,
                      }}
                    >{showAdvancedProtocol ? "收起其它协议" : "其它协议 ▾"}</button>
                    {showAdvancedProtocol && (
                      <div style={{ display: "flex", gap: 6, marginLeft: 4, flexWrap: "wrap" }}>
                        {passiveProtocols.map(p => {
                          const active = (fv.protocol || "").toLowerCase() === p.value;
                          return (
                            <button
                              key={p.value}
                              type="button"
                              onClick={() => ufv("protocol", p.value)}
                              style={{
                                padding: "5px 12px", borderRadius: "var(--r-pill)", cursor: "pointer",
                                border: `1px solid ${active ? "var(--accent)" : "var(--line)"}`,
                                background: active ? "var(--accent-soft)" : "var(--surface)",
                                color: active ? "var(--accent)" : "var(--text-4)",
                                fontSize: 12, fontWeight: 500,
                              }}
                            >{p.label}</button>
                          );
                        })}
                      </div>
                    )}
                  </div>
                </div>

                <div style={{ display: "flex", gap: 8, gridColumn: "span 12" }}>
                  <div style={{ flex: 1 }}>{field("主机 *", inp("192.168.1.1", "host"))}</div>
                  <div style={{ width: 92 }}>{field("端口", inp("22", "port", { textAlign: "center" }))}</div>
                </div>
                <div style={{ gridColumn: "span 6" }}>{field("用户名", inp("admin", "username"))}</div>
                <div style={{ gridColumn: "span 6", display: "flex", flexDirection: "column", gap: 4 }}>
                  <span style={{ fontSize: 11, color: "var(--text-4)", fontWeight: 600 }}>
                    密码 <span style={{ color: "var(--text-4)", fontWeight: 400 }}>· 后端保存为密钥，不返回明文</span>
                  </span>
                  <input
                    type="password"
                    placeholder={editingAsset ? "留空保留原密钥" : "选填；填入将覆盖"}
                    value={fv.password}
                    onChange={e => ufv("password", e.target.value)}
                    style={{
                      padding: "7px 10px", fontSize: 13, borderRadius: 6,
                      border: "1px solid var(--line)", background: "var(--surface)",
                      color: "var(--text)", outline: "none",
                      fontFamily: "var(--font-mono)", transition: "border-color .15s",
                    }}
                    onFocus={e => e.currentTarget.style.borderColor = "var(--accent)"}
                    onBlur={e => e.currentTarget.style.borderColor = "var(--line)"}
                  />
                </div>
                <div style={{ gridColumn: "span 12" }}>
                  <div style={{
                    border: "1px solid var(--line-2)", background: "var(--surface-2)",
                    borderRadius: 7, padding: "9px 11px", fontSize: 12,
                    color: "var(--text-3)", lineHeight: 1.55,
                  }}>
                    {editingAsset
                      ? "保存时密码留空 → 后端保留原 password_secret；填入新值才替换。"
                      : "保存后，LLM 和远程终端通过 asset_id 发起连接，看不到明文密码。"}
                  </div>
                </div>
              </div>

              {fv.err && (
                <div style={{ margin: "10px 24px 0", padding: "8px 12px", borderRadius: 6, background: "var(--warn-soft)", color: "var(--warn)", fontSize: 12, fontWeight: 500 }}>
                  {fv.err}
                </div>
              )}

              <div style={{
                display: "flex", gap: 8, justifyContent: "flex-end", marginTop: 18,
                padding: "14px 24px 20px", borderTop: "1px solid var(--line-2)",
              }}>
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
            const canOpenTerminal = ["ssh", "telnet"].includes((a.protocol || "").toLowerCase());
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
                  display: "flex", gap: 6,
                }}>
                  <button className="btn primary" onClick={() => canOpenTerminal && setTermAsset(a)}
                    disabled={!canOpenTerminal}
                    style={{ flex: 1, justifyContent: "center", fontWeight: 600, fontSize: 13, padding: "7px 0" }}>
                    {canOpenTerminal ? "连接" : "已保存资料"}
                  </button>
                  <button
                    className="btn"
                    type="button"
                    onClick={() => launchInspection({
                      asset_ids: [a.asset_id],
                      label: a.name || a.host,
                      source: "cmdb_asset_button",
                      type: "general",
                    })}
                    style={{
                      justifyContent: "center",
                      fontWeight: 600,
                      fontSize: 12,
                      padding: "7px 10px",
                      background: "var(--surface-2)",
                      flex: "0 1 auto",
                      whiteSpace: "nowrap",
                    }}
                  >
                    通用巡检
                  </button>
                  <button
                    className="btn"
                    type="button"
                    onClick={() => launchInspection({
                      asset_ids: [a.asset_id],
                      label: a.name || a.host,
                      source: "cmdb_asset_button",
                      type: "log",
                    })}
                    style={{
                      justifyContent: "center",
                      fontWeight: 600,
                      fontSize: 12,
                      padding: "7px 10px",
                      background: "var(--info-soft)",
                      color: "var(--info)",
                      border: "1px solid var(--info-soft)",
                      flex: "0 1 auto",
                      whiteSpace: "nowrap",
                    }}
                  >
                    日志巡检
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
