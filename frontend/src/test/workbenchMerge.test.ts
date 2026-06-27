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
});
