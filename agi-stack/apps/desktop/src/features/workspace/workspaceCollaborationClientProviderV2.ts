import type { DesktopRuntimeConfig } from '../../types';
import {
  desktopCapability,
  type DesktopCapabilitySnapshot,
} from '../runtime/capabilitySnapshot';
import {
  createCapabilityWorkspaceCollaborationClient,
} from './capabilityWorkspaceCollaborationClient';
import { createHttpWorkspaceCollaborationClient } from './httpWorkspaceCollaborationClient';
import type { WorkspaceCollaborationClient } from './workspaceCollaborationClient';

export type WorkspaceCollaborationClientProviderReasonCodeV2 =
  'workspace_collaboration_client_unpublished';

export class WorkspaceCollaborationClientProviderErrorV2 extends Error {
  readonly reasonCode: WorkspaceCollaborationClientProviderReasonCodeV2;

  constructor(reasonCode: WorkspaceCollaborationClientProviderReasonCodeV2) {
    super(reasonCode);
    this.name = 'WorkspaceCollaborationClientProviderErrorV2';
    this.reasonCode = reasonCode;
  }
}

export type WorkspaceCollaborationClientInputV2 = Readonly<{
  config: DesktopRuntimeConfig;
  capabilitySnapshot: DesktopCapabilitySnapshot | null;
}>;

export type WorkspaceCollaborationClientBindingV2 = Readonly<{
  client: WorkspaceCollaborationClient;
}>;

export type WorkspaceCollaborationClientProviderV2 = Readonly<{
  publish: (
    input: WorkspaceCollaborationClientInputV2,
  ) => WorkspaceCollaborationClientBindingV2;
  resolve: () => WorkspaceCollaborationClientBindingV2;
}>;

export function createWorkspaceCollaborationClientProviderV2():
  WorkspaceCollaborationClientProviderV2 {
  let publication: WorkspaceCollaborationClientBindingV2 | null = null;

  return Object.freeze({
    publish(input) {
      const next = createWorkspaceCollaborationClientBindingV2(input);
      publication = next;
      return next;
    },
    resolve() {
      if (publication === null) {
        throw new WorkspaceCollaborationClientProviderErrorV2(
          'workspace_collaboration_client_unpublished',
        );
      }
      return publication;
    },
  });
}

function createWorkspaceCollaborationClientBindingV2(
  input: WorkspaceCollaborationClientInputV2,
): WorkspaceCollaborationClientBindingV2 {
  const config = Object.freeze({ ...input.config });
  const capability = Object.freeze(
    desktopCapability(input.capabilitySnapshot, 'workspace_collaboration'),
  );
  const authority = createHttpWorkspaceCollaborationClient(config);
  const client = createCapabilityWorkspaceCollaborationClient(
    authority,
    capability,
    config.mode,
  );
  return Object.freeze({ client });
}
