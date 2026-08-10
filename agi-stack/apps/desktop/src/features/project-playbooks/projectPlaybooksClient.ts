import type { VaultBoundCloudRequestBroker } from '../../api/cloudRequestBroker';
import type { DesktopRuntimeConfig } from '../../types';
import {
  isRecord,
  optionalText,
  projectKnowledgeError,
  requireIdentifier,
  requireNonnegativeInteger,
  requireText,
  type ProjectKnowledgeReadOptions,
  type ProjectKnowledgeScope,
  type ProjectKnowledgeSnapshotBase,
} from '../project-knowledge/projectKnowledgeClient';

export const PROJECT_PLAYBOOKS_ROUTE_ID = 'project-playbooks' as const;
export const PROJECT_PLAYBOOKS_LOCAL_REASON =
  'local_project_playbooks_cloud_authority_unavailable' as const;

export type ProjectPlaybookTrigger = Readonly<{
  description: string;
  frictionKinds: readonly string[];
  laneTransitions: readonly (readonly [string, string])[];
}>;
export type ProjectPlaybookStep = Readonly<{
  order: number;
  instruction: string;
  rationale: string | null;
}>;
export type ProjectPlaybook = Readonly<{
  id: string;
  projectId: string;
  name: string;
  status: string;
  trigger: ProjectPlaybookTrigger;
  steps: readonly ProjectPlaybookStep[];
  hitCount: number;
  lastUsedAt: string | null;
  createdAt: string;
  updatedAt: string;
}>;
export type ReflectionVerdictAction = 'create' | 'reinforce' | 'deprecate' | 'noop';
export type ProjectReflectionVerdict = Readonly<{
  id: string;
  projectId: string;
  action: ReflectionVerdictAction;
  playbookId: string | null;
  rationale: string;
  proposedPayload: Readonly<Record<string, unknown>> | null;
  createdAt: string;
}>;
export type ProjectPlaybooksSnapshot = ProjectKnowledgeSnapshotBase &
  Readonly<{
    playbooks: readonly ProjectPlaybook[];
    verdicts: readonly ProjectReflectionVerdict[];
  }>;
export type ProjectPlaybooksClient = Readonly<{
  load(
    scope: ProjectKnowledgeScope,
    options?: ProjectKnowledgeReadOptions,
  ): Promise<ProjectPlaybooksSnapshot>;
}>;

const ACTIONS = Object.freeze(['view', 'list', 'refresh', 'review-verdicts']);
const VERDICT_ACTIONS = new Set<ReflectionVerdictAction>([
  'create',
  'reinforce',
  'deprecate',
  'noop',
]);

export function createProjectPlaybooksClient(
  config: DesktopRuntimeConfig,
  broker: VaultBoundCloudRequestBroker | null = null,
): ProjectPlaybooksClient {
  const runtimeConfig = Object.freeze({ ...config });
  return Object.freeze({
    async load(scope, options) {
      const currentScope = requireProjectPlaybooksScope(runtimeConfig, scope, broker);
      const scopeRevision = await observeScope(broker!, currentScope, options);
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
        playbooks: parsePlaybooks(playbookPayload, currentScope.projectId),
        verdicts: parseVerdicts(verdictPayload, currentScope.projectId),
      });
    },
  });
}

function requireProjectPlaybooksScope(
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

async function observeScope(
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

function parsePlaybooks(payload: unknown, projectId: string): readonly ProjectPlaybook[] {
  if (!isRecord(payload) || !Array.isArray(payload.items)) {
    throw projectKnowledgeError('project_playbooks_contract_invalid');
  }
  return Object.freeze(payload.items.map((item) => parsePlaybook(item, projectId)));
}

function parsePlaybook(value: unknown, projectId: string): ProjectPlaybook {
  if (
    !isRecord(value) ||
    value.project_id !== projectId ||
    !isRecord(value.trigger) ||
    !Array.isArray(value.steps)
  ) {
    throw projectKnowledgeError('project_playbook_contract_invalid');
  }
  const frictionKinds = stringArray(
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
    steps: Object.freeze(value.steps.map(parseStep)),
    hitCount: requireNonnegativeInteger(value.hit_count, 'project_playbook_contract_invalid'),
    lastUsedAt: optionalText(value.last_used_at, 'project_playbook_contract_invalid'),
    createdAt: requireIdentifier(value.created_at, 'project_playbook_contract_invalid'),
    updatedAt: requireIdentifier(value.updated_at, 'project_playbook_contract_invalid'),
  });
}

function parseStep(value: unknown): ProjectPlaybookStep {
  if (!isRecord(value)) throw projectKnowledgeError('project_playbook_step_contract_invalid');
  return Object.freeze({
    order: requireNonnegativeInteger(value.order, 'project_playbook_step_contract_invalid'),
    instruction: requireText(value.instruction, 'project_playbook_step_contract_invalid'),
    rationale: optionalText(value.rationale, 'project_playbook_step_contract_invalid'),
  });
}

function parseVerdicts(payload: unknown, projectId: string): readonly ProjectReflectionVerdict[] {
  if (!isRecord(payload) || !Array.isArray(payload.items)) {
    throw projectKnowledgeError('project_reflection_verdicts_contract_invalid');
  }
  return Object.freeze(payload.items.map((item) => parseVerdict(item, projectId)));
}

function parseVerdict(value: unknown, projectId: string): ProjectReflectionVerdict {
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
        : cloneRecord(value.proposed_payload, 'project_reflection_verdict_contract_invalid'),
    createdAt: requireIdentifier(value.created_at, 'project_reflection_verdict_contract_invalid'),
  });
}

function stringArray(value: unknown, reasonCode: string): readonly string[] {
  if (!Array.isArray(value) || value.some((item) => typeof item !== 'string')) {
    throw projectKnowledgeError(reasonCode);
  }
  return Object.freeze([...value]);
}

function cloneRecord(value: unknown, reasonCode: string): Readonly<Record<string, unknown>> {
  if (!isRecord(value)) throw projectKnowledgeError(reasonCode);
  return Object.freeze({ ...value });
}
