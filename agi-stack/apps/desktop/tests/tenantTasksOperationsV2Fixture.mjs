export function tenantTasksOperationsV2Fixture() {
  return Object.freeze({
    async loadTenantTasks({ scope, query = {} }) {
      const limit = query.limit ?? 1;
      const offset = query.offset ?? 0;
      return Object.freeze({
        scope: Object.freeze({ ...scope }),
        authority: scope.authority,
        availability: scope.authority === 'cloud' ? 'available' : 'degraded',
        reasonCode: scope.authority === 'cloud' ? null : 'local_task_dashboard_partial',
        serviceVersion: '0.1.0',
        contractVersion: '3.0.0',
        allowedActions: Object.freeze(
          scope.authority === 'cloud'
            ? [
                'view',
                'list',
                'search',
                'filter',
                'paginate',
                'refresh',
                'retry-task',
                'stop-task',
                'retry-pending',
                'navigate-dead-letter-queue',
              ]
            : [
                'view',
                'list',
                'search',
                'filter',
                'paginate',
                'refresh',
                'open-workspace',
              ],
        ),
        authorityRevision: null,
        stats: Object.freeze({
          total: 0,
          pending: 0,
          processing: 0,
          completed: 0,
          failed: 0,
          throughputPerMinute: 0,
          errorRate: 0,
        }),
        queue: Object.freeze({ current: 0, history: Object.freeze([]) }),
        tasks: Object.freeze([]),
        total: 0,
        limit,
        offset,
        hasMore: false,
      });
    },
    async retryTenantTask() {
      throw new Error('tenant_tasks_authority_unavailable');
    },
    async stopTenantTask() {
      throw new Error('tenant_tasks_authority_unavailable');
    },
    async retryPendingTenantTasks() {
      throw new Error('tenant_tasks_authority_unavailable');
    },
  });
}
