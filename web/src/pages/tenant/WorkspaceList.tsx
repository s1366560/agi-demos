import { useEffect, useState } from 'react';

import { Link, useParams } from 'react-router-dom';

import { LayoutGrid } from 'lucide-react';

import { useCurrentProject, useProjectStore } from '@/stores/project';
import { useCurrentTenant } from '@/stores/tenant';
import { useWorkspaceActions, useWorkspaceLoading, useWorkspaces } from '@/stores/workspace';

import { EmptyStateSimple } from '@/components/shared/ui/EmptyStateVariant';

export function WorkspaceList() {
  const params = useParams<{ tenantId?: string; projectId?: string }>();
  const currentTenant = useCurrentTenant();
  const currentProject = useCurrentProject();
  const projects = useProjectStore((state) => state.projects);
  const listProjects = useProjectStore((state) => state.listProjects);
  const workspaces = useWorkspaces();
  const isLoading = useWorkspaceLoading();
  const { loadWorkspaces, createWorkspace } = useWorkspaceActions();
  const [name, setName] = useState('');

  const tenantId = params.tenantId ?? currentTenant?.id ?? null;
  const projectId = params.projectId ?? currentProject?.id ?? projects[0]?.id ?? null;

  useEffect(() => {
    if (!tenantId || params.projectId || currentProject || projects.length > 0) return;
    void listProjects(tenantId).catch(() => {
      // ignore and keep empty-state guidance visible
    });
  }, [tenantId, params.projectId, currentProject, projects.length, listProjects]);

  useEffect(() => {
    if (!tenantId || !projectId) return;
    void loadWorkspaces(tenantId, projectId);
  }, [tenantId, projectId, loadWorkspaces]);

  const onCreate = async () => {
    if (!tenantId || !projectId || !name.trim()) return;
    await createWorkspace(tenantId, projectId, { name: name.trim() });
    setName('');
  };

  if (!tenantId || !projectId) {
    return <div className="p-6 text-slate-500">Select tenant and project to view workspaces.</div>;
  }

  return (
    <div className="p-6 space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">Workspaces</h1>
      </div>
      <div className="flex gap-2">
        <input
          placeholder="Workspace name"
          className="border rounded px-3 py-2 text-sm"
          value={name}
          onChange={(e) => {
            setName(e.target.value);
          }}
        />
        <button type="button" className="px-3 py-2 bg-primary text-white rounded" onClick={() => void onCreate()}>
          Create workspace
        </button>
      </div>
      {isLoading ? <div className="text-sm text-slate-500">Loading...</div> : null}
      <div className="grid gap-2">
        {!isLoading && workspaces.length === 0 ? (
          <EmptyStateSimple
            icon={LayoutGrid}
            title="No workspaces"
            description="Create a workspace to organize your agents"
          />
        ) : (
          workspaces.map((workspace) => (
            <Link
              key={workspace.id}
              to={`/tenant/${tenantId}/project/${projectId}/blackboard?workspaceId=${workspace.id}`}
              className="border rounded p-3 bg-white hover:border-primary"
            >
              <div className="font-medium">{workspace.name}</div>
              <div className="text-xs text-slate-500">{workspace.id}</div>
            </Link>
          ))
        )}
      </div>
    </div>
  );
}
