import type React from 'react';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router-dom';

import { Input, Select, Switch } from 'antd';
import {
  Archive,
  Check,
  Code2,
  Database,
  Loader2,
  RotateCcw,
  Rocket,
  ShieldCheck,
  SlidersHorizontal,
  Trash2,
  UserMinus,
  Users,
} from 'lucide-react';

import { useCurrentWorkspace, useWorkspaceActions, useWorkspaceMembers } from '@/stores/workspace';

import { workspaceService } from '@/services/workspaceService';

import {
  isIsolatedSandboxCodeRoot,
  normaliseSandboxCodeRoot,
  workspaceTypeForUseCase,
} from '@/utils/workspaceConfig';

import { HostedProjectionBadge } from '@/components/blackboard/HostedProjectionBadge';
import { LazyPopconfirm, useLazyMessage } from '@/components/ui/lazyAntd';

import {
  COLLABORATION_MODE_OPTIONS,
  ROLE_OPTIONS,
  USE_CASE_OPTIONS,
  VERIFICATION_GRADE_OPTIONS,
  buildWorkspaceMetadataDraft,
  getOptionLabel,
  syncDraftFromWorkspace,
  type SettingsDraft,
} from './workspaceSettingsModel';
import {
  Field,
  OptionLabel,
  SettingsSection,
  SummaryTile,
  SwitchField,
} from './WorkspaceSettingsPrimitives';

import type {
  WorkspaceCollaborationMode,
  WorkspaceMember,
  WorkspaceMemberRole,
  WorkspaceUseCase,
  WorkspaceVerificationGrade,
} from '@/types/workspace';

const { TextArea } = Input;

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

  const [draft, setDraft] = useState<SettingsDraft | null>(null);
  const [isDirty, setIsDirty] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [isDeleting, setIsDeleting] = useState(false);
  const lastSyncedSignature = useRef<string | null>(null);

  const [newMemberUserId, setNewMemberUserId] = useState('');
  const [newMemberRole, setNewMemberRole] = useState<WorkspaceMemberRole>('viewer');
  const [isAddingMember, setIsAddingMember] = useState(false);

  useEffect(() => {
    if (!workspace) return;
    const signature = `${workspace.id}:${workspace.updated_at ?? ''}`;
    if (lastSyncedSignature.current !== signature && !isDirty) {
      lastSyncedSignature.current = signature;
      setDraft(syncDraftFromWorkspace(workspace));
    }
  }, [workspace, isDirty]);

  const updateDraft = useCallback(
    <TKey extends keyof SettingsDraft>(key: TKey, value: SettingsDraft[TKey]) => {
      setDraft((current) => (current ? { ...current, [key]: value } : current));
      setIsDirty(true);
    },
    []
  );

  const metadataDraft = useMemo(
    () => (draft ? buildWorkspaceMetadataDraft(draft) : { metadata: {}, error: null }),
    [draft]
  );
  const normalizedCodeRoot = draft ? normaliseSandboxCodeRoot(draft.sandboxCodeRoot) : '';
  const codeRootRequired = draft?.workspaceUseCase === 'programming';
  const codeRootValid =
    !draft ||
    (!draft.sandboxCodeRoot.trim() && !codeRootRequired) ||
    isIsolatedSandboxCodeRoot(normalizedCodeRoot);
  const canSave =
    !!tenantId &&
    !!projectId &&
    !!workspaceId &&
    !!draft &&
    isDirty &&
    !isSaving &&
    !!draft.name.trim() &&
    !metadataDraft.error &&
    codeRootValid;

  const workspaceType = draft ? workspaceTypeForUseCase(draft.workspaceUseCase) : 'general';
  const selectedUseCaseLabel = draft
    ? getOptionLabel(draft.workspaceUseCase, USE_CASE_OPTIONS, t)
    : '';
  const selectedModeLabel = draft
    ? getOptionLabel(draft.collaborationMode, COLLABORATION_MODE_OPTIONS, t)
    : '';

  const handleReset = useCallback(() => {
    if (!workspace) return;
    setDraft(syncDraftFromWorkspace(workspace));
    setIsDirty(false);
  }, [workspace]);

  const handleSave = useCallback(async () => {
    if (!tenantId || !projectId || !workspaceId || !draft || !canSave) return;
    setIsSaving(true);
    try {
      const updated = await workspaceService.update(tenantId, projectId, workspaceId, {
        name: draft.name.trim(),
        description: draft.description.trim(),
        is_archived: draft.isArchived,
        metadata: metadataDraft.metadata,
      });
      setCurrentWorkspace(updated);
      setDraft(syncDraftFromWorkspace(updated));
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
    draft,
    canSave,
    metadataDraft.metadata,
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

  if (!workspace || !draft) {
    return null;
  }

  return (
    <div className="mx-auto flex w-full max-w-6xl flex-col gap-5 px-4 pb-8 pt-4 sm:px-6">
      <header className="flex flex-col gap-4 border-b border-border-light pb-4 dark:border-border-dark lg:flex-row lg:items-start lg:justify-between">
        <div className="min-w-0">
          <HostedProjectionBadge
            labelKey="blackboard.settingsSurfaceHint"
            fallbackLabel="workspace settings projection"
          />
          <h1 className="mt-3 text-2xl font-semibold tracking-tight text-text-primary dark:text-text-inverse">
            {t('workspaceSettings.title')}
          </h1>
          <p className="mt-1 max-w-3xl text-sm leading-6 text-text-secondary dark:text-text-muted">
            {t('workspaceSettings.description')}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <button
            type="button"
            onClick={handleReset}
            disabled={!isDirty || isSaving}
            className="inline-flex h-9 items-center gap-2 rounded-md border border-border-light bg-surface-light px-3 text-sm font-medium text-text-primary transition-colors hover:bg-surface-muted disabled:cursor-not-allowed disabled:opacity-50 dark:border-border-dark dark:bg-surface-dark dark:text-text-inverse dark:hover:bg-surface-dark-alt"
          >
            <RotateCcw size={15} aria-hidden />
            {t('workspaceSettings.actions.reset')}
          </button>
          <button
            type="button"
            onClick={() => {
              void handleSave();
            }}
            disabled={!canSave}
            className="inline-flex h-9 items-center gap-2 rounded-md bg-text-primary px-3 text-sm font-medium text-surface-light transition-colors hover:bg-text-secondary disabled:cursor-not-allowed disabled:opacity-50 dark:bg-text-inverse dark:text-surface-dark"
          >
            {isSaving ? <Loader2 size={15} className="animate-spin" /> : <Check size={15} />}
            {t('common.save')}
          </button>
        </div>
      </header>

      <section className="grid gap-3 md:grid-cols-4">
        <SummaryTile label={t('workspaceSettings.summary.useCase')} value={selectedUseCaseLabel} />
        <SummaryTile label={t('workspaceSettings.summary.type')} value={workspaceType} />
        <SummaryTile label={t('workspaceSettings.summary.mode')} value={selectedModeLabel} />
        <SummaryTile
          label={t('workspaceSettings.summary.members')}
          value={String(members.length)}
        />
      </section>

      <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_22rem]">
        <div className="flex min-w-0 flex-col gap-5">
          <SettingsSection
            icon={<SlidersHorizontal size={16} aria-hidden />}
            title={t('workspaceSettings.generalSettings')}
            description={t('workspaceSettings.generalDescription')}
          >
            <div className="grid gap-4 lg:grid-cols-2">
              <Field label={t('workspaceSettings.nameLabel')} htmlFor="workspace-name">
                <Input
                  id="workspace-name"
                  value={draft.name}
                  onChange={(event) => {
                    updateDraft('name', event.target.value);
                  }}
                  placeholder={t('workspaceSettings.namePlaceholder')}
                  maxLength={255}
                  {...(!draft.name.trim() ? { status: 'error' as const } : {})}
                />
              </Field>

              <Field label={t('workspaceSettings.archiveLabel')} htmlFor="workspace-archive">
                <div className="flex h-9 items-center justify-between rounded-md border border-border-light bg-surface-muted px-3 dark:border-border-dark dark:bg-surface-dark-alt">
                  <span className="text-sm text-text-primary dark:text-text-inverse">
                    {draft.isArchived
                      ? t('workspaceSettings.archived')
                      : t('workspaceSettings.active')}
                  </span>
                  <Switch
                    id="workspace-archive"
                    checked={draft.isArchived}
                    onChange={(checked) => {
                      updateDraft('isArchived', checked);
                    }}
                  />
                </div>
              </Field>
            </div>

            <Field label={t('workspaceSettings.descriptionLabel')} htmlFor="workspace-description">
              <TextArea
                id="workspace-description"
                value={draft.description}
                onChange={(event) => {
                  updateDraft('description', event.target.value);
                }}
                placeholder={t('workspaceSettings.descriptionPlaceholder')}
                rows={4}
                maxLength={1000}
                showCount
              />
            </Field>
          </SettingsSection>

          <SettingsSection
            icon={<Users size={16} aria-hidden />}
            title={t('workspaceSettings.operatingModel.title')}
            description={t('workspaceSettings.operatingModel.description')}
          >
            <div className="grid gap-4 lg:grid-cols-2">
              <Field
                label={t('workspaceSettings.operatingModel.useCase')}
                htmlFor="workspace-use-case"
              >
                <Select
                  id="workspace-use-case"
                  value={draft.workspaceUseCase}
                  onChange={(value: WorkspaceUseCase) => {
                    updateDraft('workspaceUseCase', value);
                  }}
                  options={USE_CASE_OPTIONS.map((option) => ({
                    value: option.value,
                    label: (
                      <OptionLabel
                        label={t(option.labelKey)}
                        description={t(option.descriptionKey)}
                      />
                    ),
                  }))}
                />
              </Field>

              <Field
                label={t('workspaceSettings.operatingModel.collaborationMode')}
                htmlFor="workspace-collaboration-mode"
              >
                <Select
                  id="workspace-collaboration-mode"
                  value={draft.collaborationMode}
                  onChange={(value: WorkspaceCollaborationMode) => {
                    updateDraft('collaborationMode', value);
                  }}
                  options={COLLABORATION_MODE_OPTIONS.map((option) => ({
                    value: option.value,
                    label: (
                      <OptionLabel
                        label={t(option.labelKey)}
                        description={t(option.descriptionKey)}
                      />
                    ),
                  }))}
                />
              </Field>
            </div>

            <div className="rounded-md border border-border-light bg-surface-muted px-3 py-2 text-xs leading-5 text-text-secondary dark:border-border-dark dark:bg-surface-dark-alt dark:text-text-muted">
              {t('workspaceSettings.operatingModel.typeHint', {
                type: workspaceType,
              })}
            </div>
          </SettingsSection>

          <SettingsSection
            icon={<Code2 size={16} aria-hidden />}
            title={t('workspaceSettings.codeContext.title')}
            description={t('workspaceSettings.codeContext.description')}
          >
            <Field
              label={t('workspaceSettings.codeContext.codeRoot')}
              htmlFor="workspace-code-root"
              hint={t('workspaceSettings.codeContext.codeRootHint')}
            >
              <Input
                id="workspace-code-root"
                value={draft.sandboxCodeRoot}
                onChange={(event) => {
                  updateDraft('sandboxCodeRoot', event.target.value);
                }}
                placeholder="/workspace/my-evo"
                {...(!codeRootValid ? { status: 'error' as const } : {})}
              />
            </Field>
            {!codeRootValid ? (
              <p className="text-xs text-status-text-error dark:text-status-text-error-dark">
                {t('workspaceSettings.codeContext.codeRootInvalid')}
              </p>
            ) : null}
          </SettingsSection>

          <SettingsSection
            icon={<Rocket size={16} aria-hidden />}
            title="Delivery / CI/CD"
            description="Sandbox-native pipeline, preview deployment, and health-check settings."
          >
            <div className="grid gap-4 lg:grid-cols-3">
              <Field label="Provider" htmlFor="workspace-delivery-provider">
                <Input
                  id="workspace-delivery-provider"
                  value={draft.deliveryProvider}
                  onChange={(event) => {
                    updateDraft('deliveryProvider', event.target.value);
                  }}
                  placeholder="sandbox_native"
                />
              </Field>
              <Field label="Timeout seconds" htmlFor="workspace-delivery-timeout">
                <Input
                  id="workspace-delivery-timeout"
                  type="number"
                  min={1}
                  value={draft.deliveryTimeoutSeconds}
                  onChange={(event) => {
                    updateDraft('deliveryTimeoutSeconds', Number(event.target.value) || 600);
                  }}
                />
              </Field>
              <Field label="Preview port" htmlFor="workspace-delivery-port">
                <Input
                  id="workspace-delivery-port"
                  type="number"
                  min={1}
                  value={draft.deliveryPreviewPort}
                  onChange={(event) => {
                    updateDraft('deliveryPreviewPort', Number(event.target.value) || 3000);
                  }}
                />
              </Field>
            </div>

            <div className="grid gap-4 lg:grid-cols-2">
              <Field label="Health URL" htmlFor="workspace-delivery-health-url">
                <Input
                  id="workspace-delivery-health-url"
                  value={draft.deliveryHealthUrl}
                  onChange={(event) => {
                    updateDraft('deliveryHealthUrl', event.target.value);
                  }}
                  placeholder="http://127.0.0.1:3000"
                />
              </Field>
              <SwitchField
                label="Auto preview deploy"
                checked={draft.deliveryAutoDeploy}
                onChange={(checked) => {
                  updateDraft('deliveryAutoDeploy', checked);
                }}
              />
            </div>

            <div className="grid gap-4 lg:grid-cols-2">
              <Field label="Install command" htmlFor="workspace-delivery-install">
                <TextArea
                  id="workspace-delivery-install"
                  value={draft.deliveryInstallCommand}
                  onChange={(event) => {
                    updateDraft('deliveryInstallCommand', event.target.value);
                  }}
                  placeholder="pnpm install --frozen-lockfile"
                  rows={3}
                />
              </Field>
              <Field label="Lint command" htmlFor="workspace-delivery-lint">
                <TextArea
                  id="workspace-delivery-lint"
                  value={draft.deliveryLintCommand}
                  onChange={(event) => {
                    updateDraft('deliveryLintCommand', event.target.value);
                  }}
                  placeholder="pnpm lint"
                  rows={3}
                />
              </Field>
              <Field label="Test command" htmlFor="workspace-delivery-test">
                <TextArea
                  id="workspace-delivery-test"
                  value={draft.deliveryTestCommand}
                  onChange={(event) => {
                    updateDraft('deliveryTestCommand', event.target.value);
                  }}
                  placeholder="pnpm test"
                  rows={3}
                />
              </Field>
              <Field label="Build command" htmlFor="workspace-delivery-build">
                <TextArea
                  id="workspace-delivery-build"
                  value={draft.deliveryBuildCommand}
                  onChange={(event) => {
                    updateDraft('deliveryBuildCommand', event.target.value);
                  }}
                  placeholder="pnpm build"
                  rows={3}
                />
              </Field>
              <Field label="Deploy command" htmlFor="workspace-delivery-deploy">
                <TextArea
                  id="workspace-delivery-deploy"
                  value={draft.deliveryDeployCommand}
                  onChange={(event) => {
                    updateDraft('deliveryDeployCommand', event.target.value);
                  }}
                  placeholder="pnpm start --host 0.0.0.0 --port 3000"
                  rows={3}
                />
              </Field>
              <Field label="Health command" htmlFor="workspace-delivery-health-command">
                <TextArea
                  id="workspace-delivery-health-command"
                  value={draft.deliveryHealthCommand}
                  onChange={(event) => {
                    updateDraft('deliveryHealthCommand', event.target.value);
                  }}
                  placeholder="curl -fsS http://127.0.0.1:3000 >/dev/null"
                  rows={3}
                />
              </Field>
            </div>
          </SettingsSection>

          <SettingsSection
            icon={<ShieldCheck size={16} aria-hidden />}
            title={t('workspaceSettings.autonomy.title')}
            description={t('workspaceSettings.autonomy.description')}
          >
            <div className="grid gap-3 lg:grid-cols-3">
              <SwitchField
                label={t('workspaceSettings.autonomy.allowInternalArtifacts')}
                checked={draft.allowInternalTaskArtifacts}
                onChange={(checked) => {
                  updateDraft('allowInternalTaskArtifacts', checked);
                }}
              />
              <SwitchField
                label={t('workspaceSettings.autonomy.requiresExternalArtifact')}
                checked={draft.requiresExternalArtifact}
                onChange={(checked) => {
                  updateDraft('requiresExternalArtifact', checked);
                }}
              />
              <Field
                label={t('workspaceSettings.autonomy.minimumVerificationGrade')}
                htmlFor="workspace-min-grade"
              >
                <Select
                  id="workspace-min-grade"
                  value={draft.minimumVerificationGrade}
                  onChange={(value: WorkspaceVerificationGrade) => {
                    updateDraft('minimumVerificationGrade', value);
                  }}
                  options={VERIFICATION_GRADE_OPTIONS.map((value) => ({
                    value,
                    label: t(`workspaceSettings.autonomy.grade.${value}`),
                  }))}
                />
              </Field>
            </div>

            <Field
              label={t('workspaceSettings.autonomy.requiredArtifactPrefixes')}
              htmlFor="workspace-artifact-prefixes"
              hint={t('workspaceSettings.autonomy.requiredArtifactPrefixesHint')}
            >
              <TextArea
                id="workspace-artifact-prefixes"
                value={draft.requiredArtifactPrefixes}
                onChange={(event) => {
                  updateDraft('requiredArtifactPrefixes', event.target.value);
                }}
                placeholder="git_diff:, patch:, commit:, test_run:"
                rows={3}
              />
            </Field>
          </SettingsSection>

          <SettingsSection
            icon={<Database size={16} aria-hidden />}
            title={t('workspaceSettings.metadata.title')}
            description={t('workspaceSettings.metadata.description')}
          >
            <Field
              label={t('workspaceSettings.metadata.rawJson')}
              htmlFor="workspace-metadata-json"
              hint={t('workspaceSettings.metadata.rawJsonHint')}
            >
              <TextArea
                id="workspace-metadata-json"
                value={draft.rawMetadata}
                onChange={(event) => {
                  updateDraft('rawMetadata', event.target.value);
                }}
                rows={12}
                className="font-mono text-xs"
                {...(metadataDraft.error ? { status: 'error' as const } : {})}
              />
            </Field>
            {metadataDraft.error ? (
              <p className="text-xs text-status-text-error dark:text-status-text-error-dark">
                {metadataDraft.error === 'metadata_object_required'
                  ? t('workspaceSettings.metadata.objectRequired')
                  : t('workspaceSettings.metadata.invalidJson')}
              </p>
            ) : null}
          </SettingsSection>
        </div>

        <aside className="flex min-w-0 flex-col gap-5">
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
                onPressEnter={() => {
                  void handleAddMember();
                }}
              />
              <div className="grid grid-cols-[minmax(0,1fr)_auto] gap-2">
                <Select
                  value={newMemberRole}
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
                    <Loader2 size={15} className="animate-spin" />
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
                      <th className="px-2 py-2 text-left text-xs font-semibold text-text-secondary dark:text-text-muted">
                        {t('workspaceSettings.members.email')}
                      </th>
                      <th className="px-2 py-2 text-left text-xs font-semibold text-text-secondary dark:text-text-muted">
                        {t('workspaceSettings.members.role')}
                      </th>
                      <th className="px-2 py-2 text-right text-xs font-semibold text-text-secondary dark:text-text-muted">
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

          <SettingsSection
            icon={<Archive size={16} aria-hidden />}
            title={t('workspaceSettings.dangerZone.title')}
            description={t('workspaceSettings.dangerZone.description')}
            tone="danger"
          >
            <div className="flex flex-col gap-3 rounded-md border border-error-border bg-error-bg px-3 py-3 dark:border-error-border-dark dark:bg-error-bg-dark">
              <div>
                <p className="text-sm font-medium text-text-primary dark:text-text-inverse">
                  {t('workspaceSettings.dangerZone.deleteWorkspace')}
                </p>
                <p className="mt-1 text-xs leading-5 text-text-secondary dark:text-text-muted">
                  {t('workspaceSettings.dangerZone.deleteDescription')}
                </p>
              </div>
              <LazyPopconfirm
                title={t('workspaceSettings.dangerZone.deleteConfirm')}
                onConfirm={() => {
                  void handleDelete();
                }}
                okText={t('common.delete')}
                cancelText={t('common.cancel')}
                okButtonProps={{ danger: true }}
              >
                <button
                  type="button"
                  disabled={isDeleting}
                  className="inline-flex h-9 items-center justify-center gap-2 rounded-md bg-error px-3 text-sm font-medium text-surface-light transition-colors hover:bg-error-dark disabled:opacity-50 dark:bg-status-text-error-dark dark:text-surface-dark"
                >
                  <Trash2 size={15} />
                  {t('common.delete')}
                </button>
              </LazyPopconfirm>
            </div>
          </SettingsSection>
        </aside>
      </div>
    </div>
  );
};
