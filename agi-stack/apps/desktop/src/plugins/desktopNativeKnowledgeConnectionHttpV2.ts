import type { DesktopRuntimeConfig } from '../types';
import {
  projectKnowledgeError,
  requestProjectKnowledgeJson,
  type ProjectKnowledgeScope,
} from '../features/project-knowledge/projectKnowledgeClient';
import {
  prepareNativeKnowledgeCloudConnection,
  requireNativeKnowledgeCloudConnectionResponse,
  type NativeKnowledgeCloudConnectionAuthority,
  type NativeKnowledgeCloudConnectionCommand,
  type NativeKnowledgeCloudConnectionOptions,
} from '../features/project-knowledge/nativeKnowledgeCloudConnectionClient';
import { requireNativeKnowledgeScope } from '../features/project-knowledge/nativeKnowledgeValidation';
import { sameJson } from '../features/project-knowledge/nativeKnowledgeRelationships';
import { requireNativeKnowledgeTransportV2 } from './desktopNativeKnowledgeSyncHttpV2';

export function createDesktopNativeKnowledgeConnectionHttpV2(
  config: DesktopRuntimeConfig,
  scope: ProjectKnowledgeScope,
): NativeKnowledgeCloudConnectionAuthority {
  return Object.freeze({
    async executeConnection<C extends NativeKnowledgeCloudConnectionCommand>(
      command: C,
      options: NativeKnowledgeCloudConnectionOptions,
      requireCurrent?: () => void,
    ) {
      const prepared = prepareNativeKnowledgeCloudConnection(command, options);
      const current = () => {
        requireCurrent?.();
        prepared.options.signal?.throwIfAborted();
      };
      current();
      requireNativeKnowledgeTransportV2(config);
      const observed = requireNativeKnowledgeScope(
        await requestProjectKnowledgeJson(config, '/api/v1/knowledge/context', {
          signal: prepared.options.signal,
        }),
        scope,
      );
      current();
      if (!sameJson(observed, prepared.options.expectedScope))
        throw projectKnowledgeError('knowledge_scope_mismatch', 409);
      const { operation, ...fields } = prepared.command;
      const value = await requestProjectKnowledgeJson(
        config,
        `/api/v1/knowledge/sync-${operation}`,
        {
          method: 'POST',
          signal: prepared.options.signal,
          body: { scope: observed, ...fields },
        },
      );
      current();
      return requireNativeKnowledgeCloudConnectionResponse(
        value,
        prepared.command,
        scope,
        observed,
      );
    },
  });
}
