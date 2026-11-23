export const RUNTIME_CLUSTERS_CLOUD_ACTIONS = Object.freeze([
  'view',
  'list',
  'refresh',
  'search-current-page',
  'filter-status-current-page',
  'paginate',
  'inspect-health',
] as const);

export const RUNTIME_CLUSTERS_CLOUD_REASON =
  'runtime_clusters_detail_and_mutations_partial';
export const RUNTIME_CLUSTERS_LOCAL_REASON =
  'cloud_cluster_control_not_applicable';

export class RuntimeClustersUnavailableError extends Error {
  readonly reasonCode: string;

  constructor(reasonCode: string) {
    super(reasonCode);
    this.name = 'RuntimeClustersUnavailableError';
    this.reasonCode = reasonCode;
  }
}
