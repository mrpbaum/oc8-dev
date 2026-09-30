import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, expect, it, vi, beforeEach } from "vitest";

const { getCredentials, startLogin, pollLogin } = vi.hoisted(() => ({
  getCredentials: vi.fn(),
  startLogin: vi.fn(),
  pollLogin: vi.fn(),
}));

vi.mock("@/lib/api", () => ({
  api: {
    get: (path: string) =>
      path.startsWith("/credentials") ? getCredentials() : Promise.reject(new Error(path)),
    post: (path: string, body?: unknown) => {
      if (path === "/models/grok-subscription/device/start") return startLogin();
      if (path === "/models/grok-subscription/device/poll") return pollLogin(body);
      return Promise.reject(new Error(`unexpected POST ${path}`));
    },
  },
}));

vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

import { GrokSubscriptionPicker } from "@/components/grok-subscription-picker";

function renderPicker(onChange = vi.fn()) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return {
    onChange,
    ...render(
      <QueryClientProvider client={qc}>
        <GrokSubscriptionPicker value="" onChange={onChange} />
      </QueryClientProvider>,
    ),
  };
}

const START_RESPONSE = {
  deviceAuthId: "dc1",
  userCode: "ABCD-1234",
  verificationUri: "https://accounts.x.ai/device",
  expiresIn: 900,
  interval: 1,
};

describe("GrokSubscriptionPicker", () => {
  beforeEach(() => {
    getCredentials.mockReset().mockResolvedValue([]);
    startLogin.mockReset();
    pollLogin.mockReset();
  });

  it("shows the user code and verification link after starting a login", async () => {
    startLogin.mockResolvedValue(START_RESPONSE);
    pollLogin.mockResolvedValue({ status: "pending", credentialId: null, error: null });
    renderPicker();

    fireEvent.click(await screen.findByRole("button", { name: /sign in with grok/i }));

    expect(await screen.findByText("ABCD-1234")).toBeInTheDocument();
    const link = screen.getByRole("link", { name: /accounts\.x\.ai\/device/i });
    expect(link).toHaveAttribute("href", "https://accounts.x.ai/device");
  });

  it("calls onChange with the new credential id once polling reports complete", async () => {
    const onChange = vi.fn();
    startLogin.mockResolvedValue(START_RESPONSE);
    pollLogin.mockResolvedValue({ status: "complete", credentialId: "cred-99", error: null });
    const { onChange: cb } = renderPicker(onChange);

    fireEvent.click(await screen.findByRole("button", { name: /sign in with grok/i }));
    await screen.findByText("ABCD-1234");

    await waitFor(() => expect(cb).toHaveBeenCalledWith("cred-99"), { timeout: 3000 });
    expect(pollLogin).toHaveBeenCalledWith(
      expect.objectContaining({ deviceAuthId: "dc1", userCode: "ABCD-1234" }),
    );
  });

  it("lists already-connected Grok accounts of the right credential type", async () => {
    getCredentials.mockResolvedValue([{ id: "c1", name: "user@example.com" }]);
    renderPicker();

    expect(await screen.findByText("user@example.com")).toBeInTheDocument();
  });

  it("says the connection is a personal subscription with manual-only runs", async () => {
    renderPicker();
    expect(await screen.findByText(/manual/i)).toBeInTheDocument();
  });
});
