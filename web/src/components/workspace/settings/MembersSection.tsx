import type React from 'react';
import { useCallback, useState } from 'react';

import { useTranslation } from 'react-i18next';

import { Input, Select } from 'antd';
import { Loader2, UserMinus, Users } from 'lucide-react';

import { useWorkspaceActions, useWorkspaceMembers } from '@/stores/workspace';

import { workspaceService } from '@/services/workspaceService';

import { ROLE_OPTIONS } from '@/pages/tenant/workspaceSettingsModel';
import { SettingsSection } from '@/pages/tenant/WorkspaceSettingsPrimitives';

import { LazyPopconfirm, useLazyMessage } from '@/components/ui/lazyAntd';

import type { WorkspaceMember, WorkspaceMemberRole } from '@/types/workspace';

export interface MembersSectionProps {
  tenantId: string;
  projectId: string;
  workspaceId: string;
}

export const MembersSection: React.FC<MembersSectionProps> = ({
  tenantId,
  projectId,
  workspaceId,
}) => {
  const { t } = useTranslation();
  const message = useLazyMessage();

  const members = useWorkspaceMembers();
  const { loadWorkspaceSurface } = useWorkspaceActions();

  const [newMemberUserId, setNewMemberUserId] = useState('');
  const [newMemberRole, setNewMemberRole] = useState<WorkspaceMemberRole>('viewer');
  const [isAddingMember, setIsAddingMember] = useState(false);

  const handleAddMember = useCallback(async () => {
    if (!tenantId || !projectId || !workspaceId || !newMemberUserId.trim()) return;
    setIsAddingMember(true);
    try {
      await workspaceService.addMember(tenantId, projectId, workspaceId, {
        user_id: newMemberUserId.trim(),
        role: newMemberRole,
      });
      message?.success(t('workspaceSettings.members.addSuccess'));
      setNewMemberUserId('');
      setNewMemberRole('viewer');
      void loadWorkspaceSurface(tenantId, projectId, workspaceId);
    } catch {
      message?.error(t('workspaceSettings.members.addFailed'));
    } finally {
      setIsAddingMember(false);
    }
  }, [
    tenantId,
    projectId,
    workspaceId,
    newMemberUserId,
    newMemberRole,
    message,
    t,
    loadWorkspaceSurface,
  ]);

  const handleRemoveMember = useCallback(
    async (memberId: string) => {
      if (!tenantId || !projectId || !workspaceId) return;
      try {
        await workspaceService.removeMember(tenantId, projectId, workspaceId, memberId);
        message?.success(t('workspaceSettings.members.removeSuccess'));
        void loadWorkspaceSurface(tenantId, projectId, workspaceId);
      } catch {
        message?.error(t('workspaceSettings.members.removeFailed'));
      }
    },
    [tenantId, projectId, workspaceId, message, t, loadWorkspaceSurface]
  );

  const handleRoleChange = useCallback(
    async (memberId: string, role: WorkspaceMemberRole) => {
      if (!tenantId || !projectId || !workspaceId) return;
      try {
        await workspaceService.updateMemberRole(tenantId, projectId, workspaceId, memberId, role);
        message?.success(t('workspaceSettings.members.roleUpdateSuccess'));
        void loadWorkspaceSurface(tenantId, projectId, workspaceId);
      } catch {
        message?.error(t('workspaceSettings.members.roleUpdateFailed'));
      }
    },
    [tenantId, projectId, workspaceId, message, t, loadWorkspaceSurface]
  );

  return (
    <SettingsSection
      icon={<Users size={16} aria-hidden />}
      title={t('workspaceSettings.members.title')}
      description={t('workspaceSettings.members.description')}
    >
      <div className="grid gap-2">
        <Input
          value={newMemberUserId}
          onChange={(event) => {
            setNewMemberUserId(event.target.value);
          }}
          placeholder={t('workspaceSettings.members.addMemberPlaceholder')}
          aria-label={t('workspaceSettings.members.addMemberPlaceholder')}
          spellCheck={false}
          autoComplete="off"
          onPressEnter={() => {
            void handleAddMember();
          }}
        />
        <div className="grid grid-cols-[minmax(0,1fr)_auto] gap-2">
          <Select
            value={newMemberRole}
            aria-label={t('workspaceSettings.members.role')}
            onChange={(value: WorkspaceMemberRole) => {
              setNewMemberRole(value);
            }}
            options={ROLE_OPTIONS.map((option) => ({
              value: option.value,
              label: t(option.labelKey),
            }))}
          />
          <button
            type="button"
            onClick={() => {
              void handleAddMember();
            }}
            disabled={isAddingMember || !newMemberUserId.trim()}
            className="inline-flex h-9 items-center gap-2 rounded-md bg-text-primary px-3 text-sm font-medium text-surface-light transition-colors hover:bg-text-secondary disabled:cursor-not-allowed disabled:opacity-50 dark:bg-text-inverse dark:text-surface-dark"
          >
            {isAddingMember ? (
              <Loader2 size={15} className="animate-spin motion-reduce:animate-none" />
            ) : (
              <Users size={15} />
            )}
            {t('workspaceSettings.members.addMember')}
          </button>
        </div>
      </div>

      {members.length === 0 ? (
        <p className="rounded-md border border-border-light bg-surface-muted px-3 py-6 text-center text-sm text-text-secondary dark:border-border-dark dark:bg-surface-dark-alt dark:text-text-muted">
          {t('workspaceSettings.members.noMembers')}
        </p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border-light dark:border-border-dark">
                <th
                  scope="col"
                  className="px-2 py-2 text-left text-xs font-semibold text-text-secondary dark:text-text-muted"
                >
                  {t('workspaceSettings.members.email')}
                </th>
                <th
                  scope="col"
                  className="px-2 py-2 text-left text-xs font-semibold text-text-secondary dark:text-text-muted"
                >
                  {t('workspaceSettings.members.role')}
                </th>
                <th
                  scope="col"
                  className="px-2 py-2 text-right text-xs font-semibold text-text-secondary dark:text-text-muted"
                >
                  {t('workspaceSettings.members.actions')}
                </th>
              </tr>
            </thead>
            <tbody>
              {members.map((member: WorkspaceMember) => (
                <tr
                  key={member.id}
                  className="border-b border-border-light last:border-0 dark:border-border-dark"
                >
                  <td className="max-w-[12rem] truncate px-2 py-2 text-text-primary dark:text-text-inverse">
                    {member.user_email ?? member.user_id}
                  </td>
                  <td className="px-2 py-2">
                    <Select
                      value={member.role}
                      aria-label={t('workspaceSettings.members.roleForMember', {
                        email: member.user_email ?? member.user_id,
                      })}
                      onChange={(value: WorkspaceMemberRole) => {
                        void handleRoleChange(member.id, value);
                      }}
                      size="small"
                      style={{ width: 108 }}
                      options={ROLE_OPTIONS.map((option) => ({
                        value: option.value,
                        label: t(option.labelKey),
                      }))}
                    />
                  </td>
                  <td className="px-2 py-2 text-right">
                    <LazyPopconfirm
                      title={t('workspaceSettings.members.removeConfirm')}
                      onConfirm={() => {
                        void handleRemoveMember(member.id);
                      }}
                      okText={t('common.delete')}
                      cancelText={t('common.cancel')}
                      okButtonProps={{ danger: true }}
                    >
                      <button
                        type="button"
                        aria-label={t('workspaceSettings.members.removeMember')}
                        className="inline-flex h-8 w-8 items-center justify-center rounded-md text-status-text-error transition-colors hover:bg-error-bg dark:text-status-text-error-dark dark:hover:bg-error-bg-dark"
                      >
                        <UserMinus size={15} />
                      </button>
                    </LazyPopconfirm>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </SettingsSection>
  );
};
