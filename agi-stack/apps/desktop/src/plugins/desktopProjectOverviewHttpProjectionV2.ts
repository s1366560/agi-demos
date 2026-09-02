import type {
  ProjectOverviewReadResult,
  ProjectOverviewScope,
} from '../features/project/projectOverviewClient';
import { readCloudProjectOverview } from '../features/project/projectOverviewClient';
import { createCloudProjectOverviewClient } from '../features/project/projectOverviewCloudClient';
import { createLocalProjectOverviewClient } from '../features/project/projectOverviewLocalClient';
import type { DesktopCapabilityAvailability } from '../features/runtime/capabilitySnapshot';
import type { DesktopRuntimeConfig } from '../types';

const CLOUD_PROJECT_OVERVIEW_SERVICE_VERSION_V2 = '0.1.0';
const CLOUD_PROJECT_OVERVIEW_CONTRACT_VERSION_V2 = '3.0.0';

export type DesktopProjectOverviewHttpAuthorityV2 = Readonly<{
  load: (signal?: AbortSignal) => Promise<ProjectOverviewReadResult>;
  probe: (signal?: AbortSignal) => Promise<DesktopCapabilityAvailability>;
}>;

export function createDesktopProjectOverviewHttpAuthorityV2(
  config: DesktopRuntimeConfig,
  scope: ProjectOverviewScope
): DesktopProjectOverviewHttpAuthorityV2 {
  const load = async (signal?: AbortSignal): Promise<ProjectOverviewReadResult> => {
    if (scope.authority === 'cloud') {
      const result = await readCloudProjectOverview(
        createCloudProjectOverviewClient(config),
        scope,
        { signal }
      );
      return result.kind === 'empty'
        ? Object.freeze({ kind: 'empty' })
        : Object.freeze({ kind: 'cloud-ready', snapshot: result.snapshot });
    }
    return Object.freeze({
      kind: 'local-ready',
      snapshot: await createLocalProjectOverviewClient(config).load(scope, {
        signal,
      }),
    });
  };

  return Object.freeze({
    load,
    async probe(signal?: AbortSignal) {
      const result = await load(signal);
      if (result.kind === 'local-ready') {
        const capability = result.snapshot.capability;
        return Object.freeze({
          availability: capability.availability,
          reason_code: capability.reasonCode,
          service_version: capability.serviceVersion,
          contract_version: capability.contractVersion,
          allowed_actions: Object.freeze([...capability.allowedActions]),
          scope: Object.freeze({
            tenant_id: capability.scope.tenantId,
            project_id: capability.scope.projectId,
            workspace_id: capability.scope.workspaceId,
            instance_id: capability.scope.instanceId,
          }),
          authority_revision: capability.authorityRevision,
        });
      }
      return Object.freeze({
        availability: 'unavailable',
        reason_code: 'capability_authority_revision_unavailable',
        service_version: CLOUD_PROJECT_OVERVIEW_SERVICE_VERSION_V2,
        contract_version: CLOUD_PROJECT_OVERVIEW_CONTRACT_VERSION_V2,
        allowed_actions: Object.freeze([]),
        scope: Object.freeze({
          tenant_id: scope.tenantId,
          project_id: scope.projectId,
          workspace_id: null,
          instance_id: null,
        }),
        authority_revision: null,
      });
    },
  });
}
