import type { ProjectSummary } from '../../types';
import { SkillEditorDialog } from './SkillEditorDialog';
import { SkillEvolutionDialog } from './SkillEvolutionDialog';
import { SkillImportDialog, SkillVersionsDialog } from './SkillPackageDialogs';
import type { useSkillManagement } from './useSkillManagement';
import type { useSkillPackageManagement } from './useSkillPackageManagement';

export function SkillManagementDialogs({
  projects,
  initialProjectId,
  allowTenantScope,
  management,
  packages,
}: {
  projects: ProjectSummary[];
  initialProjectId: string | null;
  allowTenantScope: boolean;
  management: ReturnType<typeof useSkillManagement>;
  packages: ReturnType<typeof useSkillPackageManagement>;
}) {
  return (
    <>
      {management.dialog ? (
        <SkillEditorDialog
          key={management.dialog.key}
          skill={management.dialog.skill}
          projects={projects}
          initialProjectId={initialProjectId}
          allowTenantScope={allowTenantScope}
          loading={management.dialog.loading}
          contentReady={management.dialog.contentReady}
          busy={management.busy}
          error={management.error}
          onClose={management.close}
          onSave={(input) => void management.save(input)}
          onDelete={management.dialog.skill ? () => void management.remove() : null}
        />
      ) : null}
      {packages.importKey ? (
        <SkillImportDialog
          key={packages.importKey}
          projects={projects}
          initialProjectId={initialProjectId}
          allowTenantScope={allowTenantScope}
          busy={packages.importBusy}
          error={packages.importError}
          onClose={packages.closeImport}
          onImport={(submission) => void packages.importPackage(submission)}
        />
      ) : null}
      {packages.versionsDialog ? (
        <SkillVersionsDialog
          key={packages.versionsDialog.key}
          skill={packages.versionsDialog.skill}
          versions={packages.versionsDialog.versions}
          loading={packages.versionsDialog.loading}
          rollbackVersion={packages.versionsDialog.rollbackVersion}
          preview={packages.versionsDialog.preview}
          previewLoading={packages.versionsDialog.previewLoading}
          canRollback={packages.versionsDialog.canRollback}
          error={packages.versionsError}
          onClose={packages.closeVersions}
          onRollback={(versionNumber) => void packages.rollback(versionNumber)}
          onPreview={(versionNumber) => void packages.previewVersion(versionNumber)}
          onClosePreview={packages.closeVersionPreview}
        />
      ) : null}
      {packages.evolutionDialog ? (
        <SkillEvolutionDialog
          key={packages.evolutionDialog.key}
          skill={packages.evolutionDialog.skill}
          detail={packages.evolutionDialog.detail}
          loading={packages.evolutionDialog.loading}
          running={packages.evolutionDialog.running}
          processingJobId={packages.evolutionDialog.processingJobId}
          canManage={packages.evolutionDialog.canManage}
          error={packages.evolutionError}
          onClose={packages.closeEvolution}
          onRun={() => void packages.runEvolution()}
          onProcessJob={(jobId, action) => void packages.processEvolutionJob(jobId, action)}
        />
      ) : null}
    </>
  );
}
