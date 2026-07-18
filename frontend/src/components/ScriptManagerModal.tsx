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

const ENTER_ACTION = "__ENTER__";

function isEnterAction(value: string): boolean {
  return String(value || "").trim().toUpperCase() === ENTER_ACTION;
}

function displayCommand(value: string): string {
  return isEnterAction(value) ? "回车" : value;
}

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
    if (!c) { setError("前置命令不能为空；需要回车请点击「插入回车」"); return; }
    setPreCommands(prev => [...prev, c]);
    setDirty(true);
    setNewPreCmd(""); setShowAddPreRow(false); setError("");
  };
  const addPreEnter = () => {
    setPreCommands(prev => [...prev, ENTER_ACTION]);
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
    if (!c) { setError("后置命令不能为空；需要回车请点击「插入回车」"); return; }
    setPostCommands(prev => [...prev, c]);
    setDirty(true);
    setNewPostCmd(""); setShowAddPostRow(false); setError("");
  };
  const addPostEnter = () => {
    setPostCommands(prev => [...prev, ENTER_ACTION]);
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
    addEnterFn?: () => void,
  ) => (
    <div className="mb-3">
      <div className={`script-modal-list-label ${color}`}>{label}</div>
      <div className="script-modal-list">
        {items.map((cmd, i) => (
          <div key={`${label}-${i}`} className="script-modal-row">
            <span className="script-modal-row-idx">{i + 1}</span>
            <input
              className={`script-modal-input${isEnterAction(cmd) ? " readonly" : ""}`}
              value={displayCommand(cmd)}
              readOnly={isEnterAction(cmd)}
              onChange={e => editFn(i, e.target.value)}
            />
            <button type="button" className="btn sm ghost script-modal-row-del" onClick={() => delFn(i)} title="删除">×</button>
          </div>
        ))}
        {items.length === 0 && (
          <div className="script-modal-list-empty">暂无{label}，请添加。</div>
        )}
      </div>
      {addRow ? (
        <div className="script-modal-add-row">
          <input
            className="script-modal-input"
            placeholder={`输入${label}${addEnterFn ? "，需要回车请点插入回车" : ""}`}
            value={newVal}
            onChange={e => setNewVal(e.target.value)}
            onKeyDown={e => e.key === "Enter" && addFn()}
          />
          <button type="button" className="btn sm primary" onClick={addFn}>添加</button>
          {addEnterFn && (
            <button type="button" className="btn sm" onClick={addEnterFn}>插入回车</button>
          )}
          <button type="button" className="btn sm ghost" onClick={() => { setAddRow(false); setNewVal(""); setError(""); }}>取消</button>
        </div>
      ) : (
        <div className="script-modal-add-bar">
          <button type="button" className="btn sm" onClick={() => { setAddRow(true); setNewVal(""); }}>+ 添加{label}</button>
          {addEnterFn && (
            <button type="button" className="btn sm ghost" onClick={addEnterFn}>插入回车</button>
          )}
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
    <div className="modal-overlay" onClick={handleClose}>
      <div className="script-modal-panel" onClick={e => e.stopPropagation()}>
        {/* ── header ── */}
        <div className="modal-header">
          <div>
            <div className="modal-title">{TYPE_LABELS[scriptType] || scriptType}脚本管理</div>
            <div className="modal-subtitle">
              配置各厂商{TYPE_LABELS[scriptType] || scriptType}巡检命令列表。未配置则自动使用「通用」脚本；通用也未配置则该厂商将被跳过。
              前置/后置可插入显式回车动作，用于刷新欢迎横幅或发送确认。
            </div>
          </div>
          <button type="button" className="btn sm ghost modal-close" onClick={handleClose}>×</button>
        </div>

        {/* ── vendor tabs ── */}
        <div className="script-modal-tabs">
          {loading && <span className="text-sm faint">加载中...</span>}
          {vendors.map(v => {
            const active = activeVendor === v;
            return (
              <button key={v} type="button" onClick={() => switchVendor(v)}
                className={`script-modal-tab${active ? " active" : ""}`}>
                {VENDOR_LABELS[v] || v}
              </button>
            );
          })}
        </div>

        {/* ── body ── */}
        {!activeVendor ? (
          <div className="script-modal-empty">
            请选择一个厂商查看和编辑其巡检命令脚本。
          </div>
        ) : loading ? (
          <div className="script-modal-empty">加载中...</div>
        ) : (
          <div className="script-modal-body">
            <div className="row-flex mb-2">
              <span className={`script-modal-badge ${source === "file" ? "configured" : "unconfigured"}`}>
                {source === "file" ? "已配置" : "未配置"}
              </span>
              {isModified && <span className="text-xs warning-text">已修改，请保存以生效</span>}
              {source === "builtin" && commands.length === 0 && preCommands.length === 0 && postCommands.length === 0 && (
                <span className="text-xs faint">该厂商尚无脚本，请添加或上传 .txt</span>
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
              addCmd,
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
            {error && <div className="script-modal-error mt-2">{error}</div>}
            {successMsg && <div className="script-modal-success mt-2">{successMsg}</div>}
          </div>
        )}

        {/* ── footer ── */}
        {activeVendor && !loading && (
          <div className="script-modal-footer">
            <div className="row-flex">
              <input ref={fileInputRef} type="file" accept=".txt,.text" hidden onChange={handleFileChange} />
              <button type="button" className="btn" onClick={handleUpload}>上传 .txt 脚本</button>
              <button type="button" className="btn" onClick={handleReset}>恢复默认</button>
            </div>
            <div className="row-flex">
              <button type="button" className="btn" onClick={handleClose}>关闭</button>
              <button type="button" className="btn primary" onClick={handleSave} disabled={saving}>
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
