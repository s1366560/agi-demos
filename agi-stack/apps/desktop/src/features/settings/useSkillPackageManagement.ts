import { useCallback, useEffect, useRef, useState } from 'react';

import { DesktopApiClient } from '../../api/client';
import type {
  DesktopRuntimeConfig,
  ManagedSkill,
  ManagedSkillImportInput,
  ManagedSkillVersion,
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
  canRollback: boolean;
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
  const [importBusy, setImportBusy] = useState(false);
  const [importError, setImportError] = useState<string | null>(null);
  const [versionsError, setVersionsError] = useState<string | null>(null);
  const contextKeyRef = useRef(contextKey);
  contextKeyRef.current = contextKey;

  useEffect(() => {
    setImportKey(null);
    setVersionsDialog(null);
    setImportBusy(false);
    setImportError(null);
    setVersionsError(null);
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

  return {
    importKey,
    importBusy,
    importError,
    versionsDialog,
    versionsError,
    openImport,
    closeImport,
    importPackage,
    openVersions,
    closeVersions,
    rollback,
  };
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
