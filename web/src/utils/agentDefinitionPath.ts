/**
 * Compute the agent-definitions list path for the current location.
 *
 * The definitions pages are mounted under several route prefixes
 * (tenant-scoped and global), so the list path is derived from the
 * current pathname instead of being hardcoded.
 */
export function getDefinitionListPath(pathname: string): string {
  const segments = pathname.split('/').filter(Boolean);
  const definitionsIndex = segments.lastIndexOf('agent-definitions');

  if (definitionsIndex === -1) {
    return '/tenant/agent-definitions';
  }

  return `/${segments.slice(0, definitionsIndex + 1).join('/')}`;
}
