/**
 * Test 10 — inspector 展开/收起
 */

import { describe, it, expect, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { AppLayout } from "../layouts/AppLayout";
import { useUIStore } from "../stores/session";
import { useSessionStore } from "../stores/session";
import { enqueue, installMockApi, resetMocks } from "./mockServer";

describe("Inspector collapse / expand", () => {
  beforeEach(() => {
    resetMocks();
    installMockApi();
    useUIStore.setState({ inspectorOpen: true, sidebarOpen: true, theme: "light" });
    useSessionStore.getState().reset();
  });

  it("shows inspector and toggle collapses it", async () => {
    enqueue("/workspaces", { status: 200, data: { workspaces: [] } });
    enqueue("/sessions", { status: 200, data: { sessions: [] } });
    enqueue("/runs/recent", { status: 200, data: { runs: [] } });
    render(
      <AppLayout cols={3}>
        <div data-testid="center-stub">center</div>
      </AppLayout>,
    );
    expect(screen.getByTestId("layout-right")).toBeInTheDocument();
    fireEvent.click(screen.getByTestId("btn-toggle-inspector"));
    expect(useUIStore.getState().inspectorOpen).toBe(false);
    // reopen
    fireEvent.click(screen.getByTestId("btn-open-inspector"));
    expect(useUIStore.getState().inspectorOpen).toBe(true);
  });
});
