import { useState, useCallback, useEffect, useRef } from "react";
import { createPortal } from "react-dom";
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

  // ── command add state ──
  const [newCmd, setNewCmd] = useState("");
  const [showAddRow, setShowAddRow] = useState(false);

  // ── pre command add state ──
  const [newPreCmd, setNewPreCmd] = useState("");
  const [showAddPreRow, setShowAddPreRow] = useState(false);

  // ── post command add state ──
  const [newPostCmd, setNewPostCmd] = useState("");
  const [showAddPostRow, setShowAddPostRow] = useState(false);

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
    setShowAddRow(false); setNewCmd("");
    setShowAddPreRow(false); setNewPreCmd("");
    setShowAddPostRow(false); setNewPostCmd("");
  }, [workspaceId, scriptType]);

  useEffect(() => {
    if (activeVendor) loadVendor(activeVendor);
  }, [activeVendor, loadVendor]);

  // ── command handlers ──
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

  // ── pre command handlers ──
  const editPreCmd = (index: number, value: string) => {
    setPreCommands(prev => { const n = [...prev]; n[index] = value; return n; });
    setDirty(true);
  };
  const deletePreCmd = (index: number) => {
    setPreCommands(prev => prev.filter((_, i) => i !== index));
    setDirty(true);
  };
  const addPreCmd = () => {
    const c = newPreCmd.trim();
    // pre 允许空字符串（表示回车）
    setPreCommands(prev => [...prev, c]);
    setDirty(true);
    setNewPreCmd(""); setShowAddPreRow(false); setError("");
  };
  const addPreEnter = () => {
    setPreCommands(prev => [...prev, ""]);
    setDirty(true);
    setError("");
  };

  // ── post command handlers ──
  const editPostCmd = (index: number, value: string) => {
    setPostCommands(prev => { const n = [...prev]; n[index] = value; return n; });
    setDirty(true);
  };
  const deletePostCmd = (index: number) => {
    setPostCommands(prev => prev.filter((_, i) => i !== index));
    setDirty(true);
  };
  const addPostCmd = () => {
    const c = newPostCmd.trim();
    setPostCommands(prev => [...prev, c]);
    setDirty(true);
    setNewPostCmd(""); setShowAddPostRow(false); setError("");
  };
  const addPostEnter = () => {
    setPostCommands(prev => [...prev, ""]);
    setDirty(true);
    setError("");
  };

  const handleSave = async () => {
    setSaving(true); setError(""); setSuccessMsg("");
    try {
      const r = await scriptsApi.updateScript(
        workspaceId, activeVendor, commands, scriptType, preCommands, postCommands,
      );
      if (r.ok) {
        setSource("file");
        setDirty(false);
        setSuccessMsg(`已保存 ${r.command_count} 条命令，前置 ${r.pre_command_count} 条，后置 ${r.post_command_count} 条，下次巡检生效`);
      }
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "保存失败");
    }
    setSaving(false);
  };
  const handleReset = async () => {
    if (!window.confirm("确认恢复为默认？这将删除所有已保存的自定义命令、前置和后置命令。")) return;
    setSaving(true); setError(""); setSuccessMsg("");
    try {
      const r = await scriptsApi.resetScript(workspaceId, activeVendor, scriptType);
      if (r.ok) {
        setCommands([]);
        setPreCommands([]);
        setPostCommands([]);
        setSource("builtin");
        setDirty(false);
        setSuccessMsg("已恢复为默认（所有脚本为空）");
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

  // ── render a single editable list ──
  const renderCmdList = (
    items: string[],
    label: string,
    color: string,
    editFn: (i: number, v: string) => void,
    delFn: (i: number) => void,
    addRow: boolean,
    setAddRow: (v: boolean) => void,
    newVal: string,
    setNewVal: (v: string) => void,
    addFn: () => void,
    addEnterFn: () => void,
  ) => (
    <div style={{ marginBottom: 14 }}>
      <div style={{ fontWeight: 700, fontSize: 12, color: `var(--${color})`, marginBottom: 6 }}>
        {label}
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
        {items.map((cmd, i) => (
          <div key={`${label}-${i}`} style={{
            display: "flex", gap: 8, alignItems: "center", padding: "4px 0",
            borderBottom: i < items.length - 1 ? "1px solid var(--line-2)" : "none",
          }}>
            <span style={{
              fontSize: 11, fontFamily: "var(--font-mono)", color: "var(--text-4)",
              minWidth: 28, textAlign: "right", flexShrink: 0,
            }}>{i + 1}</span>
            <input
              value={cmd}
              placeholder={cmd === "" ? "(回车)" : undefined}
              onChange={e => editFn(i, e.target.value)}
              style={{
                ...inputStyle(true),
                flex: 1,
                fontStyle: cmd === "" ? "italic" : "normal",
                color: cmd === "" ? "var(--text-4)" : "var(--text)",
              }}
              onFocus={e => e.currentTarget.style.borderColor = "var(--accent)"}
              onBlur={e => e.currentTarget.style.borderColor = "var(--line)"}
            />
            <button className="btn sm ghost" onClick={() => delFn(i)}
              style={{ fontSize: 11, padding: "2px 6px", color: "var(--text-4)", flexShrink: 0 }}
              title="删除">×</button>
          </div>
        ))}
        {items.length === 0 && (
          <div style={{ textAlign: "center", padding: "10px", color: "var(--text-4)", fontSize: 12 }}>
            暂无{label}，请添加。
          </div>
        )}
      </div>
      {/* add row */}
      {addRow ? (
        <div style={{
          display: "flex", gap: 8, alignItems: "center", marginTop: 8,
          padding: "8px 12px", background: "var(--surface-2)", borderRadius: 7,
        }}>
          <input
            placeholder={`输入${label}（留空为回车）`}
            value={newVal}
            onChange={e => setNewVal(e.target.value)}
            style={{ ...inputStyle(true), flex: 1 }}
            onKeyDown={e => e.key === "Enter" && addFn()}
          />
          <button className="btn sm primary" onClick={addFn}
            style={{ fontSize: 11, padding: "3px 10px" }}>添加</button>
          <button className="btn sm" onClick={addEnterFn}
            style={{ fontSize: 11, padding: "3px 8px" }}>插入回车</button>
          <button className="btn sm ghost" onClick={() => { setAddRow(false); setNewVal(""); setError(""); }}
            style={{ fontSize: 11, padding: "3px 6px" }}>取消</button>
        </div>
      ) : (
        <div style={{ display: "flex", gap: 6, marginTop: 8 }}>
          <button className="btn sm" onClick={() => { setAddRow(true); setNewVal(""); }}
            style={{ fontSize: 12, padding: "4px 12px" }}>+ 添加{label}</button>
          <button className="btn sm ghost" onClick={addEnterFn}
            style={{ fontSize: 12, padding: "4px 10px" }}>插入回车</button>
        </div>
      )}
    </div>
  );

  // Escape closes with the same unsaved-changes guard as the × button
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") handleClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [handleClose]);

  return createPortal(
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
              空命令表示回车（Enter），用于刷新欢迎横幅或发送确认。
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
              {source === "builtin" && commands.length === 0 && preCommands.length === 0 && postCommands.length === 0 && (
                <span style={{ fontSize: 11, color: "var(--text-4)" }}>该厂商尚无脚本，请添加或上传 .txt</span>
              )}
            </div>

            {/* pre commands */}
            {renderCmdList(
              preCommands, "前置命令", "info",
              editPreCmd, deletePreCmd,
              showAddPreRow, setShowAddPreRow,
              newPreCmd, setNewPreCmd,
              addPreCmd, addPreEnter,
            )}

            {/* commands */}
            {renderCmdList(
              commands, "巡检命令", "accent",
              editCmd, deleteCmd,
              showAddRow, setShowAddRow,
              newCmd, setNewCmd,
              addCmd, () => { /* commands 不单独提供插入回车，因为命令不能是空 */ },
            )}

            {/* post commands */}
            {renderCmdList(
              postCommands, "后置命令", "ok",
              editPostCmd, deletePostCmd,
              showAddPostRow, setShowAddPostRow,
              newPostCmd, setNewPostCmd,
              addPostCmd, addPostEnter,
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
    </div>,
    document.body,
  );
}
