import { desktopApiFetch } from '../../api/cloudRequestBroker';
import type { DesktopRuntimeConfig } from '../../types';
import {
  createAgentWorkspaceJourneyAuthorityClient,
  type AgentWorkspaceJourneyAuthorityClient,
} from '../agent-workspace/agentWorkspaceJourneyAuthorityClient';
import { requireActiveWorkbenchSnapshotV2 } from './desktopWorkbenchSnapshotSettlementV2';

/** Construction errors are observed by the snapshot branch, never a legacy fallback. */
export function createWorkbenchSnapshotJourneyV2(
  config: DesktopRuntimeConfig,
): AgentWorkspaceJourneyAuthorityClient {
  return Object.freeze({
    async probe(signal?: AbortSignal) {
      requireActiveWorkbenchSnapshotV2(signal);
      const client = createAgentWorkspaceJourneyAuthorityClient(config, {
        fetchImpl: async (input, init) => {
          requireActiveWorkbenchSnapshotV2(signal);
          requireActiveWorkbenchSnapshotV2(init?.signal ?? undefined);
          const url = new URL(
            typeof input === 'string' ? input : input instanceof URL ? input.href : input.url,
          );
          if (url.origin !== new URL(config.apiBaseUrl).origin)
            throw new Error('workbench_journey_origin_mismatch');
          const response = await desktopApiFetch(config, url.pathname + url.search, init);
          requireActiveWorkbenchSnapshotV2(signal);
          return response;
        },
      });
      const result = await client.probe(signal);
      requireActiveWorkbenchSnapshotV2(signal);
      return result;
    },
  });
}
