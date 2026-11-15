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

const mine: ProviderInfo = {
  id: "medagent-glm",
  name: "GLM",
  models: [{ id: "glm-5", name: "GLM 5" }],
};
/** What a custom endpoint added in the wizard looks like to the runtime. */
const addedEndpoint: ProviderInfo = {
  id: "glm",
  name: "GLM",
  models: [{ id: "glm-4.5", name: "glm-4.5" }],
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
    addCustomProvider: vi.fn().mockResolvedValue(undefined),
  };
}

/** A loadCatalog that only changes the provider list after a key was stored —
 *  the gate itself must read the pre-setup state, or every install would look
 *  configured as soon as the wizard loaded its own catalog. */
function loadCatalogAfterKey() {
  return vi.fn(async () => {
    if (vi.mocked(tauri.storeProviderKey).mock.calls.length > 0) {
      useRuntimeStore.setState({ providers: [deepseek] });
    }
  });
}

/** The same, for the custom-endpoint route: the provider only exists once the
 *  wizard has written it through `addCustomProvider`. */
function loadCatalogAfterEndpoint(client: ReturnType<typeof clientMock>) {
  return vi.fn(async () => {
    if (client.addCustomProvider.mock.calls.length > 0) {
      useRuntimeStore.setState({ providers: [addedEndpoint] });
    }
  });
}

async function renderWizard({
  probe = null,
}: {
  probe?: typeof tauri.probeEndpointModels | null;
} = {}) {
  let view!: ReturnType<typeof render>;
  await act(async () => {
    view = render(
      <MemoryRouter>
        <OnboardingWizard desktop web={false} probe={probe} />
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
    providers: [],
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
      useRuntimeStore.setState({ providers: [mine], defaultModel: "medagent-glm/glm-5" });
    });
    useRuntimeStore.setState({ providers: [mine], loadCatalog } as never);

    await renderWizard();
    await waitFor(() => expect(loadCatalog).toHaveBeenCalled());
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("offers API-key providers on a fresh install, not the unusable free built-in", async () => {
    vi.spyOn(runtime, "getClient").mockReturnValue(clientMock() as never);
    await renderWizard();

    const dialog = await screen.findByRole("dialog", { name: "Set up a model" });
    expect(dialog).toHaveTextContent("DeepSeek");
    expect(dialog).not.toHaveTextContent("OpenCode Zen");
    expect(dialog).not.toHaveTextContent("built-in · no key needed");
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

  it("adds a custom endpoint, probing it with the key and never writing the key to the config", async () => {
    const client = clientMock();
    vi.spyOn(runtime, "getClient").mockReturnValue(client as never);
    vi.mocked(tauri.storeProviderKey).mockResolvedValue("MEDAGENT_KEY_GLM");
    const probe = vi.fn().mockResolvedValue({
      baseUrl: "https://open.bigmodel.cn/api/paas/v4",
      models: [{ id: "glm-4.5", context: 128000 }],
    });
    useRuntimeStore.setState({ loadCatalog: loadCatalogAfterEndpoint(client) } as never);
    await renderWizard({ probe });
    await screen.findByRole("dialog", { name: "Set up a model" });

    fireEvent.click(screen.getByRole("button", { name: /custom endpoint/i }));
    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "GLM" } });
    fireEvent.change(screen.getByLabelText("Base URL"), {
      target: { value: "https://open.bigmodel.cn/api/paas/v4" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Continue" }));

    // The key step is the same one the catalog providers use.
    fireEvent.change(screen.getByLabelText("GLM API key"), { target: { value: "sk-glm-777" } });
    fireEvent.click(screen.getByRole("button", { name: /save key/i }));

    // Models were left blank, so the endpoint was asked with the key that was
    // just typed — the one moment a probe can authenticate.
    expect(await screen.findByText("glm-4.5")).toBeInTheDocument();
    expect(probe).toHaveBeenCalledWith(
      "https://open.bigmodel.cn/api/paas/v4",
      "sk-glm-777",
      "openai",
    );
    expect(tauri.storeProviderKey).toHaveBeenCalledWith("glm", "sk-glm-777");
    expect(client.addCustomProvider).toHaveBeenCalledWith("glm", {
      name: "GLM",
      npm: "@ai-sdk/openai-compatible",
      baseURL: "https://open.bigmodel.cn/api/paas/v4",
      apiKey: "{env:MEDAGENT_KEY_GLM}",
      models: ["glm-4.5"],
      contexts: { "glm-4.5": 128000 },
    });
    // The config payload carries the reference and nothing else.
    expect(JSON.stringify(client.addCustomProvider.mock.calls)).not.toContain("sk-glm-777");
    expect(client.setProviderApiKey).not.toHaveBeenCalled();

    fireEvent.click(screen.getByText("glm-4.5").closest("button")!);
    await waitFor(() =>
      expect(useRuntimeStore.getState().setDefaultModel).toHaveBeenCalledWith(
        "glm/glm-4.5",
      ),
    );
    // The closing statement is still the Settings privacy sentence.
    expect(screen.getByRole("dialog")).toHaveTextContent(/credential store/i);
    expect(screen.getByRole("dialog")).toHaveTextContent(/MEDAGENT_KEY/);
  });

  it("takes model ids typed in the form without probing the endpoint", async () => {
    const client = clientMock();
    vi.spyOn(runtime, "getClient").mockReturnValue(client as never);
    vi.mocked(tauri.storeProviderKey).mockResolvedValue("MEDAGENT_KEY_GLM");
    const probe = vi.fn();
    useRuntimeStore.setState({ loadCatalog: loadCatalogAfterEndpoint(client) } as never);
    await renderWizard({ probe });
    await screen.findByRole("dialog", { name: "Set up a model" });

    fireEvent.click(screen.getByRole("button", { name: /custom endpoint/i }));
    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "GLM" } });
    fireEvent.change(screen.getByLabelText("Base URL"), {
      target: { value: "https://open.bigmodel.cn/api/paas/v4" },
    });
    fireEvent.change(screen.getByLabelText("Models"), {
      target: { value: "glm-4.5, glm-4.5-air" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Continue" }));
    fireEvent.change(screen.getByLabelText("GLM API key"), { target: { value: "sk-glm-777" } });
    fireEvent.click(screen.getByRole("button", { name: /save key/i }));

    await screen.findByText("glm-4.5");
    expect(probe).not.toHaveBeenCalled();
    expect(client.addCustomProvider).toHaveBeenCalledWith(
      "glm",
      expect.objectContaining({
        models: ["glm-4.5", "glm-4.5-air"],
        contexts: { "glm-4.5": 500000, "glm-4.5-air": 500000 },
      }),
    );
  });

  it("asks the probe in the API dialect the form selected", async () => {
    const client = clientMock();
    vi.spyOn(runtime, "getClient").mockReturnValue(client as never);
    vi.mocked(tauri.storeProviderKey).mockResolvedValue("MEDAGENT_KEY_GLM");
    const probe = vi.fn().mockResolvedValue({
      baseUrl: "https://api.anthropic.test/v1",
      models: [{ id: "claude-sonnet" }],
    });
    useRuntimeStore.setState({
      loadCatalog: vi.fn(async () => {
        if (client.addCustomProvider.mock.calls.length > 0) {
          useRuntimeStore.setState({
            providers: [
              {
                id: "claude-relay",
                name: "Claude relay",
                models: [{ id: "claude-sonnet", name: "claude-sonnet" }],
              },
            ],
          });
        }
      }),
    } as never);
    await renderWizard({ probe });
    await screen.findByRole("dialog", { name: "Set up a model" });

    fireEvent.click(screen.getByRole("button", { name: /custom endpoint/i }));
    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Claude relay" } });
    fireEvent.change(screen.getByLabelText("API style"), {
      target: { value: "@ai-sdk/anthropic" },
    });
    fireEvent.change(screen.getByLabelText("Base URL"), {
      target: { value: "https://api.anthropic.test/v1" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Continue" }));
    fireEvent.change(screen.getByLabelText("Claude relay API key"), {
      target: { value: "sk-ant-1" },
    });
    fireEvent.click(screen.getByRole("button", { name: /save key/i }));

    await screen.findByText("claude-sonnet");
    expect(probe).toHaveBeenCalledWith("https://api.anthropic.test/v1", "sk-ant-1", "anthropic");
    expect(client.addCustomProvider).toHaveBeenCalledWith(
      "claude-relay",
      expect.objectContaining({ npm: "@ai-sdk/anthropic" }),
    );
  });

  it("refuses a custom endpoint it could not dial", async () => {
    const client = clientMock();
    vi.spyOn(runtime, "getClient").mockReturnValue(client as never);
    await renderWizard();
    await screen.findByRole("dialog", { name: "Set up a model" });

    fireEvent.click(screen.getByRole("button", { name: /custom endpoint/i }));
    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "GLM" } });
    fireEvent.change(screen.getByLabelText("Base URL"), { target: { value: "open.bigmodel.cn" } });
    fireEvent.click(screen.getByRole("button", { name: "Continue" }));

    expect(screen.getByText(/starts with http/)).toBeInTheDocument();
    expect(screen.queryByLabelText(/API key/)).not.toBeInTheDocument();
    expect(client.addCustomProvider).not.toHaveBeenCalled();
  });

  it("leaves both the store and the config untouched when the probe finds nothing", async () => {
    const client = clientMock();
    vi.spyOn(runtime, "getClient").mockReturnValue(client as never);
    const probe = vi.fn().mockRejectedValue(new Error("401 Unauthorized"));
    await renderWizard({ probe });
    await screen.findByRole("dialog", { name: "Set up a model" });

    fireEvent.click(screen.getByRole("button", { name: /custom endpoint/i }));
    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "GLM" } });
    fireEvent.change(screen.getByLabelText("Base URL"), {
      target: { value: "https://open.bigmodel.cn/api/paas/v4" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Continue" }));
    fireEvent.change(screen.getByLabelText("GLM API key"), { target: { value: "sk-glm-777" } });
    fireEvent.click(screen.getByRole("button", { name: /save key/i }));

    // The probe ran before anything was stored, so a refused key is not left
    // behind and no provider is half-configured.
    expect(
      await screen.findByText(/Could not ask the endpoint for its models/),
    ).toBeInTheDocument();
    expect(tauri.storeProviderKey).not.toHaveBeenCalled();
    expect(client.addCustomProvider).not.toHaveBeenCalled();
  });

  it("goes back from the key step to the custom form it was filling in", async () => {
    const client = clientMock();
    vi.spyOn(runtime, "getClient").mockReturnValue(client as never);
    await renderWizard();
    await screen.findByRole("dialog", { name: "Set up a model" });

    fireEvent.click(screen.getByRole("button", { name: /custom endpoint/i }));
    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "GLM" } });
    fireEvent.change(screen.getByLabelText("Base URL"), {
      target: { value: "https://open.bigmodel.cn/api/paas/v4" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Continue" }));
    fireEvent.click(screen.getByRole("button", { name: /back/i }));

    expect(screen.getByLabelText("Name")).toHaveValue("GLM");
    expect(screen.getByLabelText("Base URL")).toHaveValue(
      "https://open.bigmodel.cn/api/paas/v4",
    );
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
    // The runtime emitted session.retry with a final cause and no answer; the
    // key-based path must offer a way back to the key, not a dead end.
    vi.spyOn(runtime, "getClient").mockReturnValue(clientMock() as never);
    vi.spyOn(onboarding, "startOnboardingExample").mockResolvedValue({
      draftKey: "onboarding-key",
      sessionId: "ses_key",
    });
    useRuntimeStore.setState({ loadCatalog: loadCatalogAfterKey() } as never);
    await renderWizard();
    await screen.findByRole("dialog", { name: "Set up a model" });

    fireEvent.click(screen.getByText("DeepSeek").closest("button")!);
    fireEvent.change(screen.getByLabelText("DeepSeek API key"), { target: { value: "sk-1" } });
    fireEvent.click(screen.getByRole("button", { name: /save key/i }));
    fireEvent.click(await screen.findByText("DeepSeek Chat").then((el) => el.closest("button")!));
    fireEvent.click(await screen.findByRole("button", { name: "Send the test message" }));

    await act(async () => {
      useRuntimeStore.setState({
        runningSessions: { ses_key: true },
        retryNotices: {
          ses_key: {
            attempt: 2,
            message: "Retrying…",
            action: { reason: "free_tier_limit", message: "Free usage exceeded" },
          },
        },
      } as never);
    });

    expect(await screen.findByText(/Free usage exceeded/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Change the key" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Choose another provider" })).not.toBeInTheDocument();
  });

  it("comes back after a postponement until a model is configured", async () => {
    vi.spyOn(runtime, "getClient").mockReturnValue(clientMock() as never);
    const first = await renderWizard();
    await screen.findByRole("dialog", { name: "Set up a model" });
    fireEvent.click(screen.getByRole("button", { name: "Set up later" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    first.unmount();

    await renderWizard();
    expect(await screen.findByRole("dialog", { name: "Set up a model" })).toBeInTheDocument();
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