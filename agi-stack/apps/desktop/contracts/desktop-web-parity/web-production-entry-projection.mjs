export function resolveCapabilityWebEntries({
  capabilityId,
  kind,
  ownedRoutes,
  ownedSourceEntries,
  webMissing,
}) {
  if (kind === "native_only") {
    return [`not_applicable:web/${capabilityId}`];
  }

  const entries = new Set(ownedSourceEntries);
  for (const route of ownedRoutes) {
    for (const source of route.source_entries) {
      entries.add(source.source_entry);
    }
  }
  if (entries.size > 0) {
    return [...entries].sort();
  }
  if (webMissing) {
    return [`not_applicable:web-route-missing/${capabilityId}`];
  }
  return ["web/src/App.tsx"];
}
