// The first-run setup wizard's decisions and its one side effect.
//
// Kept out of the component so the parts worth testing are pure: which
// providers the wizard may offer, which models follow a provider, and how a
// test turn's thread reads as waiting / running / done / failed. The one
// side effect — sending the 30-second test message — is here too, because it
// has to go through the app's normal send path (a draft's first send creates
// the session, its folder and its running lock) rather than a hand-rolled
// POST that would leave no conversation behind.
//
// P0-3: pick a provider, paste its key, choose the default model, run one
// short turn. The key never touches the config file: the caller stores it in
// the OS credential store through `storeProviderKey` and writes only the
// `{env:…}` reference.
import type { ProviderAuthMethod, ProviderCatalogEntry, ProviderInfo } from "@ai4s/sdk";
import type { Thread } from "./runtime";
import { useRuntimeStore } from "./runtime";
import { customProviderId } from "./customProviderId";

/** localStorage marker: the wizard was completed. It no longer suppresses the
 *  wizard — the provider list does that — so a skipped setup still returns. */
export const ONBOARDING_DONE_KEY = "ai4s.onboarding.v1";

export function hasCompletedOnboarding(): boolean {
  try {
    return window.localStorage.getItem(ONBOARDING_DONE_KEY) === "1";
  } catch {
    // No storage (a locked-down webview): never trap the user in a dialog that
    // cannot remember being dismissed. Settings still offers both settings.
    return true;
  }
}

export function markOnboardingComplete(): void {
  try {
    window.localStorage.setItem(ONBOARDING_DONE_KEY, "1");
  } catch {
    // Best-effort: the wizard reappears next launch rather than failing.
  }
}

/**
 * Whether this install still needs the wizard. Deliberately narrow: an install
 * that already has a provider of its own (or a default model) has answered
 * these questions, so upgrading must not greet its owner with setup they did
 * years of work after. The built-in Zen provider does not count — it ships
 * with the runtime and is exactly what the wizard offers as the keyless path.
 */
export function offersOnboarding(providers: ProviderInfo[]): boolean {
  // The built-in provider is dropped before this list reaches the store, so any
  // provider left is one the user configured. An empty list means the app has
  // no usable model yet and must ask for the user's API.
  return providers.length === 0;
}

export interface ProviderChoice {
  id: string;
  name: string;
  /** False only for the built-in provider, which serves without credentials. */
  needsKey: boolean;
  /** A custom endpoint the user is adding in this wizard; its provider entry
   *  does not exist in the runtime config until the key step saves it. */
  custom?: CustomEndpointDraft;
}

/** What the wizard's custom-endpoint form collects. The id is derived from the
 *  name exactly as Settings does, so an endpoint added here and later seen
 *  there is the same provider. The key is deliberately absent: it goes into the
 *  OS credential store when the next step saves it, and the config only ever
 *  receives `{env:MEDAGENT_KEY_…}`. */
export interface CustomEndpointDraft {
  id: string;
  name: string;
  baseURL: string;
  /** The runtime's `npm` value — the API dialect, not a package of ours. */
  npm: string;
  /** Model ids, possibly empty until the endpoint is probed with the key. */
  models: string[];
  /** Context windows reported by the endpoint, keyed by model id. */
  contexts: Record<string, number>;
}

/** The two API dialects the custom-endpoint form offers (Settings → Agents). */
export const OPENAI_COMPATIBLE = "@ai-sdk/openai-compatible";
export const ANTHROPIC_COMPATIBLE = "@ai-sdk/anthropic";

/** Model ids typed into one field: commas (half- or full-width) and newlines
 *  separate them; blanks and duplicates are dropped, order is kept. */
export function parseModelIds(text: string): string[] {
  const ids: string[] = [];
  for (const part of text.split(/[,，\n\r]+/)) {
    const id = part.trim();
    if (id && !ids.includes(id)) ids.push(id);
  }
  return ids;
}

/** The draft for the custom-endpoint form, or null when it cannot describe a
 *  provider: a blank name has no id, and a base URL must be something the
 *  runtime can dial (http/https with a host). Models may be empty — they are
 *  filled in by probing with the key, or typed by the user. */
export function customEndpointDraft(input: {
  name: string;
  baseURL: string;
  npm: string;
  models: string;
  contexts?: Record<string, number>;
}): CustomEndpointDraft | null {
  const name = input.name.trim();
  const id = customProviderId(name);
  if (!id) return null;
  const baseURL = input.baseURL.trim();
  let url: URL;
  try {
    url = new URL(baseURL);
  } catch {
    return null;
  }
  if ((url.protocol !== "http:" && url.protocol !== "https:") || !url.hostname) return null;
  return {
    id,
    name,
    baseURL,
    npm: input.npm,
    models: parseModelIds(input.models),
    contexts: input.contexts ?? {},
  };
}

/** Which model-list dialect the endpoint probe asks for. */
export function probeKind(npm: string): "openai" | "anthropic" {
  return npm === ANTHROPIC_COMPATIBLE ? "anthropic" : "openai";
}

/** Providers worth offering in a first-run step: everything the runtime can
 *  authenticate with an API key. The built-in keyless provider is deliberately
 *  not offered: its free tier is not dependable, and first-run is for connecting
 *  the user's own model API. OAuth-only providers are left to Settings — a
 *  browser sign-in is not a first step. */
export function providerChoices(
  catalog: ProviderCatalogEntry[],
  authMethods: Record<string, ProviderAuthMethod[]>,
): ProviderChoice[] {
  const choices: ProviderChoice[] = [];
  for (const entry of catalog) {
    const methods = authMethods[entry.id] ?? [];
    const needsKey = methods.some((method) => method.type === "api") || entry.env.length > 0;
    if (!needsKey) continue;
    choices.push({ id: entry.id, name: entry.name, needsKey: true });
  }
  return rankProviders(choices);
}

/** The order a first-run list should open in: the models providers people
 *  usually arrive with, then everything else alphabetically. Names, not ids,
 *  decide the tail because that is what the list shows. */
const RECOMMENDED = [
  "deepseek",
  "anthropic",
  "openai",
  "google",
  "openrouter",
  "xai",
  "mistral",
];

export function rankProviders(choices: ProviderChoice[]): ProviderChoice[] {
  const rank = (id: string) => {
    const at = RECOMMENDED.indexOf(id);
    return at === -1 ? RECOMMENDED.length : at;
  };
  return [...choices].sort((a, b) => {
    const byRank = rank(a.id) - rank(b.id);
    if (byRank !== 0) return byRank;
    return a.name.localeCompare(b.name);
  });
}

/** Filter for the provider search box; matches id and display name. */
export function filterProviders(choices: ProviderChoice[], query: string): ProviderChoice[] {
  const q = query.trim().toLocaleLowerCase();
  if (!q) return choices;
  return choices.filter(
    (choice) =>
      choice.id.toLocaleLowerCase().includes(q) ||
      choice.name.toLocaleLowerCase().includes(q),
  );
}

export interface ModelChoice {
  /** `provider/model`, the form `setDefaultModel` takes. */
  key: string;
  modelID: string;
  modelName: string;
  free: boolean;
}

/** Models the wizard can offer for one provider — only what the runtime says is
 *  still served (`available !== false`); a retired model can only fail. */
export function modelChoicesFor(providers: ProviderInfo[], providerID: string): ModelChoice[] {
  const provider = providers.find((p) => p.id === providerID);
  if (!provider) return [];
  return provider.models
    .filter((model) => model.available !== false)
    .map((model) => ({
      key: `${provider.id}/${model.id}`,
      modelID: model.id,
      modelName: model.name,
      free: model.free === true,
    }));
}

/** The one prompt the 30-second test sends. Authored in Chinese and English
 *  like the workflow starters: a machine-translated research request is worse
 *  than an honest English one, and the answer language follows the model's own
 *  instruction-following, not this string. */
export function examplePrompt(language: string): string {
  return language.toLowerCase().startsWith("zh")
    ? "一个 30 秒的小测试：请用两三句话说明，在这个工作台里你能帮我做哪类医学科研工作，" +
        "并提醒我哪些结论必须由具备资质的研究者复核。不要使用工具，也不要创建文件。"
    : "A quick 30-second test: in two or three sentences, say what kinds of medical research " +
        "work you can help with in this workbench, and remind me which conclusions a qualified " +
        "researcher must review. Do not use tools and do not create files.";
}

export interface ExampleStart {
  /** The draft slot the send owns; the thread lives here until the session is
   *  created, then under `sessionId`. */
  draftKey: string;
  /** The created conversation, or null when the send failed before creating it. */
  sessionId: string | null;
}

let exampleSeq = 0;

/** Send the test message through the app's normal send path. A draft is used on
 *  purpose: its first send creates a dated workspace and a real session, so the
 *  test leaves a conversation the user can keep instead of a throwaway. The
 *  call resolves when the runtime has ACCEPTED the turn; completion is read
 *  from the thread by `exampleOutcome`. */
export async function startOnboardingExample(prompt: string): Promise<ExampleStart> {
  const draftKey = `onboarding-${Date.now().toString(36)}-${exampleSeq++}`;
  try {
    const sessionId = await useRuntimeStore.getState().sendPrompt(prompt, undefined, draftKey);
    return { draftKey, sessionId };
  } catch {
    // performTurn reports failures inside the thread rather than throwing; a
    // throw here means there is no client at all. Nothing was created.
    return { draftKey, sessionId: null };
  }
}

export type ExamplePhase = "waiting" | "running" | "done" | "failed";

/** Retry causes no number of attempts can clear — the account, not the call, is
 *  what failed (the same set SessionView reports as final; see #117). A free
 *  tier that is used up answers `session.retry` forever, so a test that only
 *  read thread blocks would sit at "waiting" until the 30-second hint. */
const LIMIT_REASONS = new Set(["free_tier_limit", "account_rate_limit"]);

/** The runtime's retry notice for the test's session (`retryNotices[sid]`). */
export interface ExampleRetry {
  message: string;
  action?: { reason: string; message?: string };
}

export interface ExampleOutcome {
  phase: ExamplePhase;
  /** The model's answer so far, markdown as streamed. */
  text: string;
  /** The failure line, without its English "Send failed:" prefix. */
  error: string | null;
}

/** Read a test turn out of its thread. `running` covers the window before the
 *  first status marker arrives; the markers themselves are authoritative, so a
 *  turn that failed cannot read as done (the runtime never emits `done` after
 *  an error — see the session.idle branch). A retry notice whose cause the
 *  account cannot fix (an exhausted free tier) is a failure too: it will never
 *  become an answer. */
export function exampleOutcome(
  thread: Thread | undefined,
  running: boolean,
  retry?: ExampleRetry,
): ExampleOutcome {
  const blocks = thread?.blocks ?? [];
  const lastAgent = [...blocks].reverse().find((block) => block.kind === "agent");
  const text = lastAgent?.kind === "agent" ? lastAgent.markdown : "";
  if (retry?.action && LIMIT_REASONS.has(retry.action.reason)) {
    return { phase: "failed", text, error: retry.action.message ?? retry.message };
  }
  for (let i = blocks.length - 1; i >= 0; i--) {
    const block = blocks[i];
    if (block.kind !== "status-line") continue;
    if (block.tone === "error") {
      return { phase: "failed", text, error: block.text.replace(/^Send failed:\s*/i, "") };
    }
    if (block.tone === "done" && lastAgent) {
      return { phase: "done", text, error: null };
    }
  }
  if (lastAgent) return { phase: "running", text, error: null };
  return { phase: running ? "running" : "waiting", text, error: null };
}