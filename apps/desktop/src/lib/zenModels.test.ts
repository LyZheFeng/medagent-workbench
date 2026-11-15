import { describe, expect, it, vi } from "vitest";
import type { OpenCodeClient, ProviderInfo } from "@ai4s/sdk";
import { listProvidersWithoutBuiltIn, ZEN_PROVIDER_ID } from "./zenModels";

const zen: ProviderInfo = {
  id: ZEN_PROVIDER_ID,
  name: "OpenCode Zen",
  models: [{ id: "beam-free", name: "Beam Free" }],
};

const mine: ProviderInfo = {
  id: "medagent-glm",
  name: "GLM",
  models: [{ id: "glm-5.3-flash", name: "GLM 5.3 Flash" }],
};

function clientReturning(providers: ProviderInfo[]) {
  return {
    listProviders: vi.fn(async () => providers),
  } as unknown as Pick<OpenCodeClient, "listProviders">;
}

describe("listProvidersWithoutBuiltIn", () => {
  it("drops the built-in provider and keeps the user's own", async () => {
    const result = await listProvidersWithoutBuiltIn(clientReturning([zen, mine]));
    expect(result.map((provider) => provider.id)).toEqual(["medagent-glm"]);
  });

  it("returns an empty list when the runtime reports only the built-in", async () => {
    expect(await listProvidersWithoutBuiltIn(clientReturning([zen]))).toEqual([]);
  });

  it("returns the provider list untouched when the built-in is absent", async () => {
    const result = await listProvidersWithoutBuiltIn(clientReturning([mine]));
    expect(result).toEqual([mine]);
  });
});