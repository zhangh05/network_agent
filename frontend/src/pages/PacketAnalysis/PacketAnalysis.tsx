import { useState, useRef, useEffect, useCallback } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { useSessionStore } from "../../stores/session";
import { apiRequest } from "../../api/client";
import { artifactsApi } from "../../api";
import { IconAlert } from "../../components/Icon";

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
  const wsId = currentWorkspaceId || "default";
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const triedRestore = useRef(false);
  const [sessionId, setSessionId] = useState("");
  const [filename, setFilename] = useState("");
  const [totalPackets, setTotalPackets] = useState(0);
  const [connections, setConnections] = useState<ConnectionGroup[]>([]);

  const [filterProto, setFilterProto] = useState("");
  const [filterText, setFilterText] = useState("");
  const [activeKey, setActiveKey] = useState("");
  const [result, setResult] = useState<AnalysisResult | null>(null);
  const [uploading, setUploading] = useState(false);
  const [recentSessions, setRecentSessions] = useState<{ session_id: string; filename: string; total_packets: number; connection_count: number }[]>([]);
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
      const res = await apiRequest<{ ok: boolean; session_id?: string; filename?: string; total_packets?: number; connections?: ConnectionGroup[]; error?: string }>({
        method: "POST", url: "/pcap/parse", data: formData,
      } as any);
      if (!res.ok) { setError(res.error || "上传失败"); return; }
      setSessionId(res.session_id || "");
      setFilename(res.filename || file.name);
      setTotalPackets(res.total_packets || 0);
      setConnections(res.connections || []);
      setResult(null); setActiveKey("");
      localStorage.setItem("pcap_session", JSON.stringify({ sessionId: res.session_id, filename: res.filename }));
      loadRecentSessions();
    } catch (e: any) {
      setError(e?.message || "上传失败");
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
	      apiRequest<{ ok: boolean; session_id: string; filename: string; total_packets: number; connections: ConnectionGroup[] }>({
	        method: "GET", url: `/pcap/session/${sidFromUrl}`, params: { workspace_id: wsId },
	      }).then(res => {
        if (aborted.signal.aborted) return;
	        if (!res.ok) return;
        setSessionId(res.session_id);
        setFilename(res.filename);
        setTotalPackets(res.total_packets);
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
	    apiRequest<{ ok: boolean; session_id: string; filename: string; total_packets: number; connections: ConnectionGroup[] }>({
	      method: "GET", url: `/pcap/session/${sid}`, params: { workspace_id: wsId },
	    }).then(res => {
        if (aborted.signal.aborted) return;
	      if (!res.ok) { localStorage.removeItem("pcap_session"); return; }
      setSessionId(res.session_id);
      setFilename(res.filename);
      setTotalPackets(res.total_packets);
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
    } catch (e: any) { setError(e?.message || "分析失败"); }
    finally { setLoading(false); }
  }

  const gaps = result ? (result.anomalies || []).filter(a => a.type === "seq_gap") : [];
  const summary = result ? verdictSummary(result) : "";
  const MAX_VISIBLE = 500;
  const [showAll, setShowAll] = useState(false);
  const visibleEvents = result ? (showAll ? result.events : result.events.slice(0, MAX_VISIBLE)) : [];
  const hasMore = result ? result.events.length > MAX_VISIBLE : false;

  return (
    <div style={{ height: "100%", display: "flex", flexDirection: "column" }}>
      {/* Top bar */}
      <div style={{ padding: "10px 18px", borderBottom: "1px solid var(--line)", background: "var(--surface)", flexShrink: 0 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
          <span style={{ fontWeight: 700, fontSize: "var(--fs-15)" }}>Packet Analysis</span>
          {/* File upload */}
          <input
            ref={fileInputRef}
            type="file"
            accept=".pcap,.pcapng,.cap"
            style={{ display: "none" }}
            onChange={(e) => { const f = e.target.files?.[0]; if (f) { handleUpload(f); e.target.value = ""; } }}
          />
          <button
            className="btn sm"
            onClick={() => fileInputRef.current?.click()}
            disabled={uploading}
          >
            {uploading ? (<span className="spinner" />) : "📤"} {uploading ? "上传中…" : "上传 pcap"}
          </button>
          {filename && <span style={{ color: "var(--text-3)", fontSize: "var(--fs-12)" }}>{filename} · {totalPackets} pkts · {(connections || []).length} flows</span>}
          {loading && <span className="status-pill"><span className="dot loading" />分析中</span>}
          {result && (
            <button className="btn"
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
                }).catch(() => ({ ok: false, artifact: null } as any));

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
              style={{ marginLeft: "auto", background: "var(--accent)", color: "#fff", border: "none", fontWeight: 600 }}>
              Ask AI →
            </button>
          )}
        </div>
        {error && <div style={{ marginTop: 6, color: "var(--warn)", fontSize: "var(--fs-12)", display: "flex", gap: 6, alignItems: "center" }}><IconAlert size={12}/>{error}</div>}
      </div>

      {/* Main: left + right */}
      <div style={{ flex: 1, display: "flex", overflow: "hidden" }}>
        {/* ===== LEFT ===== */}
        <div style={{ width: 380, flexShrink: 0, borderRight: "1px solid var(--line)", display: "flex", flexDirection: "column", background: "var(--surface)" }}>
          <div style={{ padding: "8px 12px", borderBottom: "1px solid var(--line-2)", display: "flex", gap: 6, flexShrink: 0 }}>
            <select value={filterProto} onChange={e => setFilterProto(e.target.value)}
              style={{ padding: "3px 6px", fontSize: "var(--fs-12)", borderRadius: 4, border: "1px solid var(--line)", background: "var(--surface)" }}>
              <option value="">All</option><option value="TCP">TCP</option><option value="UDP">UDP</option>
            </select>
            <input placeholder="Filter…" value={filterText} onChange={e => setFilterText(e.target.value)}
              style={{ flex: 1, padding: "3px 8px", fontSize: "var(--fs-12)", borderRadius: 4, border: "1px solid var(--line)", background: "var(--surface)" }} />
          </div>
          <div style={{ flex: 1, overflow: "auto" }}>
            {(connections || []).length === 0 && (
              <div style={{ padding: "20px 16px" }}>
                {/* Recent sessions */}
                {recentSessions.length > 0 && (
                  <div style={{ marginBottom: 16 }}>
                    <div style={{ fontSize: "var(--fs-12)", fontWeight: 600, color: "var(--text-2)", marginBottom: 8 }}>
                      最近上传 {recentSessions.length} 个文件
                    </div>
                    {recentSessions.map((s) => (
                      <div key={s.session_id}
                        onClick={async () => {
                          setError(""); setLoading(true);
                          try {
                            const res = await apiRequest<{ ok: boolean; session_id: string; filename: string; total_packets: number; connections: ConnectionGroup[] }>({
                              method: "GET", url: `/pcap/session/${s.session_id}`, params: { workspace_id: wsId },
                            });
                            if (!res.ok) { setError("加载失败"); return; }
                            setSessionId(res.session_id);
                            setFilename(res.filename);
                            setTotalPackets(res.total_packets);
                            setConnections(res.connections || []);
                            setResult(null); setActiveKey("");
                            localStorage.setItem("pcap_session", JSON.stringify({ sessionId: res.session_id, filename: res.filename }));
                          } catch { setError("加载失败"); }
                          finally { setLoading(false); }
                        }}
                        style={{
                          padding: "8px 12px", cursor: "pointer", borderRadius: 6, marginBottom: 4,
                          border: "1px solid var(--line-2)", background: "var(--surface-2)",
                          display: "flex", alignItems: "center", gap: 8,
                        }}>
                        <span style={{ fontSize: "var(--fs-13)", fontWeight: 500 }}>📦</span>
                        <div style={{ flex: 1, minWidth: 0 }}>
                          <div style={{ fontSize: "var(--fs-12)", fontWeight: 500, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                            {s.filename}
                          </div>
                          <div style={{ fontSize: "var(--fs-11)", color: "var(--text-4)" }}>
                            {s.total_packets} pkts · {s.connection_count} flows
                          </div>
                        </div>
                        <button
                          className="btn sm ghost"
                          title="删除"
                          onClick={async (e: React.MouseEvent) => {
                            e.stopPropagation();
                            try {
                              await apiRequest({ method: "DELETE", url: `/pcap/session/${s.session_id}`, params: { workspace_id: wsId } });
                              if (s.session_id === sessionId) { setSessionId(""); setFilename(""); setTotalPackets(0); setConnections([]); setResult(null); localStorage.removeItem("pcap_session"); }
                              loadRecentSessions();
                            } catch { /* ignore */ }
                          }}
                          style={{ flexShrink: 0, padding: "2px 6px", color: "var(--text-4)" }}
                        >✕</button>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}
            {filteredConnections.map((t, i) => {
              const key = `${t.src}:${t.sport}-${t.dst}:${t.dport}`;
              const isActive = key === activeKey;
              return (
                <div key={i} onClick={() => analyze(t)}
                  style={{
                    padding: "8px 12px", cursor: "pointer",
                    borderLeft: isActive ? "3px solid var(--accent)" : "3px solid transparent",
                    background: isActive ? "var(--accent-soft)" : "transparent",
                    borderBottom: "1px solid var(--line-2)",
                  }}
                >
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                    <span className="mono" style={{ fontSize: "var(--fs-12)", fontWeight: isActive ? 700 : 500 }}>
                      {t.src}:{t.sport} ↔ {t.dst}:{t.dport}
                    </span>
                    <span className="badge" style={{ fontSize: "var(--fs-10)" }}>{t.proto_name}</span>
                  </div>
                  <div style={{ display: "flex", gap: 8, fontSize: "var(--fs-11)", color: "var(--text-3)" }}>
                    <span>→ <b style={{color:"var(--accent)"}}>{t.packets_fwd}</b></span>
                    <span>← <b style={{color:t.packets_rev===0?"var(--warn)":"var(--success)"}}>{t.packets_rev}</b></span>
                    {!t.bidirectional && <span style={{color:"var(--warn)",fontWeight:600}}>no reply</span>}
                    {isActive && summary && <span style={{color:"var(--text-2)"}}>{summary}</span>}
                  </div>
                </div>
              );
            })}
          </div>
          <div style={{ padding: "5px 12px", borderTop: "1px solid var(--line-2)", fontSize: "var(--fs-10)", color: "var(--text-4)", background: "var(--bg-soft)", flexShrink: 0 }}>
            → outbound · ← reply · no reply = unreachable
          </div>
        </div>

        {/* ===== RIGHT ===== */}
        <div style={{ flex: 1, display: "flex", flexDirection: "column", minWidth: 0 }}>
          {!result && (
            <div style={{ flex: 1, display: "flex", alignItems: "center", justifyContent: "center", color: "var(--text-4)" }}>
              <div style={{ textAlign: "center" }}>
                <div style={{ fontSize: "var(--fs-28)", marginBottom: 8 }}>📊</div>
                <div>Select a flow to analyze</div>
              </div>
            </div>
          )}

          {result && (
            <>
              {/* Header bar */}
              <div style={{ padding: "6px 18px 4px", borderBottom: `2px solid ${gaps.length > 0 || result.rst_count > 0 ? "var(--warn)" : "var(--line)"}`,
                display: "flex", alignItems: "baseline", gap: 10, flexWrap: "wrap", flexShrink: 0,
                fontFamily: "var(--font-mono)", fontSize: "var(--fs-12)",
              }}>
                <span style={{ fontWeight: 700 }}>{result.conn}</span>
                <span style={{ color: gaps.length || result.rst_count ? "var(--warn)" : "var(--text-3)" }}>{summary}</span>
                <span style={{ color: "var(--text-4)", fontSize: "var(--fs-11)" }}>
                  pkts {result.total_tcp_packets} · SYN {result.syn_count} · FIN {result.fin_count}
                  {result.rst_count > 0 && <span style={{color:"var(--danger)"}}> · RST {result.rst_count}</span>}
                </span>
                {gaps.length > 0 && (
                  <span style={{color:"var(--warn)",fontWeight:600,fontSize:"var(--fs-11)"}}>
                    {gaps.length === 1
                      ? `GAP \u2212${gaps[0].gap_size}B @rel_seq=${gaps[0].rel_seq ?? "?"}`
                      : `GAP \u00d7${gaps.length} (\u2212${gaps.reduce((s,g) => s+(g.gap_size||0), 0)}B total)`}
                  </span>
                )}
              </div>
              {/* Table fills remaining height */}
              <div style={{ flex: 1, overflow: "auto" }}>
                <table style={{
                  width: "100%", borderCollapse: "collapse",
                  fontFamily: "var(--font-mono)", fontSize: "var(--fs-12)",
                }}>
                  <thead>
                    <tr style={{ position: "sticky", top: 0, zIndex: 1,
                      background: "var(--bg-soft)", borderBottom: "1px solid var(--line)",
                      fontSize: "var(--fs-11)", color: "var(--text-3)", textAlign: "left",
                    }}>
                      <th style={{ padding: "5px 10px", width: 50, fontWeight: 600 }}>No.</th>
                      <th style={{ padding: "5px 10px", width: 110, fontWeight: 600 }}>Time</th>
                      <th style={{ padding: "5px 10px", width: 75, fontWeight: 600 }}>Delta</th>
                      <th style={{ padding: "5px 10px", width: 30, fontWeight: 600 }}>Dir</th>
                      <th style={{ padding: "5px 10px", width: 80, fontWeight: 600 }}>Flags</th>
                      <th style={{ padding: "5px 10px", fontWeight: 600 }}>Info</th>
                    </tr>
                  </thead>
                  <tbody>
                    {visibleEvents.map((evt, i) => {
                      const fl = String(evt.flags);
                      const isSyn = fl.includes("S"), isFin = fl.includes("F"),
                            isRst = fl.includes("R"), isGap = evt.gap;
                      const dt = i > 0 ? evt.time - visibleEvents[i - 1].time : 0;
                      const dtStr = dt < 0.000001 ? "0" : dt < 0.01 ? `${(dt * 1000).toFixed(1)}ms` : `${dt.toFixed(3)}s`;

                      const bg = isGap ? "#fff3cd" :
                                 isRst ? "#fde8e8" :
                                 isSyn ? "#e3f0fb" :
                                 isFin ? "#e6f7e6" :
                                 evt.payload_len > 0 ? "#fff" : "#fafafa";

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

                      return (
                        <tr key={i} style={{ background: bg, borderBottom: "1px solid var(--line-2)" }}>
                          <td style={{ padding: "3px 10px", color: "var(--text-4)", textAlign: "right" }}>{i + 1}</td>
                          <td style={{ padding: "3px 10px", color: "var(--text-3)" }}>
                            {evt.time.toFixed(6).replace(/0+$/, "").replace(/\.$/, ".0")}
                          </td>
                          <td style={{ padding: "3px 10px", color: "var(--text-4)" }}>{dtStr}</td>
                          <td style={{ padding: "3px 10px", fontWeight: 700, color: evt.dir === "→" ? "var(--accent)" : "var(--success)" }}>
                            {evt.dir}
                          </td>
                          <td style={{ padding: "3px 10px" }}>
                            <span style={{
                              fontWeight: 700, fontSize: "var(--fs-10)",
                              padding: "1px 5px", borderRadius: 3,
                              background: isRst ? "var(--danger)" : isSyn ? "var(--accent)" :
                                          isFin ? "var(--success)" : isGap ? "var(--warn)" : "var(--text-4)",
                              color: isRst || isSyn || isFin || isGap ? "#fff" : "var(--text)",
                              display: "inline-block",
                            }}>{flagText}</span>
                          </td>
                          <td style={{ padding: "3px 10px", color: isGap ? "var(--warn)" : "var(--text-2)" }}>
                            {parts.join("\u00a0 \u00a0")}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                  {hasMore && (
                    <tfoot>
                      <tr><td colSpan={6} style={{ padding: "8px 12px", textAlign: "center", borderTop: "1px solid var(--line)", background: "var(--surface-2)", cursor: "pointer" }}
                        onClick={() => setShowAll(true)}>
                        显示前 {MAX_VISIBLE} / {result.events.length} 个报文 · 点击加载全部
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
