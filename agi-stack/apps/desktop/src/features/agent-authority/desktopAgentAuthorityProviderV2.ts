import type { DesktopRuntimeConfig } from '../../types';
import { createDesktopAgentAuthorityAdapter } from './cloudAgentAuthorityClient';
import type {
  CloudAgentAuthorityScope,
  DesktopAgentAuthorityAdapter,
} from './agentAuthorityTypes';

export type DesktopAgentAuthorityProviderReasonCodeV2 =
  'desktop_agent_authority_unpublished';

export class DesktopAgentAuthorityProviderErrorV2 extends Error {
  readonly reasonCode: DesktopAgentAuthorityProviderReasonCodeV2;

  constructor(reasonCode: DesktopAgentAuthorityProviderReasonCodeV2) {
    super(reasonCode);
    this.name = 'DesktopAgentAuthorityProviderErrorV2';
    this.reasonCode = reasonCode;
  }
}

export type DesktopAgentAuthorityProviderInputV2 = Readonly<{
  config: DesktopRuntimeConfig;
  principalId: string | null | undefined;
}>;

export type DesktopAgentAuthorityOperationBindingV2 = Readonly<{
  adapter: DesktopAgentAuthorityAdapter;
  cloudScope: CloudAgentAuthorityScope | undefined;
}>;

export type DesktopAgentAuthorityBindingV2 = DesktopAgentAuthorityOperationBindingV2 &
  Readonly<{
    bindOperation: (
      input: DesktopAgentAuthorityProviderInputV2,
    ) => DesktopAgentAuthorityOperationBindingV2;
  }>;

export type DesktopAgentAuthorityProviderV2 = Readonly<{
  publish: (input: DesktopAgentAuthorityProviderInputV2) => DesktopAgentAuthorityBindingV2;
  resolve: () => DesktopAgentAuthorityBindingV2;
}>;

export function createDesktopAgentAuthorityProviderV2(): DesktopAgentAuthorityProviderV2 {
  let publication: DesktopAgentAuthorityBindingV2 | null = null;

  return Object.freeze({
    publish(input) {
      const next = createDesktopAgentAuthorityBindingV2(input);
      publication = next;
      return next;
    },
    resolve() {
      if (publication === null) {
        throw new DesktopAgentAuthorityProviderErrorV2(
          'desktop_agent_authority_unpublished',
        );
      }
      return publication;
    },
  });
}

function createDesktopAgentAuthorityBindingV2(
  input: DesktopAgentAuthorityProviderInputV2,
): DesktopAgentAuthorityBindingV2 {
  const operation = createDesktopAgentAuthorityOperationBindingV2(input);
  return Object.freeze({
    ...operation,
    bindOperation: (operationInput) =>
      createDesktopAgentAuthorityOperationBindingV2(operationInput),
  });
}

function createDesktopAgentAuthorityOperationBindingV2(
  input: DesktopAgentAuthorityProviderInputV2,
): DesktopAgentAuthorityOperationBindingV2 {
  const config = Object.freeze({ ...input.config });
  const adapter = createDesktopAgentAuthorityAdapter(config);
  const cloudScope = createCloudAgentAuthorityScope(config, input.principalId);
  return Object.freeze({ adapter, cloudScope });
}

function createCloudAgentAuthorityScope(
  config: DesktopRuntimeConfig,
  principalId: string | null | undefined,
): CloudAgentAuthorityScope | undefined {
  if (
    config.mode !== 'cloud' ||
    !principalId ||
    config.tenantId.trim().length === 0 ||
    config.projectId.trim().length === 0
  ) {
    return undefined;
  }
  return Object.freeze({
    authority: 'cloud',
    principalId,
    tenantId: config.tenantId,
    projectId: config.projectId,
  });
}
