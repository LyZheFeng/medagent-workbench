import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ProviderAuthMethod, ProviderCatalogEntry, ProviderInfo } from "@ai4s/sdk";
import i18n from "@/i18n";
import * as onboarding from "@/lib/onboarding";
import * as runtime from "@/lib/runtime";
import { useRuntimeStore } from "@/lib/runtime";
import * as tauri from "@/lib/tauri";
import { useLayoutStore } from "@/lib/layout";
import { COMPLIANCE_ACK_KEY } from "@/components/compliance/ComplianceNotice";
import { FirstRun } from "./FirstRun";
import { OnboardingWizard } from "./OnboardingWizard";

const zen: ProviderInfo = {
  id: "opencode",
  name: "OpenCode Zen",
  models: [{ id: "zen-free", name: "Zen Free", free: true }],
};
const mine: ProviderInfo = {
  id: "medagent-glm",
  name: "GLM",
  models: [{ id: "glm-5", name: "GLM 5" }],
};
const deepseek: ProviderInfo = {
  id: "deepseek",
  name: "DeepSeek",
  models: [
    { id: "deepseek-chat", name: "DeepSeek Chat", free: true },
    { id: "deepseek-retired", name: "Retired", available: false },
  ],
};

const catalog: ProviderCatalogEntry[] = [
  { id: "deepseek", name: "DeepSeek", env: ["DEEPSEEK_API_KEY"] },
  { id: "opencode", name: "OpenCode Zen", env: [] },
  { id: "github-copilot", name: "GitHub Copilot", env: [] },
];
const authMethods: Record<string, ProviderAuthMethod[]> = {
  opencode: [{ type: "oauth", label: "Sign in" }],
  "github-copilot": [{ type: "oauth", label: "Sign in" }],
};

const initialRuntime = useRuntimeStore.getState();

function clientMock() {
  return {
    listProviderCatalog: vi.fn().mockResolvedValue({ all: catalog, connected: ["opencode"] }),
    listAuthMethods: vi.fn().mockResolvedValue(authMethods),
    setProviderApiKeyRef: vi.fn().mockResolvedValue(undefined),
    setProviderApiKey: vi.fn().mockResolvedValue(undefined),
    removeProviderAuth: vi.fn().mockResolvedValue(undefined),
  };
}

/** A loadCatalog that only changes the provider list after a key was stored —
 *  the gate itself must read the pre-setup state, or every install would look
 *  configured as soon as the wizard loaded its own catalog. */
function loadCatalogAfterKey() {
  return vi.fn(async () => {
    if (vi.mocked(tauri.storeProviderKey).mock.calls.length > 0) {
      useRuntimeStore.setState({ providers: [zen, deepseek] });
    }
  });
}

async function renderWizard() {
  let view!: ReturnType<typeof render>;
  await act(async () => {
    view = render(
      <MemoryRouter>
        <OnboardingWizard desktop web={false} />
      </MemoryRouter>,
    );
  });
  return view;
}

beforeEach(async () => {
  window.localStorage.clear();
  await i18n.changeLanguage("en");
  vi.spyOn(tauri, "storeProviderKey").mockResolvedValue("MEDAGENT_KEY_DEEPSEEK");
  vi.spyOn(tauri, "restartRuntime").mockResolvedValue("http://127.0.0.1:4096");
  useRuntimeStore.setState({
    status: "ready",
    providers: [zen],
    defaultModel: null,
    loadCatalog: vi.fn(async () => undefined),
    connectRetry: vi.fn(async () => true),
    setDefaultModel: vi.fn(async () => {}),
    sendPrompt: vi.fn(async () => "ses_test"),
    interrupt: vi.fn(async () => {}),
    openSession: vi.fn(async () => {}),
  } as never);
});

afterEach(() => {
  // Unmount before restoring store state: a mounted component reacting to the
  // restore is the "update not wrapped in act" warning, not a behaviour.
  cleanup();
  vi.restoreAllMocks();
  useRuntimeStore.setState(initialRuntime, true);
});

describe("the first-run wizard", () => {
  it("stays away from an install that already has a provider", async () => {
    const loadCatalog = vi.fn(async () => {
      useRuntimeStore.setState({ providers: [zen, mine], defaultModel: "medagent-glm/glm-5" });
    });
    useRuntimeStore.setState({ providers: [zen, mine], loadCatalog } as never);

    await renderWizard();
    await waitFor(() => expect(loadCatalog).toHaveBeenCalled());
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("offers a provider list on a fresh install, keyless built-in included", async () => {
    vi.spyOn(runtime, "getClient").mockReturnValue(clientMock() as never);
    await renderWizard();

    const dialog = await screen.findByRole("dialog", { name: "Set up a model" });
    expect(dialog).toHaveTextContent("DeepSeek");
    expect(dialog).toHaveTextContent("OpenCode Zen");
    expect(dialog).toHaveTextContent("built-in · no key needed");
    // OAuth-only providers belong to Settings, not to a first step.
    expect(dialog).not.toHaveTextContent("GitHub Copilot");
  });

  it("saves the key to the credential store and never to the config file", async () => {
    const client = clientMock();
    vi.spyOn(runtime, "getClient").mockReturnValue(client as never);
    useRuntimeStore.setState({ loadCatalog: loadCatalogAfterKey() } as never);
    await renderWizard();
    await screen.findByRole("dialog", { name: "Set up a model" });

    fireEvent.click(screen.getByText("DeepSeek").closest("button")!);
    fireEvent.change(screen.getByLabelText("DeepSeek API key"), {
      target: { value: "sk-deepseek-123" },
    });
    fireEvent.click(screen.getByRole("button", { name: /save key/i }));

    await waitFor(() => expect(screen.getByRole("dialog")).toHaveTextContent("DeepSeek Chat"));
    expect(tauri.storeProviderKey).toHaveBeenCalledWith("deepseek", "sk-deepseek-123");
    // The config gets the reference; the plaintext goes through OpenCode's own
    // auth route exactly never.
    expect(client.setProviderApiKeyRef).toHaveBeenCalledWith(
      "deepseek",
      "{env:MEDAGENT_KEY_DEEPSEEK}",
    );
    expect(client.setProviderApiKey).not.toHaveBeenCalled();
    expect(tauri.restartRuntime).toHaveBeenCalled();
    expect(screen.getByRole("dialog")).toHaveTextContent(
      "Key saved to the system credential store.",
    );

    // A retired model is not offered; picking one sets the default model.
    expect(screen.getByRole("dialog")).not.toHaveTextContent("Retired");
    fireEvent.click(screen.getByText("DeepSeek Chat").closest("button")!);
    await waitFor(() =>
      expect(useRuntimeStore.getState().setDefaultModel).toHaveBeenCalledWith(
        "deepseek/deepseek-chat",
      ),
    );
    expect(screen.getByRole("dialog")).toHaveTextContent("A 30-second test");
    // The credential-store statement is the Settings one, verbatim.
    expect(screen.getByRole("dialog")).toHaveTextContent(/credential store/i);
    expect(screen.getByRole("dialog")).toHaveTextContent(/MEDAGENT_KEY/);
  });

  it("runs the test turn, reads the answer, and finishes into the conversation", async () => {
    vi.spyOn(runtime, "getClient").mockReturnValue(clientMock() as never);
    const started = vi
      .spyOn(onboarding, "startOnboardingExample")
      .mockResolvedValue({ draftKey: "onboarding-x", sessionId: "ses_test" });
    useRuntimeStore.setState({ loadCatalog: loadCatalogAfterKey() } as never);
    await renderWizard();
    await screen.findByRole("dialog", { name: "Set up a model" });

    fireEvent.click(screen.getByText("DeepSeek").closest("button")!);
    fireEvent.change(screen.getByLabelText("DeepSeek API key"), { target: { value: "sk-1" } });
    fireEvent.click(screen.getByRole("button", { name: /save key/i }));
    fireEvent.click(await screen.findByText("DeepSeek Chat").then((el) => el.closest("button")!));

    fireEvent.click(await screen.findByRole("button", { name: "Send the test message" }));
    await waitFor(() => expect(started).toHaveBeenCalled());

    await act(async () => {
      useRuntimeStore.setState({
        threads: {
          ses_test: {
            loaded: true,
            index: {},
            blocks: [
              { kind: "user", text: "hi" },
              { kind: "agent", markdown: "I can help with evidence synthesis." },
              { kind: "status-line", text: "done", tone: "done" },
            ],
          },
        },
      } as never);
    });

    expect(await screen.findByText(/Answered in \d+s/)).toBeInTheDocument();
    expect(screen.getByText(/evidence synthesis/)).toBeInTheDocument();

    const openInNewGroup = vi
      .spyOn(useLayoutStore.getState(), "openInNewGroup")
      .mockReturnValue("leaf");
    fireEvent.click(screen.getByRole("button", { name: "Start working" }));
    expect(window.localStorage.getItem(onboarding.ONBOARDING_DONE_KEY)).toBe("1");
    expect(openInNewGroup).toHaveBeenCalledWith("ses_test", expect.anything());
    expect(useRuntimeStore.getState().openSession).toHaveBeenCalledWith("ses_test");
  });

  it("reports a retry the account cannot clear as a failed test", async () => {
    // The fresh install this ran on had the built-in provider's free quota used
    // up: the runtime emitted session.retry with a final cause and no answer.
    vi.spyOn(runtime, "getClient").mockReturnValue(clientMock() as never);
    vi.spyOn(onboarding, "startOnboardingExample").mockResolvedValue({
      draftKey: "onboarding-zen",
      sessionId: "ses_zen",
    });
    await renderWizard();
    await screen.findByRole("dialog", { name: "Set up a model" });

    // The built-in provider needs no key, so the flow skips straight to models.
    fireEvent.click(screen.getByText("OpenCode Zen").closest("button")!);
    fireEvent.click(await screen.findByText("Zen Free").then((el) => el.closest("button")!));
    fireEvent.click(await screen.findByRole("button", { name: "Send the test message" }));

    await act(async () => {
      useRuntimeStore.setState({
        runningSessions: { ses_zen: true },
        retryNotices: {
          ses_zen: {
            attempt: 2,
            message: "Retrying…",
            action: { reason: "free_tier_limit", message: "Free usage exceeded" },
          },
        },
      } as never);
    });

    expect(await screen.findByText(/Free usage exceeded/)).toBeInTheDocument();
    // There is no key to change on this path; the way out is another provider.
    expect(screen.getByRole("button", { name: "Choose another provider" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Change the key" })).not.toBeInTheDocument();
  });

  it("can be postponed without being a nag", async () => {
    vi.spyOn(runtime, "getClient").mockReturnValue(clientMock() as never);
    const first = await renderWizard();
    await screen.findByRole("dialog", { name: "Set up a model" });
    fireEvent.click(screen.getByRole("button", { name: "Set up later" }));
    expect(window.localStorage.getItem(onboarding.ONBOARDING_DONE_KEY)).toBe("1");
    first.unmount();

    await renderWizard();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });
});

describe("first-run ordering", () => {
  it("acknowledges the medical boundary before the setup wizard, never both at once", async () => {
    vi.spyOn(runtime, "getClient").mockReturnValue(clientMock() as never);
    render(
      <MemoryRouter>
        <FirstRun desktop web={false} />
      </MemoryRouter>,
    );

    // 1. The legal statement owns the screen.
    expect(await screen.findByRole("dialog", { name: "Notice" })).toBeInTheDocument();
    expect(screen.getAllByRole("dialog")).toHaveLength(1);
    expect(screen.queryByRole("dialog", { name: "Set up a model" })).not.toBeInTheDocument();

    // 2. Acknowledging it hands over to setup.
    fireEvent.click(screen.getByRole("button", { name: /i understand/i }));
    await act(async () => {});
    expect(window.localStorage.getItem(COMPLIANCE_ACK_KEY)).toBe("1");
    expect(await screen.findByRole("dialog", { name: "Set up a model" })).toBeInTheDocument();
    expect(screen.getAllByRole("dialog")).toHaveLength(1);
    expect(screen.queryByRole("dialog", { name: "Notice" })).not.toBeInTheDocument();
  });

  it("hides setup in the gateway web client, which cannot write provider config", async () => {
    window.localStorage.setItem(COMPLIANCE_ACK_KEY, "1");
    vi.spyOn(runtime, "getClient").mockReturnValue(clientMock() as never);
    await act(async () => {
      render(
        <MemoryRouter>
          <FirstRun desktop web />
        </MemoryRouter>,
      );
    });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });
});