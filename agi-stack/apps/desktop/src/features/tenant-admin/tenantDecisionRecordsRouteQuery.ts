export type TenantDecisionRecordsRouteQuery =
  | Readonly<{ status: 'ready'; workspaceId: string }>
  | Readonly<{
      status: 'unavailable';
      reasonCode:
        | 'tenant_decisions_workspace_query_required'
        | 'tenant_decisions_workspace_query_invalid';
    }>;

export function readTenantDecisionRecordsRouteQuery(
  location: string,
): TenantDecisionRecordsRouteQuery {
  if (typeof location !== 'string') return invalidQuery();
  const hashPath = location.includes('#')
    ? location.slice(location.indexOf('#') + 1)
    : location;
  const queryIndex = hashPath.indexOf('?');
  if (queryIndex < 0) {
    return Object.freeze({
      status: 'unavailable',
      reasonCode: 'tenant_decisions_workspace_query_required',
    });
  }
  const values = new URLSearchParams(hashPath.slice(queryIndex + 1)).getAll('workspace');
  if (values.length === 0) {
    return Object.freeze({
      status: 'unavailable',
      reasonCode: 'tenant_decisions_workspace_query_required',
    });
  }
  if (values.length !== 1 || !validIdentifier(values[0])) return invalidQuery();
  return Object.freeze({ status: 'ready', workspaceId: values[0] });
}

export function buildTenantDecisionRecordsRoutePath(
  tenantId: string,
  workspaceId: string,
): string {
  if (!validIdentifier(tenantId) || !validIdentifier(workspaceId)) {
    throw new Error('tenant_decisions_route_query_scope_invalid');
  }
  return (
    `/tenant/${encodeURIComponent(tenantId)}/decision-records` +
    `?workspace=${encodeURIComponent(workspaceId)}`
  );
}

function invalidQuery(): TenantDecisionRecordsRouteQuery {
  return Object.freeze({
    status: 'unavailable',
    reasonCode: 'tenant_decisions_workspace_query_invalid',
  });
}

function validIdentifier(value: unknown): value is string {
  if (
    typeof value !== 'string' ||
    value.length === 0 ||
    value.length > 256 ||
    value !== value.trim() ||
    value === '.' ||
    value === '..'
  ) {
    return false;
  }
  return [...value].every((character) => {
    const codePoint = character.codePointAt(0) ?? 0;
    return codePoint >= 0x20 && codePoint !== 0x7f;
  });
}
