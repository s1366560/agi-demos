import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { parseDocument } from 'yaml';

const RELEASE_PROVIDER = Object.freeze({
  provider: 'github',
  owner: 's1366560',
  repo: 'agi-demos',
});

type UpdateFeedConfig = {
  provider?: unknown;
  owner?: unknown;
  repo?: unknown;
};

function parseUpdateFeed(path: string): UpdateFeedConfig | null {
  try {
    const document = parseDocument(readFileSync(path, 'utf8'), {
      uniqueKeys: true,
    });
    if (document.errors.length > 0) return null;
    const value = document.toJS({ maxAliasCount: 0 });
    if (!value || typeof value !== 'object' || Array.isArray(value)) return null;
    return value as UpdateFeedConfig;
  } catch {
    return null;
  }
}

/**
 * Production updates are an explicit packaging capability. Local packages
 * omit app-update.yml and therefore cannot contact a release provider.
 */
export function releaseUpdateFeedIsEnabled(
  isPackaged: boolean,
  resourcesPath: string,
): boolean {
  if (!isPackaged) return false;
  const feed = parseUpdateFeed(join(resourcesPath, 'app-update.yml'));
  return (
    feed?.provider === RELEASE_PROVIDER.provider &&
    feed.owner === RELEASE_PROVIDER.owner &&
    feed.repo === RELEASE_PROVIDER.repo
  );
}
