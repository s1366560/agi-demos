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
} from '../../../stores/agent/permissionModeStore';

describe('permissionModeStore', () => {
  beforeEach(() => {
    useAgentPermissionModeStore.setState({ modesByConversation: {} });
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
      expect(shouldAutoApprovePermission('auto_edit', { permission_type: 'delegate' })).toBe(
        false
      );
    });

    it('should not auto-approve in auto_edit mode when no permission name is present', () => {
      expect(shouldAutoApprovePermission('auto_edit', { tool_name: 'edit_file' })).toBe(false);
    });
  });
});
