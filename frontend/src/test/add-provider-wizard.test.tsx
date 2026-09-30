import { render, screen, fireEvent, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, expect, it, vi, beforeEach } from "vitest";

const providersMock = vi.fn();
const credentialsMock = vi.fn();
const credentialTypesMock = vi.fn();

vi.mock("@/lib/hooks", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/hooks")>();
  return {
    ...actual,
    useModelProviders: () => providersMock(),
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

import { AddProviderWizard } from "@/routes/models";

const PROVIDERS = [
  { canonical: "anthropic", locality: "cloud", available: true },
  { canonical: "openai", locality: "cloud", available: false },
  { canonical: "mistral", locality: "cloud", available: true },
  { canonical: "ollama", locality: "local", available: true },
  // available is unconditionally true for this one server-side (there is no
  // tenant-wide key to check), which is exactly why the generic key badge
  // would lie about it.
  { canonical: "openai_chatgpt", locality: "cloud", available: true },
  { canonical: "xai_grok", locality: "cloud", available: true },
];

function renderWizard() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <AddProviderWizard onClose={vi.fn()} />
    </QueryClientProvider>,
  );
}

/** The step-1 tile for one provider. Its accessible name concatenates the
 * avatar letter, the canonical name and the badges with no separators
 * ("A anthropiccloudkey set"), so the locality badge is what reliably
 * terminates the name -- and is also what keeps "openai" from matching the
 * "openai_chatgpt" tile. */
function tile(canonical: string) {
  return screen.getByRole("button", { name: new RegExp(`^. ${canonical}(cloud|local)`) });
}

function openStep2(canonical: string) {
  fireEvent.click(tile(canonical));
  fireEvent.click(screen.getByRole("button", { name: /continue/i }));
}

describe("AddProviderWizard", () => {
  beforeEach(() => {
    providersMock.mockReset().mockReturnValue({ data: PROVIDERS });
    credentialsMock.mockReset().mockReturnValue({ data: [], refetch: vi.fn() });
    credentialTypesMock.mockReset().mockReturnValue({ data: [] });
  });

  it("keeps the key set/missing badge on every ordinary cloud provider", () => {
    renderWizard();
    expect(within(tile("anthropic")).getByText("key set")).toBeInTheDocument();
    expect(within(tile("mistral")).getByText("key set")).toBeInTheDocument();
  });

  it("shows 'key missing' for a cloud provider without a key", () => {
    renderWizard();
    expect(within(tile("openai")).getByText("key missing")).toBeInTheDocument();
  });

  it("shows no key badge on a local provider", () => {
    renderWizard();
    expect(within(tile("ollama")).queryByText(/key set|key missing/)).toBeNull();
  });

  it("skips the misleading key badge on the ChatGPT-subscription provider", () => {
    renderWizard();
    expect(within(tile("openai_chatgpt")).queryByText(/key set|key missing/)).toBeNull();
  });

  it("shows the persistent subscription risk badge on subscription tiles, and no other tile", () => {
    renderWizard();
    expect(within(tile("openai_chatgpt")).getByText(/manual only/i)).toBeInTheDocument();
    expect(within(tile("xai_grok")).getByText(/manual only/i)).toBeInTheDocument();
    expect(within(tile("anthropic")).queryByText(/manual only/i)).toBeNull();
    expect(within(tile("mistral")).queryByText(/manual only/i)).toBeNull();
    expect(within(tile("ollama")).queryByText(/manual only/i)).toBeNull();
  });

  it("offers the device-code sign-in, not the generic credential form, for openai_chatgpt", () => {
    renderWizard();
    openStep2("openai_chatgpt");

    expect(screen.getByText("ChatGPT account")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /sign in with chatgpt/i })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /create new/i })).not.toBeInTheDocument();
    expect(credentialsMock).toHaveBeenCalledWith("openai_chatgpt_subscription");
  });

  // The model router only reaches the subscription bridge through a
  // credential bound to the ModelConfig -- its tenant-wide fallback looks for
  // `{canonical}_api_key`, which this credential type can never match. A
  // model added with no account selected would therefore be unrunnable, so
  // the wizard refuses to move on without one.
  it("blocks Continue for openai_chatgpt until an account is selected", () => {
    credentialsMock.mockReturnValue({
      data: [{ id: "c1", name: "user@example.com" }],
      refetch: vi.fn(),
    });
    renderWizard();
    openStep2("openai_chatgpt");

    fireEvent.change(screen.getByPlaceholderText("llama3.1:8b"), {
      target: { value: "gpt-5" },
    });
    expect(screen.getByRole("button", { name: /continue/i })).toBeDisabled();

    // The account select is the first combobox on the step (Locality is the
    // other one).
    fireEvent.change(screen.getAllByRole("combobox")[0], { target: { value: "c1" } });
    expect(screen.getByRole("button", { name: /continue/i })).toBeEnabled();
  });

  it("skips the misleading key badge on the Grok-subscription provider", () => {
    renderWizard();
    expect(within(tile("xai_grok")).queryByText(/key set|key missing/)).toBeNull();
  });

  it("offers the device-code sign-in, not the generic credential form, for xai_grok", () => {
    renderWizard();
    openStep2("xai_grok");

    expect(screen.getByText("Grok account")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /sign in with grok/i })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /create new/i })).not.toBeInTheDocument();
    expect(credentialsMock).toHaveBeenCalledWith("xai_grok_subscription");
  });

  it("blocks Continue for xai_grok until an account is selected", () => {
    credentialsMock.mockReturnValue({
      data: [{ id: "c1", name: "user@example.com" }],
      refetch: vi.fn(),
    });
    renderWizard();
    openStep2("xai_grok");

    fireEvent.change(screen.getByPlaceholderText("llama3.1:8b"), {
      target: { value: "grok-4" },
    });
    expect(screen.getByRole("button", { name: /continue/i })).toBeDisabled();

    fireEvent.change(screen.getAllByRole("combobox")[0], { target: { value: "c1" } });
    expect(screen.getByRole("button", { name: /continue/i })).toBeEnabled();
  });

  it("does not block Continue on a missing credential for an ordinary provider", () => {
    renderWizard();
    openStep2("anthropic");

    fireEvent.change(screen.getByPlaceholderText("llama3.1:8b"), {
      target: { value: "claude-sonnet-4" },
    });
    expect(screen.getByRole("button", { name: /continue/i })).toBeEnabled();
  });

  it("still offers the generic credential picker for an ordinary provider", () => {
    renderWizard();
    openStep2("anthropic");

    expect(screen.getByRole("button", { name: /create new/i })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /sign in with chatgpt/i })).not.toBeInTheDocument();
    expect(credentialsMock).toHaveBeenCalledWith("anthropic_api_key");
  });
});
