import { beforeEach, describe, expect, it } from "vitest";
import type { ProviderAuthMethod, ProviderCatalogEntry, ProviderInfo } from "@ai4s/sdk";
import type { ThreadBlock } from "@ai4s/shared";
import type { Thread } from "./runtime";
import {
  ONBOARDING_DONE_KEY,
  exampleOutcome,
  examplePrompt,
  filterProviders,
  hasCompletedOnboarding,
  markOnboardingComplete,
  modelChoicesFor,
  offersOnboarding,
  providerChoices,
  rankProviders,
} from "./onboarding";

function thread(...blocks: ThreadBlock[]): Thread {
  return { blocks, index: {}, loaded: true };
}

beforeEach(() => window.localStorage.clear());

describe("first-run onboarding gating", () => {
  it("remembers that it ran", () => {
    expect(hasCompletedOnboarding()).toBe(false);
    markOnboardingComplete();
    expect(window.localStorage.getItem(ONBOARDING_DONE_KEY)).toBe("1");
    expect(hasCompletedOnboarding()).toBe(true);
  });

  it("offers itself only where nothing is configured yet", () => {
    const zen: ProviderInfo = { id: "opencode", name: "OpenCode Zen", models: [] };
    const mine: ProviderInfo = { id: "medagent-glm", name: "GLM", models: [] };
    expect(offersOnboarding([], null)).toBe(true);
    // The built-in provider ships with the runtime — it is what the wizard
    // offers as the keyless path, not evidence of a configured install.
    expect(offersOnboarding([zen], null)).toBe(true);
    // An existing install has answered these questions already.
    expect(offersOnboarding([zen, mine], null)).toBe(false);
    expect(offersOnboarding([zen], "opencode/zen-free")).toBe(false);
  });
});

describe("provider choices", () => {
  const catalog: ProviderCatalogEntry[] = [
    { id: "anthropic", name: "Anthropic", env: ["ANTHROPIC_API_KEY"] },
    { id: "deepseek", name: "DeepSeek", env: [] },
    { id: "github-copilot", name: "GitHub Copilot", env: [] },
    { id: "opencode", name: "OpenCode Zen", env: [] },
  ];
  const methods: Record<string, ProviderAuthMethod[]> = {
    deepseek: [{ type: "api", label: "API key" }],
    "github-copilot": [{ type: "oauth", label: "Sign in" }],
    opencode: [{ type: "oauth", label: "Sign in" }],
  };

  it("offers key-based providers and the built-in keyless one, and leaves OAuth-only ones to Settings", () => {
    const choices = providerChoices(catalog, methods, ["opencode"]);
    expect(choices.map((c) => c.id)).toEqual(["opencode", "deepseek", "anthropic"]);
    expect(choices.find((c) => c.id === "opencode")?.needsKey).toBe(false);
    expect(choices.find((c) => c.id === "deepseek")?.needsKey).toBe(true);
    expect(choices.some((c) => c.id === "github-copilot")).toBe(false);
  });

  it("does not invent the built-in provider when the runtime does not serve it", () => {
    const choices = providerChoices(catalog, methods, []);
    expect(choices.some((c) => c.id === "opencode")).toBe(false);
  });

  it("puts the models people arrive with first, then sorts by name", () => {
    const ranked = rankProviders([
      { id: "zeta", name: "Zeta", needsKey: true },
      { id: "openai", name: "OpenAI", needsKey: true },
      { id: "alpha", name: "Alpha", needsKey: true },
      { id: "deepseek", name: "DeepSeek", needsKey: true },
    ]);
    expect(ranked.map((c) => c.id)).toEqual(["deepseek", "openai", "alpha", "zeta"]);
  });

  it("filters by id or display name", () => {
    const choices = providerChoices(catalog, methods, ["opencode"]);
    expect(filterProviders(choices, "deep").map((c) => c.id)).toEqual(["deepseek"]);
    expect(filterProviders(choices, "ANTHRO").map((c) => c.id)).toEqual(["anthropic"]);
    expect(filterProviders(choices, "  ")).toHaveLength(choices.length);
    expect(filterProviders(choices, "nope")).toEqual([]);
  });
});

describe("model choices", () => {
  const providers: ProviderInfo[] = [
    {
      id: "deepseek",
      name: "DeepSeek",
      models: [
        { id: "deepseek-chat", name: "DeepSeek Chat", free: true },
        { id: "retired", name: "Retired", available: false },
      ],
    },
  ];

  it("offers only models the provider still serves, keyed the way the runtime wants", () => {
    expect(modelChoicesFor(providers, "deepseek")).toEqual([
      { key: "deepseek/deepseek-chat", modelID: "deepseek-chat", modelName: "DeepSeek Chat", free: true },
    ]);
  });

  it("returns nothing for a provider that is not there", () => {
    expect(modelChoicesFor(providers, "anthropic")).toEqual([]);
  });
});

describe("the 30-second test", () => {
  it("asks in the user's language", () => {
    expect(examplePrompt("zh-Hans")).toMatch(/30 秒/);
    expect(examplePrompt("zh-CN")).toMatch(/30 秒/);
    expect(examplePrompt("en")).toMatch(/30-second/);
    expect(examplePrompt("de")).toMatch(/30-second/); // no authored German text
  });

  it("reads the turn's own markers, not a guessed state", () => {
    const waiting = exampleOutcome(thread(), false);
    expect(waiting.phase).toBe("waiting");

    const streaming = exampleOutcome(
      thread({ kind: "user", text: "hi" }, { kind: "agent", markdown: "Hello" }),
      true,
    );
    expect(streaming).toMatchObject({ phase: "running", text: "Hello" });

    const done = exampleOutcome(
      thread(
        { kind: "user", text: "hi" },
        { kind: "agent", markdown: "Hello" },
        { kind: "status-line", text: "done", tone: "done" },
      ),
      false,
    );
    expect(done).toMatchObject({ phase: "done", text: "Hello" });

    // A failed POST leaves the runtime's own line; the wizard shows that
    // sentence rather than a generic "something went wrong".
    const failed = exampleOutcome(
      thread({ kind: "user", text: "hi" }, {
        kind: "status-line",
        text: "Send failed: Provider not found",
        tone: "error",
      }),
      false,
    );
    expect(failed).toMatchObject({ phase: "failed", error: "Provider not found" });
  });

  it("treats a retry the account cannot clear as a failure, not as waiting", () => {
    // Measured on a fresh install: the built-in provider's free quota was used
    // up, so the runtime emitted session.retry forever and the test sat at
    // "waiting" until the 30-second hint. The cause is final, not transient.
    const limited = exampleOutcome(thread({ kind: "user", text: "hi" }), true, {
      message: "Retrying…",
      action: { reason: "free_tier_limit", message: "Free usage exceeded" },
    });
    expect(limited).toMatchObject({ phase: "failed", error: "Free usage exceeded" });

    // Any other retry is the runtime's own business and can still succeed.
    const transient = exampleOutcome(thread(), true, {
      message: "Retrying in 4 s",
      action: { reason: "rate_limit" },
    });
    expect(transient.phase).toBe("running");
  });

  it("keeps a done marker from a previous attempt from reading as this one's answer", () => {
    // session.idle never follows an error, but the reverse fold is what the
    // runtime itself protects (#114); a done line before any answer is not a
    // finished test.
    const marked = exampleOutcome(thread({ kind: "status-line", text: "done", tone: "done" }), false);
    expect(marked.phase).toBe("waiting");
  });
});