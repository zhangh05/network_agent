import { useState, useCallback, useEffect, useRef } from "react";
import { scriptsApi, type VendorScriptDetailResponse, type VendorScriptsListResponse } from "../api/index";

interface Props {
  workspaceId: string;
  scriptType: "general" | "log";
  onClose: () => void;
}

const VENDOR_LABELS: Record<string, string> = {
  h3c: "H3C", huawei: "HuaWei", cisco: "Cisco", hillstone: "Hillstone", ruijie: "Ruijie", dipu: "Dipu", generic: "通用",
};

const TYPE_LABELS: Record<string, string> = {
  general: "通用", log: "日志",
};

export function ScriptManagerModal({ workspaceId, scriptType, onClose }: Props) {
  const [vendors, setVendors] = useState<string[]>([]);
  const [activeVendor, setActiveVendor] = useState("");
  const [commands, setCommands] = useState<string[]>([]);
  const [builtinCommands, setBuiltinCommands] = useState<string[]>([]);
  const [preCommands, setPreCommands] = useState<string[]>([]);
  const [postCommands, setPostCommands] = useState<string[]>([]);
  const [source, setSource] = useState<"builtin" | "file">("builtin");
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [successMsg, setSuccessMsg] = useState("");
  const [newCmd, setNewCmd] = useState("");
  const [showAddRow, setShowAddRow] = useState(false);
  const [dirty, setDirty] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  // ── load vendor list ──
  useEffect(() => {
    (async () => {
      setLoading(true);
      try {
        const r = await scriptsApi.getScripts(workspaceId, undefined, scriptType) as VendorScriptsListResponse;
        if (r.ok && r.vendors) {
          setVendors(r.vendors.map(v => v.vendor));
        }
      } catch { /* */ }
      setLoading(false);
    })();
  }, [workspaceId, scriptType]);

  // ── load vendor script when active vendor changes ──
  const loadVendor = useCallback(async (vendor: string) => {
    if (!vendor) return;
    setLoading(true);
    try {
      const r = await scriptsApi.getScripts(workspaceId, vendor, scriptType);
      if (!r.ok) return;
      const d = r as VendorScriptDetailResponse;
      setCommands(d.commands || []);
      setBuiltinCommands(d.builtin_commands || []);
      setPreCommands(d.pre_commands || []);
      setPostCommands(d.post_commands || []);
      setSource(d.source);
      setDirty(false);
      setError("");
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "加载脚本失败");
    }
    setLoading(false);
    setSuccessMsg("");
    setShowAddRow(false);
    setNewCmd("");
  }, [workspaceId, scriptType]);

  useEffect(() => {
    if (activeVendor) loadVendor(activeVendor);
  }, [activeVendor, loadVendor]);

  // ── handlers ──
  const editCmd = (index: number, value: string) => {
    setCommands(prev => { const n = [...prev]; n[index] = value; return n; });
    setDirty(true);
  };
  const deleteCmd = (index: number) => {
    setCommands(prev => prev.filter((_, i) => i !== index));
    setDirty(true);
  };
  const addCmd = () => {
    const c = newCmd.trim();
    if (!c) { setError("命令不能为空"); return; }
    setCommands(prev => [...prev, c]);
    setDirty(true);
    setNewCmd(""); setShowAddRow(false); setError("");
  };
  const handleSave = async () => {
    setSaving(true); setError(""); setSuccessMsg("");
    try {
      const r = await scriptsApi.updateScript(workspaceId, activeVendor, commands, scriptType);
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
    if (!window.confirm("确认恢复为默认？这将删除所有已保存的自定义命令。")) return;
    setSaving(true); setError(""); setSuccessMsg("");
    try {
      const r = await scriptsApi.resetScript(workspaceId, activeVendor, scriptType);
      if (r.ok) {
        setCommands([]);
        setSource("builtin");
        setDirty(false);
        setSuccessMsg("已恢复为默认（命令列表为空）");
      }
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "重置失败");
    }
    setSaving(false);
  };
  const handleUpload = () => fileInputRef.current?.click();
  const handleFileChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    try {
      const text = await file.text();
      setSaving(true); setError(""); setSuccessMsg("");
      const r = await scriptsApi.uploadScript(workspaceId, activeVendor, text, scriptType);
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

  const isModified = source === "file" || JSON.stringify(commands) !== JSON.stringify(builtinCommands);

  const switchVendor = (v: string) => {
    if (dirty && !window.confirm("当前脚本有未保存的修改，切换厂商将丢失更改。是否继续？")) return;
    setActiveVendor(v);
  };
  const handleClose = () => {
    if (dirty && !window.confirm("当前脚本有未保存的修改，关闭将丢失更改。是否继续？")) return;
    onClose();
  };

  // ── style ──
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
      <div onClick={e => e.stopPropagation()} style={{
        width: "min(820px, 100%)", maxHeight: "92vh", overflow: "auto",
        background: "var(--surface)", borderRadius: 10,
        boxShadow: "var(--shadow-menu)", padding: 0,
        display: "flex", flexDirection: "column",
      }}>
        {/* ── header ── */}
        <div style={{
          display: "flex", justifyContent: "space-between", alignItems: "flex-start",
          gap: 16, padding: "22px 24px 16px", borderBottom: "1px solid var(--line-2)",
        }}>
          <div>
            <div style={{ fontWeight: 800, fontSize: 18, color: "var(--text)" }}>{TYPE_LABELS[scriptType] || scriptType}脚本管理</div>
            <div style={{ marginTop: 5, fontSize: 12, color: "var(--text-4)", lineHeight: 1.5 }}>
              配置各厂商{TYPE_LABELS[scriptType] || scriptType}巡检命令列表。未配置则自动使用「通用」脚本；通用也未配置则该厂商将被跳过。
              前置/后置命令（screen-length disable 等）为内置脚本，不可修改。
            </div>
          </div>
          <button className="btn sm ghost" onClick={handleClose}
            style={{ fontSize: 18, padding: "2px 7px", color: "var(--text-4)", flexShrink: 0 }}>×</button>
        </div>

        {/* ── vendor tabs ── */}
        <div style={{ padding: "12px 24px", borderBottom: "1px solid var(--line-2)", display: "flex", gap: 6, flexWrap: "wrap" }}>
          {loading && <span style={{ fontSize: 12, color: "var(--text-4)" }}>加载中...</span>}
          {vendors.map(v => {
            const active = activeVendor === v;
            return (
              <button key={v} type="button" onClick={() => switchVendor(v)} style={{
                padding: "4px 14px", borderRadius: "var(--r-pill)", cursor: "pointer",
                border: `1px solid ${active ? "var(--accent)" : "var(--line-2)"}`,
                background: active ? "var(--accent-soft)" : "transparent",
                color: active ? "var(--accent)" : "var(--text-3)",
                fontSize: 12, fontWeight: 600, transition: "all .15s",
              }}>{VENDOR_LABELS[v] || v}</button>
            );
          })}
        </div>

        {/* ── body ── */}
        {!activeVendor ? (
          <div style={{ padding: "60px 24px", textAlign: "center", color: "var(--text-4)", fontSize: 13 }}>
            请选择一个厂商查看和编辑其巡检命令脚本。
          </div>
        ) : loading ? (
          <div style={{ padding: "40px 24px", textAlign: "center", color: "var(--text-4)", fontSize: 13 }}>加载中...</div>
        ) : (
          <div style={{ padding: "16px 24px", flex: 1, overflow: "auto" }}>
            {/* source badge */}
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 10 }}>
              <span style={{
                fontSize: 11, fontWeight: 600, padding: "2px 10px", borderRadius: "var(--r-pill)",
                background: source === "file" ? "var(--ok-soft)" : "var(--warn-soft)",
                color: source === "file" ? "var(--ok)" : "var(--warn)",
              }}>{source === "file" ? "已配置" : "未配置"}</span>
              {isModified && <span style={{ fontSize: 11, color: "var(--warn)" }}>已修改，请保存以生效</span>}
              {source === "builtin" && commands.length === 0 && (
                <span style={{ fontSize: 11, color: "var(--text-4)" }}>该厂商尚无巡检命令，请添加或上传 .txt</span>
              )}
            </div>

            {/* pre/post commands (read-only display) */}
            {(preCommands.length > 0 || postCommands.length > 0) && (
              <div style={{
                marginBottom: 12, padding: "8px 12px", borderRadius: 6,
                background: "var(--surface-2)", border: "1px solid var(--line-2)",
                fontSize: 11, color: "var(--text-4)", lineHeight: 1.6,
              }}>
                <div style={{ fontWeight: 600, marginBottom: 4, color: "var(--text-3)" }}>
                  内置前置/后置命令（不可编辑）
                </div>
                {preCommands.map((c, i) => (
                  <div key={`pre-${i}`} style={{ fontFamily: "var(--font-mono)", color: "var(--info)" }}>
                    [前置] {c || "(回车)"}
                  </div>
                ))}
                {postCommands.map((c, i) => (
                  <div key={`post-${i}`} style={{ fontFamily: "var(--font-mono)", color: "var(--ok)" }}>
                    [后置] {c || "(回车)"}
                  </div>
                ))}
              </div>
            )}

            {/* command list */}
            <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
              {commands.map((cmd, i) => {
                const isBuiltin = i < builtinCommands.length;
                const isChanged = !isBuiltin || builtinCommands[i] !== cmd;
                return (
                  <div key={i} style={{
                    display: "flex", gap: 8, alignItems: "center", padding: "4px 0",
                    borderBottom: i < commands.length - 1 ? "1px solid var(--line-2)" : "none",
                  }}>
                    <span style={{
                      fontSize: 11, fontFamily: "var(--font-mono)", color: "var(--text-4)",
                      minWidth: 28, textAlign: "right", flexShrink: 0,
                    }}>{i + 1}</span>
                    <input
                      value={cmd}
                      onChange={e => editCmd(i, e.target.value)}
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
                      <span style={{ fontSize: 10, color: "var(--info)", fontWeight: 600, whiteSpace: "nowrap" }}>新增</span>
                    )}
                    {isChanged && isBuiltin && (
                      <span style={{ fontSize: 10, color: "var(--warn)", fontWeight: 600, whiteSpace: "nowrap" }}>已改</span>
                    )}
                    <button className="btn sm ghost" onClick={() => deleteCmd(i)}
                      style={{ fontSize: 11, padding: "2px 6px", color: "var(--text-4)", flexShrink: 0 }}
                      title="删除">×</button>
                  </div>
                );
              })}
              {commands.length === 0 && (
                <div style={{ textAlign: "center", padding: "30px", color: "var(--text-4)", fontSize: 13, lineHeight: 1.6 }}>
                  {source === "file" ? "脚本为空，请添加命令。" : "尚未配置脚本。添加命令或上传 .txt 文件后，该厂商设备才能参与巡检。"}
                </div>
              )}
            </div>

            {/* add row */}
            {showAddRow && (
              <div style={{
                display: "flex", gap: 8, alignItems: "center", marginTop: 10,
                padding: "8px 12px", background: "var(--surface-2)", borderRadius: 7,
              }}>
                <input
                  placeholder="输入命令，如 display version"
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
              <button className="btn sm" onClick={() => { setShowAddRow(true); setNewCmd(""); }}
                style={{ marginTop: 10, fontSize: 12, padding: "4px 12px" }}>+ 添加命令</button>
            )}

            {/* messages */}
            {error && (
              <div style={{ marginTop: 10, padding: "8px 12px", borderRadius: 6,
                background: "var(--danger-soft)", color: "var(--danger)", fontSize: 12, fontWeight: 500 }}>{error}</div>
            )}
            {successMsg && (
              <div style={{ marginTop: 10, padding: "8px 12px", borderRadius: 6,
                background: "var(--ok-soft)", color: "var(--ok)", fontSize: 12, fontWeight: 500 }}>{successMsg}</div>
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
              <input ref={fileInputRef} type="file" accept=".txt,.text"
                style={{ display: "none" }} onChange={handleFileChange} />
              <button className="btn" onClick={handleUpload}
                style={{ padding: "7px 14px", fontSize: 12 }}>上传 .txt 脚本</button>
              <button className="btn" onClick={handleReset}
                style={{ padding: "7px 14px", fontSize: 12 }}>恢复默认</button>
            </div>
            <div style={{ display: "flex", gap: 8 }}>
              <button className="btn" onClick={handleClose}
                style={{ padding: "7px 16px", fontSize: 13 }}>关闭</button>
              <button className="btn primary" onClick={handleSave} disabled={saving}
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
