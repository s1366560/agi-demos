import {
  PLUGIN_MODULE_CATALOG_V2,
  RuntimeV2Error,
  type ContextV2,
  type PluginDefinitionV2,
} from '@agistack/plugin-runtime';

import type { ProjectKnowledgeScope } from '../features/project-knowledge/projectKnowledgeClient';
import type { ProjectPlaybooksEventSource } from '../features/project-playbooks/projectPlaybooksEventSource';
import type { DesktopRuntimeConfig } from '../types';
import {
  cloneDesktopProjectPlaybooksEventsConfigV2,
  prepareDesktopProjectPlaybooksEventsOperationV2,
  type DesktopProjectPlaybooksEventsOperationInputV2,
  type PreparedDesktopProjectPlaybooksEventsOperationV2,
} from './desktopProjectPlaybooksEventsOperationContractV2';
import { createDesktopProjectPlaybooksEventsSocketAuthorityV2 } from './desktopProjectPlaybooksEventsSocketProjectionV2';
import type {
  DesktopRendererGenerationActionsV2,
  DesktopRendererServiceOperationLeaseAdmissionV2,
} from './desktopRendererGenerationContextV2';

export type { DesktopProjectPlaybooksEventsOperationInputV2 } from './desktopProjectPlaybooksEventsOperationContractV2';

export const DESKTOP_PROJECT_PLAYBOOKS_EVENTS_AUTHORITY_MODULE_REF_V2 =
  'builtin://memstack/desktop/project-playbooks-events-authority';
export const DESKTOP_PROJECT_PLAYBOOKS_EVENTS_AUTHORITY_SERVICE_V2 =
  'service:desktop-renderer.project-playbooks-events-authority';
export const DESKTOP_PROJECT_PLAYBOOKS_EVENTS_AUTHORITY_VERSION_V2 = '1.0.0';

export interface DesktopProjectPlaybooksEventsAuthorityV2 {
  readonly subscribe: (listener: () => void) => () => void;
}

export interface DesktopProjectPlaybooksEventsAuthorityServiceV2 {
  readonly bindOperation: (
    config: DesktopRuntimeConfig,
    scope: ProjectKnowledgeScope,
  ) => DesktopProjectPlaybooksEventsAuthorityV2;
}

export interface DesktopProjectPlaybooksEventsOperationsV2 {
  readonly subscribeProjectPlaybooksEvents: (
    input: DesktopProjectPlaybooksEventsOperationInputV2,
  ) => () => void;
}

type ServiceAdmissionRejectionV2 = Extract<
  DesktopRendererServiceOperationLeaseAdmissionV2<never>,
  { status: 'rejected' }
>;
type GenerationActionsUnavailableV2 = Readonly<{
  reasonCode: 'desktop_renderer_generation_actions_unavailable';
  runtimeCode?: undefined;
}>;
type AuthorityAdmissionRejectionV2 =
  | ServiceAdmissionRejectionV2
  | GenerationActionsUnavailableV2;

export class DesktopProjectPlaybooksEventsAuthorityUnavailableErrorV2 extends Error {
  readonly reasonCode: AuthorityAdmissionRejectionV2['reasonCode'];
  readonly runtimeCode: string | undefined;

  constructor(rejection: AuthorityAdmissionRejectionV2) {
    super(rejection.reasonCode);
    this.name = 'DesktopProjectPlaybooksEventsAuthorityUnavailableErrorV2';
    this.reasonCode = rejection.reasonCode;
    this.runtimeCode = rejection.runtimeCode;
  }
}

export function applyDesktopProjectPlaybooksEventsAuthorityV2(
  context: ContextV2,
  config: Readonly<Record<string, unknown>>,
): void {
  if (Object.keys(config).length !== 1 || config.strategy !== 'desktop-vault-socket') {
    throw new RuntimeV2Error(
      'desktop_project_playbooks_events_authority_config_invalid',
      'desktop project playbooks events authority requires desktop-vault-socket strategy',
    );
  }
  const service: DesktopProjectPlaybooksEventsAuthorityServiceV2 = Object.freeze({
    bindOperation: createDesktopProjectPlaybooksEventsSocketAuthorityV2,
  });
  context.provide(DESKTOP_PROJECT_PLAYBOOKS_EVENTS_AUTHORITY_SERVICE_V2, service);
}

export const desktopProjectPlaybooksEventsAuthorityDefinitionV2: PluginDefinitionV2 =
  Object.freeze({
    moduleRef: DESKTOP_PROJECT_PLAYBOOKS_EVENTS_AUTHORITY_MODULE_REF_V2,
    contractDigest: generatedContractDigestV2(),
    apply: applyDesktopProjectPlaybooksEventsAuthorityV2,
  });

export function createDesktopProjectPlaybooksEventsOperationsV2(
  resolveActions: () => DesktopRendererGenerationActionsV2 | null,
): DesktopProjectPlaybooksEventsOperationsV2 {
  return Object.freeze({
    subscribeProjectPlaybooksEvents(input: DesktopProjectPlaybooksEventsOperationInputV2) {
      const prepared = prepareDesktopProjectPlaybooksEventsOperationV2(input);
      const actions = requireGenerationActionsV2(resolveActions());
      return beginDesktopProjectPlaybooksEventsSubscriptionV2(actions, prepared);
    },
  });
}

export function createDesktopProjectPlaybooksEventSourceV2(
  operations: DesktopProjectPlaybooksEventsOperationsV2,
  config: DesktopRuntimeConfig,
): ProjectPlaybooksEventSource {
  const operationConfig = cloneDesktopProjectPlaybooksEventsConfigV2(config);
  return Object.freeze({
    subscribe(scope, listener) {
      return operations.subscribeProjectPlaybooksEvents({
        config: operationConfig,
        scope,
        listener,
      });
    },
  });
}

function beginDesktopProjectPlaybooksEventsSubscriptionV2(
  actions: DesktopRendererGenerationActionsV2,
  prepared: PreparedDesktopProjectPlaybooksEventsOperationV2,
): () => void {
  let active = true;
  let disconnect: (() => void) | null = null;
  let release: (() => Promise<void>) | null = null;
  let releaseStarted = false;

  const releaseOnce = (): Promise<void> => {
    if (releaseStarted || release === null) return Promise.resolve();
    releaseStarted = true;
    return release();
  };

  const start = async (): Promise<void> => {
    const admission =
      await actions.acquireServiceOperationLease<DesktopProjectPlaybooksEventsAuthorityServiceV2>({
        service: DESKTOP_PROJECT_PLAYBOOKS_EVENTS_AUTHORITY_SERVICE_V2,
        version: DESKTOP_PROJECT_PLAYBOOKS_EVENTS_AUTHORITY_VERSION_V2,
        scope: Object.freeze({
          kind: 'project',
          tenant_id: prepared.scope.tenantId,
          project_id: prepared.scope.projectId,
        }),
      });
    if (admission.status === 'rejected') {
      throw new DesktopProjectPlaybooksEventsAuthorityUnavailableErrorV2(admission);
    }
    release = admission.release;
    if (!active) {
      await releaseOnce();
      return;
    }
    try {
      const nextDisconnect = await admission.useService((candidate) => {
        const service = requireEventsServiceV2(candidate);
        const authority = requireEventsAuthorityV2(
          service.bindOperation(prepared.config, prepared.scope),
        );
        return authority.subscribe(() => {
          if (active) prepared.listener();
        });
      });
      if (typeof nextDisconnect !== 'function') throw invalidServiceV2();
      if (active) disconnect = nextDisconnect;
      else {
        nextDisconnect();
        await releaseOnce();
      }
    } catch (error) {
      try {
        await releaseOnce();
      } catch {
        // The subscription failure is authoritative over disposer failure.
      }
      throw error;
    }
  };
  void start().catch(() => undefined);

  return () => {
    if (!active) return;
    active = false;
    let disconnectError: unknown = null;
    try {
      disconnect?.();
    } catch (error) {
      disconnectError = error;
    } finally {
      disconnect = null;
      void releaseOnce().catch(() => undefined);
    }
    if (disconnectError !== null) throw disconnectError;
  };
}

function requireEventsServiceV2(
  value: unknown,
): DesktopProjectPlaybooksEventsAuthorityServiceV2 {
  if (
    !isPlainRecordV2(value) ||
    Object.keys(value).length !== 1 ||
    typeof value.bindOperation !== 'function'
  ) {
    throw invalidServiceV2();
  }
  return value as unknown as DesktopProjectPlaybooksEventsAuthorityServiceV2;
}

function requireEventsAuthorityV2(value: unknown): DesktopProjectPlaybooksEventsAuthorityV2 {
  if (
    !isPlainRecordV2(value) ||
    Object.keys(value).length !== 1 ||
    typeof value.subscribe !== 'function'
  ) {
    throw invalidServiceV2();
  }
  return value as unknown as DesktopProjectPlaybooksEventsAuthorityV2;
}

function requireGenerationActionsV2(
  actions: DesktopRendererGenerationActionsV2 | null,
): DesktopRendererGenerationActionsV2 {
  if (actions !== null) return actions;
  throw new DesktopProjectPlaybooksEventsAuthorityUnavailableErrorV2({
    reasonCode: 'desktop_renderer_generation_actions_unavailable',
  });
}

function invalidServiceV2(): RuntimeV2Error {
  return new RuntimeV2Error(
    'desktop_project_playbooks_events_service_invalid',
    'desktop project playbooks events authority service is invalid',
  );
}

function isPlainRecordV2(value: unknown): value is Record<string, unknown> {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) return false;
  const prototype = Object.getPrototypeOf(value);
  return prototype === Object.prototype || prototype === null;
}

function generatedContractDigestV2(): string {
  const entry = PLUGIN_MODULE_CATALOG_V2.modules.find(
    (candidate) =>
      candidate.module_ref === DESKTOP_PROJECT_PLAYBOOKS_EVENTS_AUTHORITY_MODULE_REF_V2,
  );
  if (entry === undefined) {
    throw new RuntimeV2Error(
      'desktop_project_playbooks_events_authority_catalog_missing',
      'desktop project playbooks events authority is absent from the generated catalog',
    );
  }
  return entry.contract_digest;
}
