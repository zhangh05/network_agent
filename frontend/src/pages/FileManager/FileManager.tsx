import { useState, useEffect, useRef } from "react";
import { useNavigate } from "react-router-dom";
import { useSessionStore } from "../../stores/session";
import { apiRequest } from "../../api/client";
import { artifactsApi } from "../../api";

interface FileItem {
  artifact_id: string;
  file_id: string;
  artifact_type: string;
  title: string;
  file_ext?: string;
  size_bytes: number;
  created_at: string;
  updated_at?: string;
  sensitivity?: string;
  metadata?: Record<string, unknown>;
}

const TYPE_TABS = [
  { key: "all", label: "全部" },
  { key: "pcap", label: "报文" },
  { key: "knowledge_doc", label: "知识" },
  { key: "message_large_content", label: "消息" },
  { key: "report", label: "报告" },
  { key: "translated_config", label: "配置" },
] as const;

function matchesType(f: FileItem, t: string): boolean {
  if (t === "all") return true;
  return f.artifact_type === t;
}

function fmtSize(bytes: number): string {
  if (!bytes) return "0B";
  if (bytes < 1024) return `${bytes}B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)}KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)}MB`;
}

function fmtTime(iso: string): string {
  try { return new Date(iso).toLocaleDateString("zh-CN"); } catch { return (iso || "").slice(0, 10); }
}

export function FileManager() {
  const { currentWorkspaceId } = useSessionStore();
  const navigate = useNavigate();
  const ws = currentWorkspaceId || "default";

  const [activeType, setActiveType] = useState("all");
  const [allFiles, setAllFiles] = useState<FileItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [selected, setSelected] = useState<FileItem | null>(null);
  const [detailContent, setDetailContent] = useState<string | null>(null);
  const [showUpload, setShowUpload] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [pcapUploading, setPcapUploading] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  const files = activeType === "all" ? allFiles : allFiles.filter(f => matchesType(f, activeType));

  const fetchFiles = async () => {
    setLoading(true);
    try {
      const res = await artifactsApi.list(ws, { include_deleted: "0", limit: "500" });
      const items: FileItem[] = (res as any).artifacts || [];
      setAllFiles(items);
    } catch {}
    finally { setLoading(false); }
  };

  useEffect(() => { fetchFiles(); }, [activeType, ws]);

  const handleUpload = async (file: File) => {
    setUploading(true);
    const form = new FormData();
    form.append("file", file);
    form.append("artifact_type", activeType === "pcap" ? "pcap_input" : "knowledge_doc");
    form.append("title", file.name);
    form.append("workspace_id", ws);
    try {
      const res = await apiRequest<{ ok: boolean }>({
        method: "POST", url: `/workspaces/${ws}/artifacts/upload`, data: form,
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
      await apiRequest({ method: "POST", url: "/pcap/parse", data: form });
      await fetchFiles();
    } catch {}
    setPcapUploading(false);
  };

  const selectFile = (f: FileItem) => {
    setSelected(f);
    setDetailContent(null);
    artifactsApi.content(ws, f.artifact_id)
      .then((r: any) => { if (r?.ok) setDetailContent(r.content || null); })
      .catch(() => {});
  };

  const deleteFile = async (artifactId: string) => {
    if (!confirm("确认删除？")) return;
    try {
      await artifactsApi.batchDelete(ws, [{ artifact_id: artifactId }]);
      setAllFiles(prev => prev.filter(x => x.artifact_id !== artifactId));
      if (selected?.artifact_id === artifactId) setSelected(null);
    } catch {}
  };

  return (
    <div className="page">
      <div className="page-header">
        <div>
          <h1>文件管理</h1>
          <p className="subtitle">统一制品管理 — 基于 FileStore</p>
        </div>
        <div style={{ display: "flex", gap: 8 }}>
          <button className="btn primary sm" onClick={() => setShowUpload(true)}>上传文件</button>
          <button className="btn sm ghost" onClick={fetchFiles}>刷新</button>
        </div>
      </div>

      {showUpload && (
        <div className="card" style={{ padding: "12px 16px", margin: "0 0 12px", borderColor: "var(--accent)" }}>
          <div className="card-title">上传文件</div>
          <div style={{ display: "flex", gap: 8, alignItems: "center", marginTop: 8 }}>
            <input ref={fileRef} type="file" style={{ display: "none" }}
              onChange={e => { const f = e.target.files?.[0]; if (f) handleUpload(f); e.target.value = ""; }} />
            <button className="btn primary sm" onClick={() => fileRef.current?.click()} disabled={uploading}>
              {uploading ? "上传中…" : "选择文件"}
            </button>
            <button className="btn ghost sm" onClick={() => setShowUpload(false)}>取消</button>
          </div>
        </div>
      )}

      <div className="split-shell" style={{ flex: 1 }}>
        <aside style={{ display: "flex", flexDirection: "column" }}>
          <div style={{ display: "flex", gap: 6, padding: "8px 12px", borderBottom: "1px solid var(--line-2)", flexWrap: "wrap" }}>
            {TYPE_TABS.map(t => {
              const count = t.key === "all" ? allFiles.length : allFiles.filter(f => matchesType(f, t.key)).length;
              return (
                <button key={t.key} onClick={() => { setActiveType(t.key); setSelected(null); }}
                  className={`btn sm ${t.key === activeType ? "primary" : "ghost"}`}
                  style={{ padding: "4px 8px", fontSize: "var(--fs-11)", fontWeight: t.key === activeType ? 700 : 500 }}>
                  {t.label} <span style={{ marginLeft: 4, opacity: .7 }}>{count}</span>
                </button>
              );
            })}
          </div>

          <div style={{ flex: 1, overflow: "auto", padding: "8px 12px" }}>
            {loading && <div style={{ padding: 24, textAlign: "center", color: "var(--text-4)" }}>加载中…</div>}
            {!loading && files.length === 0 && (
              <div className="empty" style={{ padding: 40 }}>
                <div className="empty-text">暂无文件</div>
              </div>
            )}
            {files.map(f => {
              const isActive = selected?.artifact_id === f.artifact_id;
              return (
                <div key={f.artifact_id} className="card" onClick={() => selectFile(f)}
                  style={{ padding: "10px 12px", cursor: "pointer", marginBottom: 6,
                    borderColor: isActive ? "var(--accent)" : "var(--line)", background: isActive ? "var(--accent-soft)" : undefined }}>
                  <div style={{ fontSize: "var(--fs-13)", fontWeight: 680, wordBreak: "break-all" }}>{f.title}</div>
                  <div style={{ display: "flex", gap: 6, marginTop: 4, fontSize: "var(--fs-10)", color: "var(--text-4)" }}>
                    <span>{f.artifact_type}</span>
                    <span>{fmtSize(f.size_bytes)}</span>
                    <span>{fmtTime(f.created_at)}</span>
                  </div>
                </div>
              );
            })}
          </div>
        </aside>

        <div className="split-detail" style={{ display: "flex", flexDirection: "column" }}>
          {!selected ? (
            <div className="empty" style={{ flex: 1 }}>
              <div className="empty-text">选择文件查看详情</div>
            </div>
          ) : (
            <>
              <div className="card" style={{ padding: "14px 16px", marginBottom: 12 }}>
                <div style={{ display: "flex", justifyContent: "space-between" }}>
                  <div>
                    <h3 style={{ fontSize: "var(--fs-16)", fontWeight: 720, margin: 0 }}>{selected.title}</h3>
                    <div style={{ display: "flex", gap: 8, marginTop: 6, fontSize: "var(--fs-11)", color: "var(--text-3)" }}>
                      <span>{selected.artifact_type}</span>
                      <span style={{ fontFamily: "var(--font-mono)" }}>{selected.file_id}</span>
                      <span>{fmtSize(selected.size_bytes)}</span>
                      <span>{fmtTime(selected.created_at)}</span>
                    </div>
                  </div>
                  <button className="btn danger-ghost sm" onClick={() => deleteFile(selected.artifact_id)}>删除</button>
                </div>
              </div>

              {detailContent ? (
                <div className="card" style={{ flex: 1, overflow: "auto", padding: 0 }}>
                  <pre style={{ margin: 0, padding: "12px 16px", fontFamily: "var(--font-mono)", fontSize: "var(--fs-12)", whiteSpace: "pre-wrap", wordBreak: "break-word", color: "var(--text-2)", background: "var(--surface-2)" }}>
                    {detailContent.slice(0, 8000)}{detailContent.length > 8000 ? "\n\n..." : ""}
                  </pre>
                </div>
              ) : (
                <div className="empty" style={{ flex: 1 }}><div className="empty-text">无文本内容</div></div>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
}
