import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { ModelDTO } from "@/lib/hooks";
import type { AgentDetail } from "@/lib/hooks-agent-detail";

vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

import { AssignedModelPanel } from "@/routes/agents.$id";

const AGENT: AgentDetail = {
  id: "agent-1",
  name: "Nora",
  role: "Sales",
  llm: "gpt-5",
  provider: "openai_chatgpt",
  status: "running",
  tools: [],
  lastAction: "",
  lastRun: "",
  tasksToday: 0,
  guardrails: [],
  schedule: "",
  avatarColor: "#000",
  departmentId: "dept-1",
  modelConfigId: "m-sub",
  isLead: false,
  mission: "",
  departmentName: "Vertrieb",
  effectiveTools: {},
  departmentFrameTools: {},
  narrowingTools: {},
  runtimeRef: null,
  currentRunId: null,
  temperature: null,
  maxTokens: null,
  effort: null,
  extra: null,
};

function model(overrides: Partial<ModelDTO> = {}): ModelDTO {
  return {
    id: "m1",
    provider: "anthropic",
    name: "Claude",
    status: "healthy",
    costTier: "$",
    latency: "-",
    assignedTo: [],
    note: "",
    model: "claude-3-5-sonnet",
    locality: "cloud",
    displayName: null,
    usedByCopilot: false,
    credentialId: null,
    healthError: null,
    healthCheckedAt: null,
    ...overrides,
  };
}

const MODELS: ModelDTO[] = [
  model({ id: "m-api", provider: "anthropic", model: "claude-3-5-sonnet" }),
  model({ id: "m-sub", provider: "openai_chatgpt", model: "gpt-5" }),
  model({ id: "m-grok", provider: "xai_grok", model: "grok-4" }),
];

function renderPanel(agent: AgentDetail = AGENT) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <AssignedModelPanel agent={agent} models={MODELS} mayManage />
    </QueryClientProvider>,
  );
}

describe("Agent detail's persistent subscription risk badge", () => {
  it("shows the badge when the agent's assigned model is ChatGPT-subscription backed", () => {
    renderPanel();
    expect(screen.getByText(/manual only/i)).toBeInTheDocument();
  });

  it("shows the badge when the agent's assigned model is Grok-subscription backed", () => {
    renderPanel({ ...AGENT, modelConfigId: "m-grok", provider: "xai_grok", llm: "grok-4" });
    expect(screen.getByText(/manual only/i)).toBeInTheDocument();
  });

  it("does not show the badge for an API-key-backed assigned model", () => {
    renderPanel({ ...AGENT, modelConfigId: "m-api" });
    expect(screen.queryByText(/manual only/i)).toBeNull();
  });

  it("does not show the badge when the agent has no model assigned", () => {
    renderPanel({ ...AGENT, modelConfigId: null });
    expect(screen.queryByText(/manual only/i)).toBeNull();
  });
});
