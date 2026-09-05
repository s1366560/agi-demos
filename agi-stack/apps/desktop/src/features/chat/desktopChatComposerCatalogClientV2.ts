import type { DesktopApiClient } from '../../api/client';
import type { DesktopNewTaskFlowOperationsV2 } from '../../plugins/desktopNewTaskFlowAuthorityModuleV2';
import type { DesktopWorkspaceConversationCatalogOperationsV2 } from '../../plugins/desktopWorkspaceConversationCatalogAuthorityModuleV2';
import {
  createDesktopNewThreadComposerCatalogClientProviderV2,
  type DesktopNewThreadComposerCatalogClient,
  type DesktopNewThreadComposerCatalogClientProviderInputV2,
} from '../task/desktopNewThreadComposerCatalogClientProviderV2';

export type DesktopChatComposerCatalogClientInputV2 =
  DesktopNewThreadComposerCatalogClientProviderInputV2 &
    Readonly<{
      workspaceConversationCatalogOperationsV2: DesktopWorkspaceConversationCatalogOperationsV2;
      newTaskFlowOperationsV2: DesktopNewTaskFlowOperationsV2;
    }>;

export type DesktopChatComposerCatalogClientV2 = DesktopNewThreadComposerCatalogClient &
  Pick<DesktopApiClient, 'listConversations' | 'getConversationMessages'>;

export function createDesktopChatComposerCatalogClientV2(
  input: DesktopChatComposerCatalogClientInputV2,
): DesktopChatComposerCatalogClientV2 {
  const config = Object.freeze({ ...input.config });
  const catalog = createDesktopNewThreadComposerCatalogClientProviderV2().publish({
    ...input,
    config,
  }).client;
  const conversations = input.workspaceConversationCatalogOperationsV2;
  const history = input.newTaskFlowOperationsV2;
  return Object.freeze({
    ...catalog,
    listConversations(projectId = config.projectId, workspaceIdOrOptions, legacySignal) {
      const options =
        workspaceIdOrOptions !== null && typeof workspaceIdOrOptions === 'object'
          ? workspaceIdOrOptions
          : { workspaceId: workspaceIdOrOptions, signal: legacySignal };
      return conversations.listConversations({
        config: { ...config, projectId },
        workspaceId: options.workspaceId?.trim() || null,
        unboundOnly: options.unboundOnly === true,
        signal: options.signal,
      });
    },
    getConversationMessages(...args) {
      return history.bindOperation(config).getConversationMessages(...args);
    },
  } satisfies DesktopChatComposerCatalogClientV2);
}
