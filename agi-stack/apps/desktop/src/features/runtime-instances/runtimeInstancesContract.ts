export const RUNTIME_INSTANCES_CLOUD_ACTIONS = Object.freeze([
  'view',
  'list',
  'refresh',
  'search',
  'filter-status',
  'paginate',
  'restart',
  'delete',
] as const);
export const RUNTIME_INSTANCES_LOCAL_ACTIONS = Object.freeze([
  'view',
  'list',
  'refresh',
  'search',
  'filter-status',
] as const);

export const RUNTIME_INSTANCES_CLOUD_REASON = 'runtime_instances_nested_routes_partial';
export const RUNTIME_INSTANCES_LOCAL_REASON = 'local_instance_sidecar_projection_partial';

export class RuntimeInstancesUnavailableError extends Error {
  readonly reasonCode: string;

  constructor(reasonCode: string) {
    super(reasonCode);
    this.name = 'RuntimeInstancesUnavailableError';
    this.reasonCode = reasonCode;
  }
}
