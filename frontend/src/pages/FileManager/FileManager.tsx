import { useState, useEffect, useRef } from "react";
import { useNavigate } from "react-router-dom";
import { useSessionStore } from "../../stores/session";
import { apiRequest } from "../../api/client";

interface FileRecord {
  file_id: string;
  type: string;
  title: string;
  filename: string;
  mime_type: string;
  size: number;
  tags: string[];
  workspace_id: string;
  source: string;
  indexed: boolean;
  parent_id: string | null;
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

const TYPE_TABS: Array<{ key: string; label: string }> = [
  { key: "all", label: "全部" },
  { key: "pcap", label: "报文" },
  { key: "pcap_analysis", label: "分析结果" },
  { key: "knowledge", label: "知识" },
  { key: "memory", label: "记忆" },
  { key: "artifact", label: "制品" },
  { key: "general", label: "通用" },
];

const TYPE_BADGE_MAP: Record<string, string> = {
  pcap: "info", pcap_analysis: "muted", knowledge: "accent", memory: "ok", artifact: "muted", general: "info",
};

function hasPcapSession(f: FileRecord): boolean {
  return f.type === "pcap" && typeof f.metadata?.session_id === "string" && f.metadata.session_id.length > 0;
}

function isPcapAnalysis(f: FileRecord): boolean {
  return f.type === "pcap_analysis"
    || (f.type === "pcap" && !hasPcapSession(f) && (f.source === "agent" || f.tags?.includes("analysis")));
}

function matchesType(f: FileRecord, type: string): boolean {
  if (type === "all") return true;
  if (type === "pcap") return hasPcapSession(f);
  if (type === "pcap_analysis") return isPcapAnalysis(f);
  return f.type === type;
}

function typeLabel(f: FileRecord): string {
  if (isPcapAnalysis(f)) return "分析结果";
  return TYPE_TABS.find(t => t.key === f.type)?.label || f.type;
}

function fmtSize(bytes: number): string {
  if (bytes < 1024) return `${bytes}B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)}KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)}MB`;
}

function fmtTime(iso: string): string {
  try { return new Date(iso).toLocaleDateString("zh-CN"); } catch { return iso.slice(0, 10); }
}

export function FileManager() {
  const { currentWorkspaceId } = useSessionStore();
  const navigate = useNavigate();
  const ws = currentWorkspaceId || "default";

  const [activeType, setActiveType] = useState("all");
  const [allFiles, setAllFiles] = useState<FileRecord[]>([]);
  const [loading, setLoading] = useState(false);
  const [selected, setSelected] = useState<FileRecord | null>(null);
  const [detailContent, setDetailContent] = useState<string | null>(null);
  const [showUpload, setShowUpload] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [pcapUploading, setPcapUploading] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);
  const pcapRef = useRef<HTMLInputElement>(null);

  const triggerPcapUpload = () => {
    const input = document.createElement("input");
    input.type = "file";
    input.accept = ".pcap,.pcapng,.cap";
    input.onchange = (e) => {
      const f = (e.target as HTMLInputElement).files?.[0];
      if (f) handlePcapUpload(f);
    };
    input.click();
  };

  const triggerPcap = () => {
    if (pcapRef.current) pcapRef.current.click();
    else triggerPcapUpload();
  };
  const files = activeType === "all"
    ? allFiles
    : allFiles.filter(f => matchesType(f, activeType));

  const handleUpload = async (file: File, type: string) => {
    setUploading(true);
    const form = new FormData();
    form.append("file", file);
    form.append("type", type);
    form.append("title", file.name);
    form.append("workspace_id", ws);
    try {
      const res = await apiRequest<{ ok: boolean; file_id: string }>({
        method: "POST", url: "/files", data: form,
      });
      if (res.ok) { await fetchFiles(); setShowUpload(false); }
    } catch {}
    setUploading(false);
  };

  const handlePcapUpload = async (file: File) => {
    setPcapUploading(true);
    const form = new FormData();
    form.append("file", file);
    form.append("workspace_id", ws);
    try {
      const res = await apiRequest<{ ok: boolean; error?: string; session_id: string }>({
        method: "POST", url: "/pcap/parse", data: form,
      });
      if (res.ok) {
        // Pcap parse stores the file via files API, refresh the list
        await fetchFiles();
      }
    } catch {}
    setPcapUploading(false);
  };

  const fetchFiles = async () => {
    setLoading(true);
    try {
      const res = await apiRequest<{ ok: boolean; files: FileRecord[] }>({
        method: "GET", url: `/files?workspace_id=${ws}`,
      });
      setAllFiles(res.files || []);
    } catch {}
    finally { setLoading(false); }
  };

  useEffect(() => { fetchFiles(); }, [activeType, ws]);

  const selectFile = (f: FileRecord) => {
    setSelected(f);
    setDetailContent(null);
    if (["knowledge", "memory", "artifact", "general", "pcap_analysis"].includes(f.type) || isPcapAnalysis(f)) {
      apiRequest<{ ok: boolean; content?: string }>({
        method: "GET", url: `/files/${f.file_id}/content?workspace_id=${ws}`,
      }).then(r => { if (r.ok) setDetailContent(r.content || null); }).catch(() => {});
    }
  };

  const deleteFile = async (fileId: string) => {
    const f = files.find(x => x.file_id === fileId);
    if (!confirm(`删除 "${f?.title || f?.filename || fileId}"？`)) return;
    try {
      await apiRequest({ method: "DELETE", url: `/files/${fileId}?workspace_id=${ws}` });
      setAllFiles(prev => prev.filter(x => x.file_id !== fileId));
      if (selected?.file_id === fileId) setSelected(null);
    } catch {}
  };

  return (
    <div className="page">
      <div className="page-header">
        <div>
          <h1>文件管理</h1>
          <p className="subtitle">知识库 · 记忆 · 制品 · 报文分析 — 统一存储</p>
        </div>
        <div style={{ display: "flex", gap: 8 }}>
          {activeType === "knowledge" && (
            <button className="btn primary sm" onClick={() => setShowUpload(true)}>上传文档</button>
          )}
          {activeType === "pcap" && (
            <>
              <input ref={pcapRef} type="file" accept=".pcap,.pcapng,.cap" style={{ display: "none" }}
                onChange={e => {
                  const f = e.target.files?.[0];
                  if (f) handlePcapUpload(f);
                  e.target.value = "";
                }} />
              <button className="btn primary sm" onClick={triggerPcap} disabled={pcapUploading}>
                {pcapUploading ? "上传中…" : "上传 pcap"}
              </button>
            </>
          )}
          <button className="btn sm ghost" onClick={fetchFiles} title="刷新列表">↻</button>
        </div>
      </div>

      {/* Upload inline form — only for knowledge tab */}
      {showUpload && activeType === "knowledge" && (
        <div className="card" style={{ padding: "12px 16px", margin: "0 0 12px", borderColor: "var(--accent)" }}>
          <div className="card-title">上传知识文档</div>
          <div style={{ display: "flex", gap: 8, alignItems: "center", marginTop: 8, flexWrap: "wrap" }}>
            <input ref={fileRef} type="file" accept=".md,.txt,.pdf,.docx,.html" style={{ display: "none" }}
              onChange={e => {
                const f = e.target.files?.[0];
                if (f) handleUpload(f, "knowledge");
                e.target.value = "";
              }} />
            <button className="btn primary sm" onClick={() => fileRef.current?.click()} disabled={uploading}>
              {uploading ? "上传中…" : "选择文档"}
            </button>
            <span style={{ fontSize: "var(--fs-11)", color: "var(--text-4)" }}>支持 md / txt / pdf / docx / html</span>
            <button className="btn ghost sm" onClick={() => setShowUpload(false)} style={{ marginLeft: "auto" }}>取消</button>
          </div>
        </div>
      )}

      <div className="split-shell" style={{ flex: 1 }}>
        {/* ========== LEFT ========== */}
        <aside style={{ display: "flex", flexDirection: "column" }}>
          {/* Type tabs */}
          <div style={{
            display: "flex",
            gap: 6,
            padding: "8px 12px",
            borderBottom: "1px solid var(--line-2)",
            flexWrap: "wrap",
            alignItems: "center",
            flexShrink: 0,
          }}>
            {TYPE_TABS.map(t => {
              const count = t.key === "all"
                ? allFiles.length
                : allFiles.filter(f => matchesType(f, t.key)).length;
              return (
                <button key={t.key} onClick={() => { setActiveType(t.key); setSelected(null); }}
                  className={`btn sm ${t.key === activeType ? "primary" : "ghost"}`}
                  style={{
                    padding: "4px 8px",
                    minWidth: 0,
                    fontSize: "var(--fs-11)",
                    fontWeight: t.key === activeType ? 700 : 500,
                    display: "inline-flex",
                    alignItems: "center",
                    gap: 5,
                    whiteSpace: "nowrap",
                    lineHeight: 1.2,
                  }}>
                  <span>{t.label}</span>
                  <span style={{
                    minWidth: 16,
                    height: 16,
                    padding: "0 5px",
                    borderRadius: 999,
                    display: "inline-flex",
                    alignItems: "center",
                    justifyContent: "center",
                    fontSize: "var(--fs-10)",
                    fontWeight: 700,
                    background: t.key === activeType ? "rgba(255,255,255,0.22)" : "var(--surface-2)",
                    color: t.key === activeType ? "inherit" : "var(--text-3)",
                  }}>{count}</span>
                </button>
              );
            })}
          </div>

          {/* File list */}
          <div style={{ flex: 1, overflow: "auto", padding: "8px 12px" }}>
            {loading && <div style={{ padding: 24, textAlign: "center", color: "var(--text-4)" }}>加载中…</div>}

            {!loading && files.length === 0 && (
              <div className="empty" style={{ padding: 40 }}>
                <div className="empty-text">暂无文件</div>
                {activeType === "pcap" && (
                  <button className="btn primary" style={{ marginTop: 12 }} onClick={triggerPcap} disabled={pcapUploading}>
                    上传 pcap →
                  </button>
                )}
              </div>
            )}

            {files.map(f => {
              const isActive = selected?.file_id === f.file_id;
              return (
                <div key={f.file_id} className="card" onClick={() => selectFile(f)}
                  style={{
                    padding: "10px 12px", cursor: "pointer", marginBottom: 6,
                    borderColor: isActive ? "var(--accent)" : "var(--line)",
                    background: isActive ? "var(--accent-soft)" : undefined,
                  }}>
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 6 }}>
                    <div style={{ fontSize: "var(--fs-13)", fontWeight: 680, wordBreak: "break-all", minWidth: 0 }}>
                      {f.title || f.filename}
                    </div>
                    <div style={{ display: "flex", gap: 4, flexShrink: 0 }}>
                      {f.indexed && <span className="badge ok" style={{ fontSize: "var(--fs-10)" }}>RAG</span>}
                    </div>
                  </div>
                  <div style={{ display: "flex", gap: 6, marginTop: 4, alignItems: "center", flexWrap: "wrap" }}>
                    <span className={`badge ${TYPE_BADGE_MAP[f.type] || "muted"}`} style={{ fontSize: "var(--fs-10)" }}>
                      {typeLabel(f)}
                    </span>
                    {f.filename && f.title && f.filename !== f.title && (
                      <span style={{ fontSize: "var(--fs-10)", color: "var(--text-4)" }}>{f.filename}</span>
                    )}
                    <span style={{ fontSize: "var(--fs-10)", color: "var(--text-4)" }}>{fmtSize(f.size)}</span>
                    <span style={{ fontSize: "var(--fs-10)", color: "var(--text-4)" }}>{fmtTime(f.created_at)}</span>
                  </div>
                </div>
              );
            })}
          </div>

          {/* Left footer */}
          <div style={{ padding: "6px 12px", borderTop: "1px solid var(--line-2)", fontSize: "var(--fs-10)", color: "var(--text-4)", flexShrink: 0 }}>
            {allFiles.length} 项 · 工作区 {ws}
          </div>
        </aside>

        {/* ========== RIGHT ========== */}
        <div className="split-detail" style={{ display: "flex", flexDirection: "column" }}>
          {!selected ? (
            <div className="empty" style={{ flex: 1 }}>
              <div className="empty-text">选择文件查看详情</div>
              <div className="empty-hint">点击左侧列表中的文件查看元数据、内容预览与操作</div>
            </div>
          ) : (
            <>
              {/* Detail header */}
              <div className="card" style={{ padding: "14px 16px", marginBottom: 12, flexShrink: 0 }}>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
                  <div>
                    <h3 style={{ fontSize: "var(--fs-16)", fontWeight: 720, margin: 0 }}>
                      {selected.title || selected.filename}
                    </h3>
                    <div style={{ display: "flex", gap: 6, marginTop: 6, flexWrap: "wrap", fontSize: "var(--fs-11)", color: "var(--text-3)" }}>
                      <span className={`badge ${TYPE_BADGE_MAP[selected.type] || "muted"}`}>
                        {typeLabel(selected)}
                      </span>
                      <span style={{ fontFamily: "var(--font-mono)", color: "var(--text-4)" }}>{selected.file_id}</span>
                      {selected.filename && <span>{selected.filename}</span>}
                      <span>{fmtSize(selected.size)}</span>
                      <span>{selected.source}</span>
                      <span>{fmtTime(selected.created_at)}</span>
                      {selected.indexed && <span className="badge ok">已索引</span>}
                      {selected.parent_id && <span style={{ fontFamily: "var(--font-mono)", color: "var(--text-4)" }}>← {selected.parent_id}</span>}
                    </div>
                  </div>
                  <div style={{ display: "flex", gap: 6 }}>
                    {hasPcapSession(selected) && (
                      <button className="btn primary sm" onClick={() => navigate(`/packet?sid=${selected.metadata?.session_id || ""}`)}>分析</button>
                    )}
                    <button className="btn danger-ghost sm" onClick={() => deleteFile(selected.file_id)}>删除</button>
                  </div>
                </div>
                {/* Tags */}
                {selected.tags.length > 0 && (
                  <div style={{ display: "flex", gap: 4, marginTop: 8 }}>
                    {selected.tags.map(t => (
                      <span key={t} className="badge muted" style={{ fontSize: "var(--fs-10)" }}>{t}</span>
                    ))}
                  </div>
                )}
              </div>

              {/* Metadata card */}
              <div className="card" style={{ padding: "12px 16px", marginBottom: 12, flexShrink: 0 }}>
                <div className="card-title">元数据</div>
                <div style={{ display: "grid", gridTemplateColumns: "auto 1fr", gap: "3px 16px", fontSize: "var(--fs-11)", fontFamily: "var(--font-mono)", marginTop: 8 }}>
                  <span style={{ color: "var(--text-4)" }}>ID</span><span>{selected.file_id}</span>
                  <span style={{ color: "var(--text-4)" }}>类型</span><span>{selected.type}</span>
                  <span style={{ color: "var(--text-4)" }}>大小</span><span>{fmtSize(selected.size)}</span>
                  <span style={{ color: "var(--text-4)" }}>MIME</span><span>{selected.mime_type || "—"}</span>
                  <span style={{ color: "var(--text-4)" }}>来源</span><span>{selected.source}</span>
                  <span style={{ color: "var(--text-4)" }}>工作区</span><span>{selected.workspace_id}</span>
                  <span style={{ color: "var(--text-4)" }}>更新时间</span><span>{selected.updated_at}</span>
                  {selected.metadata && Object.entries(selected.metadata)
                    .filter(([k]) => k !== "content" && k !== "filepath")
                    .map(([k, v]) => [
                      <span key={`k-${k}`} style={{ color: "var(--text-4)" }}>{k}</span>,
                      <span key={`v-${k}`} style={{ wordBreak: "break-all" }}>
                        {typeof v === "object" ? JSON.stringify(v) : String(v)}
                      </span>
                    ]).flat()}
                </div>
              </div>

              {/* Content / Preview */}
              {hasPcapSession(selected) ? (
                <div className="card" style={{ padding: "14px 16px", flex: 1 }}>
                  <div className="card-title">报文信息</div>
                  <div style={{ marginTop: 8, fontSize: "var(--fs-13)", color: "var(--text-2)" }}>
                    {selected.metadata?.total_packets
                      ? `${selected.metadata.total_packets} 个报文 · ${selected.metadata.connection_count ?? 0} 条连接`
                      : "上传后可查看详情"}
                  </div>
                  <button className="btn primary" style={{ marginTop: 12 }} onClick={() => navigate(`/packet?sid=${selected.metadata?.session_id || ""}`)}>
                    打开报文分析 →
                  </button>
                </div>
              ) : detailContent ? (
                <div className="card" style={{ padding: "0", flex: 1, overflow: "auto", display: "flex", flexDirection: "column" }}>
                  <div className="card-title" style={{ margin: "12px 16px 0" }}>内容预览</div>
                  <pre style={{
                    margin: "8px 0 0", padding: "12px 16px", flex: 1,
                    fontFamily: "var(--font-mono)", fontSize: "var(--fs-12)",
                    lineHeight: 1.6, whiteSpace: "pre-wrap", wordBreak: "break-word",
                    color: "var(--text-2)", background: "var(--surface-2)",
                    borderTop: "1px solid var(--line-2)",
                  }}>{detailContent.slice(0, 8000)}{detailContent.length > 8000 ? "\n\n... (内容已截断)" : ""}</pre>
                </div>
              ) : !hasPcapSession(selected) ? (
                <div className="empty" style={{ flex: 1 }}>
                  <div className="empty-text">无内容</div>
                  <div className="empty-hint">该文件无文本内容或内容不支持预览</div>
                </div>
              ) : null}
            </>
          )}
        </div>
      </div>
    </div>
  );
}
