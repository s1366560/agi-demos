import { DesktopApiClient } from '../../api/client';
import type { DesktopRuntimeConfig } from '../../types';

type DesktopWorkspaceExecutionSnapshotMethod =
  | 'listTasks'
  | 'getPlanSnapshot';

export type DesktopWorkspaceExecutionSnapshotClient = Readonly<
  Pick<DesktopApiClient, DesktopWorkspaceExecutionSnapshotMethod>
>;

export type DesktopWorkspaceExecutionSnapshotClientProviderReasonCodeV2 =
  'desktop_workspace_execution_snapshot_client_unpublished';

export class DesktopWorkspaceExecutionSnapshotClientProviderErrorV2 extends Error {
  readonly reasonCode: DesktopWorkspaceExecutionSnapshotClientProviderReasonCodeV2;

  constructor(reasonCode: DesktopWorkspaceExecutionSnapshotClientProviderReasonCodeV2) {
    super(reasonCode);
    this.name = 'DesktopWorkspaceExecutionSnapshotClientProviderErrorV2';
    this.reasonCode = reasonCode;
  }
}

export type DesktopWorkspaceExecutionSnapshotClientProviderInputV2 = Readonly<{
  config: DesktopRuntimeConfig;
}>;

export type DesktopWorkspaceExecutionSnapshotClientBindingV2 = Readonly<{
  client: DesktopWorkspaceExecutionSnapshotClient;
  bindOperation: (
    config: DesktopRuntimeConfig,
  ) => DesktopWorkspaceExecutionSnapshotClient;
}>;

export type DesktopWorkspaceExecutionSnapshotClientProviderV2 = Readonly<{
  publish: (
    input: DesktopWorkspaceExecutionSnapshotClientProviderInputV2,
  ) => DesktopWorkspaceExecutionSnapshotClientBindingV2;
  resolve: () => DesktopWorkspaceExecutionSnapshotClientBindingV2;
}>;

export function createDesktopWorkspaceExecutionSnapshotClientProviderV2():
  DesktopWorkspaceExecutionSnapshotClientProviderV2 {
  let publication: DesktopWorkspaceExecutionSnapshotClientBindingV2 | null = null;

  return Object.freeze({
    publish(input) {
      const next = createDesktopWorkspaceExecutionSnapshotClientBindingV2(input);
      publication = next;
      return next;
    },
    resolve() {
      if (publication === null) {
        throw new DesktopWorkspaceExecutionSnapshotClientProviderErrorV2(
          'desktop_workspace_execution_snapshot_client_unpublished',
        );
      }
      return publication;
    },
  });
}

function createDesktopWorkspaceExecutionSnapshotClientBindingV2(
  input: DesktopWorkspaceExecutionSnapshotClientProviderInputV2,
): DesktopWorkspaceExecutionSnapshotClientBindingV2 {
  const config = Object.freeze({ ...input.config });
  return Object.freeze({
    client: createDesktopWorkspaceExecutionSnapshotClient(config),
    bindOperation: (operationConfig) =>
      createDesktopWorkspaceExecutionSnapshotClient(Object.freeze({ ...operationConfig })),
  });
}

function createDesktopWorkspaceExecutionSnapshotClient(
  config: DesktopRuntimeConfig,
): DesktopWorkspaceExecutionSnapshotClient {
  const authority = new DesktopApiClient(config);
  return Object.freeze({
    listTasks: (...args: Parameters<DesktopApiClient['listTasks']>) =>
      authority.listTasks(...args),
    getPlanSnapshot: (...args: Parameters<DesktopApiClient['getPlanSnapshot']>) =>
      authority.getPlanSnapshot(...args),
  });
}
