import type React from 'react';
import { useCallback, useEffect, useRef, useState } from 'react';

import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router-dom';

import { Input, Select } from 'antd';
import { Loader2, Trash2, UserMinus } from 'lucide-react';

import {
  useCurrentWorkspace,
  useWorkspaceActions,
  useWorkspaceMembers,
} from '@/stores/workspace';

import { workspaceService } from '@/services/workspaceService';

import { LazyPopconfirm, useLazyMessage } from '@/components/ui/lazyAntd';

import type { WorkspaceMember, WorkspaceMemberRole } from '@/types/workspace';

const { TextArea } = Input;

const ROLE_OPTIONS: Array<{ value: WorkspaceMemberRole; labelKey: string }> = [
  { value: 'owner', labelKey: 'workspaceSettings.members.owner' },
  { value: 'editor', labelKey: 'workspaceSettings.members.editor' },
  { value: 'viewer', labelKey: 'workspaceSettings.members.viewer' },
];

export const WorkspaceSettingsPanel: React.FC<{
  tenantId: string;
  projectId: string;
  workspaceId: string;
}> = ({ tenantId, projectId, workspaceId }) => {
  const { t } = useTranslation();
  const message = useLazyMessage();
  const navigate = useNavigate();

  const workspace = useCurrentWorkspace();
  const members = useWorkspaceMembers();
  const { loadWorkspaceSurface, setCurrentWorkspace } = useWorkspaceActions();

  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [isDirty, setIsDirty] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [isDeleting, setIsDeleting] = useState(false);
  const lastSyncedId = useRef<string | null>(null);

  const [newMemberUserId, setNewMemberUserId] = useState('');
  const [newMemberRole, setNewMemberRole] = useState<WorkspaceMemberRole>('viewer');
  const [isAddingMember, setIsAddingMember] = useState(false);

  useEffect(() => {
    if (workspace && lastSyncedId.current !== workspace.id) {
      lastSyncedId.current = workspace.id;
      setName(workspace.name);
      setDescription(workspace.description ?? '');
      setIsDirty(false);
    }
  }, [workspace]);

  const handleNameChange = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    setName(e.target.value);
    setIsDirty(true);
  }, []);

  const handleDescriptionChange = useCallback((e: React.ChangeEvent<HTMLTextAreaElement>) => {
    setDescription(e.target.value);
    setIsDirty(true);
  }, []);

  const handleSave = useCallback(async () => {
    if (!tenantId || !projectId || !workspaceId || !isDirty) return;
    setIsSaving(true);
    try {
      const updated = await workspaceService.update(tenantId, projectId, workspaceId, {
        name,
        description,
      });
      setCurrentWorkspace(updated);
      message?.success(t('workspaceSettings.updateSuccess'));
      setIsDirty(false);
    } catch {
      message?.error(t('workspaceSettings.updateFailed'));
    } finally {
      setIsSaving(false);
    }
  }, [
    tenantId,
    projectId,
    workspaceId,
    isDirty,
    name,
    description,
    setCurrentWorkspace,
    message,
    t,
  ]);

  const handleDelete = useCallback(async () => {
    if (!tenantId || !projectId || !workspaceId) return;
    setIsDeleting(true);
    try {
      await workspaceService.remove(tenantId, projectId, workspaceId);
      message?.success(t('workspaceSettings.dangerZone.deleteSuccess'));
      void navigate('../..', { relative: 'path' });
    } catch {
      message?.error(t('workspaceSettings.dangerZone.deleteFailed'));
    } finally {
      setIsDeleting(false);
    }
  }, [tenantId, projectId, workspaceId, message, t, navigate]);

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
      loadWorkspaceSurface(tenantId, projectId, workspaceId);
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
        loadWorkspaceSurface(tenantId, projectId, workspaceId);
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
        loadWorkspaceSurface(tenantId, projectId, workspaceId);
      } catch {
        message?.error(t('workspaceSettings.members.roleUpdateFailed'));
      }
    },
    [tenantId, projectId, workspaceId, message, t, loadWorkspaceSurface]
  );

  if (!workspace) {
    return null;
  }

  return (
    <div className="max-w-3xl mx-auto w-full flex flex-col gap-8 pb-8 pt-4">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold text-slate-900 dark:text-white">
          {t('workspaceSettings.title')}
        </h1>
        <p className="text-sm text-slate-500 mt-1">{t('workspaceSettings.description')}</p>
      </div>

      {/* General Settings */}
      <div className="bg-white dark:bg-slate-800 rounded-lg border border-slate-200 dark:border-slate-700 p-6">
        <h2 className="text-lg font-semibold text-slate-900 dark:text-white mb-6">
          {t('workspaceSettings.generalSettings')}
        </h2>

        <div className="space-y-5">
          <div>
            <label
              htmlFor="workspace-name"
              className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-1"
            >
              {t('workspaceSettings.nameLabel')}
            </label>
            <Input
              id="workspace-name"
              value={name}
              onChange={handleNameChange}
              placeholder={t('workspaceSettings.namePlaceholder')}
              maxLength={100}
            />
          </div>

          <div>
            <label
              htmlFor="workspace-description"
              className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-1"
            >
              {t('workspaceSettings.descriptionLabel')}
            </label>
            <TextArea
              id="workspace-description"
              value={description}
              onChange={handleDescriptionChange}
              placeholder={t('workspaceSettings.descriptionPlaceholder')}
              rows={4}
              maxLength={500}
              showCount
            />
          </div>

          <div className="flex justify-end">
            <button
              type="button"
              onClick={handleSave}
              disabled={!isDirty || isSaving}
              className="inline-flex items-center justify-center gap-2 px-4 py-2 bg-primary-600 hover:bg-primary-700 text-white rounded-lg transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {isSaving && (
                <Loader2 size={16} className="animate-spin" />
              )}
              {t('common.save')}
            </button>
          </div>
        </div>
      </div>

      {/* Members */}
      <div className="bg-white dark:bg-slate-800 rounded-lg border border-slate-200 dark:border-slate-700 p-6">
        <h2 className="text-lg font-semibold text-slate-900 dark:text-white mb-2">
          {t('workspaceSettings.members.title')}
        </h2>
        <p className="text-sm text-slate-500 dark:text-slate-400 mb-6">
          {t('workspaceSettings.members.description')}
        </p>

        {/* Add member form */}
        <div className="flex gap-3 mb-6">
          <Input
            value={newMemberUserId}
            onChange={(e) => {
              setNewMemberUserId(e.target.value);
            }}
            placeholder={t('workspaceSettings.members.addMemberPlaceholder')}
            className="flex-1"
            onPressEnter={handleAddMember}
          />
          <Select
            value={newMemberRole}
            onChange={(value: WorkspaceMemberRole) => {
              setNewMemberRole(value);
            }}
            style={{ width: 120 }}
            options={ROLE_OPTIONS.map((opt) => ({
              value: opt.value,
              label: t(opt.labelKey),
            }))}
          />
          <button
            type="button"
            onClick={handleAddMember}
            disabled={isAddingMember || !newMemberUserId.trim()}
            className="inline-flex items-center justify-center gap-2 px-4 py-2 bg-primary-600 hover:bg-primary-700 text-white rounded-lg transition-colors disabled:opacity-50 disabled:cursor-not-allowed whitespace-nowrap"
          >
            {isAddingMember && (
              <Loader2 size={16} className="animate-spin" />
            )}
            {t('workspaceSettings.members.addMember')}
          </button>
        </div>

        {/* Members table */}
        {members.length === 0 ? (
          <p className="text-sm text-slate-500 dark:text-slate-400 text-center py-8">
            {t('workspaceSettings.members.noMembers')}
          </p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-slate-200 dark:border-slate-700">
                  <th className="text-left py-3 px-2 font-medium text-slate-600 dark:text-slate-400">
                    {t('workspaceSettings.members.email')}
                  </th>
                  <th className="text-left py-3 px-2 font-medium text-slate-600 dark:text-slate-400">
                    {t('workspaceSettings.members.role')}
                  </th>
                  <th className="text-right py-3 px-2 font-medium text-slate-600 dark:text-slate-400">
                    {t('workspaceSettings.members.actions')}
                  </th>
                </tr>
              </thead>
              <tbody>
                {members.map((member: WorkspaceMember) => (
                  <tr
                    key={member.id}
                    className="border-b border-slate-100 dark:border-slate-700/50 last:border-0"
                  >
                    <td className="py-3 px-2 text-slate-900 dark:text-white">
                      {member.user_email ?? member.user_id}
                    </td>
                    <td className="py-3 px-2">
                      <Select
                        value={member.role}
                        onChange={(value: WorkspaceMemberRole) =>
                          handleRoleChange(member.id, value)
                        }
                        size="small"
                        style={{ width: 110 }}
                        options={ROLE_OPTIONS.map((opt) => ({
                          value: opt.value,
                          label: t(opt.labelKey),
                        }))}
                      />
                    </td>
                    <td className="py-3 px-2 text-right">
                      <LazyPopconfirm
                        title={t('workspaceSettings.members.removeConfirm')}
                        onConfirm={() => handleRemoveMember(member.id)}
                        okText={t('common.delete')}
                        cancelText={t('common.cancel')}
                        okButtonProps={{ danger: true }}
                      >
                        <button
                          type="button"
                          className="inline-flex items-center justify-center p-1.5 text-red-500 hover:text-red-700 hover:bg-red-50 dark:hover:bg-red-900/20 rounded transition-colors"
                        >
                          <UserMinus size={16} />
                        </button>
                      </LazyPopconfirm>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Danger Zone */}
      <div className="bg-white dark:bg-slate-800 rounded-lg border border-red-200 dark:border-red-900/50 p-6">
        <h2 className="text-lg font-semibold text-red-600 dark:text-red-400 mb-2">
          {t('workspaceSettings.dangerZone.title')}
        </h2>
        <p className="text-sm text-slate-600 dark:text-slate-400 mb-4">
          {t('workspaceSettings.dangerZone.description')}
        </p>

        <div className="flex items-center justify-between p-4 border border-red-200 dark:border-red-900/50 rounded-lg">
          <div>
            <p className="text-sm font-medium text-slate-900 dark:text-white">
              {t('workspaceSettings.dangerZone.deleteWorkspace')}
            </p>
            <p className="text-xs text-slate-500 dark:text-slate-400 mt-0.5">
              {t('workspaceSettings.dangerZone.deleteDescription')}
            </p>
          </div>
          <LazyPopconfirm
            title={t('workspaceSettings.dangerZone.deleteConfirm')}
            onConfirm={handleDelete}
            okText={t('common.delete')}
            cancelText={t('common.cancel')}
            okButtonProps={{ danger: true }}
          >
            <button
              type="button"
              disabled={isDeleting}
              className="inline-flex items-center justify-center gap-2 px-4 py-2 bg-red-600 hover:bg-red-700 text-white rounded-lg transition-colors disabled:opacity-50"
            >
              <Trash2 size={16} />
              {t('common.delete')}
            </button>
          </LazyPopconfirm>
        </div>
      </div>
    </div>
  );
};
