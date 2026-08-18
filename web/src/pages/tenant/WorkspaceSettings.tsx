import type React from 'react';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router-dom';

import { useCurrentWorkspace, useWorkspaceActions, useWorkspaceMembers } from '@/stores/workspace';

import { workspaceService } from '@/services/workspaceService';

import { useUnsavedChangesWarning } from '@/hooks/useUnsavedChangesWarning';

import { confirmAction } from '@/utils/confirmAction';
import {
  sourceControlDefaultsForProvider,
  isIsolatedSandboxCodeRoot,
  normaliseSandboxCodeRoot,
  workspaceTypeForUseCase,
} from '@/utils/workspaceConfig';

import { Spinner } from '@/components/common/Spinner';
import { useLazyMessage } from '@/components/ui/lazyAntd';
import { AutonomySection } from '@/components/workspace/settings/AutonomySection';
import { CodeContextSection } from '@/components/workspace/settings/CodeContextSection';
import { DangerZoneSection } from '@/components/workspace/settings/DangerZoneSection';
import { DeliverySection } from '@/components/workspace/settings/DeliverySection';
import { GeneralSettingsSection } from '@/components/workspace/settings/GeneralSettingsSection';
import { MembersSection } from '@/components/workspace/settings/MembersSection';
import { MetadataSection } from '@/components/workspace/settings/MetadataSection';
import { OperatingModelSection } from '@/components/workspace/settings/OperatingModelSection';
import { SettingsHeader } from '@/components/workspace/settings/SettingsHeader';
import { SourceControlSection } from '@/components/workspace/settings/SourceControlSection';
import { SummarySection } from '@/components/workspace/settings/SummarySection';

import {
  COLLABORATION_MODE_OPTIONS,
  USE_CASE_OPTIONS,
  buildWorkspaceMetadataDraft,
  createBlankDeliveryService,
  getOptionLabel,
  syncDraftFromWorkspace,
  type SettingsDraft,
} from './workspaceSettingsModel';

import type {
  WorkspaceDeliveryServiceConfig,
  WorkspaceSourceControlProvider,
} from '@/types/workspace';

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
  const { setCurrentWorkspace } = useWorkspaceActions();

  const [draft, setDraft] = useState<SettingsDraft | null>(null);
  const [isDirty, setIsDirty] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [isDeleting, setIsDeleting] = useState(false);
  const lastSyncedSignature = useRef<string | null>(null);

  useUnsavedChangesWarning(isDirty && !isSaving);

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

  const updateSourceControlProvider = useCallback((provider: WorkspaceSourceControlProvider) => {
    setDraft((current) => {
      if (!current) return current;
      const currentDefaults = sourceControlDefaultsForProvider(current.sourceControlProvider);
      const nextDefaults = sourceControlDefaultsForProvider(provider);
      return {
        ...current,
        sourceControlProvider: provider,
        sourceControlServerUrl:
          !current.sourceControlServerUrl ||
          current.sourceControlServerUrl === currentDefaults.serverUrl
            ? nextDefaults.serverUrl
            : current.sourceControlServerUrl,
        sourceControlAuthTokenEnv:
          !current.sourceControlAuthTokenEnv ||
          current.sourceControlAuthTokenEnv === currentDefaults.authTokenEnv
            ? nextDefaults.authTokenEnv
            : current.sourceControlAuthTokenEnv,
        sourceControlCloneUrl: '',
      };
    });
    setIsDirty(true);
  }, []);

  const updateSourceControlDraft = useCallback(
    <TKey extends keyof SettingsDraft>(key: TKey, value: SettingsDraft[TKey]) => {
      setDraft((current) => {
        if (!current) return current;
        const next = { ...current, [key]: value };
        if (
          key === 'sourceControlRepo' ||
          key === 'sourceControlDefaultBranch' ||
          key === 'sourceControlServerUrl'
        ) {
          next.sourceControlCloneUrl = '';
        }
        return next;
      });
      setIsDirty(true);
    },
    []
  );

  const updateDeliveryService = useCallback(
    <TKey extends keyof WorkspaceDeliveryServiceConfig>(
      index: number,
      key: TKey,
      value: WorkspaceDeliveryServiceConfig[TKey]
    ) => {
      setDraft((current) => {
        if (!current) return current;
        const services = current.deliveryServices.map((service, serviceIndex) =>
          serviceIndex === index ? { ...service, [key]: value } : service
        );
        return { ...current, deliveryServices: services };
      });
      setIsDirty(true);
    },
    []
  );

  const addDeliveryService = useCallback(() => {
    setDraft((current) => {
      if (!current) return current;
      return {
        ...current,
        deliveryServices: [
          ...current.deliveryServices,
          createBlankDeliveryService(current.deliveryServices.length + 1),
        ],
      };
    });
    setIsDirty(true);
  }, []);

  const removeDeliveryService = useCallback((index: number) => {
    setDraft((current) => {
      if (!current) return current;
      return {
        ...current,
        deliveryServices: current.deliveryServices.filter(
          (_, serviceIndex) => serviceIndex !== index
        ),
      };
    });
    setIsDirty(true);
  }, []);

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

  const handleReset = useCallback(async () => {
    if (!workspace) return;
    if (
      isDirty &&
      !(await confirmAction({
        title: t('workspaceSettings.actions.resetConfirm'),
        danger: true,
      }))
    ) {
      return;
    }
    setDraft(syncDraftFromWorkspace(workspace));
    setIsDirty(false);
  }, [isDirty, t, workspace]);

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
      // Land on the project workspace list: it always matches a route and
      // reloads fresh data, unlike '../..' which resolved to a non-route
      // (/tenant/{t}/project) and left the main area blank.
      void navigate(`/tenant/${tenantId}/project/${projectId}/workspaces`);
    } catch {
      message?.error(t('workspaceSettings.dangerZone.deleteFailed'));
    } finally {
      setIsDeleting(false);
    }
  }, [tenantId, projectId, workspaceId, message, t, navigate]);

  if (!workspace || !draft) {
    return (
      <div className="flex min-h-[240px] items-center justify-center" role="status">
        <Spinner size={32} />
      </div>
    );
  }

  return (
    <div className="mx-auto flex w-full max-w-6xl flex-col gap-5 px-4 pb-8 pt-4 sm:px-6">
      <SettingsHeader
        isDirty={isDirty}
        isSaving={isSaving}
        canSave={canSave}
        onReset={handleReset}
        onSave={handleSave}
      />

      <SummarySection
        useCaseLabel={selectedUseCaseLabel}
        workspaceType={workspaceType}
        modeLabel={selectedModeLabel}
        memberCount={members.length}
      />

      <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_22rem]">
        <div className="flex min-w-0 flex-col gap-5">
          <GeneralSettingsSection draft={draft} updateDraft={updateDraft} />
          <OperatingModelSection
            draft={draft}
            updateDraft={updateDraft}
            workspaceType={workspaceType}
          />
          <CodeContextSection
            draft={draft}
            updateDraft={updateDraft}
            codeRootValid={codeRootValid}
          />
          <SourceControlSection
            draft={draft}
            updateSourceControlProvider={updateSourceControlProvider}
            updateSourceControlDraft={updateSourceControlDraft}
          />
          <DeliverySection
            draft={draft}
            updateDraft={updateDraft}
            onAddService={addDeliveryService}
            onRemoveService={removeDeliveryService}
            onUpdateService={updateDeliveryService}
          />
          <AutonomySection draft={draft} updateDraft={updateDraft} />
          <MetadataSection
            draft={draft}
            updateDraft={updateDraft}
            metadataError={metadataDraft.error}
          />
        </div>

        <aside className="flex min-w-0 flex-col gap-5">
          <MembersSection tenantId={tenantId} projectId={projectId} workspaceId={workspaceId} />
          <DangerZoneSection
            workspaceName={draft.name}
            isDeleting={isDeleting}
            onDelete={handleDelete}
          />
        </aside>
      </div>
    </div>
  );
};
