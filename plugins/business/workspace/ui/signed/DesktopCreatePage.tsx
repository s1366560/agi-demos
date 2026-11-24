import React from 'react';
import { createRoot } from 'react-dom/client';
import { useHostAppearance } from './useHostAppearance';
import { Theme } from '@radix-ui/themes';
import '@radix-ui/themes/styles.css';
import '../../../../../agi-stack/apps/desktop/src/styles/tokens.css';
import { WorkspaceCreateDialog } from '../desktop/workspace/WorkspaceCreateDialog';
import { projectDirectory, workspaceCreation } from './createWorkspace';
import en from '../desktop/workspace/workspaceCreate.en.json';
import zh from '../desktop/workspace/workspaceCreate.zh.json';

async function mount() {
  const host = window.memstack;
  const context = await host.getContext();
  if (!context.projectId) throw new Error('project_required');
  const scope = {
    projectId: context.projectId,
    tenantId: context.tenantId,
    epoch: 0,
    contextRevision: 0,
  };
  const directory = projectDirectory(scope.tenantId, scope.projectId);
  let destination = directory;
  const create = workspaceCreation(host);
  const labels: Record<string, string> = context.locale.startsWith('zh') ? zh : en;
  const translate = (key: string, values: Record<string, string | number> = {}) =>
    Object.entries(values).reduce(
      (text, [field, value]) => text.replaceAll('{' + field + '}', String(value)),
      labels[key] ?? key
    );
  function Page() {
    const appearance = useHostAppearance();
    return (
      <Theme
        appearance={appearance}
        accentColor="gray"
        grayColor="slate"
        radius="medium"
        scaling="95%"
      >
        <WorkspaceCreateDialog
          open
          projectName={scope.projectId}
          scope={scope}
          t={translate}
          isDuplicate={(error) => error instanceof Error && error.message === 'conflict'}
          onOpenChange={(open) => {
            if (!open) void host.navigate(destination);
          }}
          onCreate={async (
            { useCase, collaborationMode, sandboxCodeRoot, ...input },
            _scope,
            signal
          ) => {
            const payload = {
              ...input,
              use_case: useCase,
              collaboration_mode: collaborationMode,
              ...(sandboxCodeRoot ? { sandbox_code_root: sandboxCodeRoot } : {}),
            };
            const created = await create(payload, signal);
            destination = directory + '/' + encodeURIComponent(created.id);
          }}
        />
      </Theme>
    );
  }
  createRoot(document.getElementById('root')!).render(<Page />);
}
void mount();
