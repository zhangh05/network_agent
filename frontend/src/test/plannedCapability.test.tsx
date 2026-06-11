/**
 * Test 6 — planned capability 不显示调用按钮
 */

import { describe, it, expect, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import { CapabilityCenter } from "../pages/CapabilityCenter/CapabilityCenter";
import { enqueue, installMockApi, resetMocks } from "./mockServer";
import type { CapabilityManifest } from "../types";

const sampleCaps: CapabilityManifest[] = [
  {
    capability_id: "config_translation",
    name: "Config Translation",
    status: "enabled",
    description: "Translate vendor configs to canonical IR",
    module: { module_id: "config_translation", status: "enabled", service_path: "agent.modules.config_translation.service", operations: ["translate_config"], description: "" },
    skills: [
      { skill_id: "config_translation", status: "enabled", related_tools: ["config_translation.translate_config"], intent_patterns: ["translate config"], required_inputs: [], prompt_summary: "", preconditions: [], postconditions: [], safety_rules: [] },
    ],
    tools: [
      { tool_id: "config_translation.translate_config", status: "enabled", callable_by_llm: true, risk_level: "low", requires_approval: false, forbidden: false, handler_ref: "agent.modules.config_translation.tools", input_schema: {}, description: "" },
    ],
    outputs: [],
    safety: { real_device_access: false, allows_config_push: false, produces_deployable_config: false, may_fabricate_sources: false, requires_human_review: false, notes: "" },
    dependencies: [],
    metadata: {},
  },
  {
    capability_id: "topology",
    name: "Topology",
    status: "planned",
    description: "Topology discovery & rendering (planned)",
    module: { module_id: "topology", status: "planned", service_path: "agent.modules.topology.service", operations: [], description: "" },
    skills: [
      { skill_id: "topology_draw", status: "planned", related_tools: [], intent_patterns: [], required_inputs: [], prompt_summary: "", preconditions: [], postconditions: [], safety_rules: [] },
    ],
    tools: [
      { tool_id: "topology.extract", status: "planned", callable_by_llm: false, risk_level: "low", requires_approval: false, forbidden: false, handler_ref: "", input_schema: {}, description: "" },
      { tool_id: "topology.render", status: "planned", callable_by_llm: false, risk_level: "low", requires_approval: false, forbidden: false, handler_ref: "", input_schema: {}, description: "" },
    ],
    outputs: [],
    safety: { real_device_access: false, allows_config_push: false, produces_deployable_config: false, may_fabricate_sources: false, requires_human_review: false, notes: "" },
    dependencies: [],
    metadata: {},
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
    // The (not callable) tag is present, but no button to invoke.
    expect(screen.getByTestId("cap-planned-tag-topology")).toBeInTheDocument();
    // Sanity: no buttons inside the planned card whose text is "Invoke" / "调用" / "Run"
    const buttons = planned.querySelectorAll("button");
    buttons.forEach((b) => {
      expect(b.textContent).not.toMatch(/invoke|调用|run|execute/i);
    });
  });
});
