import type { DesktopRuntimeConfig } from '../../types';
import type {
  DesktopCapabilityAvailability,
  DesktopCapabilityProvenance,
  DesktopCapabilityScope,
} from '../runtime/capabilitySnapshot';
import {
  createChannelsRouteClient,
  type ChannelsRouteClient,
  type ChannelsRouteScope,
} from './channelsRouteClient';
import {
  createEvolutionRouteClient,
  type EvolutionRouteClient,
  type EvolutionRouteScope,
} from './evolutionRouteClient';
import { NativeRouteClientError } from './nativeRouteHttpClient';
import {
  createProfileRouteClient,
  type ProfileRouteClient,
  type ProfileRouteScope,
} from './profileRouteClient';
import {
  createTemplatesRouteClient,
  type TemplatesRouteClient,
  type TemplatesRouteScope,
} from './templatesRouteClient';

const SERVICE_VERSION = '0.1.0' as const;
const CONTRACT_VERSION = '4.0.0' as const;

export const P2_THIRD_BATCH_CAPABILITY_IDS = Object.freeze([
  'tenant-tenant-evolution',
  'project-project-channels',
  'tenant-tenant-templates',
  'user-profile',
] as const);

export type P2ThirdBatchCapabilityId =
  (typeof P2_THIRD_BATCH_CAPABILITY_IDS)[number];

export type P2ThirdBatchCapabilityProjection = Readonly<{
  capability: DesktopCapabilityAvailability;
  provenance: DesktopCapabilityProvenance;
}>;

export type P2ThirdBatchCapabilitySet = Readonly<
  Record<P2ThirdBatchCapabilityId, P2ThirdBatchCapabilityProjection>
>;

export type P2ThirdBatchCapabilityClient = Readonly<{
  load(signal?: AbortSignal): Promise<P2ThirdBatchCapabilitySet>;
}>;

export type P2ThirdBatchCapabilityDependencies = Readonly<{
  evolution?: Pick<EvolutionRouteClient, 'observe'>;
  channels?: Pick<ChannelsRouteClient, 'observe'>;
  templates?: Pick<TemplatesRouteClient, 'observe'>;
  profile?: Pick<ProfileRouteClient, 'observe'>;
}>;

type RouteObservation = Readonly<{
  scope: Readonly<Record<string, unknown>>;
  authority: DesktopRuntimeConfig['mode'];
  availability: 'available' | 'degraded';
  reasonCode: string | null;
  allowedActions: readonly string[];
  itemCount: number;
}>;

const ACTION_CATALOG = Object.freeze({
  'tenant-tenant-evolution': Object.freeze([
    'view',
    'configure',
    'run',
    'apply-job',
    'reject-job',
  ]),
  'project-project-channels': Object.freeze([
    'view',
    'view-channel-catalog',
    'view-channel-schema',
    'list-channel-configs',
    'create-channel-config',
    'update-channel-config',
    'delete-channel-config',
    'test-channel-config',
  ]),
  'tenant-tenant-templates': Object.freeze([
    'view',
    'list',
    'search',
    'filter',
    'view-detail',
    'install',
    'seed',
    'retry',
  ]),
  'user-profile': Object.freeze([
    'view',
    'update',
    'change-language',
    'change-password',
  ]),
} satisfies Record<P2ThirdBatchCapabilityId, readonly string[]>);

const REASON_PREFIX = Object.freeze({
  'tenant-tenant-evolution': 'skill_evolution',
  'project-project-channels': 'project_channels',
  'tenant-tenant-templates': 'template_marketplace',
  'user-profile': 'user_profile',
} satisfies Record<P2ThirdBatchCapabilityId, string>);

export function createP2ThirdBatchCapabilityClient(
  config: DesktopRuntimeConfig,
  dependencies: P2ThirdBatchCapabilityDependencies = {},
): P2ThirdBatchCapabilityClient {
  const runtime = Object.freeze({ ...config });
  const clients = Object.freeze({
    evolution: dependencies.evolution ?? createEvolutionRouteClient(runtime),
    channels: dependencies.channels ?? createChannelsRouteClient(runtime),
    templates: dependencies.templates ?? createTemplatesRouteClient(runtime),
    profile: dependencies.profile ?? createProfileRouteClient(runtime),
  });

  return Object.freeze({
    async load(signal?: AbortSignal): Promise<P2ThirdBatchCapabilitySet> {
      const tenantId = identifier(runtime.tenantId);
      const projectId = identifier(runtime.projectId);
      const authority = runtime.mode;
      const evolutionScope = tenantId
        ? Object.freeze({ authority, tenantId })
        : null;
      const channelsScope =
        tenantId && projectId
          ? Object.freeze({ authority, tenantId, projectId })
          : null;
      const templatesScope = evolutionScope;
      const profileScope = Object.freeze({ authority });

      const [evolution, channels, templates, profile] = await Promise.all([
        observeRoute(
          'tenant-tenant-evolution',
          evolutionScope,
          (scope) => clients.evolution.observe(scope as EvolutionRouteScope, signal),
          signal,
        ),
        observeRoute(
          'project-project-channels',
          channelsScope,
          (scope) => clients.channels.observe(scope as ChannelsRouteScope, signal),
          signal,
          runtime.mode === 'local'
            ? 'local_channel_runtime_not_applicable'
            : null,
        ),
        observeRoute(
          'tenant-tenant-templates',
          templatesScope,
          (scope) => clients.templates.observe(scope as TemplatesRouteScope, {}, signal),
          signal,
        ),
        observeRoute(
          'user-profile',
          profileScope,
          (scope) => clients.profile.observe(scope as ProfileRouteScope, signal),
          signal,
        ),
      ]);

      return Object.freeze({
        'tenant-tenant-evolution': evolution,
        'project-project-channels': channels,
        'tenant-tenant-templates': templates,
        'user-profile': profile,
      });
    },
  });
}

async function observeRoute(
  id: P2ThirdBatchCapabilityId,
  scope: Readonly<Record<string, unknown>> | null,
  load: (scope: Readonly<Record<string, unknown>>) => Promise<RouteObservation>,
  signal?: AbortSignal,
  notApplicableReasonCode: string | null = null,
): Promise<P2ThirdBatchCapabilityProjection> {
  if (!scope) {
    return declared(
      unavailable(
        `${REASON_PREFIX[id]}_scope_unavailable`,
        capabilityScope(null, null),
      ),
    );
  }
  try {
    const observation = await load(scope);
    return observed(normalizeObservation(id, scope, observation));
  } catch (error) {
    if (signal?.aborted) throw error;
    if (
      error instanceof NativeRouteClientError &&
      notApplicableReasonCode !== null &&
      error.reasonCode === notApplicableReasonCode
    ) {
      return observed(
        notApplicable(
          notApplicableReasonCode,
          capabilityScopeFromRouteScope(scope),
        ),
      );
    }
    return observed(
      unavailable(
        failureReasonCode(id, error),
        capabilityScopeFromRouteScope(scope),
      ),
    );
  }
}

function normalizeObservation(
  id: P2ThirdBatchCapabilityId,
  expectedScope: Readonly<Record<string, unknown>>,
  observation: RouteObservation,
): DesktopCapabilityAvailability {
  if (
    observation.authority !== expectedScope.authority ||
    !sameScope(expectedScope, observation.scope) ||
    !Number.isSafeInteger(observation.itemCount) ||
    observation.itemCount < 0 ||
    !orderedActionSubset(id, observation.allowedActions) ||
    (observation.availability === 'available' && observation.reasonCode !== null) ||
    (observation.availability === 'degraded' && !stableReasonCode(observation.reasonCode))
  ) {
    throw new AuthorityContractError();
  }
  return Object.freeze({
    availability: observation.availability,
    reason_code: observation.reasonCode,
    service_version: SERVICE_VERSION,
    contract_version: CONTRACT_VERSION,
    allowed_actions: Object.freeze([...observation.allowedActions]),
    scope: capabilityScopeFromRouteScope(observation.scope),
    authority_revision: null,
  });
}

function failureReasonCode(id: P2ThirdBatchCapabilityId, error: unknown): string {
  if (error instanceof AuthorityContractError) {
    return `${REASON_PREFIX[id]}_authority_contract_invalid`;
  }
  if (error instanceof NativeRouteClientError) {
    if (error.status === 401 || error.status === 403) {
      return `${REASON_PREFIX[id]}_forbidden`;
    }
    if (error.status === 409 || error.status === 412 || error.status === 428) {
      return `${REASON_PREFIX[id]}_scope_conflict`;
    }
    if (error.status === 501 && stableReasonCode(error.reasonCode)) {
      return error.reasonCode;
    }
    if (error.reasonCode.endsWith('_contract_invalid')) {
      return `${REASON_PREFIX[id]}_authority_contract_invalid`;
    }
  }
  return `${REASON_PREFIX[id]}_authority_unavailable`;
}

function orderedActionSubset(
  id: P2ThirdBatchCapabilityId,
  input: unknown,
): input is readonly string[] {
  if (!Array.isArray(input) || input.length === 0 || input[0] !== 'view') {
    return false;
  }
  let previousIndex = -1;
  const seen = new Set<string>();
  for (const action of input) {
    if (typeof action !== 'string' || seen.has(action)) return false;
    const index = ACTION_CATALOG[id].indexOf(action);
    if (index <= previousIndex) return false;
    previousIndex = index;
    seen.add(action);
  }
  return true;
}

function sameScope(
  expected: Readonly<Record<string, unknown>>,
  actual: Readonly<Record<string, unknown>>,
): boolean {
  const keys = Object.keys(expected);
  return (
    keys.length === Object.keys(actual).length &&
    keys.every((key) => actual[key] === expected[key])
  );
}

function capabilityScopeFromRouteScope(
  scope: Readonly<Record<string, unknown>>,
): DesktopCapabilityScope {
  return capabilityScope(identifier(scope.tenantId), identifier(scope.projectId));
}

function capabilityScope(
  tenantId: string | null,
  projectId: string | null,
): DesktopCapabilityScope {
  return {
    tenant_id: tenantId,
    project_id: projectId,
    workspace_id: null,
    instance_id: null,
  };
}

function unavailable(
  reasonCode: string,
  scope: DesktopCapabilityScope,
): DesktopCapabilityAvailability {
  return Object.freeze({
    availability: 'unavailable',
    reason_code: reasonCode,
    service_version: null,
    contract_version: null,
    allowed_actions: Object.freeze([]),
    scope,
    authority_revision: null,
  });
}

function notApplicable(
  reasonCode: string,
  scope: DesktopCapabilityScope,
): DesktopCapabilityAvailability {
  return Object.freeze({
    ...unavailable(reasonCode, scope),
    availability: 'not_applicable',
  });
}

function observed(
  capability: DesktopCapabilityAvailability,
): P2ThirdBatchCapabilityProjection {
  return Object.freeze({ capability, provenance: 'observed' });
}

function declared(
  capability: DesktopCapabilityAvailability,
): P2ThirdBatchCapabilityProjection {
  return Object.freeze({ capability, provenance: 'declared' });
}

function identifier(value: unknown): string | null {
  return typeof value === 'string' && value.trim() === value && value.length > 0
    ? value
    : null;
}

function stableReasonCode(value: unknown): value is string {
  return (
    typeof value === 'string' &&
    /^[a-z][a-z0-9]*(?:_[a-z0-9]+)+$/.test(value)
  );
}

class AuthorityContractError extends Error {}
