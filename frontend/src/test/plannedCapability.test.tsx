/**
 * Test 6 — planned capability 不显示调用按钮
 *
 * /api/capabilities 返回 business capability catalog projection.
 */

import { describe, it, expect, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import { CapabilityCenter } from "../pages/CapabilityCenter/CapabilityCenter";
import { enqueue, installMockApi, resetMocks } from "./mockServer";
import type { BusinessCapability } from "../types";

const sampleCaps: BusinessCapability[] = [
  {
    capability_id: "config_translation",
    status: "enabled",
    enabled: true,
    description: "Translate vendor configs to canonical IR",
    category: "translation",
    intent: "translate_config",
    module: "config_translation",
    skill: "config_translation",
    risk_level: "low",
    can_generate_deployable: true,
    requires_verification: true,
    requires_human_review: false,
  },
  {
    capability_id: "topology",
    status: "planned",
    enabled: false,
    description: "Topology discovery & rendering (planned)",
    category: "topology",
    intent: "topology_render",
    module: "topology",
    skill: "topology_draw",
    risk_level: "low",
    can_generate_deployable: false,
    requires_verification: false,
    requires_human_review: false,
  },
];

describe("CapabilityCenter — planned capability has NO invoke button", () => {
  beforeEach(() => {
    resetMocks();
    installMockApi();
  });

  it("renders enabled + planned but no invoke button on planned", async () => {
    enqueue("/capabilities", { status: 200, data: { capabilities: sampleCaps } });
    render(<CapabilityCenter />);
    await screen.findByTestId("cap-config_translation");
    const planned = await screen.findByTestId("cap-topology");
    expect(planned.dataset.status).toBe("planned");
    // The (不可调用) tag is present, but no button to invoke.
    expect(screen.getByTestId("cap-planned-tag-topology")).toBeInTheDocument();
    // Sanity: no buttons inside the planned card whose text is "调用" / "Run" / "Invoke"
    const buttons = planned.querySelectorAll("button");
    buttons.forEach((b) => {
      expect(b.textContent).not.toMatch(/调用|invoke|run|execute/i);
    });
  });
});
