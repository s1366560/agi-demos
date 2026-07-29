export function mergeDefinitionFragments(metadata, fragmentRecords) {
  const capabilities = [];
  const sourceOwnership = {};
  const routeOwnerOverrides = {};
  const capabilityIds = new Set();
  const sourceSymbols = new Set();
  const overriddenRouteKeys = new Set();

  for (const { fragment, sourceEntry } of fragmentRecords) {
    for (const capability of fragment.capabilities) {
      if (capabilityIds.has(capability.id)) {
        throw new Error(
          `Capability ${capability.id} appears in multiple definition fragments.`,
        );
      }
      capabilityIds.add(capability.id);
      capabilities.push({
        ...capability,
        definition_source_entry: sourceEntry,
      });
    }

    for (const [capabilityId, symbols] of Object.entries(
      fragment.source_ownership,
    )) {
      if (Object.hasOwn(sourceOwnership, capabilityId)) {
        throw new Error(
          `Source ownership for ${capabilityId} appears in multiple fragments.`,
        );
      }
      for (const symbol of symbols) {
        if (sourceSymbols.has(symbol)) {
          throw new Error(
            `Routed source symbol ${symbol} appears in multiple fragments.`,
          );
        }
        sourceSymbols.add(symbol);
      }
      sourceOwnership[capabilityId] = [...symbols];
    }

    for (const [capabilityId, routeKeys] of Object.entries(
      fragment.route_owner_overrides,
    )) {
      if (Object.hasOwn(routeOwnerOverrides, capabilityId)) {
        throw new Error(
          `Route overrides for ${capabilityId} appear in multiple fragments.`,
        );
      }
      for (const routeKey of routeKeys) {
        if (overriddenRouteKeys.has(routeKey)) {
          throw new Error(
            `Production route ${routeKey} appears in multiple override fragments.`,
          );
        }
        overriddenRouteKeys.add(routeKey);
      }
      routeOwnerOverrides[capabilityId] = [...routeKeys];
    }
  }

  return {
    ...metadata,
    capabilities,
    source_ownership: sourceOwnership,
    route_owner_overrides: routeOwnerOverrides,
  };
}
