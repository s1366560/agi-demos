/**
 * Unit tests for permissionModeStore.
 *
 * Feature: per-conversation permission mode controlling how incoming
 * permission_asked requests are handled (ask / auto_edit / full_access).
 *
 * Verifies:
 * - Mode persistence and default ('ask') for unknown conversations
 * - shouldAutoApprovePermission set membership on declared permission names
 */

import { describe, it, expect, beforeEach } from 'vitest';

import {
  shouldAutoApprovePermission,
  useAgentPermissionModeStore,
} from '@business/agent/ui/web/stores/agent/permissionModeStore';

describe('permissionModeStore', () => {
  beforeEach(() => {
    useAgentPermissionModeStore.setState({
      modesByConversation: {},
      autoApprovedRequestIds: {},
      pendingAutoApprovalIds: {},
    });
  });

  it('persists only exact automatically approved request IDs after a server verdict', () => {
    const store = useAgentPermissionModeStore.getState();
    expect(store.beginAutoApproval('conv-a', 'request-a')).toBe(true);
    expect(store.beginAutoApproval('conv-a', 'request-a')).toBe(false);
    expect(useAgentPermissionModeStore.getState().autoApprovedRequestIds['conv-a']).toBeUndefined();
    expect(
      JSON.parse(localStorage.getItem('agent-permission-mode')!).state.pendingAutoApprovalIds
    ).toBeUndefined();
    store.completeAutoApproval('conv-a', 'request-a', true, true);
    expect(useAgentPermissionModeStore.getState().autoApprovedRequestIds['conv-a']).toEqual([
      'request-a',
    ]);
    expect(
      JSON.parse(localStorage.getItem('agent-permission-mode')!).state.autoApprovedRequestIds[
        'conv-a'
      ]
    ).toEqual(['request-a']);
    store.setPermissionMode('conv-a', 'ask');
    expect(useAgentPermissionModeStore.getState().autoApprovedRequestIds['conv-a']).toEqual([
      'request-a',
    ]);
    expect(useAgentPermissionModeStore.getState().autoApprovedRequestIds['conv-b']).toBeUndefined();
    store.completeAutoApproval('conv-a', 'manual', true);
    expect(useAgentPermissionModeStore.getState().autoApprovedRequestIds['conv-a']).toEqual([
      'request-a',
    ]);
    store.beginAutoApproval('conv-a', 'denied');
    store.completeAutoApproval('conv-a', 'denied', false);
    expect(useAgentPermissionModeStore.getState().autoApprovedRequestIds['conv-a']).toEqual([
      'request-a',
    ]);
    store.clearConversation('conv-a');
    expect(useAgentPermissionModeStore.getState().autoApprovedRequestIds['conv-a']).toBeUndefined();
  });

  it('does not infer automatic origin when a manual client settles a pending automatic send', () => {
    const store = useAgentPermissionModeStore.getState();
    store.beginAutoApproval('conversation', 'race');
    store.completeAutoApproval('conversation', 'race', true);
    expect(useAgentPermissionModeStore.getState().autoApprovedRequestIds.conversation).toEqual([]);
    store.completeAutoApproval('conversation', 'remote-auto', true, true);
    expect(useAgentPermissionModeStore.getState().autoApprovedRequestIds.conversation).toEqual([
      'remote-auto',
    ]);
    store.completeAutoApproval('conversation', 'remote-denied', false, true);
    expect(useAgentPermissionModeStore.getState().autoApprovedRequestIds.conversation).toEqual([
      'remote-auto',
    ]);
  });

  it('discards legacy local inferred provenance during migration', async () => {
    localStorage.setItem(
      'agent-permission-mode',
      JSON.stringify({
        version: 0,
        state: {
          modesByConversation: { conversation: 'full_access' },
          autoApprovedRequestIds: { conversation: ['inferred'] },
        },
      })
    );
    await useAgentPermissionModeStore.persist.rehydrate();
    expect(useAgentPermissionModeStore.getState().autoApprovedRequestIds).toEqual({});
    expect(useAgentPermissionModeStore.getState().getPermissionMode('conversation')).toBe('ask');
  });

  describe('Mode state', () => {
    it('should default to ask for unknown conversations', () => {
      expect(useAgentPermissionModeStore.getState().getPermissionMode('conv-1')).toBe('ask');
    });

    it('should persist a mode per conversation', () => {
      useAgentPermissionModeStore.getState().setPermissionMode('conv-1', 'full_access');
      useAgentPermissionModeStore.getState().setPermissionMode('conv-2', 'auto_edit');

      expect(useAgentPermissionModeStore.getState().getPermissionMode('conv-1')).toBe(
        'full_access'
      );
      expect(useAgentPermissionModeStore.getState().getPermissionMode('conv-2')).toBe('auto_edit');
      expect(useAgentPermissionModeStore.getState().getPermissionMode('conv-3')).toBe('ask');
    });

    it('should clear a conversation mode without touching others', () => {
      useAgentPermissionModeStore.getState().setPermissionMode('conv-1', 'auto_edit');
      useAgentPermissionModeStore.getState().setPermissionMode('conv-2', 'full_access');

      useAgentPermissionModeStore.getState().clearConversation('conv-1');

      expect(useAgentPermissionModeStore.getState().getPermissionMode('conv-1')).toBe('ask');
      expect(useAgentPermissionModeStore.getState().getPermissionMode('conv-2')).toBe(
        'full_access'
      );
    });
  });

  describe('shouldAutoApprovePermission', () => {
    it('never automates native application and device grants even in full access', () => {
      expect(shouldAutoApprovePermission('full_access', { permission: 'computer_use' })).toBe(
        false
      );
      expect(
        shouldAutoApprovePermission('full_access', { metadata: { native_binding: null } })
      ).toBe(false);
      expect(shouldAutoApprovePermission('full_access', { native_binding: {} })).toBe(false);
      expect(
        shouldAutoApprovePermission('full_access', {
          decision: { target: { kind: 'device_mcp_tool' } },
        })
      ).toBe(false);
    });
    it('should never auto-approve in ask mode', () => {
      expect(shouldAutoApprovePermission('ask', { permission: 'write' })).toBe(false);
    });

    it('should auto-approve every request in full_access mode', () => {
      expect(shouldAutoApprovePermission('full_access', { permission: 'system_api' })).toBe(true);
      expect(shouldAutoApprovePermission('full_access', {})).toBe(true);
    });

    it('should auto-approve edit permissions in auto_edit mode', () => {
      expect(shouldAutoApprovePermission('auto_edit', { permission: 'write' })).toBe(true);
      expect(shouldAutoApprovePermission('auto_edit', { permission: 'workspace_file_write' })).toBe(
        true
      );
      expect(shouldAutoApprovePermission('auto_edit', { permission: 'workspace_task_write' })).toBe(
        true
      );
    });

    it('should keep asking for non-edit permissions in auto_edit mode', () => {
      expect(shouldAutoApprovePermission('auto_edit', { permission: 'system_api' })).toBe(false);
      expect(shouldAutoApprovePermission('auto_edit', { permission: 'bash' })).toBe(false);
      expect(shouldAutoApprovePermission('auto_edit', { permission: 'read' })).toBe(false);
    });

    it('should read the permission name from the projection field as fallback', () => {
      expect(
        shouldAutoApprovePermission('auto_edit', { permission_type: 'workspace_file_write' })
      ).toBe(true);
      expect(shouldAutoApprovePermission('auto_edit', { permission_type: 'delegate' })).toBe(false);
    });

    it('should not auto-approve in auto_edit mode when no permission name is present', () => {
      expect(shouldAutoApprovePermission('auto_edit', { tool_name: 'edit_file' })).toBe(false);
    });
  });
});
