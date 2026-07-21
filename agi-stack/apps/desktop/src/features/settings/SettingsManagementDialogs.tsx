import type { AuthState, DesktopRuntimeConfig } from '../../types';
import { AgentDefinitionEditorDialog } from './AgentDefinitionEditorDialog';
import { PluginConfigDialog, PluginInstallDialog } from './PluginManagementDialogs';
import { SkillManagementDialogs } from './SkillManagementDialogs';
import { SubAgentLibraryDialog } from './SubAgentLibraryDialog';
import type { useAgentDefinitionManagement } from './useAgentDefinitionManagement';
import type { usePluginManagement } from './usePluginManagement';
import type { useSkillManagement } from './useSkillManagement';
import type { useSkillPackageManagement } from './useSkillPackageManagement';
import type { useSubAgentLibraryManagement } from './useSubAgentLibraryManagement';

export function SettingsManagementDialogs({
  auth,
  config,
  allowTenantSkillScope,
  agents,
  skills,
  skillPackages,
  plugins,
  subagents,
}: {
  auth: AuthState;
  config: DesktopRuntimeConfig;
  allowTenantSkillScope: boolean;
  agents: ReturnType<typeof useAgentDefinitionManagement>;
  skills: ReturnType<typeof useSkillManagement>;
  skillPackages: ReturnType<typeof useSkillPackageManagement>;
  plugins: ReturnType<typeof usePluginManagement>;
  subagents: ReturnType<typeof useSubAgentLibraryManagement>;
}) {
  const projects = auth.projects.filter((project) => project.tenant_id === config.tenantId);
  return (
    <>
      {agents.dialog ? (
        <AgentDefinitionEditorDialog
          key={agents.dialog.key}
          definition={agents.dialog.definition}
          projects={projects}
          initialProjectId={config.projectId || null}
          busy={agents.busy}
          error={agents.error}
          onClose={agents.close}
          onSave={(input) => void agents.save(input)}
          onDelete={agents.dialog.definition ? () => void agents.remove() : null}
        />
      ) : null}
      <SkillManagementDialogs
        projects={projects}
        initialProjectId={config.projectId || null}
        allowTenantScope={allowTenantSkillScope}
        management={skills}
        packages={skillPackages}
      />
      {plugins.dialog?.kind === 'install' ? (
        <PluginInstallDialog
          key={plugins.dialog.key}
          busy={plugins.dialogBusy}
          error={plugins.dialogError}
          onClose={plugins.closeDialog}
          onInstall={(requirement) => void plugins.install(requirement)}
        />
      ) : null}
      {plugins.dialog?.kind === 'config' ? (
        <PluginConfigDialog
          key={plugins.dialog.key}
          plugin={plugins.dialog.plugin}
          schema={plugins.dialog.schema}
          record={plugins.dialog.record}
          loading={plugins.dialog.loading}
          busy={plugins.dialogBusy}
          error={plugins.dialogError}
          initialConfirmUninstall={plugins.dialog.confirmUninstall}
          onClose={plugins.closeDialog}
          onSave={(input) => void plugins.saveConfig(input)}
          onUninstall={() => void plugins.uninstall()}
        />
      ) : null}
      {subagents.dialog ? (
        <SubAgentLibraryDialog
          key={subagents.dialog.key}
          templates={subagents.dialog.templates}
          loading={subagents.dialog.loading}
          busyId={subagents.busyId}
          error={subagents.error}
          onClose={subagents.close}
          onInstall={(template) => void subagents.install(template)}
        />
      ) : null}
    </>
  );
}
