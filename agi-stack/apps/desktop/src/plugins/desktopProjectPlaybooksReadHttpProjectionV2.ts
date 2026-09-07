import type { VaultBoundCloudRequestBroker } from '../api/cloudRequestBroker';
import type { DesktopRuntimeConfig } from '../types';
import {
  isRecord,
  optionalText,
  projectKnowledgeError,
  requireIdentifier,
  requireNonnegativeInteger,
  requireText,
  type ProjectKnowledgeReadOptions,
  type ProjectKnowledgeScope,
} from '../features/project-knowledge/projectKnowledgeClient';
import {
  PROJECT_PLAYBOOKS_LOCAL_REASON,
  type ProjectPlaybook,
  type ProjectPlaybooksClient,
  type ProjectPlaybooksSnapshot,
  type ProjectPlaybookStep,
  type ProjectReflectionVerdict,
  type ReflectionVerdictAction,
} from '../features/project-playbooks/projectPlaybooksClient';

const ACTIONS = Object.freeze(['view', 'list', 'refresh', 'review-verdicts']);
const VERDICT_ACTIONS = new Set<ReflectionVerdictAction>([
  'create',
  'reinforce',
  'deprecate',
  'noop',
]);

export function createDesktopProjectPlaybooksReadHttpAuthorityV2(
  config: DesktopRuntimeConfig,
  broker: VaultBoundCloudRequestBroker | null,
): ProjectPlaybooksClient {
  const runtimeConfig = Object.freeze({ ...config });
  return Object.freeze({
    async load(scope, options) {
      const currentScope = requireScopeV2(runtimeConfig, scope, broker);
      const scopeRevision = await observeScopeV2(broker!, currentScope, options);
      const root = `/api/v1/projects/${encodeURIComponent(currentScope.projectId)}`;
      const [playbookPayload, verdictPayload] = await Promise.all([
        broker!.requestJson({
          path: `${root}/playbooks?limit=200`,
          signal: options?.signal,
        }),
        broker!.requestJson({
          path: `${root}/reflection-verdicts?limit=200`,
          signal: options?.signal,
        }),
      ]);
      return Object.freeze({
        scope: currentScope,
        scopeRevision,
        authority: 'cloud',
        availability: 'available',
        reasonCode: null,
        allowedActions: ACTIONS,
        playbooks: parsePlaybooksV2(playbookPayload, currentScope.projectId),
        verdicts: parseVerdictsV2(verdictPayload, currentScope.projectId),
      });
    },
  });
}

function requireScopeV2(
  config: DesktopRuntimeConfig,
  scope: ProjectKnowledgeScope,
  broker: VaultBoundCloudRequestBroker | null,
): ProjectKnowledgeScope {
  const tenantId = requireIdentifier(scope.tenantId, 'project_playbooks_tenant_scope_invalid');
  const projectId = requireIdentifier(scope.projectId, 'project_playbooks_project_scope_invalid');
  if (scope.authority === 'local') {
    throw projectKnowledgeError(PROJECT_PLAYBOOKS_LOCAL_REASON, 503);
  }
  if (scope.authority !== 'cloud') {
    throw projectKnowledgeError('project_playbooks_authority_mode_mismatch', 409);
  }
  if (config.tenantId !== tenantId || config.projectId !== projectId) {
    throw projectKnowledgeError('project_playbooks_configured_scope_mismatch', 409);
  }
  if (!broker) throw projectKnowledgeError('cloud_request_broker_missing', 501);
  return Object.freeze({ authority: 'cloud', tenantId, projectId });
}

async function observeScopeV2(
  broker: VaultBoundCloudRequestBroker,
  scope: ProjectKnowledgeScope,
  options?: ProjectKnowledgeReadOptions,
): Promise<number> {
  const payload = await broker.requestJson({
    path: '/api/v1/workspace-context',
    signal: options?.signal,
  });
  if (!isRecord(payload) || !isRecord(payload.context)) {
    throw projectKnowledgeError('project_playbooks_scope_contract_invalid');
  }
  if (
    payload.context.tenant_id !== scope.tenantId ||
    payload.context.project_id !== scope.projectId
  ) {
    throw projectKnowledgeError('project_playbooks_scope_conflict', 409);
  }
  return requireNonnegativeInteger(
    payload.context.revision,
    'project_playbooks_scope_contract_invalid',
  );
}

function parsePlaybooksV2(payload: unknown, projectId: string): readonly ProjectPlaybook[] {
  if (!isRecord(payload) || !Array.isArray(payload.items)) {
    throw projectKnowledgeError('project_playbooks_contract_invalid');
  }
  return Object.freeze(payload.items.map((item) => parsePlaybookV2(item, projectId)));
}

function parsePlaybookV2(value: unknown, projectId: string): ProjectPlaybook {
  if (
    !isRecord(value) ||
    value.project_id !== projectId ||
    !isRecord(value.trigger) ||
    !Array.isArray(value.steps)
  ) {
    throw projectKnowledgeError('project_playbook_contract_invalid');
  }
  const frictionKinds = stringArrayV2(
    value.trigger.friction_kinds,
    'project_playbook_trigger_contract_invalid',
  );
  if (!Array.isArray(value.trigger.lane_transitions)) {
    throw projectKnowledgeError('project_playbook_trigger_contract_invalid');
  }
  const laneTransitions = Object.freeze(
    value.trigger.lane_transitions.map((transition) => {
      if (
        !Array.isArray(transition) ||
        transition.length !== 2 ||
        typeof transition[0] !== 'string' ||
        typeof transition[1] !== 'string'
      ) {
        throw projectKnowledgeError('project_playbook_trigger_contract_invalid');
      }
      return Object.freeze([transition[0], transition[1]] as const);
    }),
  );
  return Object.freeze({
    id: requireIdentifier(value.id, 'project_playbook_contract_invalid'),
    projectId,
    name: requireText(value.name, 'project_playbook_contract_invalid'),
    status: requireIdentifier(value.status, 'project_playbook_contract_invalid'),
    trigger: Object.freeze({
      description: requireText(
        value.trigger.description,
        'project_playbook_trigger_contract_invalid',
      ),
      frictionKinds,
      laneTransitions,
    }),
    steps: Object.freeze(value.steps.map(parseStepV2)),
    hitCount: requireNonnegativeInteger(value.hit_count, 'project_playbook_contract_invalid'),
    lastUsedAt: optionalText(value.last_used_at, 'project_playbook_contract_invalid'),
    createdAt: requireIdentifier(value.created_at, 'project_playbook_contract_invalid'),
    updatedAt: requireIdentifier(value.updated_at, 'project_playbook_contract_invalid'),
  });
}

function parseStepV2(value: unknown): ProjectPlaybookStep {
  if (!isRecord(value)) throw projectKnowledgeError('project_playbook_step_contract_invalid');
  return Object.freeze({
    order: requireNonnegativeInteger(value.order, 'project_playbook_step_contract_invalid'),
    instruction: requireText(value.instruction, 'project_playbook_step_contract_invalid'),
    rationale: optionalText(value.rationale, 'project_playbook_step_contract_invalid'),
  });
}

function parseVerdictsV2(payload: unknown, projectId: string): readonly ProjectReflectionVerdict[] {
  if (!isRecord(payload) || !Array.isArray(payload.items)) {
    throw projectKnowledgeError('project_reflection_verdicts_contract_invalid');
  }
  return Object.freeze(payload.items.map((item) => parseVerdictV2(item, projectId)));
}

function parseVerdictV2(value: unknown, projectId: string): ProjectReflectionVerdict {
  if (
    !isRecord(value) ||
    value.project_id !== projectId ||
    !VERDICT_ACTIONS.has(value.action as ReflectionVerdictAction)
  ) {
    throw projectKnowledgeError('project_reflection_verdict_contract_invalid');
  }
  return Object.freeze({
    id: requireIdentifier(value.id, 'project_reflection_verdict_contract_invalid'),
    projectId,
    action: value.action as ReflectionVerdictAction,
    playbookId: optionalText(value.playbook_id, 'project_reflection_verdict_contract_invalid'),
    rationale: requireText(value.rationale, 'project_reflection_verdict_contract_invalid'),
    proposedPayload:
      value.proposed_payload === null
        ? null
        : cloneRecordV2(value.proposed_payload, 'project_reflection_verdict_contract_invalid'),
    createdAt: requireIdentifier(value.created_at, 'project_reflection_verdict_contract_invalid'),
  });
}

function stringArrayV2(value: unknown, reasonCode: string): readonly string[] {
  if (!Array.isArray(value) || value.some((item) => typeof item !== 'string')) {
    throw projectKnowledgeError(reasonCode);
  }
  return Object.freeze([...value]);
}

function cloneRecordV2(value: unknown, reasonCode: string): Readonly<Record<string, unknown>> {
  if (!isRecord(value)) throw projectKnowledgeError(reasonCode);
  return Object.freeze({ ...value });
}

export function requireDesktopProjectPlaybooksSnapshotV2(
  value: unknown,
  scope: ProjectKnowledgeScope,
): ProjectPlaybooksSnapshot {
  if (
    !isRecord(value) ||
    !isRecord(value.scope) ||
    value.scope.authority !== 'cloud' ||
    value.scope.tenantId !== scope.tenantId ||
    value.scope.projectId !== scope.projectId ||
    value.authority !== 'cloud' ||
    value.availability !== 'available' ||
    value.reasonCode !== null ||
    !Number.isSafeInteger(value.scopeRevision) ||
    Number(value.scopeRevision) < 0 ||
    !Array.isArray(value.allowedActions) ||
    !Array.isArray(value.playbooks) ||
    !Array.isArray(value.verdicts)
  ) {
    throw projectKnowledgeError('desktop_project_playbooks_read_service_contract_invalid');
  }
  return value as ProjectPlaybooksSnapshot;
}
