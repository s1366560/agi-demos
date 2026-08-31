import { DesktopApiClient } from '../../api/client';
import type { DesktopRuntimeConfig } from '../../types';

type DesktopWorkspaceMemberMutationMethod =
  | 'addWorkspaceMemberForProject'
  | 'removeWorkspaceMemberForProject'
  | 'updateWorkspaceMemberRoleForProject';

export type DesktopWorkspaceMemberMutationClient = Readonly<
  Pick<DesktopApiClient, DesktopWorkspaceMemberMutationMethod>
>;

export type DesktopWorkspaceMemberMutationClientProviderReasonCodeV2 =
  'desktop_workspace_member_mutation_client_unpublished';

export class DesktopWorkspaceMemberMutationClientProviderErrorV2 extends Error {
  readonly reasonCode: DesktopWorkspaceMemberMutationClientProviderReasonCodeV2;

  constructor(reasonCode: DesktopWorkspaceMemberMutationClientProviderReasonCodeV2) {
    super(reasonCode);
    this.name = 'DesktopWorkspaceMemberMutationClientProviderErrorV2';
    this.reasonCode = reasonCode;
  }
}

export type DesktopWorkspaceMemberMutationClientProviderInputV2 = Readonly<{
  config: DesktopRuntimeConfig;
}>;

export type DesktopWorkspaceMemberMutationClientBindingV2 = Readonly<{
  client: DesktopWorkspaceMemberMutationClient;
  bindOperation: (
    config: DesktopRuntimeConfig,
  ) => DesktopWorkspaceMemberMutationClient;
}>;

export type DesktopWorkspaceMemberMutationClientProviderV2 = Readonly<{
  publish: (
    input: DesktopWorkspaceMemberMutationClientProviderInputV2,
  ) => DesktopWorkspaceMemberMutationClientBindingV2;
  resolve: () => DesktopWorkspaceMemberMutationClientBindingV2;
}>;

export function createDesktopWorkspaceMemberMutationClientProviderV2():
  DesktopWorkspaceMemberMutationClientProviderV2 {
  let publication: DesktopWorkspaceMemberMutationClientBindingV2 | null = null;

  return Object.freeze({
    publish(input) {
      const next = createDesktopWorkspaceMemberMutationClientBindingV2(input);
      publication = next;
      return next;
    },
    resolve() {
      if (publication === null) {
        throw new DesktopWorkspaceMemberMutationClientProviderErrorV2(
          'desktop_workspace_member_mutation_client_unpublished',
        );
      }
      return publication;
    },
  });
}

function createDesktopWorkspaceMemberMutationClientBindingV2(
  input: DesktopWorkspaceMemberMutationClientProviderInputV2,
): DesktopWorkspaceMemberMutationClientBindingV2 {
  const config = Object.freeze({ ...input.config });
  return Object.freeze({
    client: createDesktopWorkspaceMemberMutationClient(config),
    bindOperation: (operationConfig) =>
      createDesktopWorkspaceMemberMutationClient(
        Object.freeze({ ...operationConfig }),
      ),
  });
}

function createDesktopWorkspaceMemberMutationClient(
  config: DesktopRuntimeConfig,
): DesktopWorkspaceMemberMutationClient {
  const authority = new DesktopApiClient(config);
  return Object.freeze({
    addWorkspaceMemberForProject: (
      ...args: Parameters<DesktopApiClient['addWorkspaceMemberForProject']>
    ) => authority.addWorkspaceMemberForProject(...args),
    removeWorkspaceMemberForProject: (
      ...args: Parameters<DesktopApiClient['removeWorkspaceMemberForProject']>
    ) => authority.removeWorkspaceMemberForProject(...args),
    updateWorkspaceMemberRoleForProject: (
      ...args: Parameters<DesktopApiClient['updateWorkspaceMemberRoleForProject']>
    ) => authority.updateWorkspaceMemberRoleForProject(...args),
  });
}
