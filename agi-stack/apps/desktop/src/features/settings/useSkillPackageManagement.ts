import { useCallback, useEffect, useRef, useState } from 'react';

import { DesktopApiClient } from '../../api/client';
import type {
  DesktopRuntimeConfig,
  ManagedSkill,
  ManagedSkillEvolutionDetail,
  ManagedSkillImportInput,
  ManagedSkillVersion,
  ManagedSkillVersionDetail,
  ManagedSkillZipImportInput,
} from '../../types';

export type SkillImportSubmission = {
  archive: File | null;
  package: ManagedSkillImportInput;
};

export type SkillVersionsDialogState = {
  key: string;
  skill: ManagedSkill;
  versions: ManagedSkillVersion[];
  loading: boolean;
  rollbackVersion: number | null;
  preview: ManagedSkillVersionDetail | null;
  previewLoading: boolean;
  canRollback: boolean;
};

export type SkillEvolutionDialogState = {
  key: string;
  skill: ManagedSkill;
  detail: ManagedSkillEvolutionDetail | null;
  loading: boolean;
  running: boolean;
  processingJobId: string | null;
  canManage: boolean;
};

export function useSkillPackageManagement({
  active,
  config,
  contextKey,
  canImport,
  onReload,
  onSelected,
}: {
  active: boolean;
  config: DesktopRuntimeConfig;
  contextKey: string;
  canImport: boolean;
  onReload: () => Promise<void>;
  onSelected: (skillId: string) => void;
}) {
  const [importKey, setImportKey] = useState<string | null>(null);
  const [versionsDialog, setVersionsDialog] = useState<SkillVersionsDialogState | null>(null);
  const [evolutionDialog, setEvolutionDialog] = useState<SkillEvolutionDialogState | null>(null);
  const [importBusy, setImportBusy] = useState(false);
  const [exportBusyId, setExportBusyId] = useState<string | null>(null);
  const [importError, setImportError] = useState<string | null>(null);
  const [versionsError, setVersionsError] = useState<string | null>(null);
  const [packageActionError, setPackageActionError] = useState<string | null>(null);
  const [evolutionError, setEvolutionError] = useState<string | null>(null);
  const contextKeyRef = useRef(contextKey);
  contextKeyRef.current = contextKey;

  useEffect(() => {
    setImportKey(null);
    setVersionsDialog(null);
    setEvolutionDialog(null);
    setImportBusy(false);
    setExportBusyId(null);
    setImportError(null);
    setVersionsError(null);
    setPackageActionError(null);
    setEvolutionError(null);
  }, [active, contextKey]);

  const openImport = useCallback(() => {
    if (!canImport) return;
    setImportError(null);
    setImportKey(crypto.randomUUID());
  }, [canImport]);

  const closeImport = useCallback(() => {
    if (!importBusy) setImportKey(null);
  }, [importBusy]);

  const importPackage = useCallback(
    async (submission: SkillImportSubmission) => {
      if (!importKey || !canImport) return;
      const requestContextKey = contextKey;
      setImportBusy(true);
      setImportError(null);
      try {
        const client = new DesktopApiClient(config);
        const { archive, package: packageInput } = submission;
        const result = archive
          ? await client.importManagedSkillZip(archive, zipImportInput(packageInput))
          : await client.importManagedSkillPackage(packageInput);
        if (contextKeyRef.current !== requestContextKey) return;
        setImportKey(null);
        await onReload();
        onSelected(result.skill.id);
      } catch (error) {
        if (contextKeyRef.current === requestContextKey) setImportError(errorMessage(error));
      } finally {
        if (contextKeyRef.current === requestContextKey) setImportBusy(false);
      }
    },
    [canImport, config, contextKey, importKey, onReload, onSelected]
  );

  const loadVersions = useCallback(
    async (skill: ManagedSkill, key: string, requestContextKey: string) => {
      try {
        const result = await new DesktopApiClient(config).listManagedSkillVersions(skill.id);
        if (contextKeyRef.current !== requestContextKey) return;
        setVersionsDialog((current) =>
          current?.key === key
            ? { ...current, versions: result.versions, loading: false }
            : current
        );
      } catch (error) {
        if (contextKeyRef.current !== requestContextKey) return;
        setVersionsDialog((current) =>
          current?.key === key ? { ...current, versions: [], loading: false } : current
        );
        setVersionsError(errorMessage(error));
      }
    },
    [config]
  );

  const openVersions = useCallback(
    (skill: ManagedSkill, canRollback: boolean) => {
      const key = `${skill.id}:${crypto.randomUUID()}`;
      setVersionsError(null);
      setVersionsDialog({
        key,
        skill,
        versions: [],
        loading: true,
        rollbackVersion: null,
        preview: null,
        previewLoading: false,
        canRollback,
      });
      void loadVersions(skill, key, contextKey);
    },
    [contextKey, loadVersions]
  );

  const closeVersions = useCallback(() => {
    setVersionsDialog((current) =>
      current?.rollbackVersion === null ? null : current
    );
  }, []);

  const rollback = useCallback(
    async (versionNumber: number) => {
      if (!versionsDialog?.canRollback || versionsDialog.rollbackVersion !== null) return;
      const requestContextKey = contextKey;
      const key = versionsDialog.key;
      setVersionsError(null);
      setVersionsDialog((current) =>
        current?.key === key ? { ...current, rollbackVersion: versionNumber } : current
      );
      try {
        const client = new DesktopApiClient(config);
        const updated = await client.rollbackManagedSkill(versionsDialog.skill.id, versionNumber);
        if (contextKeyRef.current !== requestContextKey) return;
        const [versionResult] = await Promise.all([
          client.listManagedSkillVersions(updated.id),
          onReload(),
        ]);
        if (contextKeyRef.current !== requestContextKey) return;
        setVersionsDialog((current) =>
          current?.key === key
            ? {
                ...current,
                skill: updated,
                versions: versionResult.versions,
                rollbackVersion: null,
              }
            : current
        );
        onSelected(updated.id);
      } catch (error) {
        if (contextKeyRef.current !== requestContextKey) return;
        setVersionsError(errorMessage(error));
        setVersionsDialog((current) =>
          current?.key === key ? { ...current, rollbackVersion: null } : current
        );
      }
    },
    [config, contextKey, onReload, onSelected, versionsDialog]
  );

  const previewVersion = useCallback(
    async (versionNumber: number) => {
      if (!versionsDialog || versionsDialog.previewLoading) return;
      const requestContextKey = contextKey;
      const key = versionsDialog.key;
      setVersionsError(null);
      setVersionsDialog((current) =>
        current?.key === key ? { ...current, preview: null, previewLoading: true } : current
      );
      try {
        const preview = await new DesktopApiClient(config).getManagedSkillVersion(
          versionsDialog.skill.id,
          versionNumber
        );
        if (contextKeyRef.current !== requestContextKey) return;
        setVersionsDialog((current) =>
          current?.key === key ? { ...current, preview, previewLoading: false } : current
        );
      } catch (error) {
        if (contextKeyRef.current !== requestContextKey) return;
        setVersionsError(errorMessage(error));
        setVersionsDialog((current) =>
          current?.key === key ? { ...current, previewLoading: false } : current
        );
      }
    },
    [config, contextKey, versionsDialog]
  );

  const closeVersionPreview = useCallback(() => {
    setVersionsDialog((current) => (current ? { ...current, preview: null } : current));
  }, []);

  const exportPackage = useCallback(
    async (skill: ManagedSkill) => {
      if (exportBusyId) return;
      const requestContextKey = contextKey;
      setExportBusyId(skill.id);
      setPackageActionError(null);
      try {
        const exportId = skill.source === 'filesystem' ? skill.name : skill.id;
        const exported = await new DesktopApiClient(config).exportManagedSkillPackage(exportId);
        if (contextKeyRef.current !== requestContextKey) return;
        downloadSkillPackage(skill.name, exported);
      } catch (error) {
        if (contextKeyRef.current === requestContextKey) {
          setPackageActionError(errorMessage(error));
        }
      } finally {
        if (contextKeyRef.current === requestContextKey) setExportBusyId(null);
      }
    },
    [config, contextKey, exportBusyId]
  );

  const loadEvolution = useCallback(
    async (skill: ManagedSkill, key: string, requestContextKey: string) => {
      try {
        const detail = await new DesktopApiClient(config).getManagedSkillEvolution(skill.id);
        if (contextKeyRef.current !== requestContextKey) return;
        setEvolutionDialog((current) =>
          current?.key === key ? { ...current, detail, loading: false } : current
        );
      } catch (error) {
        if (contextKeyRef.current !== requestContextKey) return;
        setEvolutionError(errorMessage(error));
        setEvolutionDialog((current) =>
          current?.key === key ? { ...current, loading: false } : current
        );
      }
    },
    [config]
  );

  const openEvolution = useCallback(
    (skill: ManagedSkill, canManage: boolean) => {
      const key = `${skill.id}:evolution:${crypto.randomUUID()}`;
      setEvolutionError(null);
      setEvolutionDialog({
        key,
        skill,
        detail: null,
        loading: true,
        running: false,
        processingJobId: null,
        canManage,
      });
      void loadEvolution(skill, key, contextKey);
    },
    [contextKey, loadEvolution]
  );

  const closeEvolution = useCallback(() => {
    setEvolutionDialog((current) =>
      current && !current.running && current.processingJobId === null ? null : current
    );
  }, []);

  const runEvolution = useCallback(async () => {
    if (!evolutionDialog?.canManage || evolutionDialog.running) return;
    const requestContextKey = contextKey;
    const key = evolutionDialog.key;
    setEvolutionError(null);
    setEvolutionDialog((current) =>
      current?.key === key ? { ...current, running: true } : current
    );
    try {
      const client = new DesktopApiClient(config);
      await client.runManagedSkillEvolution(evolutionDialog.skill.id);
      const detail = await client.getManagedSkillEvolution(evolutionDialog.skill.id);
      if (contextKeyRef.current !== requestContextKey) return;
      setEvolutionDialog((current) =>
        current?.key === key ? { ...current, detail, running: false } : current
      );
    } catch (error) {
      if (contextKeyRef.current !== requestContextKey) return;
      setEvolutionError(errorMessage(error));
      setEvolutionDialog((current) =>
        current?.key === key ? { ...current, running: false } : current
      );
    }
  }, [config, contextKey, evolutionDialog]);

  const processEvolutionJob = useCallback(
    async (jobId: string, action: 'apply' | 'reject') => {
      if (!evolutionDialog?.canManage || evolutionDialog.processingJobId) return;
      const requestContextKey = contextKey;
      const key = evolutionDialog.key;
      setEvolutionError(null);
      setEvolutionDialog((current) =>
        current?.key === key ? { ...current, processingJobId: jobId } : current
      );
      try {
        const client = new DesktopApiClient(config);
        if (action === 'apply') await client.applyManagedSkillEvolutionJob(jobId);
        else await client.rejectManagedSkillEvolutionJob(jobId);
        const reload = action === 'apply' ? onReload() : Promise.resolve();
        const [detail] = await Promise.all([
          client.getManagedSkillEvolution(evolutionDialog.skill.id),
          reload,
        ]);
        if (contextKeyRef.current !== requestContextKey) return;
        setEvolutionDialog((current) =>
          current?.key === key ? { ...current, detail, processingJobId: null } : current
        );
        if (action === 'apply') onSelected(evolutionDialog.skill.id);
      } catch (error) {
        if (contextKeyRef.current !== requestContextKey) return;
        setEvolutionError(errorMessage(error));
        setEvolutionDialog((current) =>
          current?.key === key ? { ...current, processingJobId: null } : current
        );
      }
    },
    [config, contextKey, evolutionDialog, onReload, onSelected]
  );

  return {
    importKey,
    importBusy,
    importError,
    versionsDialog,
    evolutionDialog,
    versionsError,
    evolutionError,
    exportBusyId,
    packageActionError,
    openImport,
    closeImport,
    importPackage,
    openVersions,
    closeVersions,
    rollback,
    previewVersion,
    closeVersionPreview,
    exportPackage,
    openEvolution,
    closeEvolution,
    runEvolution,
    processEvolutionJob,
  };
}

function downloadSkillPackage(skillName: string, value: unknown): void {
  const blob = new Blob([JSON.stringify(value, null, 2)], { type: 'application/json' });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = `${skillName}.agentskill.json`;
  link.click();
  URL.revokeObjectURL(url);
}

function zipImportInput(input: ManagedSkillImportInput): ManagedSkillZipImportInput {
  return {
    scope: input.scope,
    project_id: input.project_id,
    overwrite: input.overwrite,
    change_summary: input.change_summary,
  };
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}
