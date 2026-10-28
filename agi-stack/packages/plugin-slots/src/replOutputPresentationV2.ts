/** Structured REPL output only; selection is made by the declared tool contract. */
export type ToolResultMediaStoreV2 = "device" | "conversation_tool_media";
export type ReplMediaReferenceV2 = Readonly<{
  store: ToolResultMediaStoreV2;
  kind: "image" | "audio";
  artifactId: string;
  mimeType: string;
  sizeBytes: number;
}>;
export type ReplOutputEntryV2 =
  | Readonly<{ kind: "text"; text: string }>
  | ReplMediaReferenceV2
  | Readonly<{ kind: "unavailable"; reason: "media_size_limit" }>;
export type ReplOutputPresentationV2 = Readonly<{
  kind: "repl_output";
  entries: readonly ReplOutputEntryV2[];
}>;
export type ToolResultMediaV2 = Readonly<{
  store: ToolResultMediaStoreV2;
  artifactId: string;
  mimeType: string;
  bytes: Uint8Array;
}>;

const MAX_ENTRIES = 256;
const MAX_TEXT = 32768;
const MAX_MEDIA = 10 * 1024 * 1024;
const MAX_CELL_MEDIA = 32 * 1024 * 1024;
const imageTypes = new Set(["image/png", "image/jpeg", "image/webp"]);
const audioTypes = new Set([
  "audio/wav",
  "audio/x-wav",
  "audio/mpeg",
  "audio/ogg",
]);
function record(value: unknown): Record<string, unknown> | null {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}
function media(value: unknown): ReplMediaReferenceV2 | null {
  const item = record(value);
  if (
    !item ||
    (item.store !== "device" && item.store !== "conversation_tool_media") ||
    (item.kind !== "image" && item.kind !== "audio") ||
    typeof item.artifactId !== "string" ||
    !/^[a-zA-Z0-9][a-zA-Z0-9_-]{0,255}$/u.test(item.artifactId) ||
    typeof item.mimeType !== "string" ||
    !(item.kind === "image" ? imageTypes : audioTypes).has(item.mimeType) ||
    typeof item.sizeBytes !== "number" ||
    !Number.isSafeInteger(item.sizeBytes) ||
    item.sizeBytes < 1
  )
    return null;
  return Object.freeze({
    store: item.store,
    kind: item.kind,
    artifactId: item.artifactId,
    mimeType: item.mimeType,
    sizeBytes: item.sizeBytes,
  });
}
export function validateReplOutputPresentationV2(
  value: unknown,
): ReplOutputPresentationV2 | null {
  const source = record(value);
  if (
    source?.kind !== "repl_output" ||
    !Array.isArray(source.entries) ||
    source.entries.length > MAX_ENTRIES
  )
    return null;
  const entries: ReplOutputEntryV2[] = [];
  let textBudget = MAX_TEXT;
  let mediaBytes = 0;
  for (const input of source.entries) {
    const item = record(input);
    if (item?.kind === "text" && typeof item.text === "string") {
      const text = item.text.slice(0, textBudget);
      textBudget -= text.length;
      entries.push(Object.freeze({ kind: "text", text }));
    } else if (
      item?.kind === "unavailable" &&
      item.reason === "media_size_limit"
    ) {
      entries.push(
        Object.freeze({ kind: "unavailable", reason: "media_size_limit" }),
      );
    } else {
      const reference = media(item);
      if (!reference) return null;
      if (
        reference.sizeBytes > MAX_MEDIA ||
        mediaBytes + reference.sizeBytes > MAX_CELL_MEDIA
      ) {
        entries.push(
          Object.freeze({ kind: "unavailable", reason: "media_size_limit" }),
        );
      } else {
        mediaBytes += reference.sizeBytes;
        entries.push(reference);
      }
    }
  }
  return Object.freeze({
    kind: "repl_output",
    entries: Object.freeze(entries),
  });
}

/** output_order records receipt order from the Node output frames, before media persistence. */
export function projectReplOutputPresentationV2(
  output: unknown,
  legacyStore?: ToolResultMediaStoreV2,
): ReplOutputPresentationV2 | null {
  let input = output;
  if (typeof input === "string") {
    try {
      input = JSON.parse(input);
    } catch {
      return null;
    }
  }
  const value = record(input);
  if (
    !value ||
    !Array.isArray(value.outputs) ||
    value.outputs.length > MAX_ENTRIES
  )
    return null;
  const artifacts = value.artifacts ?? [];
  if (
    !Array.isArray(artifacts) ||
    artifacts.length + value.outputs.length > MAX_ENTRIES
  )
    return null;
  const texts: ReplOutputEntryV2[] = [];
  for (const output of value.outputs) {
    const part = record(output);
    if (part?.type !== "text" || typeof part.text !== "string") return null;
    texts.push({ kind: "text", text: part.text });
  }
  const references: ReplMediaReferenceV2[] = [];
  for (const artifact of artifacts) {
    const part = record(artifact);
    const reference = media({
      store: part?.store ?? legacyStore,
      kind: part?.kind,
      artifactId: part?.artifact_id,
      mimeType: part?.mime_type,
      sizeBytes: part?.size_bytes,
    });
    if (!reference) return null;
    references.push(reference);
  }
  let order = value.output_order;
  if (order === undefined) {
    // Historical output can be ordered only if it contains one kind of stream.
    if (texts.length && references.length) return null;
    order = texts.length
      ? texts.map((_, index) => ({ source: "text", index }))
      : references.map((_, index) => ({ source: "media", index }));
  }
  if (
    !Array.isArray(order) ||
    order.length !== texts.length + references.length
  )
    return null;
  const entries: ReplOutputEntryV2[] = [];
  const seen = new Set<string>();
  for (const item of order) {
    const position = record(item);
    if (
      !position ||
      (position.source !== "text" && position.source !== "media") ||
      typeof position.index !== "number" ||
      !Number.isSafeInteger(position.index) ||
      position.index < 0
    )
      return null;
    const key = position.source + ":" + position.index;
    const entry = (position.source === "text" ? texts : references)[
      position.index
    ];
    if (!entry || seen.has(key)) return null;
    seen.add(key);
    entries.push(entry);
  }
  return validateReplOutputPresentationV2({ kind: "repl_output", entries });
}

export function replMediaReferencesV2(
  presentation: ReplOutputPresentationV2,
): readonly ReplMediaReferenceV2[] {
  return presentation.entries.filter(
    (entry): entry is ReplMediaReferenceV2 =>
      entry.kind === "image" || entry.kind === "audio",
  );
}
export function validatedReplMediaV2(
  presentation: ReplOutputPresentationV2,
  values: readonly ToolResultMediaV2[],
): readonly ToolResultMediaV2[] {
  return values.filter(
    (value) =>
      value.bytes instanceof Uint8Array &&
      replMediaReferencesV2(presentation).some(
        (reference) =>
          reference.store === value.store &&
          reference.artifactId === value.artifactId &&
          reference.mimeType === value.mimeType &&
          reference.sizeBytes === value.bytes.byteLength,
      ),
  );
}

/** Publish one complete bounded batch so late assets cannot restart an audio player. */
export async function loadReplMediaV2(
  presentation: ReplOutputPresentationV2,
  read: (reference: ReplMediaReferenceV2, signal: AbortSignal) => Promise<Blob>,
  signal: AbortSignal,
): Promise<readonly ToolResultMediaV2[]> {
  const values: ToolResultMediaV2[] = [];
  for (const reference of replMediaReferencesV2(presentation)) {
    signal.throwIfAborted();
    try {
      const blob = await read(reference, signal);
      signal.throwIfAborted();
      if (blob.type !== reference.mimeType || blob.size !== reference.sizeBytes)
        continue;
      const bytes = new Uint8Array(await blob.arrayBuffer());
      signal.throwIfAborted();
      values.push({
        store: reference.store,
        artifactId: reference.artifactId,
        mimeType: blob.type,
        bytes,
      });
    } catch {
      signal.throwIfAborted();
    }
  }
  signal.throwIfAborted();
  return validatedReplMediaV2(presentation, values);
}

/** The authenticated host supplies the response; no descriptor URL is accepted. */
export async function readToolResultMediaResponseV2(
  response: Response,
  reference: ReplMediaReferenceV2,
  signal: AbortSignal,
): Promise<Blob> {
  signal.throwIfAborted();
  if (
    !response.ok ||
    response.headers.get("content-type")?.split(";")[0]?.trim() !==
      reference.mimeType ||
    response.headers.get("content-length") !== String(reference.sizeBytes) ||
    !response.body
  )
    throw new Error("tool_media_response_invalid");
  const reader = response.body.getReader();
  const parts: Uint8Array<ArrayBuffer>[] = [];
  let length = 0;
  try {
    for (;;) {
      signal.throwIfAborted();
      const chunk = await reader.read();
      signal.throwIfAborted();
      if (chunk.done) break;
      length += chunk.value.byteLength;
      if (length > reference.sizeBytes)
        throw new Error("tool_media_size_invalid");
      parts.push(new Uint8Array(chunk.value));
    }
    if (length !== reference.sizeBytes)
      throw new Error("tool_media_size_invalid");
    return new Blob(parts, { type: reference.mimeType });
  } catch (error) {
    await reader.cancel().catch(() => undefined);
    throw error;
  } finally {
    reader.releaseLock();
  }
}
