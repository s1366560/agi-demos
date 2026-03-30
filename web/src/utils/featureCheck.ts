let _features: Record<string, boolean> = {};

export function setFeatures(features: Array<{ id: string; enabled: boolean }>) {
  _features = {};
  features.forEach((f) => {
    _features[f.id] = f.enabled;
  });
}

export function isFeatureEnabled(featureId: string): boolean {
  return !!_features[featureId];
}
