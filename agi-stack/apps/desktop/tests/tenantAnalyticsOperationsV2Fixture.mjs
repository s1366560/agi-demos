export function tenantAnalyticsOperationsV2Fixture() {
  return Object.freeze({
    async loadTenantAnalytics({ signal }) {
      if (signal?.aborted) throw new DOMException('Aborted', 'AbortError');
      throw new Error('tenant_analytics_authority_unavailable');
    },
  });
}
