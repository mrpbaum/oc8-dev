import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, expect, it, vi, beforeEach } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

const credentialsMock = vi.fn();
const credentialTypesMock = vi.fn();
const deleteModelMock = vi.fn();
const deleteCredentialMock = vi.fn();

vi.mock("@/lib/hooks", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/hooks")>();
  return {
    ...actual,
    useCredentials: (type?: string) => credentialsMock(type),
    useCredentialTypes: () => credentialTypesMock(),
    useDeleteModel: () => ({ mutateAsync: deleteModelMock, isPending: false }),
    useDeleteCredential: () => ({ mutateAsync: deleteCredentialMock, isPending: false }),
  };
});

vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

import { toast } from "sonner";
import { ProviderCard } from "@/routes/models";
import type { ModelDTO } from "@/lib/hooks";

function config(overrides: Partial<ModelDTO> = {}): ModelDTO {
  return {
    id: "m1",
    name: "claude-3-5-sonnet",
    provider: "anthropic",
    model: "claude-3-5-sonnet",
    locality: "cloud",
    status: "healthy",
    latency: "-",
    costTier: "$$",
    note: "",
    assignedTo: [],
    ...overrides,
  } as ModelDTO;
}

function renderCard(configs: ModelDTO[]) {
  const qc = new QueryClient();
  return {
    qc,
    ...render(
      <QueryClientProvider client={qc}>
        <ProviderCard
          group={{ canonical: "anthropic", locality: "cloud", available: true, configs }}
          mayManage={true}
        />
      </QueryClientProvider>,
    ),
  };
}

describe("ProviderCard's Remove provider action", () => {
  beforeEach(() => {
    credentialsMock.mockReset();
    credentialTypesMock.mockReset();
    deleteModelMock.mockReset();
    deleteCredentialMock.mockReset();
    credentialsMock.mockReturnValue({ data: [{ id: "cred-1", name: "Prod Anthropic" }] });
    credentialTypesMock.mockReturnValue({ data: [] });
    deleteModelMock.mockResolvedValue(undefined);
    deleteCredentialMock.mockResolvedValue(undefined);
    vi.mocked(toast.error).mockClear();
    vi.mocked(toast.success).mockClear();
  });

  it("blocks removal with an error toast, no confirm dialog, when a model is assigned to an agent", () => {
    renderCard([config({ assignedTo: ["agent-1"] })]);

    fireEvent.click(screen.getByRole("button", { name: /remove provider/i }));

    expect(toast.error).toHaveBeenCalled();
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
    expect(deleteModelMock).not.toHaveBeenCalled();
  });

  it("deletes every model and the provider's credential once confirmed", async () => {
    renderCard([config({ id: "m1" }), config({ id: "m2" })]);

    fireEvent.click(screen.getByRole("button", { name: /remove provider/i }));
    fireEvent.click(await screen.findByRole("button", { name: /^remove$/i }));

    await waitFor(() => expect(deleteModelMock).toHaveBeenCalledWith("m1"));
    expect(deleteModelMock).toHaveBeenCalledWith("m2");
    await waitFor(() => expect(deleteCredentialMock).toHaveBeenCalledWith("cred-1"));
    expect(toast.success).toHaveBeenCalled();
  });

  it("skips credential deletion for a local provider (no credential exists)", async () => {
    const qc = new QueryClient();
    render(
      <QueryClientProvider client={qc}>
        <ProviderCard
          group={{ canonical: "ollama", locality: "local", available: true, configs: [] }}
          mayManage={true}
        />
      </QueryClientProvider>,
    );

    fireEvent.click(screen.getByRole("button", { name: /remove provider/i }));
    fireEvent.click(await screen.findByRole("button", { name: /^remove$/i }));

    await waitFor(() => expect(toast.success).toHaveBeenCalled());
    expect(deleteCredentialMock).not.toHaveBeenCalled();
  });

  it("cancelling the confirm dialog deletes nothing", async () => {
    renderCard([config()]);

    fireEvent.click(screen.getByRole("button", { name: /remove provider/i }));
    fireEvent.click(await screen.findByRole("button", { name: /^cancel$/i }));

    expect(deleteModelMock).not.toHaveBeenCalled();
    expect(deleteCredentialMock).not.toHaveBeenCalled();
  });
});

describe("ProviderCard's persistent subscription risk badge", () => {
  beforeEach(() => {
    credentialsMock.mockReset().mockReturnValue({ data: [] });
    credentialTypesMock.mockReset().mockReturnValue({ data: [] });
    deleteModelMock.mockReset().mockResolvedValue(undefined);
    deleteCredentialMock.mockReset().mockResolvedValue(undefined);
  });

  it("shows a persistent risk badge for an openai_chatgpt-provider tile", () => {
    const qc = new QueryClient();
    render(
      <QueryClientProvider client={qc}>
        <ProviderCard
          group={{ canonical: "openai_chatgpt", locality: "cloud", available: true, configs: [] }}
          mayManage={true}
        />
      </QueryClientProvider>,
    );

    expect(screen.getByText(/manual only/i)).toBeInTheDocument();
  });

  it("shows a persistent risk badge for an xai_grok-provider tile", () => {
    const qc = new QueryClient();
    render(
      <QueryClientProvider client={qc}>
        <ProviderCard
          group={{ canonical: "xai_grok", locality: "cloud", available: true, configs: [] }}
          mayManage={true}
        />
      </QueryClientProvider>,
    );

    expect(screen.getByText(/manual only/i)).toBeInTheDocument();
  });

  it("does not show the risk badge for an ordinary cloud provider tile", () => {
    renderCard([config()]);

    expect(screen.queryByText(/manual only/i)).toBeNull();
  });

  it("does not show the risk badge for a local provider tile", () => {
    const qc = new QueryClient();
    render(
      <QueryClientProvider client={qc}>
        <ProviderCard
          group={{ canonical: "ollama", locality: "local", available: true, configs: [] }}
          mayManage={true}
        />
      </QueryClientProvider>,
    );

    expect(screen.queryByText(/manual only/i)).toBeNull();
  });
});
