import { render, screen, fireEvent } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, expect, it, vi, beforeEach } from "vitest";

// With no model connected yet, AgentModelStep must offer the SAME real
// provider-connection flow as Settings -> Models (AddProviderWizard, with a
// real credential step) -- not the bare {provider, model, locality} form it
// used to render inline, which created a ModelConfig with no credential
// attached and so could never actually authenticate against the provider.
const modelsMock = vi.fn();
const providersMock = vi.fn();
const runtimesMock = vi.fn();
const credentialsMock = vi.fn();
const credentialTypesMock = vi.fn();

vi.mock("@/lib/hooks", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/hooks")>();
  return {
    ...actual,
    useModels: () => modelsMock(),
    useModelProviders: () => providersMock(),
    useRuntimes: () => runtimesMock(),
    useCreateAgent: () => ({ mutateAsync: vi.fn(), isPending: false }),
    useCredentials: (type?: string) => credentialsMock(type),
    useCredentialTypes: () => credentialTypesMock(),
    useCreateCredential: () => ({ mutateAsync: vi.fn(), isPending: false }),
    useCreateModel: () => ({ mutateAsync: vi.fn(), isPending: false }),
    useDiscoverModels: () => ({ mutateAsync: vi.fn(), isPending: false }),
    useStartChatGptDeviceLogin: () => ({ mutateAsync: vi.fn(), isPending: false }),
    usePollChatGptDeviceLogin: () => ({ mutateAsync: vi.fn(), isPending: false }),
    useStartGrokDeviceLogin: () => ({ mutateAsync: vi.fn(), isPending: false }),
    usePollGrokDeviceLogin: () => ({ mutateAsync: vi.fn(), isPending: false }),
  };
});

vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

import { AgentModelStep } from "@/components/onboarding/agent-model-step";

function renderStep() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <AgentModelStep
        identity={{
          name: "Astra",
          role: "Support",
          description: "",
          departmentId: "dept-1",
          avatarIdx: 0,
        }}
        onDone={vi.fn()}
      />
    </QueryClientProvider>,
  );
}

describe("AgentModelStep with no model connected yet", () => {
  beforeEach(() => {
    modelsMock.mockReset().mockReturnValue({ data: [] });
    providersMock
      .mockReset()
      .mockReturnValue({ data: [{ canonical: "anthropic", locality: "cloud", available: true }] });
    runtimesMock.mockReset().mockReturnValue({ data: [] });
    credentialsMock.mockReset().mockReturnValue({ data: [], refetch: vi.fn() });
    credentialTypesMock.mockReset().mockReturnValue({ data: [] });
  });

  it("offers to connect a provider instead of a bare model-tag form", () => {
    renderStep();
    expect(screen.getByRole("button", { name: /connect a provider/i })).toBeInTheDocument();
    // The old inline form's own fields must be gone.
    expect(screen.queryByPlaceholderText(/llama3\.1:8b/)).not.toBeInTheDocument();
  });

  it("opens the real AddProviderWizard, with its own credential step", () => {
    renderStep();
    fireEvent.click(screen.getByRole("button", { name: /connect a provider/i }));
    expect(screen.getByText(/add model provider/i)).toBeInTheDocument();
    expect(screen.getByText(/step 1 of 3/i)).toBeInTheDocument();
  });
});
