import { RuntimeV2Error } from '@agistack/plugin-runtime';

import type { DesktopTenantEvolutionOperationsV2 } from '../plugins/desktopTenantEvolutionAuthorityModuleV2';
import { createDesktopTenantEvolutionHttpProjectionV2 } from '../plugins/desktopTenantEvolutionHttpProjectionV2';
import {
  prepareTenantEvolutionInputV2,
  prepareTenantEvolutionReviewV2,
  prepareTenantEvolutionUpdateV2,
  requireTenantEvolutionConfigV2,
  requireTenantEvolutionObservationV2,
} from '../plugins/desktopTenantEvolutionOperationContractV2';

// Standalone QA has no generation host. This preserves production transport and
// operation contracts without representing Loader leases or native acceptance.
export function createDesktopTenantEvolutionQaOperationsV2(): DesktopTenantEvolutionOperationsV2 {
  const operations: DesktopTenantEvolutionOperationsV2 = {
    async observeTenantEvolution(input) {
      const prepared = prepareTenantEvolutionInputV2(input);
      const authority = createDesktopTenantEvolutionHttpProjectionV2(prepared.config);
      return requireTenantEvolutionObservationV2(
        await authority.observe(prepared.scope, prepared.signal),
        prepared.scope,
      );
    },
    async runTenantEvolution(input) {
      const prepared = prepareTenantEvolutionInputV2(input);
      const authority = createDesktopTenantEvolutionHttpProjectionV2(prepared.config);
      requireVoidResult(await authority.run(prepared.scope, prepared.signal));
    },
    async updateTenantEvolutionConfig(input) {
      const prepared = prepareTenantEvolutionUpdateV2(input);
      const authority = createDesktopTenantEvolutionHttpProjectionV2(prepared.config);
      return requireTenantEvolutionConfigV2(
        await authority.updateConfig(prepared.scope, prepared.update, prepared.signal),
      );
    },
    async reviewTenantEvolutionJob(input) {
      const prepared = prepareTenantEvolutionReviewV2(input);
      const authority = createDesktopTenantEvolutionHttpProjectionV2(prepared.config);
      requireVoidResult(
        await authority.reviewJob(prepared.scope, prepared.jobId, prepared.action, prepared.signal),
      );
    },
  };
  return Object.freeze(operations);
}

function requireVoidResult(value: unknown): void {
  if (value !== undefined) {
    throw new RuntimeV2Error(
      'desktop_tenant_evolution_service_invalid',
      'desktop tenant evolution authority service invalid',
    );
  }
}
