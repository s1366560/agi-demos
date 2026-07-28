import type {
  WorkspaceCollaborationSurface,
  WorkspaceSurfaceMutation,
} from './workspaceCollaborationClient';
import {
  isWorkspaceRecord,
  scopedWorkspacePath,
  workspaceContractError,
  workspaceRootPath,
  type WorkspaceHttpScope,
} from './workspaceCollaborationHttpContract';

export type WorkspaceMutationRequest = {
  method: 'POST' | 'PATCH' | 'DELETE';
  path: string;
  body?: Record<string, unknown> | FormData;
};

const DANGEROUS_PAYLOAD_KEYS = new Set(['__proto__', 'constructor', 'prototype']);

export const WORKSPACE_HTTP_MUTATION_ACTIONS = Object.freeze({
  goals: Object.freeze([
    'create_objective',
    'update_objective',
    'delete_objective',
    'project_objective_to_task',
    'create_task',
    'update_task',
    'delete_task',
    'assign_task_agent',
    'unassign_task_agent',
  ]),
  discussion: Object.freeze([
    'create_post',
    'update_post',
    'delete_post',
    'pin_post',
    'unpin_post',
    'create_reply',
    'update_reply',
    'delete_reply',
  ]),
  status: Object.freeze(['update_task', 'apply_task_recovery_action']),
  collaboration: Object.freeze([
    'bind_agent',
    'update_agent_binding',
    'unbind_agent',
    'add_member',
    'update_member_role',
    'remove_member',
    'create_task',
    'update_task',
    'delete_task',
    'assign_task_agent',
    'unassign_task_agent',
  ]),
  members: Object.freeze(['add_member', 'update_member_role', 'remove_member']),
  genes: Object.freeze(['create_gene', 'update_gene', 'delete_gene']),
  files: Object.freeze([
    'create_directory',
    'upload_file',
    'update_file',
    'delete_file',
    'copy_file',
  ]),
  notes: Object.freeze([]),
  topology: Object.freeze([
    'create_node',
    'update_node',
    'delete_node',
    'create_edge',
    'update_edge',
    'delete_edge',
  ]),
  settings: Object.freeze(['update_workspace']),
}) satisfies Readonly<Record<WorkspaceCollaborationSurface, readonly string[]>>;

export function requireWorkspaceMutationAuthority(
  mutation: WorkspaceSurfaceMutation,
): void {
  if (
    !Number.isSafeInteger(mutation.expected_revision) ||
    mutation.expected_revision < 0
  ) {
    throw workspaceContractError('workspace_surface_revision_required');
  }
  const idempotencyKey = mutation.idempotency_key.trim();
  if (
    idempotencyKey.length < 8 ||
    idempotencyKey.length > 256 ||
    idempotencyKey !== mutation.idempotency_key
  ) {
    throw workspaceContractError('workspace_surface_idempotency_invalid');
  }
}

export function isAllowedWorkspaceMutation(
  surface: WorkspaceCollaborationSurface,
  action: string,
): boolean {
  const actions = WORKSPACE_HTTP_MUTATION_ACTIONS[surface] as
    | readonly string[]
    | undefined;
  return actions?.includes(action) ?? false;
}

export function buildWorkspaceMutationRequest(
  scope: WorkspaceHttpScope,
  surface: WorkspaceCollaborationSurface,
  mutation: WorkspaceSurfaceMutation,
): WorkspaceMutationRequest {
  const scopedBase = scopedWorkspacePath(scope);
  const workspaceRoot = workspaceRootPath(scope);
  const payload = requireSafePayload(mutation.payload);
  const canonicalBody = (excluded: readonly string[] = []) =>
    canonicalPayload(payload, excluded);
  const pathId = (name: string) =>
    encodeURIComponent(requirePayloadId(payload, name));

  switch (`${surface}:${mutation.action}`) {
    case 'goals:create_objective':
      return { method: 'POST', path: `${scopedBase}/objectives`, body: canonicalBody() };
    case 'goals:update_objective':
      return {
        method: 'PATCH',
        path: `${scopedBase}/objectives/${pathId('objective_id')}`,
        body: canonicalBody(['objective_id']),
      };
    case 'goals:delete_objective':
      return {
        method: 'DELETE',
        path: `${scopedBase}/objectives/${pathId('objective_id')}`,
      };
    case 'goals:project_objective_to_task':
      return {
        method: 'POST',
        path: `${scopedBase}/objectives/${pathId('objective_id')}/project-to-task`,
        body: canonicalBody(['objective_id']),
      };
    case 'goals:create_task':
    case 'collaboration:create_task':
      return { method: 'POST', path: `${workspaceRoot}/tasks`, body: canonicalBody() };
    case 'goals:update_task':
    case 'status:update_task':
    case 'collaboration:update_task':
      return {
        method: 'PATCH',
        path: `${workspaceRoot}/tasks/${pathId('task_id')}`,
        body: canonicalBody(['task_id']),
      };
    case 'goals:delete_task':
    case 'collaboration:delete_task':
      return {
        method: 'DELETE',
        path: `${workspaceRoot}/tasks/${pathId('task_id')}`,
      };
    case 'goals:assign_task_agent':
    case 'collaboration:assign_task_agent':
      return {
        method: 'POST',
        path: `${workspaceRoot}/tasks/${pathId('task_id')}/assign-agent`,
        body: canonicalBody(['task_id']),
      };
    case 'goals:unassign_task_agent':
    case 'collaboration:unassign_task_agent':
      return {
        method: 'POST',
        path: `${workspaceRoot}/tasks/${pathId('task_id')}/unassign-agent`,
      };
    case 'status:apply_task_recovery_action':
      return {
        method: 'POST',
        path: `${workspaceRoot}/tasks/${pathId('task_id')}/recovery-actions`,
        body: canonicalBody(['task_id']),
      };
    case 'discussion:create_post':
      return {
        method: 'POST',
        path: `${scopedBase}/blackboard/posts`,
        body: canonicalBody(),
      };
    case 'discussion:update_post':
      return {
        method: 'PATCH',
        path: `${scopedBase}/blackboard/posts/${pathId('post_id')}`,
        body: canonicalBody(['post_id']),
      };
    case 'discussion:delete_post':
      return {
        method: 'DELETE',
        path: `${scopedBase}/blackboard/posts/${pathId('post_id')}`,
      };
    case 'discussion:pin_post':
    case 'discussion:unpin_post':
      return {
        method: 'POST',
        path:
          `${scopedBase}/blackboard/posts/${pathId('post_id')}/` +
          (mutation.action === 'pin_post' ? 'pin' : 'unpin'),
      };
    case 'discussion:create_reply':
      return {
        method: 'POST',
        path: `${scopedBase}/blackboard/posts/${pathId('post_id')}/replies`,
        body: canonicalBody(['post_id']),
      };
    case 'discussion:update_reply':
    case 'discussion:delete_reply':
      return {
        method: mutation.action === 'update_reply' ? 'PATCH' : 'DELETE',
        path:
          `${scopedBase}/blackboard/posts/${pathId('post_id')}/replies/` +
          pathId('reply_id'),
        body:
          mutation.action === 'update_reply'
            ? canonicalBody(['post_id', 'reply_id'])
            : undefined,
      };
    case 'collaboration:bind_agent':
      return { method: 'POST', path: `${scopedBase}/agents`, body: canonicalBody() };
    case 'collaboration:update_agent_binding':
      return {
        method: 'PATCH',
        path: `${scopedBase}/agents/${pathId('workspace_agent_id')}`,
        body: canonicalBody(['workspace_agent_id']),
      };
    case 'collaboration:unbind_agent':
      return {
        method: 'DELETE',
        path: `${scopedBase}/agents/${pathId('workspace_agent_id')}`,
      };
    case 'collaboration:add_member':
    case 'members:add_member':
      return { method: 'POST', path: `${scopedBase}/members`, body: canonicalBody() };
    case 'collaboration:update_member_role':
    case 'members:update_member_role':
      return {
        method: 'PATCH',
        path: `${scopedBase}/members/${pathId('user_id')}`,
        body: canonicalBody(['user_id']),
      };
    case 'collaboration:remove_member':
    case 'members:remove_member':
      return {
        method: 'DELETE',
        path: `${scopedBase}/members/${pathId('user_id')}`,
      };
    case 'genes:create_gene':
      return { method: 'POST', path: `${scopedBase}/genes`, body: canonicalBody() };
    case 'genes:update_gene':
      return {
        method: 'PATCH',
        path: `${scopedBase}/genes/${pathId('gene_id')}`,
        body: canonicalBody(['gene_id']),
      };
    case 'genes:delete_gene':
      return {
        method: 'DELETE',
        path: `${scopedBase}/genes/${pathId('gene_id')}`,
      };
    case 'files:create_directory':
      return {
        method: 'POST',
        path: `${scopedBase}/blackboard/files/mkdir`,
        body: canonicalBody(),
      };
    case 'files:upload_file':
      return {
        method: 'POST',
        path: `${scopedBase}/blackboard/files/upload`,
        body: uploadFormData(payload),
      };
    case 'files:update_file':
      return {
        method: 'PATCH',
        path: `${scopedBase}/blackboard/files/${pathId('file_id')}`,
        body: canonicalBody(['file_id']),
      };
    case 'files:delete_file':
      if (payload.recursive !== undefined && typeof payload.recursive !== 'boolean') {
        throw workspaceContractError('workspace_surface_payload_invalid');
      }
      return {
        method: 'DELETE',
        path:
          `${scopedBase}/blackboard/files/${pathId('file_id')}` +
          (payload.recursive === true ? '?recursive=true' : ''),
      };
    case 'files:copy_file':
      return {
        method: 'POST',
        path: `${scopedBase}/blackboard/files/${pathId('file_id')}/copy`,
        body: canonicalBody(['file_id']),
      };
    case 'topology:create_node':
      return {
        method: 'POST',
        path: `${workspaceRoot}/topology/nodes`,
        body: canonicalBody(),
      };
    case 'topology:update_node':
      return {
        method: 'PATCH',
        path: `${workspaceRoot}/topology/nodes/${pathId('node_id')}`,
        body: canonicalBody(['node_id']),
      };
    case 'topology:delete_node':
      return {
        method: 'DELETE',
        path: `${workspaceRoot}/topology/nodes/${pathId('node_id')}`,
      };
    case 'topology:create_edge':
      return {
        method: 'POST',
        path: `${workspaceRoot}/topology/edges`,
        body: canonicalBody(),
      };
    case 'topology:update_edge':
      return {
        method: 'PATCH',
        path: `${workspaceRoot}/topology/edges/${pathId('edge_id')}`,
        body: canonicalBody(['edge_id']),
      };
    case 'topology:delete_edge':
      return {
        method: 'DELETE',
        path: `${workspaceRoot}/topology/edges/${pathId('edge_id')}`,
      };
    case 'settings:update_workspace':
      return { method: 'PATCH', path: scopedBase, body: canonicalBody() };
    default:
      throw workspaceContractError('workspace_surface_action_unavailable');
  }
}

function requireSafePayload(input: unknown): Record<string, unknown> {
  if (!isWorkspaceRecord(input)) {
    throw workspaceContractError('workspace_surface_payload_invalid');
  }
  for (const key of Object.keys(input)) {
    if (DANGEROUS_PAYLOAD_KEYS.has(key)) {
      throw workspaceContractError('workspace_surface_payload_invalid');
    }
  }
  return input;
}

function canonicalPayload(
  payload: Record<string, unknown>,
  excluded: readonly string[],
): Record<string, unknown> {
  const excludedKeys = new Set([
    ...excluded,
    'expected_revision',
    'idempotency_key',
    'tenant_id',
    'project_id',
    'workspace_id',
  ]);
  const body: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(payload)) {
    if (!excludedKeys.has(key)) body[key] = value;
  }
  return body;
}

function uploadFormData(
  payload: Record<string, unknown>,
): FormData {
  if (
    typeof FormData === 'undefined' ||
    typeof Blob === 'undefined' ||
    !(payload.file instanceof Blob)
  ) {
    throw workspaceContractError('workspace_surface_payload_invalid');
  }
  const parentPath = requirePayloadId(payload, 'parent_path');
  const form = new FormData();
  const filename =
    typeof payload.filename === 'string' && payload.filename.trim()
      ? payload.filename.trim()
      : 'upload.bin';
  if (filename.length > 255) {
    throw workspaceContractError('workspace_surface_payload_invalid');
  }
  form.append('file', payload.file, filename);
  form.append('parent_path', parentPath);
  return form;
}

function requirePayloadId(payload: Record<string, unknown>, key: string): string {
  const value = payload[key];
  if (typeof value !== 'string' || !value.trim() || value.length > 512) {
    throw workspaceContractError('workspace_surface_payload_invalid');
  }
  return value.trim();
}
