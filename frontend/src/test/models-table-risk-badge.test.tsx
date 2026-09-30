import { render, screen, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, expect, it, vi, beforeEach } from "vitest";
import type { ModelDTO, ModelProviderDTO } from "@/lib/hooks";

const modelsMock = vi.fn();
const providersMock = vi.fn();
const credentialsMock = vi.fn();
const modelPricesMock = vi.fn();

vi.mock("@/lib/hooks", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/hooks")>();
  return {
    ...actual,
    useModels: () => modelsMock(),
    useModelProviders: () => providersMock(),
    useCredentials: () => credentialsMock(),
  };
});

vi.mock("@/lib/governance-hooks", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/governance-hooks")>();
  return { ...actual, useMay: () => () => true };
});

vi.mock("@/lib/model-prices-hooks", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/model-prices-hooks")>();
  return {
    ...actual,
    useModelPrices: () => modelPricesMock(),
    useCreateModelPrice: () => ({ mutateAsync: vi.fn(), isPending: false }),
    useDeactivateModelPrice: () => ({ mutateAsync: vi.fn(), isPending: false }),
  };
});

vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

import { ModelsPage } from "@/routes/models";

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

const PROVIDERS: ModelProviderDTO[] = [
  { canonical: "anthropic", locality: "cloud", available: true },
  { canonical: "openai_chatgpt", locality: "cloud", available: true },
];

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <ModelsPage />
    </QueryClientProvider>,
  );
}

describe("Models table's persistent subscription risk badge", () => {
  beforeEach(() => {
    credentialsMock.mockReset().mockReturnValue({ data: [] });
    providersMock.mockReset().mockReturnValue({ data: PROVIDERS });
    modelPricesMock.mockReset().mockReturnValue({ data: [] });
  });

  it("shows a persistent risk badge for an openai_chatgpt-provider model's row", () => {
    modelsMock.mockReturnValue({
      data: [
        model({ id: "m1", provider: "anthropic", name: "Claude" }),
        model({ id: "m2", provider: "openai_chatgpt", name: "ChatGPT Sub", model: "gpt-5" }),
        model({ id: "m3", provider: "xai_grok", name: "Grok Sub", model: "grok-4" }),
      ],
    });
    renderPage();

    const row = screen.getByText("ChatGPT Sub").closest("tr");
    expect(row).not.toBeNull();
    expect(within(row as HTMLElement).getByText(/manual only/i)).toBeInTheDocument();
    const grokRow = screen.getByText("Grok Sub").closest("tr");
    expect(grokRow).not.toBeNull();
    expect(within(grokRow as HTMLElement).getByText(/manual only/i)).toBeInTheDocument();
  });

  it("does not show the risk badge on a non-subscription model's row", () => {
    modelsMock.mockReturnValue({
      data: [model({ id: "m1", provider: "anthropic", name: "Claude" })],
    });
    renderPage();

    const row = screen.getByText("Claude").closest("tr");
    expect(row).not.toBeNull();
    expect(within(row as HTMLElement).queryByText(/manual only/i)).toBeNull();
  });
});
