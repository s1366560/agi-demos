let coreFeatureIds: readonly string[] = [];

/** Registered by the route composition module after the core route tree is built. */
export function registerCoreWebFeatureIdsV2(ids: readonly string[]): void {
  coreFeatureIds = ids;
}

export function isCoreWebFeatureV2(featureId: string): boolean {
  return coreFeatureIds.includes(featureId);
}
