type EventLike = {
  runRevision?: unknown;
  authorityRevision?: unknown;
  run_revision?: unknown;
  authority_revision?: unknown;
  metadata?: unknown;
  data?: unknown;
};

const record = (value: unknown): Record<string, unknown> | null =>
  value !== null && typeof value === 'object' && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;

export function latestSubagentRunRevision(events: EventLike[]): number | null {
  for (let index = events.length - 1; index >= 0; index -= 1) {
    const event = record(events[index]);
    if (!event) continue;
    const sources = [event, record(event.metadata), record(event.data)].filter(
      (source): source is Record<string, unknown> => source !== null
    );
    const dataMetadata = record(record(event.data)?.metadata);
    if (dataMetadata) {
      sources.push(dataMetadata);
    }

    for (const source of sources) {
      const revision =
        source.run_revision ??
        source.runRevision ??
        source.authority_revision ??
        source.authorityRevision;
      if (typeof revision === 'number' && Number.isInteger(revision) && revision >= 1) {
        return revision;
      }
    }
  }
  return null;
}
