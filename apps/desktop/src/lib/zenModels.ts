// The built-in OpenCode Zen provider is not part of this product.
//
// Zen is the runtime's free gateway. Its free tier is not dependable (retired
// models answer 401, and the rest are quota/region limited), so a medical
// workbench must not present it as a model choice at all. The runtime still
// reports it — OpenCode carries the provider — and the one place that turns
// `/config/providers` into the app's provider list drops it here. Everything
// downstream (first-run wizard, Settings, the composer's model picker) therefore
// sees only providers the user actually configured.

import type { OpenCodeClient, ProviderInfo } from "@ai4s/sdk";

/** Provider id of OpenCode Zen — its models.dev key, and what the runtime reports. */
export const ZEN_PROVIDER_ID = "opencode";

/**
 * `listProviders`, without the built-in Zen provider.
 *
 * Use this everywhere the result reaches the UI. The raw client call stays
 * available for diagnostics, but no screen offers a model the app will not
 * support.
 */
export async function listProvidersWithoutBuiltIn(
  client: Pick<OpenCodeClient, "listProviders">,
): Promise<ProviderInfo[]> {
  const providers = await client.listProviders();
  return providers.filter((provider) => provider.id !== ZEN_PROVIDER_ID);
}