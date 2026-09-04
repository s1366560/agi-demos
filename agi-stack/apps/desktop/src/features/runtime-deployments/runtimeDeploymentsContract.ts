export const RUNTIME_DEPLOYMENTS_CLOUD_ACTIONS = Object.freeze([
  'view',
  'list',
  'refresh',
  'paginate',
  'inspect-progress',
  'reconnect-progress',
] as const);

export const RUNTIME_DEPLOYMENTS_CLOUD_REASON =
  'runtime_deployments_mutations_and_instance_discovery_partial';
export const RUNTIME_DEPLOYMENTS_LOCAL_REASON =
  'cloud_deployment_authority_not_applicable';

export class RuntimeDeploymentsUnavailableError extends Error {
  readonly reasonCode: string;

  constructor(reasonCode: string) {
    super(reasonCode);
    this.name = 'RuntimeDeploymentsUnavailableError';
    this.reasonCode = reasonCode;
  }
}
