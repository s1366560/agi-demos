import { DesktopApiClient } from '../../api/client';
import type { DesktopRuntimeConfig } from '../../types';

type DesktopWorkspaceAgentBindingDialogMethod =
  | 'listWorkspaceBindingAgentDefinitionsForProject'
  | 'bindWorkspaceAgentForProject'
  | 'unbindWorkspaceAgentForProject';

export type DesktopWorkspaceAgentBindingDialogClient = Readonly<
  Pick<DesktopApiClient, DesktopWorkspaceAgentBindingDialogMethod>
>;

export type DesktopWorkspaceAgentBindingDialogClientProviderReasonCodeV2 =
  'desktop_workspace_agent_binding_dialog_client_unpublished';

export class DesktopWorkspaceAgentBindingDialogClientProviderErrorV2 extends Error {
  readonly reasonCode: DesktopWorkspaceAgentBindingDialogClientProviderReasonCodeV2;

  constructor(reasonCode: DesktopWorkspaceAgentBindingDialogClientProviderReasonCodeV2) {
    super(reasonCode);
    this.name = 'DesktopWorkspaceAgentBindingDialogClientProviderErrorV2';
    this.reasonCode = reasonCode;
  }
}

export type DesktopWorkspaceAgentBindingDialogClientProviderInputV2 = Readonly<{
  config: DesktopRuntimeConfig;
}>;

export type DesktopWorkspaceAgentBindingDialogClientBindingV2 = Readonly<{
  client: DesktopWorkspaceAgentBindingDialogClient;
  bindOperation: (config: DesktopRuntimeConfig) => DesktopWorkspaceAgentBindingDialogClient;
}>;

export type DesktopWorkspaceAgentBindingDialogClientProviderV2 = Readonly<{
  publish: (
    input: DesktopWorkspaceAgentBindingDialogClientProviderInputV2,
  ) => DesktopWorkspaceAgentBindingDialogClientBindingV2;
  resolve: () => DesktopWorkspaceAgentBindingDialogClientBindingV2;
}>;

export function createDesktopWorkspaceAgentBindingDialogClientProviderV2():
  DesktopWorkspaceAgentBindingDialogClientProviderV2 {
  let publication: DesktopWorkspaceAgentBindingDialogClientBindingV2 | null = null;

  return Object.freeze({
    publish(input) {
      const next = createDesktopWorkspaceAgentBindingDialogClientBindingV2(input);
      publication = next;
      return next;
    },
    resolve() {
      if (publication === null) {
        throw new DesktopWorkspaceAgentBindingDialogClientProviderErrorV2(
          'desktop_workspace_agent_binding_dialog_client_unpublished',
        );
      }
      return publication;
    },
  });
}

function createDesktopWorkspaceAgentBindingDialogClientBindingV2(
  input: DesktopWorkspaceAgentBindingDialogClientProviderInputV2,
): DesktopWorkspaceAgentBindingDialogClientBindingV2 {
  const config = Object.freeze({ ...input.config });
  return Object.freeze({
    client: createDesktopWorkspaceAgentBindingDialogClient(config),
    bindOperation: (operationConfig) =>
      createDesktopWorkspaceAgentBindingDialogClient(
        Object.freeze({ ...operationConfig }),
      ),
  });
}

function createDesktopWorkspaceAgentBindingDialogClient(
  config: DesktopRuntimeConfig,
): DesktopWorkspaceAgentBindingDialogClient {
  const authority = new DesktopApiClient(config);
  return Object.freeze({
    listWorkspaceBindingAgentDefinitionsForProject: (
      ...args: Parameters<
        DesktopApiClient['listWorkspaceBindingAgentDefinitionsForProject']
      >
    ) => authority.listWorkspaceBindingAgentDefinitionsForProject(...args),
    bindWorkspaceAgentForProject: (
      ...args: Parameters<DesktopApiClient['bindWorkspaceAgentForProject']>
    ) => authority.bindWorkspaceAgentForProject(...args),
    unbindWorkspaceAgentForProject: (
      ...args: Parameters<DesktopApiClient['unbindWorkspaceAgentForProject']>
    ) => authority.unbindWorkspaceAgentForProject(...args),
  });
}
