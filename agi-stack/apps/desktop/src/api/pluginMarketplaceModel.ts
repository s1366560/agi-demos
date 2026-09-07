import type { ManagedPlugin, MarketplacePluginCatalogEntry } from '../types';

export function managedPluginFromMarketplaceEntry(
  entry: MarketplacePluginCatalogEntry,
): ManagedPlugin {
  return {
    ...entry,
    id: `${entry.plugin_id}@${entry.version}`,
    name: entry.plugin_id,
    source: 'marketplace-v2',
    package: entry.artifact_repository,
    kind: 'bundle-v2',
    enabled: entry.install_status === 'installed' && !entry.revoked,
    discovered: !entry.revoked,
    targets: marketplacePluginTargets(entry.manifest),
  };
}

export function marketplacePluginTargets(manifest: Record<string, unknown>): string[] {
  const targets: string[] = [];
  appendTargets(targets, manifest.targets);
  appendModuleTargets(targets, manifest.modules);

  if (Array.isArray(manifest.manifests)) {
    for (const candidate of manifest.manifests) {
      if (!isRecord(candidate)) continue;
      appendTargets(targets, candidate.targets);
      appendModuleTargets(targets, candidate.modules);
    }
  }
  return [...new Set(targets)];
}

function appendModuleTargets(targets: string[], modules: unknown): void {
  if (!Array.isArray(modules)) return;
  for (const candidate of modules) {
    if (isRecord(candidate)) appendTargets(targets, candidate.targets);
  }
}

function appendTargets(targets: string[], candidates: unknown): void {
  if (!Array.isArray(candidates)) return;
  for (const candidate of candidates) {
    if (typeof candidate !== 'string') continue;
    const target = candidate.trim();
    if (target) targets.push(target);
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value);
}
