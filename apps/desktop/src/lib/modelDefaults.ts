/**
 * Context window assumed for a model the user adds without one.
 *
 * Adding an endpoint by hand usually means the provider does not report a
 * context window (or the user did not probe it). The old fallback was the
 * SDK's 128k, which silently truncated long clinical documents; 500k matches
 * the long-context models this workbench is used with. A probed value always
 * wins, and the form field stays editable.
 */
export const DEFAULT_CONTEXT_WINDOW = 500_000;