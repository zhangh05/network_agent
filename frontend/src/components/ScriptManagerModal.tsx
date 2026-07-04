import { useState, useCallback, useEffect, useRef } from "react";
import { scriptsApi, type VendorScriptDetailResponse, type VendorScriptsListResponse } from "../api/index";

interface Props {
  workspaceId: string;
  onClose: () => void;
}

const VENDOR_LABELS: Record<string, string> = {
  h3c: "H3C", h3c_firewall: "H3C 防火墙", huawei: "Huawei",
  cisco: "Cisco", ruijie: "Ruijie", hillstone: "Hillstone",
  server: "服务器", generic: "通用",
};

export function ScriptManagerModal({ workspaceId, onClose }: Props) {
  const [vendors, setVendors] = useState<string[]>([]);
  const [activeVendor, setActiveVendor] = useState("");
  const [commands, setCommands] = useState<Record<string, string>>({});
  const [builtinCommands, setBuiltinCommands] = useState<Record<string, string>>({});
  const [source, setSource] = useState<"builtin" | "file">("builtin");
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [successMsg, setSuccessMsg] = useState("");
  const [newKey, setNewKey] = useState("");
  const [newCmd, setNewCmd] = useState("");
  const [showAddRow, setShowAddRow] = useState(false);
  const [dirty, setDirty] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  // ── load vendor list ──
  useEffect(() => {
    (async () => {
      setLoading(true);
      try {
        const r = await scriptsApi.getScripts(workspaceId) as VendorScriptsListResponse;
        if (r.ok && r.vendors) {
          setVendors(r.vendors.map(v => v.vendor));
        }
      } catch { /* */ }
      setLoading(false);
    })();
  }, [workspaceId]);

  // ── load vendor script when active vendor changes ──
  const loadVendor = useCallback(async (vendor: string) => {
    if (!vendor) return;
    setLoading(true);
    try {
      const r = await scriptsApi.getScripts(workspaceId, vendor);
      if (!r.ok) return;
      const d = r as VendorScriptDetailResponse;
      setCommands(d.commands || {});
      setBuiltinCommands(d.builtin_commands || {});
      setSource(d.source);
      setDirty(false);
      setError("");
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "加载脚本失败");
    }
    setLoading(false);
    setSuccessMsg("");
    setShowAddRow(false);
    setNewKey(""); setNewCmd("");
  }, [workspaceId]);

  useEffect(() => {
    if (activeVendor) loadVendor(activeVendor);
  }, [activeVendor, loadVendor]);

  // ── handlers ──
  const editCmd = (key: string, value: string) => {
    setCommands(prev => ({ ...prev, [key]: value }));
    setDirty(true);
  };
  const deleteCmd = (key: string) => {
    setCommands(prev => {
      const next = { ...prev };
      delete next[key];
      return next;
    });
    setDirty(true);
  };
  const addCmd = () => {
    const k = newKey.trim();
    const c = newCmd.trim();
    if (!k || !c) { setError("命令键和命令内容不能为空"); return; }
    if (commands[k]) { setError(`命令键 "${k}" 已存在`); return; }
    setCommands(prev => ({ ...prev, [k]: c }));
    setDirty(true);
    setNewKey(""); setNewCmd(""); setShowAddRow(false); setError("");
  };
  const handleSave = async () => {
    setSaving(true); setError(""); setSuccessMsg("");
    try {
      const r = await scriptsApi.updateScript(workspaceId, activeVendor, commands);
      if (r.ok) {
        setSource("file");
        setDirty(false);
        setSuccessMsg(`已保存 ${r.command_count} 条命令，下次巡检生效`);
      }
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "保存失败");
    }
    setSaving(false);
  };
  const handleReset = async () => {
    if (!window.confirm("确认恢复为内置默认脚本？这将删除已保存的自定义命令。")) return;
    setSaving(true); setError(""); setSuccessMsg("");
    try {
      const r = await scriptsApi.resetScript(workspaceId, activeVendor);
      if (r.ok) {
        setCommands({ ...builtinCommands });
        setSource("builtin");
        setDirty(false);
        setSuccessMsg("已恢复为默认脚本");
      }
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "重置失败");
    }
    setSaving(false);
  };
  const handleUpload = () => {
    fileInputRef.current?.click();
  };
  const handleFileChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    try {
      const text = await file.text();
      setSaving(true); setError(""); setSuccessMsg("");
      const r = await scriptsApi.uploadScript(workspaceId, activeVendor, text);
      if (r.ok) {
        setSuccessMsg("脚本文件已上传，正在重新加载...");
        await loadVendor(activeVendor);
      }
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "上传失败");
    }
    setSaving(false);
    if (fileInputRef.current) fileInputRef.current.value = "";
  };

  const commandEntries = Object.entries(commands);
  const isModified = source === "file" || Object.entries(commands).some(
    ([k, v]) => builtinCommands[k] !== v
  );

  const switchVendor = (v: string) => {
    if (dirty && !window.confirm("当前脚本有未保存的修改，切换厂商将丢失更改。是否继续？")) {
      return;
    }
    setActiveVendor(v);
  };

  const handleClose = () => {
    if (dirty && !window.confirm("当前脚本有未保存的修改，关闭将丢失更改。是否继续？")) {
      return;
    }
    onClose();
  };

  // ── shared style helpers (matching CMDBPage conventions) ──
  const inputStyle = (mono = true, extra: Record<string, string> = {}) => ({
    padding: "5px 8px", fontSize: 12, borderRadius: 5,
    border: "1px solid var(--line)", background: "var(--surface)",
    color: "var(--text)", outline: "none",
    fontFamily: mono ? "var(--font-mono)" : "var(--font-sans)",
    transition: "border-color .15s",
    ...extra,
  } as const);

  return (
    <div style={{
      position: "fixed", inset: 0, zIndex: 9999,
      background: "var(--overlay)", backdropFilter: "blur(3px)",
      display: "flex", alignItems: "center", justifyContent: "center",
      padding: 18,
    }} onClick={handleClose}>
      <div
        onClick={e => e.stopPropagation()}
        style={{
          width: "min(780px, 100%)", maxHeight: "92vh", overflow: "auto",
          background: "var(--surface)", borderRadius: 10,
          boxShadow: "var(--shadow-menu)", padding: 0,
          display: "flex", flexDirection: "column",
        }}>
        {/* ── header ── */}
        <div style={{
          display: "flex", justifyContent: "space-between", alignItems: "flex-start",
          gap: 16, padding: "22px 24px 16px", borderBottom: "1px solid var(--line-2)",
          background: "var(--surface)",
        }}>
          <div>
            <div style={{ fontWeight: 800, fontSize: 18, color: "var(--text)" }}>
              厂商脚本管理
            </div>
            <div style={{ marginTop: 5, fontSize: 12, color: "var(--text-4)", lineHeight: 1.5 }}>
              自定义各厂商的巡检命令。修改后下次巡检生效，不影响内置默认值。
            </div>
          </div>
          <button className="btn sm ghost" onClick={handleClose}
            style={{ fontSize: 18, padding: "2px 7px", color: "var(--text-4)", flexShrink: 0 }}>×</button>
        </div>

        {/* ── vendor tabs ── */}
        <div style={{
          padding: "12px 24px", borderBottom: "1px solid var(--line-2)",
          display: "flex", gap: 6, flexWrap: "wrap",
        }}>
          {loading && <span style={{ fontSize: 12, color: "var(--text-4)" }}>加载中...</span>}
          {vendors.map(v => {
            const active = activeVendor === v;
            return (
              <button
                key={v}
                type="button"
                onClick={() => switchVendor(v)}
                style={{
                  padding: "4px 14px", borderRadius: "var(--r-pill)", cursor: "pointer",
                  border: `1px solid ${active ? "var(--accent)" : "var(--line-2)"}`,
                  background: active ? "var(--accent-soft)" : "transparent",
                  color: active ? "var(--accent)" : "var(--text-3)",
                  fontSize: 12, fontWeight: 600, transition: "all .15s",
                }}
              >{VENDOR_LABELS[v] || v}</button>
            );
          })}
        </div>

        {/* ── body ── */}
        {!activeVendor ? (
          <div style={{ padding: "60px 24px", textAlign: "center", color: "var(--text-4)", fontSize: 13 }}>
            请选择一个厂商查看和编辑其巡检命令脚本。
          </div>
        ) : loading ? (
          <div style={{ padding: "40px 24px", textAlign: "center", color: "var(--text-4)", fontSize: 13 }}>
            加载中...
          </div>
        ) : (
          <div style={{ padding: "16px 24px", flex: 1, overflow: "auto" }}>
            {/* source badge */}
            <div style={{
              display: "flex", alignItems: "center", justifyContent: "space-between",
              marginBottom: 14,
            }}>
              <span style={{
                fontSize: 11, fontWeight: 600, padding: "2px 10px", borderRadius: "var(--r-pill)",
                background: source === "file" ? "var(--ok-soft)" : "var(--surface-3)",
                color: source === "file" ? "var(--ok)" : "var(--text-4)",
              }}>
                {source === "file" ? "自定义脚本" : "内置默认"}
              </span>
              {isModified && (
                <span style={{ fontSize: 11, color: "var(--warn)" }}>
                  已修改，请保存以生效
                </span>
              )}
            </div>

            {/* command list */}
            <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
              {commandEntries.map(([key, cmd], i) => {
                const isBuiltin = builtinCommands.hasOwnProperty(key);
                const isChanged = builtinCommands[key] !== cmd;
                return (
                  <div key={key}
                    style={{
                      display: "flex", gap: 8, alignItems: "center",
                      padding: "4px 0",
                      borderBottom: i < commandEntries.length - 1 ? "1px solid var(--line-2)" : "none",
                    }}>
                    <span style={{
                      fontSize: 11, fontFamily: "var(--font-mono)", color: "var(--text-4)",
                      minWidth: 120, maxWidth: 160, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
                      flexShrink: 0,
                    }} title={key}>{key}</span>
                    <div style={{ flex: 1, display: "flex", gap: 6, alignItems: "center" }}>
                      <input
                        value={cmd}
                        onChange={e => editCmd(key, e.target.value)}
                        style={{
                          ...inputStyle(true),
                          flex: 1,
                          borderColor: isChanged ? "var(--warn)" : "var(--line)",
                          background: isChanged ? "var(--warn-soft)" : "var(--surface)",
                        }}
                        onFocus={e => e.currentTarget.style.borderColor = "var(--accent)"}
                        onBlur={e => e.currentTarget.style.borderColor = isChanged ? "var(--warn)" : "var(--line)"}
                      />
                      {!isBuiltin && (
                        <span style={{ fontSize: 10, color: "var(--info)", fontWeight: 600, whiteSpace: "nowrap" }}>自定义</span>
                      )}
                      {isChanged && (
                        <span style={{ fontSize: 10, color: "var(--warn)", fontWeight: 600, whiteSpace: "nowrap" }}>已改</span>
                      )}
                      <button
                        className="btn sm ghost"
                        onClick={() => deleteCmd(key)}
                        style={{ fontSize: 11, padding: "2px 6px", color: "var(--text-4)", flexShrink: 0 }}
                        title="删除此命令"
                      >×</button>
                    </div>
                  </div>
                );
              })}
              {commandEntries.length === 0 && (
                <div style={{ textAlign: "center", padding: "30px", color: "var(--text-4)", fontSize: 13 }}>
                  该厂商暂无命令配置。
                </div>
              )}
            </div>

            {/* add row */}
            {showAddRow && (
              <div style={{
                display: "flex", gap: 8, alignItems: "center",
                marginTop: 10, padding: "8px 12px",
                background: "var(--surface-2)", borderRadius: 7,
              }}>
                <input
                  placeholder="命令键 (如 custom_check)"
                  value={newKey}
                  onChange={e => setNewKey(e.target.value)}
                  style={{ ...inputStyle(true), width: 140 }}
                  onKeyDown={e => e.key === "Enter" && addCmd()}
                />
                <input
                  placeholder="命令内容 (如 display ip route)"
                  value={newCmd}
                  onChange={e => setNewCmd(e.target.value)}
                  style={{ ...inputStyle(true), flex: 1 }}
                  onKeyDown={e => e.key === "Enter" && addCmd()}
                />
                <button className="btn sm primary" onClick={addCmd}
                  style={{ fontSize: 11, padding: "3px 10px" }}>添加</button>
                <button className="btn sm ghost" onClick={() => { setShowAddRow(false); setError(""); }}
                  style={{ fontSize: 11, padding: "3px 6px" }}>取消</button>
              </div>
            )}

            {!showAddRow && (
              <button
                className="btn sm"
                onClick={() => { setShowAddRow(true); setNewKey(""); setNewCmd(""); }}
                style={{ marginTop: 10, fontSize: 12, padding: "4px 12px" }}
              >+ 添加命令</button>
            )}

            {/* messages */}
            {error && (
              <div style={{
                marginTop: 10, padding: "8px 12px", borderRadius: 6,
                background: "var(--danger-soft)", color: "var(--danger)",
                fontSize: 12, fontWeight: 500,
              }}>{error}</div>
            )}
            {successMsg && (
              <div style={{
                marginTop: 10, padding: "8px 12px", borderRadius: 6,
                background: "var(--ok-soft)", color: "var(--ok)",
                fontSize: 12, fontWeight: 500,
              }}>{successMsg}</div>
            )}
          </div>
        )}

        {/* ── footer ── */}
        {activeVendor && !loading && (
          <div style={{
            display: "flex", gap: 8, justifyContent: "space-between",
            padding: "14px 24px 20px", borderTop: "1px solid var(--line-2)",
          }}>
            <div style={{ display: "flex", gap: 8 }}>
              <input
                ref={fileInputRef}
                type="file"
                accept=".txt,.text"
                style={{ display: "none" }}
                onChange={handleFileChange}
              />
              <button className="btn" onClick={handleUpload}
                style={{ padding: "7px 14px", fontSize: 12 }}>
                上传 .txt 脚本
              </button>
              <button className="btn" onClick={handleReset}
                style={{ padding: "7px 14px", fontSize: 12 }}>
                恢复默认
              </button>
            </div>
            <div style={{ display: "flex", gap: 8 }}>
              <button className="btn" onClick={handleClose}
                style={{ padding: "7px 16px", fontSize: 13 }}>关闭</button>
              <button className="btn primary" onClick={handleSave}
                disabled={saving}
                style={{ padding: "7px 22px", fontSize: 13 }}>
                {saving ? "保存中..." : "保存脚本"}
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
