import { DesktopApiClient } from '../../api/client';
import type { DesktopRuntimeConfig } from '../../types';

type DesktopWorkspaceLifecycleMethod =
  | 'createWorkspaceForProject'
  | 'updateWorkspaceForProject';

export type DesktopWorkspaceLifecycleClient = Readonly<
  Pick<DesktopApiClient, DesktopWorkspaceLifecycleMethod>
>;

export type DesktopWorkspaceLifecycleClientProviderReasonCodeV2 =
  'desktop_workspace_lifecycle_client_unpublished';

export class DesktopWorkspaceLifecycleClientProviderErrorV2 extends Error {
  readonly reasonCode: DesktopWorkspaceLifecycleClientProviderReasonCodeV2;

  constructor(reasonCode: DesktopWorkspaceLifecycleClientProviderReasonCodeV2) {
    super(reasonCode);
    this.name = 'DesktopWorkspaceLifecycleClientProviderErrorV2';
    this.reasonCode = reasonCode;
  }
}

export type DesktopWorkspaceLifecycleClientProviderInputV2 = Readonly<{
  config: DesktopRuntimeConfig;
}>;

export type DesktopWorkspaceLifecycleClientBindingV2 = Readonly<{
  client: DesktopWorkspaceLifecycleClient;
  bindOperation: (config: DesktopRuntimeConfig) => DesktopWorkspaceLifecycleClient;
}>;

export type DesktopWorkspaceLifecycleClientProviderV2 = Readonly<{
  publish: (
    input: DesktopWorkspaceLifecycleClientProviderInputV2,
  ) => DesktopWorkspaceLifecycleClientBindingV2;
  resolve: () => DesktopWorkspaceLifecycleClientBindingV2;
}>;

export function createDesktopWorkspaceLifecycleClientProviderV2():
  DesktopWorkspaceLifecycleClientProviderV2 {
  let publication: DesktopWorkspaceLifecycleClientBindingV2 | null = null;

  return Object.freeze({
    publish(input) {
      const next = createDesktopWorkspaceLifecycleClientBindingV2(input);
      publication = next;
      return next;
    },
    resolve() {
      if (publication === null) {
        throw new DesktopWorkspaceLifecycleClientProviderErrorV2(
          'desktop_workspace_lifecycle_client_unpublished',
        );
      }
      return publication;
    },
  });
}

function createDesktopWorkspaceLifecycleClientBindingV2(
  input: DesktopWorkspaceLifecycleClientProviderInputV2,
): DesktopWorkspaceLifecycleClientBindingV2 {
  const config = Object.freeze({ ...input.config });
  return Object.freeze({
    client: createDesktopWorkspaceLifecycleClient(config),
    bindOperation: (operationConfig) =>
      createDesktopWorkspaceLifecycleClient(Object.freeze({ ...operationConfig })),
  });
}

function createDesktopWorkspaceLifecycleClient(
  config: DesktopRuntimeConfig,
): DesktopWorkspaceLifecycleClient {
  const authority = new DesktopApiClient(config);
  return Object.freeze({
    createWorkspaceForProject: (
      ...args: Parameters<DesktopApiClient['createWorkspaceForProject']>
    ) => authority.createWorkspaceForProject(...args),
    updateWorkspaceForProject: (
      ...args: Parameters<DesktopApiClient['updateWorkspaceForProject']>
    ) => authority.updateWorkspaceForProject(...args),
  });
}
