let _features: Record<string, boolean> = {};

function isFeatureFlag(value: unknown): value is { id: string; enabled: boolean } {
  return (
    typeof value === 'object' &&
    value !== null &&
    'id' in value &&
    'enabled' in value &&
    typeof value.id === 'string' &&
    typeof value.enabled === 'boolean'
  );
}

export function setFeatures(features: unknown) {
  _features = {};
  if (!Array.isArray(features)) return;

  features.filter(isFeatureFlag).forEach((f) => {
    _features[f.id] = f.enabled;
  });
}

export function isFeatureEnabled(featureId: string): boolean {
  return !!_features[featureId];
}
