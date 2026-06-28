import { beforeEach, describe, expect, it } from "vitest";
import { isInternalSessionId, useSessionStore } from "../stores/session";

describe("session store boundaries", () => {
  beforeEach(() => {
    useSessionStore.getState().reset();
    useSessionStore.setState({ currentWorkspaceId: "default", currentSessionId: null, sessions: [] });
  });

  it("rejects internal subagent sessions as the active UI session", () => {
    expect(isInternalSessionId("sub-a0206b29")).toBe(true);

    useSessionStore.getState().setCurrentSession("sub-a0206b29");

    expect(useSessionStore.getState().currentSessionId).toBeNull();
  });

  it("filters internal sessions from the user-visible session list", () => {
    useSessionStore.getState().setSessions([
      { session_id: "sess-user", workspace_id: "default", title: "User", status: "active", created_at: "", updated_at: "", message_count: 1 },
      { session_id: "sub-hidden", workspace_id: "default", title: "Internal", status: "active", created_at: "", updated_at: "", message_count: 1 },
    ] as any);

    expect(useSessionStore.getState().sessions.map((s) => s.session_id)).toEqual(["sess-user"]);
  });
});
