import { useState, useRef, useEffect, useCallback } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { useSessionStore } from "../../stores/session";
import { apiRequest } from "../../api/client";
import { artifactsApi } from "../../api";
import { IconAlert } from "../../components/Icon";
import { Button, Select, Input } from "../../components/ui";

interface ConnectionGroup {
  src: string; sport: number; dst: string; dport: number;
  proto: number; proto_name: string;
  packets_fwd: number; packets_rev: number; total: number;
  bidirectional: boolean;
}

interface AlignEvent {
  seq: number; ack: number; rel_seq: number; rel_ack: number;
  dir: string; flags: string;
  time: number; payload_len: number; gap?: boolean; gap_size?: number;
}

type ProtocolCounts = Record<string, number>;

type AnalysisResult = {
  conn: string;
  events: AlignEvent[];
  anomalies: { type: string; at_seq: number; rel_seq?: number; reason: string; direction: string; gap_size?: number }[];
  syn_count: number; fin_count: number; rst_count: number;
  total_tcp_packets: number;
};

function humanEvent(evt: AlignEvent, i: number, all: AlignEvent[]): string {
  const fl = String(evt.flags);
  const isSyn = fl.includes("S"), isRst = fl.includes("R"), isFin = fl.includes("F"), isGap = evt.gap;
  const prev = i > 0 ? all[i-1] : null;
  const prevF = prev ? String(prev.flags) : "";

  if (isSyn && !prev) return "SYN — 第一次握手";
  if (isSyn && prevF.includes("S")) return "SYN+ACK — 第二次握手";
  if (isSyn && i === 2 && prev?.dir === "←") return "ACK — 第三次握手完成";
  if (isSyn) return "SYN";
  if (isRst) return "RST — 连接重置";
  if (isFin && prevF.includes("A")) return "FIN+ACK — 关闭连接";
  if (isFin) return "FIN";
  if (isGap) return `GAP −${evt.gap_size}B`;
  if (evt.payload_len > 0) return `PSH+ACK — ${evt.payload_len}B`;
  return "ACK";
}

function verdictSummary(res: AnalysisResult): string {
  const gaps = (res.anomalies || []).filter(a => a.type === "seq_gap");
  const parts: string[] = [];
  if (res.syn_count >= 3) parts.push("3WHS ✅");
  else if (res.syn_count > 0) parts.push(`SYN ${res.syn_count} (incomplete)`);
  if (res.fin_count > 0) parts.push(`FIN ${res.fin_count}`);
  if (res.rst_count > 0) parts.push(`RST ${res.rst_count}`);
  if (gaps.length > 0) parts.push(`GAP ×${gaps.length}`);
  if (!res.syn_count && !res.fin_count && !res.rst_count) parts.push("data only");
  return parts.join(" · ");
}

export function PacketAnalysis() {
  const currentWorkspaceId = useSessionStore((s) => s.currentWorkspaceId);
  const wsId = currentWorkspaceId;
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const triedRestore = useRef(false);
  const [sessionId, setSessionId] = useState("");
  const [filename, setFilename] = useState("");
  const [totalPackets, setTotalPackets] = useState(0);
  const [protocolCounts, setProtocolCounts] = useState<ProtocolCounts>({});
  const [connections, setConnections] = useState<ConnectionGroup[]>([]);

  const [filterProto, setFilterProto] = useState("");
  const [filterText, setFilterText] = useState("");
  const [activeKey, setActiveKey] = useState("");
  const [result, setResult] = useState<AnalysisResult | null>(null);
  const [uploading, setUploading] = useState(false);
  const [recentSessions, setRecentSessions] = useState<{ session_id: string; filename: string; total_packets: number; connection_count: number; protocol_counts?: ProtocolCounts }[]>([]);
  const fileInputRef = useRef<HTMLInputElement>(null);

  // Load recent sessions from backend (persistent)
  const loadRecentSessions = useCallback(async () => {
    try {
      const res = await apiRequest<{ ok: boolean; sessions: typeof recentSessions }>({
        method: "GET", url: "/pcap/sessions", params: { workspace_id: wsId, limit: 10 },
      });
      if (res.ok) setRecentSessions(res.sessions || []);
    } catch { /* ignore */ }
  }, [wsId]);

  useEffect(() => { loadRecentSessions(); }, [loadRecentSessions]);

  // Upload PCAP file
  const handleUpload = useCallback(async (file: File) => {
    if (!file) return;
    setUploading(true);
    setError("");
    try {
      const formData = new FormData();
      formData.append("file", file);
      formData.append("workspace_id", wsId);
      const res = await apiRequest<{ ok: boolean; session_id?: string; filename?: string; total_packets?: number; protocol_counts?: ProtocolCounts; connections?: ConnectionGroup[]; error?: string }>({
        method: "POST", url: "/pcap/parse", data: formData,
      });
      if (!res.ok) { setError(res.error || "上传失败"); return; }
      setSessionId(res.session_id || "");
      setFilename(res.filename || file.name);
      setTotalPackets(res.total_packets || 0);
      setProtocolCounts(res.protocol_counts || {});
      {
        const conns = res.connections || [];
        setConnections(conns);
        // Don't show recent sessions — session already loaded
        if (conns.length === 0) {
          // Fallback: no connections in parse response, try loading session detail
          try {
            const detail = await apiRequest<{ ok: boolean; connections: ConnectionGroup[]; total_packets: number; protocol_counts?: ProtocolCounts }>({
              method: "GET", url: `/pcap/session/${res.session_id}`, params: { workspace_id: wsId },
            });
            if (detail.ok) {
              setConnections(detail.connections || []);
              if (detail.total_packets) setTotalPackets(detail.total_packets);
              if (detail.protocol_counts) setProtocolCounts(detail.protocol_counts);
            }
          } catch { /* fine, connections already set */ }
        }
      }
      setResult(null); setActiveKey("");
      localStorage.setItem("pcap_session", JSON.stringify({ sessionId: res.session_id, filename: res.filename || file.name }));
      loadRecentSessions();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "上传失败");
    } finally {
      setUploading(false);
    }
  }, [wsId]);

  // Restore session from URL params (from file manager) or localStorage
  useEffect(() => {
    if (triedRestore.current) return;
    triedRestore.current = true;
    const aborted = new AbortController();

    // Try URL param first (from FileManager "打开分析" link)
	    const sidFromUrl = searchParams.get("sid");
	    if (sidFromUrl) {
	      localStorage.removeItem("pcap_session"); // clear stale
	      apiRequest<{ ok: boolean; session_id: string; filename: string; total_packets: number; protocol_counts?: ProtocolCounts; connections: ConnectionGroup[] }>({
	        method: "GET", url: `/pcap/session/${sidFromUrl}`, params: { workspace_id: wsId },
	      }).then(res => {
        if (aborted.signal.aborted) return;
	        if (!res.ok) return;
        setSessionId(res.session_id);
        setFilename(res.filename);
        setTotalPackets(res.total_packets);
        setProtocolCounts(res.protocol_counts || {});
        setConnections(res.connections || []);
        localStorage.setItem("pcap_session", JSON.stringify({ sessionId: res.session_id, filename: res.filename }));
      }).catch(() => {});
      return () => { aborted.abort(); };
    }

    // Fallback to localStorage
    const saved = localStorage.getItem("pcap_session");
    if (!saved) return;
	    let sid = "";
	    try { sid = JSON.parse(saved).sessionId; } catch { return; }
	    if (!sid) return;
	    apiRequest<{ ok: boolean; session_id: string; filename: string; total_packets: number; protocol_counts?: ProtocolCounts; connections: ConnectionGroup[] }>({
	      method: "GET", url: `/pcap/session/${sid}`, params: { workspace_id: wsId },
	    }).then(res => {
        if (aborted.signal.aborted) return;
	      if (!res.ok) { localStorage.removeItem("pcap_session"); return; }
      setSessionId(res.session_id);
      setFilename(res.filename);
      setTotalPackets(res.total_packets);
      setProtocolCounts(res.protocol_counts || {});
      setConnections(res.connections || []);
    }).catch(() => localStorage.removeItem("pcap_session"));
    return () => { aborted.abort(); };
  }, []);

  const filteredConnections = (connections || []).filter(t => {
    if (filterProto && t.proto_name !== filterProto) return false;
    if (filterText) {
      const q = filterText.toLowerCase();
      if (!t.src.includes(q) && !t.dst.includes(q)
        && !String(t.sport).includes(q) && !String(t.dport).includes(q))
        return false;
    }
    return true;
  });

  async function analyze(conn: ConnectionGroup) {
	    const key = `${conn.src}:${conn.sport}-${conn.dst}:${conn.dport}`;
	    setActiveKey(key); setError(""); setLoading(true);
	    try {
	      await apiRequest({ method: "POST", url: "/pcap/filter",
	        data: { workspace_id: wsId, session_id: sessionId, src: conn.src, sport: conn.sport, dst: conn.dst, dport: conn.dport } });
	      const aRes = await apiRequest<{ ok: boolean; error?: string;
	        events: AlignEvent[]; anomalies: any[];
	        syn_count: number; fin_count: number; rst_count: number; total_tcp_packets: number;
	      }>({ method: "POST", url: "/pcap/align",
	        data: { workspace_id: wsId, session_id: sessionId, src: conn.src, sport: conn.sport, dst: conn.dst, dport: conn.dport } });
      if (!aRes.ok) { setError(aRes.error || "分析失败"); return; }
      setResult({
        conn: `${conn.src}:${conn.sport} ↔ ${conn.dst}:${conn.dport}`,
        events: aRes.events, anomalies: aRes.anomalies,
        syn_count: aRes.syn_count, fin_count: aRes.fin_count,
        rst_count: aRes.rst_count, total_tcp_packets: aRes.total_tcp_packets,
      });
    } catch (e: unknown) { setError(e instanceof Error ? e.message : "分析失败"); }
    finally { setLoading(false); }
  }

  const gaps = result ? (result.anomalies || []).filter(a => a.type === "seq_gap") : [];
  const summary = result ? verdictSummary(result) : "";
  const MAX_VISIBLE = 500;
  const [showAll, setShowAll] = useState(false);
  const visibleEvents = result ? (showAll ? result.events : result.events.slice(0, MAX_VISIBLE)) : [];
  const hasMore = result ? result.events.length > MAX_VISIBLE : false;

  return (
    <div className="packet-page">
      {/* Top bar */}
      <div className="packet-toolbar">
        <div className="row-flex packet-toolbar-row">
          <span className="text-md packet-toolbar-title">Packet Analysis</span>
          {/* File upload */}
          <input
            ref={fileInputRef}
            type="file"
            accept=".pcap,.pcapng,.cap"
            className="packet-file-input"
            onChange={(e) => { const f = e.target.files?.[0]; if (f) { handleUpload(f); e.target.value = ""; } }}
          />
          <Button
            size="sm"
            onClick={() => fileInputRef.current?.click()}
            disabled={uploading}
          >
            {uploading ? (<span className="spinner" />) : "📤"} {uploading ? "上传中…" : "上传 pcap"}
          </Button>
          {filename && <span className="faint text-sm">{filename} · {totalPackets} pkts · {(connections || []).length} flows{Object.keys(protocolCounts).length ? ` · ${Object.entries(protocolCounts).map(([k, v]) => `${k}:${v}`).join(" ")}` : ""}</span>}
          {loading && <span className="status-pill"><span className="dot loading" />分析中</span>}
          {result && (
            <Button
              variant="primary"
              onClick={async () => {
                // 1. Save analysis as an artifact (writes through FileStore)
                const analysisData = JSON.stringify({
                  conn: result.conn,
                  stats: { pkts: result.total_tcp_packets, syn: result.syn_count, fin: result.fin_count, rst: result.rst_count },
                  anomalies: result.anomalies,
                  events: result.events.map(e => ({
                    no: 0, time: e.time, dir: e.dir, flags: e.flags,
                    rel_seq: e.rel_seq, rel_ack: e.rel_ack, payload_len: e.payload_len, gap: e.gap, gap_size: e.gap_size,
                  })),
                }, null, 2);

                const saveRes = await artifactsApi.create(wsId, {
                  content: analysisData,
                  artifact_type: "pcap_analysis",
                  title: `${result.conn}`,
                  tags: ["tcp", "analysis"],
                  metadata: { session_id: sessionId, conn: result.conn },
                  source: "agent",
                }).catch(() => ({ ok: false, artifact: null } as { ok: boolean; artifact: null }));

                // Build prompt: give LLM context to find and read the artifact itself
                const artifactTitle = saveRes.ok && saveRes.artifact
                  ? saveRes.artifact.title || ""
                  : "";
                const filepath = saveRes.ok && saveRes.artifact
                  ? saveRes.artifact.relative_path || saveRes.artifact.file_id || ""
                  : "";
                const text = filepath
                  ? `请分析这份 TCP 报文数据。分析结果已保存为制品 "${artifactTitle}"，文件路径为 "${filepath}"。请先读取该文件内容，然后给出分析结论。`
                  : `帮我分析这个 TCP 连接：${result.conn}，${result.total_tcp_packets} 个报文，${(result.anomalies||[]).length} 个异常`;

                // 3. Store and navigate
                sessionStorage.setItem("pcap_ai_prompt", text);
                navigate("/workbench");
              }}
              className="packet-ask-ai-btn">
              Ask AI →
            </Button>
          )}
        </div>
        {error && <div className="packet-error"><IconAlert size={12}/>{error}</div>}
      </div>

      {/* Main: left + right */}
      <div className="packet-main">
        {/* ===== LEFT ===== */}
        <div className="packet-sidebar">
          <div className="packet-sidebar-filter">
            <Select value={filterProto} onChange={e => setFilterProto(e.target.value)} className="packet-filter-select">
              <option value="">All</option><option value="TCP">TCP</option><option value="UDP">UDP</option>
            </Select>
            <Input placeholder="Filter…" value={filterText} onChange={e => setFilterText(e.target.value)}
              className="packet-filter-input" />
          </div>
          <div className="packet-sidebar-scroll">
            {(connections || []).length === 0 && (
              <div className="packet-sidebar-empty">
                {/* Recent sessions */}
                {recentSessions.length > 0 && (
                  <div className="mb-3">
                    <div className="packet-recent-title">
                      最近上传 {recentSessions.length} 个文件
                    </div>
                    {recentSessions.map((s) => (
                      <div key={s.session_id}
                        className="packet-session-row"
                        onClick={async () => {
                          try {
                            const res = await apiRequest<{ ok: boolean; session_id: string; filename: string; total_packets: number; protocol_counts?: ProtocolCounts; connections: ConnectionGroup[]; error?: string }>({
                              method: "GET", url: `/pcap/session/${s.session_id}`, params: { workspace_id: wsId },
                            });
                            if (!res.ok) { setError(res.ok === false ? "加载失败：" + (res.error || "session not found") : "加载失败"); setLoading(false); return; }
                            setSessionId(res.session_id);
                            setFilename(res.filename);
                            setTotalPackets(res.total_packets);
                            setProtocolCounts(res.protocol_counts || {});
                            setConnections(res.connections || []);
                            setResult(null); setActiveKey("");
                            localStorage.setItem("pcap_session", JSON.stringify({ sessionId: res.session_id, filename: res.filename }));
                          } catch (e: unknown) { setError("加载失败：" + (e instanceof Error ? e.message : "unknown")); }
                          finally { setLoading(false); }
                        }}
                      >
                        <span className="packet-session-icon">📦</span>
                        <div className="packet-session-info">
                          <div className="packet-session-name">{s.filename}</div>
                          <div className="packet-session-meta">
                            {s.total_packets} pkts · {s.connection_count} flows
                            {s.protocol_counts && Object.keys(s.protocol_counts).length ? ` · ${Object.entries(s.protocol_counts).map(([k, v]) => `${k}:${v}`).join(" ")}` : ""}
                          </div>
                        </div>
                        <Button
                          variant="ghost"
                          size="sm"
                          title="删除"
                          onClick={async (e: React.MouseEvent) => {
                            e.stopPropagation();
                            try {
                              await apiRequest({ method: "DELETE", url: `/pcap/session/${s.session_id}`, params: { workspace_id: wsId, confirm: "true" } });
                              if (s.session_id === sessionId) { setSessionId(""); setFilename(""); setTotalPackets(0); setProtocolCounts({}); setConnections([]); setResult(null); localStorage.removeItem("pcap_session"); }
                              loadRecentSessions();
                            } catch { /* ignore */ }
                          }}
                          className="packet-session-delete"
                        >✕</Button>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}
            {filteredConnections.map((t) => {
              const key = `${t.src}:${t.sport}-${t.dst}:${t.dport}`;
              const isActive = key === activeKey;
              return (
                <button key={key} type="button" onClick={() => analyze(t)}
                  className={"packet-conn-row" + (isActive ? " active" : "")}
                  aria-label={`分析连接 ${t.src}:${t.sport} 到 ${t.dst}:${t.dport}`}
                >
                  <div className="packet-conn-head">
                    <span className={"mono packet-conn-addr" + (isActive ? " active" : "")}>
                      {t.src}:{t.sport} ↔ {t.dst}:{t.dport}
                    </span>
                    <span className="badge text-xs">{t.proto_name}</span>
                  </div>
                  <div className="packet-conn-meta">
                    <span>→ <b className="accent-text">{t.packets_fwd}</b></span>
                    <span>← <b className={t.packets_rev === 0 ? "packet-conn-count-rev-warn" : ""}>{t.packets_rev}</b></span>
                    {!t.bidirectional && <span className="packet-conn-noreply">no reply</span>}
                    {isActive && summary && <span className="packet-conn-summary">{summary}</span>}
                  </div>
                </button>
              );
            })}
          </div>
          <div className="packet-sidebar-footer">
            → outbound · ← reply · no reply = unreachable
          </div>
        </div>

        {/* ===== RIGHT ===== */}
        <div className="packet-pane">
          {!result && (
            <div className="packet-empty">
              <div className="packet-empty-inner">
                <div className="packet-empty-icon">📊</div>
                <div>Select a flow to analyze</div>
              </div>
            </div>
          )}

          {result && (
            <>
              {/* Header bar */}
              <div className={"packet-detail-header " + (gaps.length > 0 || result.rst_count > 0 ? "has-warning" : "")}>
                <span className="packet-detail-conn">{result.conn}</span>
                <span className={"packet-detail-summary " + (gaps.length || result.rst_count ? "warn" : "")}>{summary}</span>
                <span className="packet-detail-meta">
                  pkts {result.total_tcp_packets} · SYN {result.syn_count} · FIN {result.fin_count}
                  {result.rst_count > 0 && <span className="packet-detail-rst"> · RST {result.rst_count}</span>}
                </span>
                {gaps.length > 0 && (
                  <span className="packet-detail-gap">
                    {gaps.length === 1
                      ? `GAP \u2212${gaps[0].gap_size}B @rel_seq=${gaps[0].rel_seq ?? "?"}`
                      : `GAP \u00d7${gaps.length} (\u2212${gaps.reduce((s,g) => s+(g.gap_size||0), 0)}B total)`}
                  </span>
                )}
              </div>
              {/* Table fills remaining height */}
              <div className="packet-table-scroll">
                <table className="packet-table">
                  <thead>
                    <tr>
                      <th className="packet-col-no">No.</th>
                      <th className="packet-col-time">Time</th>
                      <th className="packet-col-delta">Delta</th>
                      <th className="packet-col-dir">Dir</th>
                      <th className="packet-col-flags">Flags</th>
                      <th>Info</th>
                    </tr>
                  </thead>
                  <tbody>
                    {visibleEvents.map((evt, i) => {
                      const fl = String(evt.flags);
                      const isSyn = fl.includes("S"), isFin = fl.includes("F"),
                            isRst = fl.includes("R"), isGap = evt.gap;
                      const dt = i > 0 ? evt.time - visibleEvents[i - 1].time : 0;
                      const dtStr = dt < 0.000001 ? "0" : dt < 0.01 ? `${(dt * 1000).toFixed(1)}ms` : `${dt.toFixed(3)}s`;

                      const rowClass = isGap ? "gap" : isRst ? "rst" : isSyn ? "syn" : isFin ? "fin" : evt.payload_len > 0 ? "payload" : "default";

                      const parts: string[] = [];
                      parts.push(humanEvent(evt, i, visibleEvents));
                      parts.push(`seq ${evt.rel_seq}  (${evt.seq})`);
                      if (evt.payload_len > 0) parts.push(`len ${evt.payload_len}`);
                      if (evt.rel_ack > 0 || isFin || isRst) parts.push(`ack ${evt.rel_ack}  (${evt.ack})`);
                      else if (isSyn) parts.push(`ack 0  (0)`);
                      if (isGap) parts.push(`\u26a0 gap \u2212${evt.gap_size}B`);

                      const flagMap: Record<string, string> = {
                        "S": "SYN", "A": "ACK", "P": "PSH", "F": "FIN", "R": "RST",
                      };
                      const flagText = fl
                        ? fl.split("").map(c => flagMap[c] || c).join("+")
                        : "ACK";

                      const flagClass = isRst ? "rst" : isSyn ? "syn" : isFin ? "fin" : isGap ? "gap" : "default";

                      return (
                        <tr key={i} className={`packet-table-row packet-table-row--${rowClass}`}>
                          <td className="packet-table-cell-no">{i + 1}</td>
                          <td className="packet-table-cell-time">
                            {evt.time.toFixed(6).replace(/0+$/, "").replace(/\.$/, ".0")}
                          </td>
                          <td className="packet-table-cell-delta">{dtStr}</td>
                          <td className={"packet-table-cell-dir " + (evt.dir === "→" ? "fwd" : "rev")}>
                            {evt.dir}
                          </td>
                          <td>
                            <span className={`packet-flag-badge packet-flag-badge--${flagClass}`}>{flagText}</span>
                          </td>
                          <td className={"packet-table-cell-info " + (isGap ? "warn" : "")}>
                            {parts.join("\u00a0 \u00a0")}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                  {hasMore && (
                    <tfoot>
                      <tr><td colSpan={6} className="packet-load-more">
                        <button type="button" onClick={() => setShowAll(true)}>
                          显示前 {MAX_VISIBLE} / {result.events.length} 个报文 · 点击加载全部
                        </button>
                      </td></tr>
                    </tfoot>
                  )}
                </table>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
