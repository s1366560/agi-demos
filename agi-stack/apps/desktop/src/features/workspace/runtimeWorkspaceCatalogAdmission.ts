import { DesktopApiError } from '../../api/client';
import type { DesktopRuntimeConfig } from '../../types';

/** A missing optional catalog does not authorize a bound workspace or hide a denial. */
export function workspaceCatalogFailureAllowsUnboundRuntime(
  config: Pick<DesktopRuntimeConfig, 'mode' | 'workspaceId'>,
  error: unknown,
): boolean {
  if (
    config.mode !== 'cloud' ||
    config.workspaceId.trim() ||
    !(error instanceof DesktopApiError) ||
    error.status !== 404
  ) {
    return false;
  }
  const payload = error.payload;
  // Plain HTTP diagnostics are distinct from structured permission or authority failures.
  return (
    typeof payload === 'object' &&
    payload !== null &&
    !Array.isArray(payload) &&
    Object.keys(payload).every((key) => key === 'detail') &&
    'detail' in payload &&
    typeof payload.detail === 'string'
  );
}

export function selectRuntimeWorkspaceAfterCatalog(
  config: Pick<DesktopRuntimeConfig, 'mode' | 'workspaceId'>,
  failure: unknown,
  selectFromCatalog: () => string,
): string {
  return workspaceCatalogFailureAllowsUnboundRuntime(config, failure) ? '' : selectFromCatalog();
}
