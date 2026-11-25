// Removing a provider must report what the runtime actually did.
//
// The bug this pins down: the row is drawn from `listProviders`, but the
// cleanup only touches what the app owns (auth entry, credential, config).
// A provider whose key arrives through the sidecar's environment — DeepSeek
// and Alibaba on a machine with DEEPSEEK_API_KEY / DASHSCOPE_API_KEY — comes
// straight back, and the old code still toasted "removed". The row stayed and
// nothing explained why.

import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ProviderCatalogEntry, ProviderInfo } from "@ai4s/sdk";
import i18n from "@/i18n";
import * as runtime from "@/lib/runtime";
import { useRuntimeStore } from "@/lib/runtime";
import { useSetupStore } from "@/lib/setup";
import { useToastStore } from "@/lib/toast";
import { Toaster } from "@/components/ui/Toaster";
import { SettingsPage } from "./SettingsPage";

const deepseek: ProviderInfo = {
  id: "deepseek",
  name: "DeepSeek",
  models: [{ id: "deepseek-chat", name: "DeepSeek Chat" }],
};

const catalog: ProviderCatalogEntry[] = [
  { id: "deepseek", name: "DeepSeek", env: ["DEEPSEEK_API_KEY"] },
];

/** `listProviders` reads the mutable list, so a test can decide what the
 *  runtime still offers AFTER the cleanup ran — which is the whole question. */
function providerClient(state: { current: ProviderInfo[] }) {
  return {
    listProviders: vi.fn(async () => state.current),
    listAuthMethods: vi.fn().mockResolvedValue({}),
    listProviderCatalog: vi.fn().mockResolvedValue({ all: catalog, connected: ["deepseek"] }),
    listCustomProviderIds: vi.fn().mockResolvedValue([]),
    listMcpServers: vi.fn().mockResolvedValue([]),
    removeProviderAuth: vi.fn().mockResolvedValue(undefined),
    getProviderRegion: vi.fn().mockResolvedValue(null),
    setProviderRegion: vi.fn().mockResolvedValue(undefined),
    setProviderApiKey: vi.fn().mockResolvedValue(undefined),
    addCustomProvider: vi.fn().mockResolvedValue(undefined),
  } as unknown as NonNullable<ReturnType<typeof runtime.getClient>>;
}

async function renderSettings() {
  let view!: ReturnType<typeof render>;
  await act(async () => {
    view = render(
      <MemoryRouter initialEntries={["/settings/agents"]}>
        <Routes>
          <Route path="/settings/:section" element={<SettingsPage />} />
        </Routes>
        <Toaster />
      </MemoryRouter>,
    );
  });
  return view;
}

describe("provider removal reports the outcome", () => {
  const initialRuntime = useRuntimeStore.getState();
  const initialSetup = useSetupStore.getState();

  beforeEach(async () => {
    window.localStorage.clear();
    useToastStore.setState({ toasts: [] });
    useSetupStore.setState({ generation: 0 });
    useRuntimeStore.setState({
      status: "ready",
      defaultModel: "deepseek/deepseek-chat",
      switching: false,
      // The real one dials the runtime; the removal flow only needs the call.
      connectRetry: vi.fn().mockResolvedValue(true),
    });
    await i18n.changeLanguage("en");
  });

  afterEach(() => {
    vi.restoreAllMocks();
    useToastStore.setState({ toasts: [] });
    useSetupStore.setState(initialSetup, true);
    useRuntimeStore.setState(initialRuntime, true);
  });

  it("names the environment variable instead of claiming success", async () => {
    const state = { current: [deepseek] };
    const client = providerClient(state);
    vi.spyOn(runtime, "getClient").mockReturnValue(client);
    const view = await renderSettings();
    const remove = await screen.findByRole("button", { name: "Remove" });

    await userEvent.click(remove);

    expect(await screen.findByText(/DEEPSEEK_API_KEY/)).toBeInTheDocument();
    expect(screen.queryByText("deepseek removed")).not.toBeInTheDocument();
    // The row is still there, which is the truth the message now matches.
    expect(screen.getAllByText("DeepSeek").length).toBeGreaterThan(0);
    view.unmount();
  });

  it("says removed only when the runtime stops offering the provider", async () => {
    const state = { current: [deepseek] };
    const client = providerClient(state);
    vi.spyOn(runtime, "getClient").mockReturnValue(client);
    const view = await renderSettings();
    const remove = await screen.findByRole("button", { name: "Remove" });

    state.current = [];
    await userEvent.click(remove);

    expect(await screen.findByText("deepseek removed")).toBeInTheDocument();
    view.unmount();
  });
});