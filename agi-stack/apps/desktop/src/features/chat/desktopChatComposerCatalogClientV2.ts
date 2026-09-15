import type { DesktopApiClient } from "../../api/client";
import type { DesktopConversationConfigOperationsV2 } from "../../plugins/desktopConversationConfigAuthorityModuleV2";
import type { AgentConversation } from "../../types";
import type { DesktopNewTaskFlowOperationsV2 } from "../../plugins/desktopNewTaskFlowAuthorityModuleV2";
import type { DesktopWorkspaceConversationCatalogOperationsV2 } from "../../plugins/desktopWorkspaceConversationCatalogAuthorityModuleV2";
import {
  createDesktopNewThreadComposerCatalogClientProviderV2,
  type DesktopNewThreadComposerCatalogClient,
  type DesktopNewThreadComposerCatalogClientProviderInputV2,
} from "../task/desktopNewThreadComposerCatalogClientProviderV2";

export type DesktopChatComposerCatalogClientInputV2 =
  DesktopNewThreadComposerCatalogClientProviderInputV2 &
    Readonly<{
      conversationConfigOperationsV2?: DesktopConversationConfigOperationsV2;
      workspaceConversationCatalogOperationsV2: DesktopWorkspaceConversationCatalogOperationsV2;
      newTaskFlowOperationsV2: DesktopNewTaskFlowOperationsV2;
    }>;

export type DesktopChatComposerCatalogClientV2 =
  DesktopNewThreadComposerCatalogClient &
    Pick<DesktopApiClient, "listConversations" | "getConversationMessages"> &
    Pick<
      import("./composerCatalogModel").ComposerCatalogClient,
      "readExecutionSelection" | "updateExecutionSelection"
    >;

export function createDesktopChatComposerCatalogClientV2(
  input: DesktopChatComposerCatalogClientInputV2,
): DesktopChatComposerCatalogClientV2 {
  const config = Object.freeze({ ...input.config });
  const catalog =
    createDesktopNewThreadComposerCatalogClientProviderV2().publish({
      ...input,
      config,
    }).client;
  const conversations = input.workspaceConversationCatalogOperationsV2;
  const history = input.newTaskFlowOperationsV2;
  return Object.freeze({
    ...catalog,
    ...(config.mode === "local" && input.conversationConfigOperationsV2
      ? {
          readExecutionSelection: (conversation: AgentConversation) =>
            input.conversationConfigOperationsV2!.readExecutionSelection({
              config,
              conversation,
            }),
          updateExecutionSelection: (
            conversation: AgentConversation,
            patch: Partial<
              NonNullable<AgentConversation["execution_selection"]>
            >,
          ) =>
            input.conversationConfigOperationsV2!.updateExecutionSelection({
              config,
              conversation,
              patch,
            }),
        }
      : {}),
    listConversations(
      projectId = config.projectId,
      workspaceIdOrOptions,
      legacySignal,
    ) {
      const options =
        workspaceIdOrOptions !== null &&
        typeof workspaceIdOrOptions === "object"
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
