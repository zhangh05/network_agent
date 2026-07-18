import { useState, useEffect, useRef } from "react";
import { useNavigate } from "react-router-dom";
import { useSessionStore } from "../../stores/session";
import { useToastStore } from "../../stores/toast";
import { apiRequest } from "../../api/client";
import { artifactsApi } from "../../api";
import { isApiError } from "../../types";
import { formatFileSize, formatDate } from "../../utils/format";
import { EmptyState } from "../../components/common";
import { PageHeader, FilterBar, DetailPanel } from "../../components/ui";

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
  if (t === "pcap") return ["pcap", "pcap_input", "pcap_analysis", "pcap_session", "pcap_connections"].includes(f.artifact_type);
  return f.artifact_type === t;
}

function isRawPacketCapture(f: FileItem): boolean {
  if (!["pcap", "pcap_input"].includes(f.artifact_type)) return false;
  const suffix = String(f.file_ext || f.title || "").toLowerCase();
  return suffix.endsWith(".pcap") || suffix.endsWith(".pcapng");
}

export function FileManager() {
  const { currentWorkspaceId } = useSessionStore();
  const navigate = useNavigate();
  const toast = useToastStore((s) => s.show);
  const ws = currentWorkspaceId;

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
      const res = await artifactsApi.list(ws);
      const items: FileItem[] = res.artifacts || [];
      setAllFiles(items);
    } catch (e: unknown) {
      toast({ kind: "error", title: "文件列表加载失败", body: isApiError(e) ? e.message : String(e) });
    }
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
    } catch (e: unknown) {
      toast({ kind: "error", title: "上传失败", body: isApiError(e) ? e.message : String(e) });
    }
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
    } catch (e: unknown) {
      toast({ kind: "error", title: "pcap 解析失败", body: isApiError(e) ? e.message : String(e) });
    }
    setPcapUploading(false);
  };

  const selectFile = (f: FileItem) => {
    setSelected(f);
    setDetailContent(null);
    artifactsApi.content(ws, f.artifact_id)
      .then((r: any) => { if (r?.ok) setDetailContent(r.content || null); })
      .catch((e: unknown) => {
        toast({ kind: "error", title: "读取文件内容失败", body: isApiError(e) ? e.message : String(e) });
      });
  };

  const deleteFile = async (artifactId: string) => {
    if (!confirm("确认删除？")) return;
    try {
      await artifactsApi.batchDelete(ws, [artifactId]);
      setAllFiles(prev => prev.filter(x => x.artifact_id !== artifactId));
      if (selected?.artifact_id === artifactId) setSelected(null);
    } catch (e: unknown) {
      toast({ kind: "error", title: "删除失败", body: isApiError(e) ? e.message : String(e) });
    }
  };

  const openPacketAnalysis = async (f: FileItem) => {
    const existingSessionId = String(f.metadata?.session_id || "");
    if (existingSessionId) {
      navigate(`/packet?sid=${encodeURIComponent(existingSessionId)}`);
      return;
    }
    try {
      const res = await apiRequest<{ ok: boolean; session_id?: string; error?: string; message?: string }>({
        method: "POST",
        url: "/pcap/parse-file",
        data: { workspace_id: ws, file_id: f.file_id },
      });
      if (res.ok && res.session_id) {
        navigate(`/packet?sid=${encodeURIComponent(res.session_id)}`);
      } else if (res && (res.error || res.message)) {
        toast({ kind: "error", title: "无法打开流量分析", body: res.error || res.message });
      }
    } catch (e: unknown) {
      toast({ kind: "error", title: "无法打开流量分析", body: isApiError(e) ? e.message : String(e) });
    }
  };

  return (
    <div className="page">
      <PageHeader title="文件管理" subtitle="统一制品管理 — 基于 FileStore">
        <button className="btn primary sm" onClick={() => setShowUpload(true)}>上传文件</button>
        <button className="btn sm ghost" onClick={fetchFiles}>刷新</button>
      </PageHeader>

      {showUpload && (
        <div className="card card-highlight" style={{ padding: "12px 16px", margin: "0 0 12px" }}>
          <div className="card-title">上传文件</div>
          <div className="row-flex mt-2">
            <input ref={fileRef} type="file" style={{ display: "none" }}
              onChange={e => {
                const f = e.target.files?.[0];
                if (f) {
                  activeType === "pcap" ? handlePcapUpload(f) : handleUpload(f);
                }
                e.target.value = "";
              }} />
            <button className="btn primary sm" onClick={() => fileRef.current?.click()} disabled={uploading || pcapUploading}>
              {uploading || pcapUploading ? "上传中…" : "选择文件"}
            </button>
            <button className="btn ghost sm" onClick={() => setShowUpload(false)}>取消</button>
          </div>
        </div>
      )}

      <div className="split-shell" style={{ flex: 1 }}>
        <aside style={{ display: "flex", flexDirection: "column" }}>
          <FilterBar>
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
          </FilterBar>

          <div className="file-list">
            {loading && <div className="empty-sm">加载中…</div>}
            {!loading && files.length === 0 && (
              <div className="empty" style={{ padding: 40 }}>
                <div className="empty-text">暂无文件</div>
              </div>
            )}
            {files.map(f => {
              const isActive = selected?.artifact_id === f.artifact_id;
              return (
                <div key={f.artifact_id} className={`card file-list-item ${isActive ? "active" : ""}`} onClick={() => selectFile(f)}>
                  <div className="file-list-item-title">{f.title}</div>
                  <div className="file-list-item-meta">
                    <span>{f.artifact_type}</span>
                    <span>{formatFileSize(f.size_bytes)}</span>
                    <span>{formatDate(f.created_at, "short")}</span>
                  </div>
                </div>
              );
            })}
          </div>
        </aside>

        <DetailPanel title={selected?.title || "选择文件"} subtitle={selected ? selected.artifact_type : "点击左侧文件查看详情"}>
          {!selected ? (
            <EmptyState text="选择文件查看详情" />
          ) : (
            <>
              <div className="card file-detail-card">
                <div className="file-detail-head">
                  <div>
                    <h3 className="file-detail-title">{selected.title}</h3>
                    <div className="file-detail-meta">
                      <span>{selected.artifact_type}</span>
                      <span className="mono">{selected.file_id}</span>
                      <span>{formatFileSize(selected.size_bytes)}</span>
                      <span>{formatDate(selected.created_at, "short")}</span>
                    </div>
                  </div>
                  <div className="file-detail-actions">
                    {isRawPacketCapture(selected) && selected.file_id && (
                      <button className="btn primary sm" onClick={() => openPacketAnalysis(selected)}>打开分析</button>
                    )}
                    <button className="btn danger-ghost sm" onClick={() => deleteFile(selected.artifact_id)}>删除</button>
                  </div>
                </div>
              </div>

              {detailContent ? (
                <div className="card file-content-card">
                  <pre>{detailContent.slice(0, 8000)}{detailContent.length > 8000 ? "\n\n..." : ""}</pre>
                </div>
              ) : (
                <div className="empty" style={{ flex: 1 }}><div className="empty-text">无文本内容</div></div>
              )}
            </>
          )}
        </DetailPanel>
      </div>
    </div>
  );
}
