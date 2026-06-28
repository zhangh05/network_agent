import { beforeEach, describe, expect, it } from "vitest";
import { useWorkbenchStore } from "../stores/workbench";

describe("workbench backend message merge", () => {
  beforeEach(() => {
    localStorage.clear();
    useWorkbenchStore.setState({
      bySession: {},
      currentSessionId: null,
      results: {},
      sending: false,
      lastUserInput: "",
    });
  });

  it("deduplicates repeated backend user messages and preserves assistant content", () => {
    const store = useWorkbenchStore.getState();
    store.switchSession("sess-merge");
    store.mergeFromBackend("sess-merge", [
      {
        message_id: "run-1:user",
        session_id: "sess-merge",
        role: "user",
        content: "查看明天上海天气",
        created_at: "2026-06-28T10:00:00Z",
        run_id: "run-1",
      },
      {
        message_id: "run-1:user",
        session_id: "sess-merge",
        role: "user",
        content: "查看明天上海天气",
        created_at: "2026-06-28T10:00:00Z",
        run_id: "run-1",
      },
      {
        message_id: "run-1:assistant",
        session_id: "sess-merge",
        role: "assistant",
        content: "明天上海天气：多云。",
        created_at: "2026-06-28T10:00:01Z",
        run_id: "run-1",
      },
    ]);

    const messages = useWorkbenchStore.getState().bySession["sess-merge"];
    expect(messages.map((m) => `${m.role}:${m.text}`)).toEqual([
      "user:查看明天上海天气",
      "assistant:明天上海天气：多云。",
    ]);
  });

  it("keeps backend turn ordering when replacing optimistic local messages", () => {
    const store = useWorkbenchStore.getState();
    store.switchSession("sess-order");
    store.appendUser("你好，查看明天杭州天气", "sess-order");
    const assistantId = store.appendAssistantStreaming("sess-order");
    useWorkbenchStore.getState().updateAssistant(assistantId, {
      status: "ready",
      text: "明天杭州天气：小雨。",
    }, "sess-order");

    useWorkbenchStore.setState((state) => ({
      bySession: {
        ...state.bySession,
        "sess-order": state.bySession["sess-order"].map((m) =>
          m.role === "user"
            ? { ...m, created_at: "2026-06-28T10:00:05Z" }
            : { ...m, created_at: "2026-06-28T10:00:06Z" },
        ),
      },
    }));

    store.mergeFromBackend("sess-order", [
      {
        message_id: "run-weather:user",
        session_id: "sess-order",
        role: "user",
        content: "你好，查看明天杭州天气",
        created_at: "2026-06-28T10:00:00Z",
        run_id: "run-weather",
      },
      {
        message_id: "run-weather:assistant",
        session_id: "sess-order",
        role: "assistant",
        content: "明天杭州天气：小雨。",
        created_at: "2026-06-28T10:00:01Z",
        run_id: "run-weather",
      },
    ]);

    const messages = useWorkbenchStore.getState().bySession["sess-order"];
    expect(messages.map((m) => `${m.role}:${m.text}`)).toEqual([
      "user:你好，查看明天杭州天气",
      "assistant:明天杭州天气：小雨。",
    ]);
    expect(messages.map((m) => m.created_at)).toEqual([
      "2026-06-28T10:00:00Z",
      "2026-06-28T10:00:01Z",
    ]);
  });

  it("collapses duplicate local users and replaces pending assistant with backend answer", () => {
    const store = useWorkbenchStore.getState();
    store.switchSession("sess-live");
    store.appendUser("派发子agent，让它搜索一下BGP邻居的建立条件", "sess-live");
    store.appendUser("派发子agent，让它搜索一下BGP邻居的建立条件", "sess-live");
    store.appendAssistantStreaming("sess-live");

    store.mergeFromBackend("sess-live", [
      {
        message_id: "run-sub:user",
        session_id: "sess-live",
        role: "user",
        content: "派发子agent，让它搜索一下BGP邻居的建立条件",
        created_at: "2026-06-28T10:00:00Z",
        run_id: "run-sub",
      },
      {
        message_id: "run-sub:assistant",
        session_id: "sess-live",
        role: "assistant",
        content: "子 agent 已完成搜索，BGP 邻居建立条件如下。",
        created_at: "2026-06-28T10:00:01Z",
        run_id: "run-sub",
      },
    ]);

    const messages = useWorkbenchStore.getState().bySession["sess-live"];
    expect(messages.map((m) => `${m.role}:${m.text}`)).toEqual([
      "user:派发子agent，让它搜索一下BGP邻居的建立条件",
      "assistant:子 agent 已完成搜索，BGP 邻居建立条件如下。",
    ]);
    expect(messages.every((m) => m.status === "ready")).toBe(true);
  });
});
