const BEGIN_RENDERING_PATTERNS = [
  /"beginRendering"\s*:/,
  /"begin_rendering"\s*:/,
  /"type"\s*:\s*"beginRendering"/,
  /"type"\s*:\s*"begin_rendering"/,
];

const SURFACE_UPDATE_PATTERN =
  /"surfaceUpdate"\s*:|"surface_update"\s*:|"type"\s*:\s*"surfaceUpdate"|"type"\s*:\s*"surface_update"/;
const DATA_MODEL_UPDATE_PATTERN =
  /"dataModelUpdate"\s*:|"data_model_update"\s*:|"type"\s*:\s*"dataModelUpdate"|"type"\s*:\s*"data_model_update"/;

/**
 * Merge A2UI incremental update payloads into the prior message stream.
 *
 * Some canvas_update events only contain surfaceUpdate diffs (without beginRendering).
 * Replacing content with such diffs drops the root definition and causes renderer fallback.
 */
export function mergeA2UIMessageStream(
  previousMessages: string | undefined,
  incomingMessages: string
): string {
  if (!incomingMessages) return previousMessages ?? '';
  if (!previousMessages) return incomingMessages;

  const hasBeginRendering = BEGIN_RENDERING_PATTERNS.some((pattern) =>
    pattern.test(incomingMessages)
  );
  const hasIncrementalUpdate =
    SURFACE_UPDATE_PATTERN.test(incomingMessages) ||
    DATA_MODEL_UPDATE_PATTERN.test(incomingMessages);
  if (hasBeginRendering || !hasIncrementalUpdate) {
    return incomingMessages;
  }

  return previousMessages.endsWith('\n')
    ? `${previousMessages}${incomingMessages}`
    : `${previousMessages}\n${incomingMessages}`;
}
