import { useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import { ArrowLeft, Check, ChevronRight, KeyRound, Loader2, Search } from "lucide-react";
import type { ProviderAuthMethod, ProviderCatalogEntry } from "@ai4s/sdk";
import { getClient, useRuntimeStore } from "@/lib/runtime";
import { restartRuntime, isTauri, storeProviderKey } from "@/lib/tauri";
import { DEFAULT_PROJECT, useLayoutStore } from "@/lib/layout";
import {
  exampleOutcome,
  examplePrompt,
  filterProviders,
  hasCompletedOnboarding,
  markOnboardingComplete,
  modelChoicesFor,
  offersOnboarding,
  providerChoices,
  startOnboardingExample,
  type ExampleStart,
  type ModelChoice,
  type ProviderChoice,
} from "@/lib/onboarding";
import { cn } from "@/lib/cn";
import { inputCls } from "@/components/settings/inputCls";
import { isGatewayWeb } from "@/lib/webMode";
import { ZEN_PROVIDER_ID } from "@/lib/zenModels";

type Step = "provider" | "key" | "model" | "example";

/** The wizard is an on-ramp, not a surface: it runs once (per install) and its
 *  answers stay editable in Settings → Agents. Ordering with the compliance
 *  notice is decided by `FirstRun`: the legal statement is acknowledged first,
 *  and this dialog never renders on top of it. */
export function OnboardingWizard({
  desktop = isTauri,
  web = isGatewayWeb,
}: {
  desktop?: boolean;
  web?: boolean;
} = {}) {
  const { t, i18n } = useTranslation(["settings", "common"]);
  const navigate = useNavigate();
  // null = still deciding; false = stay away. Rendering nothing until the
  // runtime is up avoids a flash of setup on an install that already has one.
  const [offer, setOffer] = useState<boolean | null>(null);
  const decided = useRef(false);
  const status = useRuntimeStore((s) => s.status);
  const providers = useRuntimeStore((s) => s.providers);

  const [catalog, setCatalog] = useState<ProviderCatalogEntry[]>([]);
  const [authMethods, setAuthMethods] = useState<Record<string, ProviderAuthMethod[]>>({});
  const [loadError, setLoadError] = useState<string | null>(null);
  const [loadingCatalog, setLoadingCatalog] = useState(false);

  const [step, setStep] = useState<Step>("provider");
  const [selected, setSelected] = useState<ProviderChoice | null>(null);
  const [query, setQuery] = useState("");

  const [keyInput, setKeyInput] = useState("");
  const [keyBusy, setKeyBusy] = useState(false);
  const [keyError, setKeyError] = useState<string | null>(null);
  const [keyStored, setKeyStored] = useState(false);

  const [modelBusy, setModelBusy] = useState(false);
  const [modelError, setModelError] = useState<string | null>(null);

  const [example, setExample] = useState<ExampleStart | null>(null);
  const [exampleBusy, setExampleBusy] = useState(false);
  const [exampleError, setExampleError] = useState<string | null>(null);
  const [seconds, setSeconds] = useState(0);
  const [keepWaiting, setKeepWaiting] = useState(false);
  const [firstToken, setFirstToken] = useState<number | null>(null);
  const startedAt = useRef<number | null>(null);
  const firstTokenSeen = useRef(false);

  const refreshCatalog = async () => {
    setLoadingCatalog(true);
    setLoadError(null);
    try {
      const client = getClient();
      if (!client) throw new Error(t("onboarding.connectFailed", { message: "no client" }));
      // The provider catalog decides which providers need a key; providers the
      // runtime already serves decide the built-in keyless option.
      const [list, methods] = await Promise.all([
        client.listProviderCatalog(),
        client.listAuthMethods(),
      ]);
      setCatalog(list.all);
      setAuthMethods(methods);
    } catch (e) {
      setLoadError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoadingCatalog(false);
    }
  };

  // Decide once per app run, after the bundled runtime answers: an existing
  // install has providers/default model and must never see this.
  useEffect(() => {
    if (decided.current) return;
    if (!desktop || web || hasCompletedOnboarding()) {
      decided.current = true;
      setOffer(false);
      return;
    }
    if (status !== "ready") return; // bootstrap is still starting the sidecar
    decided.current = true;
    let cancelled = false;
    void (async () => {
      const runtime = useRuntimeStore.getState();
      await runtime.loadCatalog().catch(() => undefined);
      if (cancelled) return;
      const fresh = useRuntimeStore.getState();
      if (!offersOnboarding(fresh.providers, fresh.defaultModel)) {
        setOffer(false);
        return;
      }
      await refreshCatalog();
      if (cancelled) return;
      setOffer(true);
    })();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- one decision per run
  }, [desktop, web, status]);

  const choices = useMemo(
    () => providerChoices(catalog, authMethods, providers.map((p) => p.id)),
    [catalog, authMethods, providers],
  );
  const shownChoices = useMemo(() => filterProviders(choices, query), [choices, query]);

  // The stepper follows the flow: the keyless built-in has no key step.
  const flow: Step[] = selected && !selected.needsKey
    ? ["provider", "model", "example"]
    : ["provider", "key", "model", "example"];
  const activeIndex = Math.max(0, flow.indexOf(step));

  const models: ModelChoice[] = useMemo(
    () => (selected ? modelChoicesFor(providers, selected.id) : []),
    [providers, selected],
  );

  const thread = useRuntimeStore((s) =>
    example ? (example.sessionId ? s.threads[example.sessionId] : s.threads[example.draftKey]) : undefined,
  );
  const running = useRuntimeStore((s) =>
    example?.sessionId ? Boolean(s.runningSessions[example.sessionId]) : false,
  );
  // A used-up free tier (or account rate limit) never becomes an answer: the
  // runtime keeps emitting session.retry, and without reading that notice this
  // step would say "waiting" until the 30-second hint — measured on a fresh
  // install whose built-in provider had no free quota left.
  const retry = useRuntimeStore((s) =>
    example?.sessionId ? s.retryNotices[example.sessionId] : undefined,
  );
  const outcome = exampleOutcome(thread, running, retry);

  // The 30-second budget is an expectation, not a timeout: past it the step
  // says so and lets the user keep waiting or skip. A cold provider can take a
  // minute, and killing a working turn would be the wrong lesson to teach.
  useEffect(() => {
    if (!example || outcome.phase === "done" || outcome.phase === "failed") return;
    const id = setInterval(() => {
      if (startedAt.current) setSeconds(Math.round((Date.now() - startedAt.current) / 1000));
    }, 500);
    return () => clearInterval(id);
  }, [example, outcome.phase]);

  useEffect(() => {
    if (firstTokenSeen.current || !outcome.text) return;
    firstTokenSeen.current = true;
    setFirstToken(seconds);
  }, [outcome.text, seconds]);

  if (offer !== true) return null;

  const close = (interrupt = false) => {
    markOnboardingComplete();
    if (interrupt && example?.sessionId)
      void useRuntimeStore.getState().interrupt(example.sessionId);
    setOffer(false);
  };

  const finish = () => {
    markOnboardingComplete();
    const sessionId = example?.sessionId ?? null;
    setOffer(false);
    if (!sessionId) return;
    // Keep the test conversation instead of throwing it away: the first thing
    // the user sees after setup is a real answer in a real session.
    useLayoutStore.getState().openInNewGroup(sessionId, DEFAULT_PROJECT);
    void useRuntimeStore.getState().openSession(sessionId);
  };

  const openSettings = () => {
    markOnboardingComplete();
    setOffer(false);
    navigate("/settings/agents");
  };

  const chooseProvider = (choice: ProviderChoice) => {
    setSelected(choice);
    setKeyInput("");
    setKeyError(null);
    setKeyStored(false);
    setModelError(null);
    setStep(choice.needsKey ? "key" : "model");
  };

  const saveKey = async () => {
    if (!selected) return;
    setKeyBusy(true);
    setKeyError(null);
    try {
      // Same order as Settings: the credential store first, the reference
      // second. `options.apiKey` beats OpenCode's own auth store, so the
      // reference is what takes effect; the plaintext entry the old flow left
      // in the runtime's auth file is removed, not left beside it. The key
      // never enters the config file.
      const envVar = await storeProviderKey(selected.id, keyInput.trim());
      const client = getClient();
      if (!client) throw new Error(t("onboarding.connectFailed", { message: "no client" }));
      await client.setProviderApiKeyRef(selected.id, `{env:${envVar}}`);
      await client.removeProviderAuth(selected.id).catch(() => undefined);
      // The variable reaches the sidecar only when it is spawned again.
      await restartRuntime();
      await useRuntimeStore.getState().connectRetry();
      await useRuntimeStore.getState().loadCatalog().catch(() => undefined);
      if (modelChoicesFor(useRuntimeStore.getState().providers, selected.id).length === 0) {
        setKeyError(t("onboarding.noModels"));
        return;
      }
      setKeyInput("");
      setKeyStored(true);
      setStep("model");
    } catch (e) {
      // The store refused the key: no config was touched, so nothing is
      // half-written and the message can be acted on as it stands.
      setKeyError(t("onboarding.keyFailed", { message: e instanceof Error ? e.message : String(e) }));
    } finally {
      setKeyBusy(false);
    }
  };

  const chooseModel = async (model: ModelChoice) => {
    setModelBusy(true);
    setModelError(null);
    try {
      await useRuntimeStore.getState().setDefaultModel(model.key);
      setStep("example");
    } catch (e) {
      setModelError(
        t("onboarding.modelFailed", { message: e instanceof Error ? e.message : String(e) }),
      );
    } finally {
      setModelBusy(false);
    }
  };

  const runTest = async () => {
    setExampleBusy(true);
    setExampleError(null);
    setKeepWaiting(false);
    setFirstToken(null);
    firstTokenSeen.current = false;
    setSeconds(0);
    startedAt.current = Date.now();
    try {
      setExample(await startOnboardingExample(examplePrompt(i18n.language)));
    } catch (e) {
      setExampleError(
        t("onboarding.exampleFailed", { message: e instanceof Error ? e.message : String(e) }),
      );
    } finally {
      setExampleBusy(false);
    }
  };

  const back = () => {
    setModelError(null);
    setKeyError(null);
    if (step === "key") setStep("provider");
    else if (step === "model") setStep(selected?.needsKey ? "key" : "provider");
    else if (step === "example") {
      if (example?.sessionId) void useRuntimeStore.getState().interrupt(example.sessionId);
      setExample(null);
      setStep("model");
    }
  };

  const slow = seconds >= 30 && !keepWaiting && outcome.phase !== "done" && outcome.phase !== "failed";
  const testStarted = example !== null || exampleBusy;

  return (
    <div className="fixed inset-0 z-[60] flex items-center justify-center bg-black/40 p-4" role="presentation">
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="onboarding-title"
        className="flex max-h-[86vh] w-[560px] max-w-full flex-col rounded-card border border-border bg-surface shadow-card"
      >
        <div className="shrink-0 px-5 pt-5">
          <div className="text-[11px] font-semibold uppercase tracking-wide text-accent">
            {t("onboarding.eyebrow")}
          </div>
          <h2 id="onboarding-title" className="mt-1 font-serif text-xl text-text">
            {t("onboarding.title")}
          </h2>
          <p className="mt-1.5 text-[12.5px] leading-relaxed text-muted">{t("onboarding.intro")}</p>

          <ol className="mt-4 flex items-center gap-1.5" aria-label={t("onboarding.eyebrow")}>
            {flow.map((name, index) => (
              <li key={name} className="flex items-center gap-1.5">
                {index > 0 && <ChevronRight size={12} className="text-faint" />}
                <span
                  className={cn(
                    "rounded-full px-2 py-0.5 text-[11px]",
                    index === activeIndex
                      ? "bg-accent/15 font-medium text-accent"
                      : index < activeIndex
                        ? "text-muted"
                        : "text-muted/60",
                  )}
                >
                  {t(`onboarding.steps.${name}`)}
                </span>
              </li>
            ))}
          </ol>
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4">
          {step === "provider" && (
            <div className="space-y-2">
              {loadingCatalog && (
                <div className="flex items-center gap-2 py-6 text-[13px] text-muted">
                  <Loader2 size={14} className="animate-spin" /> {t("onboarding.connecting")}
                </div>
              )}
              {loadError && (
                <div className="space-y-2 py-2">
                  <p className="text-[13px] text-error">{loadError}</p>
                  <button className="text-[13px] text-accent underline" onClick={() => void refreshCatalog()}>
                    {t("onboarding.retry")}
                  </button>
                </div>
              )}
              {!loadingCatalog && !loadError && (
                <>
                  <div className="relative">
                    <Search
                      size={13}
                      className="pointer-events-none absolute left-3 top-1/2 -mt-[6.5px] text-muted"
                    />
                    <input
                      value={query}
                      onChange={(e) => setQuery(e.target.value)}
                      placeholder={t("onboarding.searchProviders")}
                      className={inputCls("w-full pl-8")}
                      aria-label={t("onboarding.searchProviders")}
                    />
                  </div>
                  {shownChoices.length === 0 ? (
                    <p className="py-3 text-[13px] text-muted">{t("onboarding.providerNote")}</p>
                  ) : (
                    <ul className="max-h-[280px] overflow-y-auto rounded-input border border-faint">
                      {shownChoices.map((choice) => (
                        <li key={choice.id}>
                          <button
                            type="button"
                            onClick={() => chooseProvider(choice)}
                            className="flex w-full items-center gap-2 border-t border-faint px-3 py-2 text-left text-[13px] first:border-t-0 hover:bg-surface-2"
                          >
                            <span className="font-medium text-text">{choice.name}</span>
                            <span className="font-mono text-[11px] text-muted">{choice.id}</span>
                            <span className="flex-1" />
                            {choice.needsKey ? (
                              <KeyRound size={12} className="text-muted" />
                            ) : (
                              <span className="rounded-full bg-surface-2 px-2 py-0.5 text-[10px] text-muted ring-1 ring-border">
                                {t("onboarding.noKeyNeeded")}
                              </span>
                            )}
                            <ChevronRight size={13} className="text-muted/60" />
                          </button>
                        </li>
                      ))}
                    </ul>
                  )}
                  <p className="pt-1 text-[11.5px] leading-relaxed text-muted">
                    {t("onboarding.providerNote")}
                  </p>
                </>
              )}
            </div>
          )}

          {step === "key" && selected && (
            <div className="space-y-3">
              <h3 className="text-[14px] font-medium text-text">
                {t("onboarding.keyTitle", { provider: selected.name })}
              </h3>
              <input
                type="password"
                value={keyInput}
                onChange={(e) => setKeyInput(e.target.value)}
                placeholder={t("onboarding.keyPlaceholder")}
                aria-label={t("onboarding.keyTitle", { provider: selected.name })}
                className={inputCls("w-full font-mono")}
                autoComplete="off"
                spellCheck={false}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && keyInput.trim() && !keyBusy) void saveKey();
                }}
              />
              <p className="text-[12px] leading-relaxed text-muted">{t("onboarding.keyHint")}</p>
              {keyError && <p className="text-[12.5px] leading-relaxed text-error">{keyError}</p>}
            </div>
          )}

          {step === "model" && selected && (
            <div className="space-y-2">
              <h3 className="text-[14px] font-medium text-text">{t("onboarding.modelTitle")}</h3>
              <p className="text-[12px] leading-relaxed text-muted">{t("onboarding.modelHint")}</p>
              {keyStored && selected.needsKey && (
                <p className="flex items-center gap-1.5 text-[12px] text-ok">
                  <Check size={12} /> {t("onboarding.keySaved")}
                </p>
              )}
              {modelError && <p className="text-[12.5px] leading-relaxed text-error">{modelError}</p>}
              {models.length === 0 ? (
                <div className="space-y-2 py-2">
                  <p className="text-[13px] leading-relaxed text-muted">{t("onboarding.noModels")}</p>
                  <button
                    className="text-[13px] text-accent underline"
                    onClick={() => {
                      void useRuntimeStore
                        .getState()
                        .loadCatalog()
                        .catch(() => undefined);
                    }}
                  >
                    {t("onboarding.retry")}
                  </button>
                </div>
              ) : (
                <ul className="max-h-[280px] overflow-y-auto rounded-input border border-faint">
                  {models.map((model) => (
                    <li key={model.key}>
                      <button
                        type="button"
                        disabled={modelBusy}
                        onClick={() => void chooseModel(model)}
                        className="flex w-full items-center gap-2 border-t border-faint px-3 py-2 text-left text-[13px] first:border-t-0 hover:bg-surface-2 disabled:opacity-60"
                      >
                        <span className="font-medium text-text">{model.modelName}</span>
                        {model.modelName !== model.modelID && (
                          <span className="font-mono text-[11px] text-muted">{model.modelID}</span>
                        )}
                        <span className="flex-1" />
                        {model.free && selected.id === ZEN_PROVIDER_ID && (
                          <span className="rounded-full bg-ok/15 px-2 py-0.5 text-[10px] text-ok">
                            {t("providers.builtInFree")}
                          </span>
                        )}
                        <ChevronRight size={13} className="text-muted/60" />
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          )}

          {step === "example" && (
            <div className="space-y-3">
              <h3 className="text-[14px] font-medium text-text">{t("onboarding.exampleTitle")}</h3>
              <p className="text-[12px] leading-relaxed text-muted">{t("onboarding.exampleHint")}</p>
              <p className="rounded-input bg-surface-2 px-3 py-2 text-[12px] leading-relaxed text-muted">
                {examplePrompt(i18n.language)}
              </p>

              {!testStarted && (
                <button
                  type="button"
                  onClick={() => void runTest()}
                  className="inline-flex items-center gap-2 rounded-input bg-accent px-4 py-2 text-[13px] font-medium text-white transition-opacity hover:opacity-90"
                >
                  {t("onboarding.exampleRun")}
                </button>
              )}

              {testStarted && (
                <div className="space-y-2 rounded-input border border-faint p-3">
                  <div className="flex items-center gap-2 text-[12px] text-muted">
                    {outcome.phase === "done" ? (
                      <Check size={13} className="text-ok" />
                    ) : outcome.phase === "failed" ? null : (
                      <Loader2 size={13} className="shrink-0 animate-spin" />
                    )}
                    <span>
                      {exampleBusy
                        ? t("onboarding.exampleWaiting")
                        : outcome.phase === "done"
                          ? t("onboarding.exampleDone", { seconds })
                          : outcome.phase === "failed"
                            ? t("onboarding.exampleFailed", { message: outcome.error ?? "" })
                            : `${t("onboarding.exampleWaiting")} ${seconds}s`}
                    </span>
                    {firstToken !== null && outcome.phase !== "failed" && (
                      <span className="text-muted/70">
                        · {t("onboarding.exampleFirstToken", { seconds: firstToken })}
                      </span>
                    )}
                  </div>

                  {outcome.text && (
                    <pre className="max-h-40 overflow-y-auto whitespace-pre-wrap break-words rounded bg-surface-2/60 p-2 font-sans text-[12.5px] leading-relaxed text-text">
                      {outcome.text}
                    </pre>
                  )}

                  {slow && (
                    <div className="flex flex-wrap items-center gap-3 text-[11.5px] text-muted">
                      <span>{t("onboarding.exampleSlow")}</span>
                      <button className="underline" onClick={() => setKeepWaiting(true)}>
                        {t("onboarding.exampleKeepWaiting")}
                      </button>
                      <button className="underline" onClick={() => close(true)}>
                        {t("onboarding.exampleSkip")}
                      </button>
                    </div>
                  )}

                  {outcome.phase === "failed" && (
                    <div className="flex flex-wrap items-center gap-3 pt-1">
                      <button
                        className="rounded-input bg-surface-2 px-3 py-1.5 text-[12.5px] text-text hover:bg-border/50"
                        onClick={() => void runTest()}
                      >
                        {t("onboarding.exampleRetry")}
                      </button>
                      <button
                        className="text-[12.5px] text-accent underline"
                        onClick={() => {
                          if (example?.sessionId)
                            void useRuntimeStore.getState().interrupt(example.sessionId);
                          setExample(null);
                          setStep(selected?.needsKey ? "key" : "provider");
                        }}
                      >
                        {t(selected?.needsKey ? "onboarding.exampleBackToKey" : "onboarding.exampleChangeProvider")}
                      </button>
                    </div>
                  )}
                </div>
              )}

              {exampleError && <p className="text-[12.5px] text-error">{exampleError}</p>}

              {/* Only a key-based provider stored something: the built-in one
                  has no credential, so the statement would describe nothing. */}
              {selected?.needsKey && <CredentialNote />}
            </div>
          )}
        </div>

        <div className="flex shrink-0 flex-wrap items-center gap-2 border-t border-faint px-5 py-3">
          {step !== "provider" && (
            <button
              type="button"
              onClick={back}
              className="inline-flex items-center gap-1 text-[13px] text-muted hover:text-text"
            >
              <ArrowLeft size={13} /> {t("onboarding.back")}
            </button>
          )}
          <button
            type="button"
            onClick={() => close(true)}
            className="text-[13px] text-muted hover:text-text"
          >
            {t("onboarding.later")}
          </button>
          <span className="flex-1" />
          {step === "key" && (
            <button
              type="button"
              onClick={() => void saveKey()}
              disabled={keyBusy || !keyInput.trim()}
              className="inline-flex items-center gap-1.5 rounded-input bg-accent px-4 py-2 text-[13px] font-medium text-white transition-opacity hover:opacity-90 disabled:cursor-default disabled:opacity-50"
            >
              {keyBusy ? <Loader2 size={13} className="animate-spin" /> : <KeyRound size={13} />}
              {t("onboarding.keySave")}
            </button>
          )}
          {step === "example" && outcome.phase === "done" && (
            <>
              <button
                type="button"
                onClick={openSettings}
                className="text-[13px] text-muted hover:text-text"
              >
                {t("onboarding.openSettings")}
              </button>
              <button
                type="button"
                onClick={finish}
                className="rounded-input bg-accent px-4 py-2 text-[13px] font-medium text-white hover:opacity-90"
              >
                {t("onboarding.finish")}
              </button>
            </>
          )}
          {step === "example" && outcome.phase !== "done" && testStarted && (
            <button
              type="button"
              onClick={() => close(true)}
              className="rounded-input bg-surface-2 px-4 py-2 text-[13px] text-text hover:bg-border/50"
            >
              {t("onboarding.exampleSkip")}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

/** The "where the key went" statement, rendered from the same translation the
 *  privacy card uses — the wizard must not be able to describe the placement
 *  differently from Settings. */
function CredentialNote() {
  const { t } = useTranslation("settings");
  return (
    <div className="rounded-input border border-faint p-3">
      <div className="text-[11px] font-semibold uppercase tracking-wide text-muted">
        {t("onboarding.credentialsTitle")}
      </div>
      <p className="mt-1 text-[12px] leading-relaxed text-muted">
        {t("dataFlow.local.providerKeys")}
      </p>
    </div>
  );
}