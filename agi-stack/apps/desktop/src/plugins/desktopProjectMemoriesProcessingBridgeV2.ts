import type { DesktopNativeKnowledgeProcessingHttpV2 } from './desktopNativeKnowledgeProcessingHttpV2';
import type { ProjectKnowledgeScope } from '../features/project-knowledge/projectKnowledgeClient';
import type {
  NativeKnowledgeProcessingQuery,
  NativeKnowledgeProcessingCommand,
  NativeKnowledgeSyncOptions,
  NativeKnowledgeObservedOptions,
  NativeKnowledgeProcessingClient,
  NativeKnowledgeProcessingCommandClient,
} from '../features/project-knowledge/nativeKnowledgeContracts';
import {
  prepareNativeKnowledgeProcessingQuery,
  prepareNativeKnowledgeProcessingCommand,
  prepareNativeKnowledgeProcessingOptions,
  requireNativeKnowledgeProcessingQueryResponse,
  requireNativeKnowledgeProcessingCommandResponse,
} from '../features/project-knowledge/nativeKnowledgeProcessingValidation';
import { requireNativeKnowledgeScope } from '../features/project-knowledge/nativeKnowledgeValidation';
import { isRecord } from '../features/project-knowledge/projectKnowledgeClient';
import type { DesktopProjectMemoriesOperationsV2 } from './desktopProjectMemoriesAuthorityModuleV2';
import type { DesktopRuntimeConfig } from '../types';

export function createRevocableKnowledgeProcessingV2(
  authority: Partial<DesktopNativeKnowledgeProcessingHttpV2>,
  scope: ProjectKnowledgeScope,
  requireActive: () => void,
): Partial<DesktopNativeKnowledgeProcessingHttpV2> {
  return Object.freeze({
    ...(authority.queryProcessing
      ? {
          async queryProcessing<Q extends NativeKnowledgeProcessingQuery>(
            query: Q,
            inputOptions?: NativeKnowledgeSyncOptions,
          ) {
            requireActive();
            const prepared = prepareNativeKnowledgeProcessingQuery(query, scope);
            const options = prepareNativeKnowledgeProcessingOptions(prepared, inputOptions);
            options.signal?.throwIfAborted();
            const result = await authority.queryProcessing!(
              prepared,
              options as NativeKnowledgeObservedOptions,
            );
            requireActive();
            options.signal?.throwIfAborted();
            const native =
              options.expectedScope ??
              requireNativeKnowledgeScope(
                {
                  contract_version: isRecord(result) ? result.contract_version : null,
                  scope: isRecord(result) ? result.scope : null,
                },
                scope,
              );
            return requireNativeKnowledgeProcessingQueryResponse(result, prepared, scope, native);
          },
        }
      : {}),
    ...(authority.executeProcessing
      ? {
          async executeProcessing<C extends NativeKnowledgeProcessingCommand>(
            command: C,
            inputOptions: NativeKnowledgeObservedOptions,
          ) {
            requireActive();
            const prepared = prepareNativeKnowledgeProcessingCommand(command, scope);
            const options = prepareNativeKnowledgeProcessingOptions(
              prepared,
              inputOptions,
            ) as NativeKnowledgeObservedOptions;
            options.signal?.throwIfAborted();
            const result = await authority.executeProcessing!(prepared, options);
            requireActive();
            options.signal?.throwIfAborted();
            return requireNativeKnowledgeProcessingCommandResponse(
              result,
              prepared,
              scope,
              options.expectedScope,
            );
          },
        }
      : {}),
  });
}
export function createDesktopNativeKnowledgeProcessingClientV2(
  operations: Pick<DesktopProjectMemoriesOperationsV2, 'queryKnowledgeProcessing'>,
  config: DesktopRuntimeConfig,
): NativeKnowledgeProcessingClient {
  const operationConfig = Object.freeze({ ...config });
  return Object.freeze({
    async query<Q extends NativeKnowledgeProcessingQuery>(
      scope: ProjectKnowledgeScope,
      query: Q,
      options?: NativeKnowledgeSyncOptions,
    ) {
      return operations.queryKnowledgeProcessing({
        config: operationConfig,
        scope,
        query,
        ...options,
      });
    },
  });
}
export function createDesktopNativeKnowledgeProcessingCommandClientV2(
  operations: Pick<DesktopProjectMemoriesOperationsV2, 'executeKnowledgeProcessing'>,
  config: DesktopRuntimeConfig,
): NativeKnowledgeProcessingCommandClient {
  const operationConfig = Object.freeze({ ...config });
  return Object.freeze({
    async execute<C extends NativeKnowledgeProcessingCommand>(
      scope: ProjectKnowledgeScope,
      command: C,
      options: NativeKnowledgeObservedOptions,
    ) {
      return operations.executeKnowledgeProcessing({
        config: operationConfig,
        scope,
        command,
        ...options,
      });
    },
  });
}
