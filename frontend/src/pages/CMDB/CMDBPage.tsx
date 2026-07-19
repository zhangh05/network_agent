import { useState, useCallback, useEffect, type CSSProperties, type ReactNode } from "react";
import { useNavigate } from "react-router-dom";
import { useSessionStore } from "../../stores/session";
import { useToastStore } from "../../stores/toast";
import { apiRequest } from "../../api/client";
import { isApiError } from "../../types";
import { RemoteTerminal } from "../../components/RemoteTerminal/RemoteTerminal";
import { ScriptManagerModal } from "../../components/ScriptManagerModal";
import { confirm } from "../../components/ConfirmDialog";
import { PageHeader, FilterBar, Button, Input, Select, FormField } from "../../components/ui";

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
  H3C: "var(--info)", HuaWei: "var(--danger)", Cisco: "var(--ok)", Hillstone: "var(--accent)",
  Ruijie: "var(--accent)", Dipu: "var(--region-purple)",
};
const REGION_PRESETS = ["华东", "华南", "华北", "华西", "华东-核心", "华东-汇聚", "华东-接入",
                          "华南-核心", "华北-核心", "海外"];
const REGION_TINT: Record<string, string> = {
  "华东": "var(--info-soft)", "华南": "var(--ok-soft)", "华北": "var(--info-soft)",
  "华西": "var(--region-purple-soft)", "华东-核心": "var(--info-soft)", "华东-汇聚": "var(--info-soft)", "华东-接入": "var(--surface-3)",
  "华南-核心": "var(--ok-soft)", "华北-核心": "var(--info-soft)", "海外": "var(--region-amber-soft)",
};
const REGION_TEXT: Record<string, string> = {
  "华东": "var(--info)", "华南": "var(--ok)", "华北": "var(--info)",
  "华西": "var(--region-purple)", "华东-核心": "var(--info)", "华东-汇聚": "var(--info)", "华东-接入": "var(--text-3)",
  "华南-核心": "var(--ok)", "华北-核心": "var(--info)", "海外": "var(--region-amber)",
};
type CssVars = CSSProperties & Record<`--${string}`, string>;

function regionChipStyle(region: string, active: boolean): CssVars | undefined {
  if (!active) return undefined;
  return {
    "--chip-bg": REGION_TINT[region] || "var(--surface-3)",
    "--chip-color": REGION_TEXT[region] || "var(--text)",
    "--chip-border": REGION_TEXT[region] || "var(--text-3)",
  };
}

function assetCardStyle(asset: Asset): CssVars {
  const region = asset.region || "";
  return {
    "--asset-strip": VENDOR_STRIP[asset.vendor] || "var(--accent)",
    "--asset-region-bg": REGION_TINT[region] || "var(--surface-3)",
    "--asset-region-color": REGION_TEXT[region] || "var(--text-3)",
  };
}

// Vendor and region are user-typed strings. The combobox
// (``<datalist>``) lets the operator pick a preset or type anything
// for a custom entry — no more "select + extra input field" ceremony.
const VENDOR_PRESETS_LIST = [
  "H3C", "HuaWei", "Cisco", "Hillstone", "Ruijie", "Dipu",
];

// ── compact stat pill ──
function Stat({ label, value, className, sub }: { label: string; value: number | string; className?: string; sub?: string }) {
  return (
    <div className="stat-card">
      <div className={className ? `stat-value ${className}` : "stat-value"}>{value}</div>
      <div className="stat-label">{label}</div>
      {sub && <div className="stat-sub">{sub}</div>}
    </div>
  );
}

export function CMDBPage() {
  const wsId = useSessionStore((s) => s.currentWorkspaceId);
  const toast = useToastStore((s) => s.show);
  const navigate = useNavigate();
  const [assets, setAssets] = useState<Asset[]>([]);
  const [showForm, setShowForm] = useState(false);
  const [editingAsset, setEditingAsset] = useState<Asset | null>(null);
  const [termAsset, setTermAsset] = useState<Asset | null>(null);
  const [globalTerm, setGlobalTerm] = useState(false);
  const [regionFilter, setRegionFilter] = useState("");
  const [scriptManagerType, setScriptManagerType] = useState<"general" | "log" | null>(null);
  const [inspectionLoading, setInspectionLoading] = useState(false); // guard against double-click

  // ── form ──
  const [fv, setFv] = useState<Record<string, string>>({
    name: "", type: "switch", vendor: "", model: "", host: "", port: "22",
    protocol: "ssh", username: "", password: "", region: "", location: "", description: "", tags: "", err: "",
  });
  const ufv = (k: string, v: string) => setFv((p) => ({ ...p, [k]: v }));

  // Vendor and region are user-typed strings. The combobox
  // (``<datalist>``) lets the operator pick a preset or type anything
  // for a custom entry — no more "select + extra input field" ceremony.
  // We collect the union of preset + previously-typed values so the
  // combobox stays helpful as the CMDB grows.
  const [savedVendors] = useState<string[]>([...VENDOR_PRESETS_LIST]);
  const [savedRegions, setSavedRegions] = useState<string[]>([...REGION_PRESETS]);
  // Protocol picker shows the two primary live-terminal
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
    } catch { toast({ kind: "error", title: "资产加载失败", body: "无法加载 CMDB 资产列表" }); }
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
    // SSH / Telnet live on the primary chip row; everything
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
    try {
      await apiRequest({
        method: "POST", url: "/cmdb/assets",
        data: payload,
      });
      setShowForm(false); load();
    } catch (e: unknown) {
      ufv("err", isApiError(e) ? e.message : "保存失败");
    }
  };

  const doDelete = async (aid: string) => {
    const ok = await confirm({ title: "确认删除此资产？", destructive: true, confirmLabel: "删除" });
    if (!ok) return;
    try {
      await apiRequest({ method: "DELETE", url: `/cmdb/assets/${aid}`, params: { workspace_id: wsId } });
      load();
    } catch (e: unknown) {
      toast({ kind: "error", title: "删除失败", body: isApiError(e) ? e.message : "未知错误" });
    }
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
    if (inspectionLoading) return; // guard double-click
    setInspectionLoading(true);

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
      ? `异常告警和错误信息(CRITICAL/ERROR/WARNING)、重复错误模式及频次、接口UP/DOWN变更、认证失败或安全事件、时间分布规律`
      : `设备完成情况、关键指标(CPU/内存/接口)健康状态、潜在风险或告警、下一步建议`;

    // Fire inspection async, frontend polls in background
    (async () => {
      try {
        const scopePayload: Record<string, unknown> = {};
        if (region) scopePayload.region = region;
        if (assetIds.length) scopePayload.asset_ids = assetIds;

        const { inspectionApi } = await import("../../api/index");
        const r = await inspectionApi.createTask({
          workspace_id: wsId,
          profile_id: profileId,
          scope: scopePayload,
          async_run: true,
        });
        if (!r.ok) {
          toast({ kind: "error", title: "巡检启动失败", body: r.error || "未知错误" });
          setInspectionLoading(false);
          return;
        }
        // Use safe wrapper to avoid silent failures on localStorage
        try {
          localStorage.setItem("workbench_inspection", JSON.stringify({
            task_id: r.task_id,
            metadata: {
              intent: scope.type === "log" ? "cmdb_log_inspection" : (region ? "cmdb_region_inspection" : "cmdb_asset_inspection"),
              inspection_task_id: r.task_id,
              target: targetText,
              vendor: vendorInfo.trim(),
              type: scope.type,
              typeLabel,
              analysisHints,
              region,
              asset_ids: assetIds,
              source: scope.source,
            },
          }));
        } catch { /* localStorage unavailable — workbench won't auto-poll but task is running */ }
        navigate("/workbench");
      } catch (e: unknown) {
        toast({ kind: "error", title: "巡检启动失败", body: e instanceof Error ? e.message : String(e) });
        setInspectionLoading(false);
      }
    })();
  }, [navigate, assets, wsId, toast, inspectionLoading]);

  // ── form helpers ──
  const field = (label: string, child: ReactNode, span = 1) => (
    <FormField label={label} className={span > 1 ? "span-" + span : ""}>
      {child}
    </FormField>
  );
  const inp = (ph: string, key: string, _w: CSSProperties = {}, mono = true) => (
    <Input
      placeholder={ph} value={fv[key] || ""} onChange={e => ufv(key, e.target.value)}
      className={mono ? "mono" : ""}
    />
  );
  const sel = (key: string, opts: [string, string][], onChange?: (v: string) => void) => (
    <Select
      value={fv[key] || ""} onChange={e => { ufv(key, e.target.value); onChange?.(e.target.value); }}
    >
      {opts.map(([k, v]) => <option key={k} value={k}>{v}</option>)}
    </Select>
  );
  // Custom input helper removed — vendor/region are
  // ``<input list="...">`` comboboxes tied to ``<datalist>``s that
  // grow with previously-saved values. No extra "select + 自定义填
  // 写" switch any more.
  const sectionTitle = (title: string, desc: string) => (
    <div className="form-section-title">
      <span className="form-section-title-text">{title}</span>
      <span className="form-section-title-desc">{desc}</span>
    </div>
  );
  const helpText = (text: string) => (
    <div className="form-help-text">{text}</div>
  );

  // ── build dropdown options ──
  const typeOpts: [string, string][] = [
    ["switch", "交换机"], ["router", "路由器"], ["firewall", "防火墙"], ["server", "服务器"],
    ["load_balancer", "负载均衡"], ["wireless", "无线"], ["other", "其他"],
  ];

  // SSH/Telnet are the *primary* live-terminal protocols and
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
    <div className="page">
      <PageHeader title="设备资产" subtitle={`已注册 ${assets.length} 台设备`}>
        <Button onClick={() => setScriptManagerType("general")}>
          通用脚本管理
        </Button>
        <Button onClick={() => setScriptManagerType("log")}>
          日志脚本管理
        </Button>
        <Button onClick={() => setGlobalTerm(true)}>
          终端
        </Button>
        <Button variant="primary" onClick={openNew}>
          + 新增设备
        </Button>
      </PageHeader>

      <div className="page-body">
        {/* ── 统计栏 ── */}
        <div className="stat-grid">
          <Stat label="总资产" value={stats.total} className="stat-value-accent" sub={`${stats.regions.size} 区域`} />
          <Stat label="可连接" value={stats.connectable} className="stat-value-ok" sub={`SSH ${stats.ssh} / Telnet ${stats.telnet}`} />
          <Stat label="厂商" value={stats.vendors.size} className="stat-value-purple" sub="已登记厂商" />
          <Stat label="交换机" value={stats.switch} className="stat-value-info" />
          <Stat label="路由器" value={stats.router} className="stat-value-red" />
          <Stat label="防火墙" value={stats.firewall} className="stat-value-orange" />
          <Stat label="服务器" value={stats.server} className="stat-value-slate" />
          <Stat label="其它" value={stats.other} className="stat-value-muted" />
        </div>

        {/* ── 区域筛选 ── */}
        {regionSet.length > 0 && (
          <FilterBar>
            <span className="filter-chip-label">区域：</span>
            <button
              type="button"
              onClick={() => setRegionFilter("")}
              className={`filter-chip ${!regionFilter ? "active" : ""}`}
            >全部</button>
            {regionSet.map(r => {
              const active = regionFilter === r;
              return (
                <button
                  type="button"
                  key={r}
                  onClick={() => setRegionFilter(active ? "" : r)}
                  className={`filter-chip region ${active ? "active" : ""}`}
                  style={regionChipStyle(r, active)}
                >{r}</button>
          );
        })}
        <div className="spacer" />
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
        >
          通用巡检
        </button>
        <button
          type="button"
          className="btn btn-info-soft"
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
        >
          日志巡检
        </button>
      </FilterBar>
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
          <div className="modal-overlay" onClick={() => setShowForm(false)}>
            <div className="modal-sheet" onClick={e => e.stopPropagation()}>
              {/* 标题 */}
              <div className="modal-header">
                <div>
                  <div className="row-flex-sm">
                    <span className="modal-title">
                      {editingAsset ? "编辑设备资产" : "新增设备资产"}
                    </span>
                    {editingAsset?.asset_id && (
                      <span className="mono asset-id-badge">{editingAsset.asset_id}</span>
                    )}
                  </div>
                  <div className="modal-subtitle">
                    字段与 CMDB 后端一致；密码只会保存为服务端密钥，列表和详情不会返回明文。
                  </div>
                </div>
                <Button size="sm" variant="ghost" className="modal-close" onClick={() => setShowForm(false)}>×</Button>
              </div>

              <div className="modal-form-grid">
                {/* 基本信息 */}
                {sectionTitle("基础信息", "用于识别资产，LLM 会优先根据名称、厂商、型号和标签检索。")}
                <div className="span-6">{field("名称 *", inp("设备名称，例如：杭州核心交换机-01", "name", {}, false))}</div>
                <div className="span-3">{field("类型", sel("type", typeOpts))}</div>
                <div className="span-3">
                  <FormField label="厂商">
                    <Input list="cmdb-vendor-options" placeholder="选择或输入，例如：H3C" value={fv.vendor || ""} onChange={e => ufv("vendor", e.target.value)} />
                    <datalist id="cmdb-vendor-options">
                      {savedVendors.map(v => <option key={v} value={v} />)}
                    </datalist>
                  </FormField>
                </div>
                <div className="span-4">{field("型号", inp("型号，例如：S5735 / AR3260", "model", {}, false))}</div>
                <div className="span-8">{field("标签", inp("多个标签用逗号分隔，例如：核心, BGP, 生产", "tags", {}, false))}</div>

                {/* 区域 & 位置 */}
                {sectionTitle("区域与位置", "区域用于 LLM 分区检索和运维调度；位置用于机房、机柜、U 位等物理定位。")}
                <div className="span-4">
                  <FormField label="区域">
                    <Input list="cmdb-region-options" placeholder="选择或输入，例如：华东" value={fv.region || ""} onChange={e => ufv("region", e.target.value)} />
                    <datalist id="cmdb-region-options">
                      {savedRegions.map(r => <option key={r} value={r} />)}
                    </datalist>
                  </FormField>
                </div>
                <div className="span-4">{field("位置", inp("机房 / 机柜 / U 位，例如：7A-18U", "location", {}, false))}</div>
                <div className="span-4 align-end">{helpText("示例：华东 / 杭州-A机房 / 7A-18U。区域越稳定，LLM 按区域查找越可靠。")}</div>
                <div className="span-12">{field("备注", inp("备注信息，例如用途、业务归属、维护窗口", "description", {}, false))}</div>

                {/* 连接信息分隔 */}
                {sectionTitle("连接凭据", "SSH / Telnet 可直接从资产发起远程终端；其它协议先作为资产资料保存。")}

                <div className="protocol-section">
                  <span className="protocol-label">协议</span>
                  <div className="protocol-row">
                    {terminalProtocols.map(p => {
                      const active = (fv.protocol || "").toLowerCase() === p.value;
                      return (
                        <button
                          key={p.value}
                          type="button"
                          title={p.desc}
                          onClick={() => { ufv("protocol", p.value); setShowAdvancedProtocol(false); }}
                          className={"protocol-chip" + (active ? " active" : "")}
                        >{p.label}</button>
                      );
                    })}
                    <button
                      type="button"
                      onClick={() => setShowAdvancedProtocol(v => !v)}
                      className={"protocol-advanced-toggle" + (showAdvancedProtocol ? " active" : "")}
                    >{showAdvancedProtocol ? "收起其它协议" : "其它协议 ▾"}</button>
                    {showAdvancedProtocol && (
                      <div className="protocol-advanced-list">
                        {passiveProtocols.map(p => {
                          const active = (fv.protocol || "").toLowerCase() === p.value;
                          return (
                            <button
                              key={p.value}
                              type="button"
                              onClick={() => ufv("protocol", p.value)}
                              className={"protocol-advanced-chip" + (active ? " active" : "")}
                            >{p.label}</button>
                          );
                        })}
                      </div>
                    )}
                  </div>
                </div>

                <div className="host-port-row">
                  <div className="flex-1">{field("主机 *", inp("192.168.1.1", "host"))}</div>
                  <div className="cmdb-port-field">{field("端口", inp("22", "port"))}</div>
                </div>
                <div className="span-6">{field("用户名", inp("admin", "username"))}</div>
                <div className="span-6">
                  <FormField label={<span>密码 <span className="password-label-hint">· 后端保存为密钥，不返回明文</span></span>}>
                    <Input type="password" placeholder={editingAsset ? "留空保留原密钥" : "选填；填入将覆盖"} value={fv.password} onChange={e => ufv("password", e.target.value)} className="mono" />
                  </FormField>
                </div>
                <div className="span-12">
                  <div className="password-hint-box">
                    {editingAsset
                      ? "保存时密码留空 → 后端保留原 password_secret；填入新值才替换。"
                      : "保存后，LLM 和远程终端通过内部设备编号发起连接，看不到明文密码。"}
                  </div>
                </div>
              </div>

              {fv.err && (
                <div className="error-banner">
                  {fv.err}
                </div>
              )}

              <div className="modal-footer">
                <Button onClick={() => setShowForm(false)}>取消</Button>
                <Button variant="primary" onClick={doSave}>
                  {editingAsset ? "保存更改" : "创建设备"}
                </Button>
              </div>
            </div>
          </div>
        )}

        {/* ── 空状态 ── */}
        {assets.length === 0 && (
          <div className="empty-center">
            <div className="empty-icon">⊞</div>
            <div className="empty-title">暂无设备</div>
            <div className="empty-hint">点击 <b>+ 新增设备</b> 注册第一台网络设备。</div>
          </div>
        )}

        {/* ── 设备卡片 ── */}
        <div className="asset-card-grid">
          {filtered.map(a => {
            const regionName = a.region || "";
            const canOpenTerminal = ["ssh", "telnet"].includes((a.protocol || "").toLowerCase());
            return (
            <div key={a.asset_id} className="asset-card" style={assetCardStyle(a)}>
              <div className="asset-card-header">
                <div className="asset-card-title">
                  <div className="asset-card-name">{a.name || a.host}</div>
                  <div className="asset-card-meta">
                    <span className="asset-card-type">{TYPE_LABEL[a.type] || a.type}</span>
                    {a.vendor && (
                      <span className="asset-card-vendor">{a.vendor}</span>
                    )}
                    {regionName && (
                      <span className="asset-card-region">
                        {regionName}
                      </span>
                    )}
                  </div>
                </div>
                <div className="asset-card-actions">
                  <button type="button" className="btn sm ghost" onClick={() => openEdit(a)}>编辑</button>
                  <button type="button" className="btn sm ghost text-danger" onClick={() => doDelete(a.asset_id)}>删除</button>
                </div>
              </div>

              <div className="asset-card-body">
                <div className="asset-card-host">
                  <span className="asset-card-protocol">{a.protocol}</span>
                  <span>{a.host}:{a.port}</span>
                  {a.username && <span className="asset-card-username">@{a.username}</span>}
                </div>
                {(a.model || a.location) && (
                  <div className="asset-card-extra">
                    {a.model && <span>{a.model}</span>}
                    {a.location && <span>· {a.location}</span>}
                  </div>
                )}
              </div>

              <div className="asset-card-footer">
                <button type="button" className="btn primary" onClick={() => canOpenTerminal && setTermAsset(a)}
                  disabled={!canOpenTerminal}>
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
                >
                  通用巡检
                </button>
                <button
                  className="btn btn-info-soft"
                  type="button"
                  onClick={() => launchInspection({
                    asset_ids: [a.asset_id],
                    label: a.name || a.host,
                    source: "cmdb_asset_button",
                    type: "log",
                  })}
                >
                  日志巡检
                </button>
              </div>
            </div>
            );
          })}
        </div>

        {assets.length > 0 && filtered.length === 0 && (
          <div className="empty-sm">该区域暂无设备。</div>
        )}
      </div>
    </div>
  );
}
