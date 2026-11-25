import type {} from "../../../../../sdk/memstack-plugin-sdk/src/pageRuntime";
import type {
  PoolStatus,
  PoolAuthorityScope,
  ListInstancesParams,
  InstanceListResponse,
  MetricsResponse,
  OperationResponse,
  SetTierResponse,
  ProjectTier,
} from "../web/services/poolService";

export const GLOBAL_POOL_SCOPE: PoolAuthorityScope = Object.freeze({
  scope: "global",
});
class PoolPermissionError extends Error {}
export const isPoolForbiddenError = (error: unknown) =>
  error instanceof PoolPermissionError;

async function invoke<T>(
  command: string,
  input: Record<string, unknown>,
): Promise<T> {
  const result = await window.memstack.invoke(command, input);
  if (
    result &&
    typeof result === "object" &&
    "forbidden" in result &&
    result.forbidden === true
  ) {
    throw new PoolPermissionError("403");
  }
  return result as T;
}

export const poolService = {
  getStatus: () =>
    invoke<PoolStatus>("read-runtime-pool", { resource: "status" }),
  listInstances: (filters: ListInstancesParams) =>
    invoke<InstanceListResponse>("read-runtime-pool", {
      resource: "instances",
      ...filters,
    }),
  getMetrics: () =>
    invoke<MetricsResponse>("read-runtime-pool", { resource: "metrics" }),
  pauseInstance: (key: string) =>
    invoke<OperationResponse>("control-runtime-pool", {
      action: "pause",
      instance_key: key,
    }),
  resumeInstance: (key: string) =>
    invoke<OperationResponse>("control-runtime-pool", {
      action: "resume",
      instance_key: key,
    }),
  terminateInstance: (key: string, graceful: boolean) =>
    invoke<OperationResponse>("control-runtime-pool", {
      action: "terminate",
      instance_key: key,
      graceful,
    }),
  setProjectTier: (projectId: string, _tenantId: string, tier: ProjectTier) =>
    invoke<SetTierResponse>("set-runtime-pool-tier", {
      project_id: projectId,
      tier,
    }),
};
