import { DesktopApiClient } from '../../api/client';
import type { DesktopRuntimeConfig } from '../../types';

type DesktopWorkspaceRosterMethod =
  | 'listWorkspaceMembers'
  | 'listWorkspaceAgents';

export type DesktopWorkspaceRosterClient = Readonly<
  Pick<DesktopApiClient, DesktopWorkspaceRosterMethod>
>;

export type DesktopWorkspaceRosterClientProviderReasonCodeV2 =
  'desktop_workspace_roster_client_unpublished';

export class DesktopWorkspaceRosterClientProviderErrorV2 extends Error {
  readonly reasonCode: DesktopWorkspaceRosterClientProviderReasonCodeV2;

  constructor(reasonCode: DesktopWorkspaceRosterClientProviderReasonCodeV2) {
    super(reasonCode);
    this.name = 'DesktopWorkspaceRosterClientProviderErrorV2';
    this.reasonCode = reasonCode;
  }
}

export type DesktopWorkspaceRosterClientProviderInputV2 = Readonly<{
  config: DesktopRuntimeConfig;
}>;

export type DesktopWorkspaceRosterClientBindingV2 = Readonly<{
  client: DesktopWorkspaceRosterClient;
  bindOperation: (config: DesktopRuntimeConfig) => DesktopWorkspaceRosterClient;
}>;

export type DesktopWorkspaceRosterClientProviderV2 = Readonly<{
  publish: (
    input: DesktopWorkspaceRosterClientProviderInputV2,
  ) => DesktopWorkspaceRosterClientBindingV2;
  resolve: () => DesktopWorkspaceRosterClientBindingV2;
}>;

export function createDesktopWorkspaceRosterClientProviderV2():
  DesktopWorkspaceRosterClientProviderV2 {
  let publication: DesktopWorkspaceRosterClientBindingV2 | null = null;

  return Object.freeze({
    publish(input) {
      const next = createDesktopWorkspaceRosterClientBindingV2(input);
      publication = next;
      return next;
    },
    resolve() {
      if (publication === null) {
        throw new DesktopWorkspaceRosterClientProviderErrorV2(
          'desktop_workspace_roster_client_unpublished',
        );
      }
      return publication;
    },
  });
}

function createDesktopWorkspaceRosterClientBindingV2(
  input: DesktopWorkspaceRosterClientProviderInputV2,
): DesktopWorkspaceRosterClientBindingV2 {
  const config = Object.freeze({ ...input.config });
  return Object.freeze({
    client: createDesktopWorkspaceRosterClient(config),
    bindOperation: (operationConfig) =>
      createDesktopWorkspaceRosterClient(Object.freeze({ ...operationConfig })),
  });
}

function createDesktopWorkspaceRosterClient(
  config: DesktopRuntimeConfig,
): DesktopWorkspaceRosterClient {
  const authority = new DesktopApiClient(config);
  return Object.freeze({
    listWorkspaceMembers: (
      ...args: Parameters<DesktopApiClient['listWorkspaceMembers']>
    ) => authority.listWorkspaceMembers(...args),
    listWorkspaceAgents: (
      ...args: Parameters<DesktopApiClient['listWorkspaceAgents']>
    ) => authority.listWorkspaceAgents(...args),
  });
}
