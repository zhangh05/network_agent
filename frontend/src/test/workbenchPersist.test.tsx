/**
 * Test — workbench store 持久化 (plan-C 方案)
 *
 * 验证:
 *  1. appendUser/appendAssistant 写入 bySession map
 *  2. switchSession 切换当前会话
 *  3. 跨 session 隔离: 切走再切回来, 历史独立
 *  4. mergeFromBackend 按 created_at 升序 merge, 不删本地
 *  5. clear 清空当前会话
 *  6. localStorage 持久化 (zustand persist)
 */

import { describe, it, expect, beforeEach } from "vitest";
import { useWorkbenchStore } from "../stores/workbench";
import type { SessionMessage, AgentResult } from "../types";

const SAMPLE_RESULT: AgentResult = {
  ok: true,
  final_response: "ok",
  events: [],
  trace_id: "trace-1",
  session_id: "s-a",
  turn_id: "t-1",
  tool_calls: [],
  warnings: [],
  errors: [],
  metadata: { source_count: 0, source_summary: [] },
};

beforeEach(() => {
  useWorkbenchStore.getState().clear();
  useWorkbenchStore.setState({ bySession: {} });
});

describe("useWorkbenchStore — bySession + persist (plan-C)", () => {
  it("appendUser + appendAssistant writes to bySession[currentSessionId]", () => {
    useWorkbenchStore.getState().switchSession("s-a");
    useWorkbenchStore.getState().appendUser("你好", "s-a");
    useWorkbenchStore.getState().appendAssistant("你好, 有什么可以帮您?", SAMPLE_RESULT, "s-a");
    const s = useWorkbenchStore.getState();
    expect(s.bySession["s-a"]?.length).toBe(2);
    expect(s.bySession["s-a"]?.[0]?.text).toBe("你好");
    expect(s.bySession["s-a"]?.[0]?.role).toBe("user");
    expect(s.bySession["s-a"]?.[1]?.text).toBe("你好, 有什么可以帮您?");
    expect(s.bySession["s-a"]?.[1]?.role).toBe("assistant");
    expect(s.bySession["s-a"]?.[1]?.result?.trace_id).toBe("trace-1");
    expect(s.results["s-a"]?.[0]?.trace_id).toBe("trace-1");
  });

  it("null session_id → _scratch 池 (等后端 resolve 后由页面层迁移)", () => {
    useWorkbenchStore.setState({ currentSessionId: null });
    useWorkbenchStore.getState().appendUser("临时", null);
    useWorkbenchStore.getState().appendAssistant("临时回应", undefined, null);
    const s = useWorkbenchStore.getState();
    expect(s.bySession["_scratch"]?.length).toBe(2);
    expect(s.bySession["_scratch"]?.[0]?.text).toBe("临时");
    expect(s.bySession["_scratch"]?.[1]?.text).toBe("临时回应");
  });

  it("session isolation: 切走再切回, 历史独立保留", () => {
    useWorkbenchStore.getState().switchSession("s-a");
    useWorkbenchStore.getState().appendUser("会话A问题", "s-a");
    useWorkbenchStore.getState().switchSession("s-b");
    expect(useWorkbenchStore.getState().bySession["s-b"]).toEqual([]);
    useWorkbenchStore.getState().appendUser("会话B问题", "s-b");
    expect(useWorkbenchStore.getState().bySession["s-a"]?.length).toBe(1);
    expect(useWorkbenchStore.getState().bySession["s-b"]?.length).toBe(1);
    expect(useWorkbenchStore.getState().bySession["s-a"]?.[0]?.text).toBe("会话A问题");
    expect(useWorkbenchStore.getState().bySession["s-b"]?.[0]?.text).toBe("会话B问题");
    // 切回 A
    useWorkbenchStore.getState().switchSession("s-a");
    expect(useWorkbenchStore.getState().bySession["s-a"]?.[0]?.text).toBe("会话A问题");
  });

  it("mergeFromBackend 不删本地, 按 created_at 升序", () => {
    useWorkbenchStore.getState().switchSession("s-a");
    useWorkbenchStore.getState().appendUser("本地用户", "s-a");
    // 模拟服务端有更早的 2 条 (user + assistant pair)
    const serverMsgs: SessionMessage[] = [
      {
        message_id: "srv-1",
        role: "user",
        content: "服务端用户",
        created_at: "2026-06-11T08:00:00Z",
      },
      {
        message_id: "srv-2",
        role: "assistant",
        content: "服务端助手",
        created_at: "2026-06-11T08:00:01Z",
      },
    ];
    useWorkbenchStore.getState().mergeFromBackend("s-a", serverMsgs);
    const combined = useWorkbenchStore.getState().bySession["s-a"] ?? [];
    expect(combined.length).toBe(3); // 本地 1 + 服务端 2, 不会丢本地
    // 按 created_at 升序
    expect(combined[0]?.text).toBe("服务端用户");
    expect(combined[1]?.text).toBe("服务端助手");
    expect(combined[2]?.text).toBe("本地用户");
  });

  it("mergeFromBackend 服务端自身重复 id 去重", () => {
    useWorkbenchStore.getState().switchSession("s-a");
    useWorkbenchStore.getState().appendUser("本地消息", "s-a");  // 本地有 1 条
    const dup: SessionMessage[] = [
      { message_id: "srv-1", role: "user", content: "服务端消息 1", created_at: "2026-06-11T08:00:00Z" },
      { message_id: "srv-1", role: "user", content: "服务端消息 1 (重复)", created_at: "2026-06-11T08:00:00Z" },
    ];
    useWorkbenchStore.getState().mergeFromBackend("s-a", dup);
    // 本地 1 条 (id 不同于 srv-1) + 服务端去重 1 条 = 2
    expect(useWorkbenchStore.getState().bySession["s-a"]?.length).toBe(2);
    expect(useWorkbenchStore.getState().bySession["s-a"]?.[0]?.text).toBe("服务端消息 1");
    expect(useWorkbenchStore.getState().bySession["s-a"]?.[1]?.text).toBe("本地消息");
  });

  it("mergeFromBackend keeps the active session when the persisted cache is full", () => {
    useWorkbenchStore.setState({
      bySession: Object.fromEntries(
        ["session_28", "session_21", "session_29", "session_3", "session_4"].map((id) => [
          id,
          [{ id: `${id}-1`, role: "user", text: id, status: "ready", created_at: "2026-06-18T00:00:00Z" }],
        ]),
      ),
      currentSessionId: "f07f3f4731b8495c",
    });

    useWorkbenchStore.getState().mergeFromBackend("f07f3f4731b8495c", [
      {
        message_id: "run-current:user",
        role: "user",
        content: "你好",
        created_at: "2026-06-19T04:01:10Z",
        run_id: "run-current",
      },
      {
        message_id: "run-current:assistant",
        role: "assistant",
        content: "你好，我在。",
        created_at: "2026-06-19T04:01:11Z",
        run_id: "run-current",
      },
    ]);

    expect(useWorkbenchStore.getState().bySession["f07f3f4731b8495c"]).toHaveLength(2);
  });

  it("clear 清空指定 session", () => {
    useWorkbenchStore.getState().switchSession("s-a");
    useWorkbenchStore.getState().appendUser("A", "s-a");
    useWorkbenchStore.getState().switchSession("s-b");
    useWorkbenchStore.getState().appendUser("B", "s-b");
    useWorkbenchStore.getState().clear("s-b");
    expect(useWorkbenchStore.getState().bySession["s-a"]?.length).toBe(1);
    expect(useWorkbenchStore.getState().bySession["s-b"]).toBeUndefined();
  });

  it("localStorage 持久化 bySession (zustand persist)", () => {
    useWorkbenchStore.getState().switchSession("persist-1");
    useWorkbenchStore.getState().appendUser("刷新不丢", "persist-1");
    // 验证 localStorage["na_workbench"] 里有数据
    const raw = localStorage.getItem("na_workbench");
    expect(raw).toBeTruthy();
    const parsed = JSON.parse(raw ?? "{}");
    const bySession = parsed?.state?.bySession ?? parsed?.bySession;
    expect(bySession?.["persist-1"]?.length).toBe(1);
    expect(bySession?.["persist-1"]?.[0]?.text).toBe("刷新不丢");
  });

  it("cap: 每会话 30 条, 全局 5 个 session", () => {
    useWorkbenchStore.getState().switchSession("big");
    for (let i = 0; i < 50; i++) {
      useWorkbenchStore.getState().appendUser(`msg-${i}`, "big");
    }
    // 超过 100 → 保留最新 100 条 (v3.9: cap raised to 100)
    const big = useWorkbenchStore.getState().bySession["big"] ?? [];
    expect(big.length).toBe(50);
    expect(big[0]?.text).toBe("msg-0");
    expect(big[49]?.text).toBe("msg-49");

    // 加 5 个 session
    for (const sid of ["s2", "s3", "s4", "s5", "s6"]) {
      useWorkbenchStore.getState().appendUser("x", sid);
    }
    // 全局没超上限, big 还在
    let keys = Object.keys(useWorkbenchStore.getState().bySession);
    expect(keys.length).toBe(6);
    expect(keys).toContain("big");
  });
});
