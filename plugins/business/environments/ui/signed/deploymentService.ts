import type {
  DeployResponse,
  DeployCreate,
  DeployListResponse,
} from '../web/services/deployService';
import type { RuntimeDeploymentStatus } from '../desktop/runtime-deployments/runtimeDeploymentsTypes';

export type Deployment = DeployResponse & {
  action: string;
  revision: number;
  replicas: number | null;
  status: RuntimeDeploymentStatus;
};
type Query = { instance_id?: string; page?: number; page_size?: number };
function read<T>(view: string, id: string, params = {}, signal?: AbortSignal) {
  return window.memstack.invoke('read-deploys', { view, id, ...params }, { signal }) as Promise<T>;
}
function change(action: string, id: string, message?: string) {
  return window.memstack.invoke('change-deploy', { action, id, message }) as Promise<Deployment>;
}
export const deployService = {
  list({ instance_id, ...pagination }: Query = {}, signal?: AbortSignal) {
    if (!instance_id) throw Error('instance_required');
    return read<Omit<DeployListResponse, 'deployments'> & { deployments: Deployment[] }>(
      'list',
      instance_id,
      pagination,
      signal,
    );
  },
  getById: (id: string, signal?: AbortSignal) => read<Deployment>('detail', id, {}, signal),
  getLatestForInstance: (id: string) => read<Deployment>('latest', id),
  create: (data: DeployCreate) => change('create', data.instance_id),
  markFailed: (id: string, message = '') => change('failed', id, message),
  markSuccess: (id: string) => change('success', id),
  cancel: (id: string) => change('cancel', id),
};

// Tenant package commands return individually authorized results. Refresh only on a state change.
export async function streamDeployProgress({
  deployId,
  signal,
  onEvent,
}: {
  deployId: string;
  signal: AbortSignal;
  onEvent: (event: { type: string; status: string; deploy_id: string }) => void | Promise<void>;
}) {
  let previous: string | undefined;
  while (!signal.aborted) {
    const row = await deployService.getById(deployId, signal);
    if (signal.aborted) return;
    const terminal = ['success', 'failed', 'cancelled'].includes(row.status);
    if (terminal || (previous !== undefined && row.status !== previous)) {
      await onEvent({
        type: terminal ? 'done' : 'status',
        status: row.status,
        deploy_id: deployId,
      });
    }
    if (terminal) return;
    previous = row.status;
    await new Promise((resolve) => setTimeout(resolve, 1500));
  }
}
