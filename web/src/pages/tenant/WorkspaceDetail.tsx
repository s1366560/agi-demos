import { useCallback, useEffect, useMemo, useState, Suspense, lazy } from 'react';
import type { MouseEvent as ReactMouseEvent } from 'react';

import { Link, useParams } from 'react-router-dom';

import { Tabs, Segmented } from 'antd';

import { useCurrentProject } from '@/stores/project';
import { useCurrentTenant } from '@/stores/tenant';
import {
  useCurrentWorkspace,
  useWorkspaceActions,
  useWorkspaceLoading,
  useWorkspaceAgents,
  useWorkspaceTopology,
  useWorkspaceObjectives,
  useWorkspaceGenes,
  useWorkspaceStore,
} from '@/stores/workspace';

import { unifiedEventService } from '@/services/unifiedEventService';

import { AddAgentModal } from '@/components/workspace/AddAgentModal';
import { BlackboardPanel } from '@/components/workspace/BlackboardPanel';
import { ChatPanel } from '@/components/workspace/chat/ChatPanel';
import { GeneList } from '@/components/workspace/genes/GeneList';
import { HexContextMenu } from '@/components/workspace/hex/HexContextMenu';
import { HexGrid } from '@/components/workspace/hex/HexGrid';
import { MemberPanel } from '@/components/workspace/MemberPanel';
import { ObjectiveCreateModal } from '@/components/workspace/objectives/ObjectiveCreateModal';
import { ObjectiveList } from '@/components/workspace/objectives/ObjectiveList';
import { PresenceBar } from '@/components/workspace/presence/PresenceBar';
import { TaskBoard } from '@/components/workspace/TaskBoard';

import type { CyberObjectiveType } from '@/types/workspace';

const HexCanvas3D = lazy(() => import('@/components/workspace/hex3d').then((m) => ({ default: m.HexCanvas3D })));

export function WorkspaceDetail() {
  const params = useParams<{ tenantId?: string; projectId?: string; workspaceId?: string }>();
  const currentTenant = useCurrentTenant();
  const currentProject = useCurrentProject();
  const currentWorkspace = useCurrentWorkspace();
  const isLoading = useWorkspaceLoading();
  const { loadWorkspaceSurface, createObjective, deleteObjective, deleteGene, updateGene, bindAgent } = useWorkspaceActions();
  const agents = useWorkspaceAgents();
  const topology = useWorkspaceTopology();
  const objectives = useWorkspaceObjectives();
  const genes = useWorkspaceGenes();

  const [showCreateObjective, setShowCreateObjective] = useState(false);
  const [hexAgentModal, setHexAgentModal] = useState<{ q: number; r: number } | null>(null);

  const [contextMenu, setContextMenu] = useState<{
    q: number;
    r: number;
    x: number;
    y: number;
  } | null>(null);

  const [viewMode, setViewMode] = useState<'2D' | '3D'>(() => {
    return (localStorage.getItem('workspace-view-mode') ?? '2D') as '2D' | '3D';
  });

  const handleViewModeChange = (val: '2D' | '3D') => {
    setViewMode(val);
    localStorage.setItem('workspace-view-mode', val);
  };

  const tenantId = useMemo(
    () => params.tenantId ?? currentTenant?.id ?? null,
    [params.tenantId, currentTenant?.id]
  );
  const projectId = useMemo(
    () => params.projectId ?? currentProject?.id ?? null,
    [params.projectId, currentProject?.id]
  );
  const workspaceId = params.workspaceId ?? null;

  useEffect(() => {
    if (!tenantId || !projectId || !workspaceId) return;
    void loadWorkspaceSurface(tenantId, projectId, workspaceId);
  }, [tenantId, projectId, workspaceId, loadWorkspaceSurface]);

  useEffect(() => {
    if (!workspaceId) return;

    const store = useWorkspaceStore.getState();
    const unsubscribe = unifiedEventService.subscribeWorkspace(workspaceId, (event) => {
      const type = event.type;
      const data = event.data as Record<string, unknown>;

      if (type === 'workspace_message_created') {
        store.handleChatEvent({ type, data });
      }
    });

    return () => {
      unsubscribe();
    };
  }, [workspaceId]);

  const handleSelectHex = (_q: number, _r: number) => {};

  const handleContextMenu = (q: number, r: number, e: ReactMouseEvent | MouseEvent) => {
    setContextMenu({ q, r, x: ('clientX' in e ? e.clientX : 0), y: ('clientY' in e ? e.clientY : 0) });
  };

  const handleHexAction = useCallback((action: string, q: number, r: number) => {
    if (action === 'assign_agent') {
      setHexAgentModal({ q, r });
    }
  }, []);

  const handleAddAgentFromHex = useCallback(
    async (data: { agent_id: string; display_name?: string; description?: string }) => {
      if (!tenantId || !projectId || !workspaceId) return;
      await bindAgent(tenantId, projectId, workspaceId, {
        ...data,
        hex_q: hexAgentModal?.q,
        hex_r: hexAgentModal?.r,
      });
    },
    [bindAgent, tenantId, projectId, workspaceId, hexAgentModal]
  );

  if (!tenantId || !projectId || !workspaceId) {
    return <div className="p-6 text-slate-500">Missing workspace context.</div>;
  }

  return (
    <div className="flex flex-col h-full p-6 space-y-4">
      <header>
        <h1 className="text-2xl font-bold">{currentWorkspace?.name ?? 'Workspace'}</h1>
        <p className="text-sm text-slate-500">{workspaceId}</p>
        <div className="mt-3">
          <Link
            to={`/tenant/${tenantId}/agent-workspace?projectId=${projectId}&workspaceId=${workspaceId}`}
            className="inline-flex items-center rounded-md bg-primary px-3 py-2 text-sm font-medium text-white hover:opacity-90"
          >
            Open in Agent Workspace
          </Link>
        </div>
      </header>
      <PresenceBar workspaceId={workspaceId} />
      {isLoading ? (
        <div className="text-sm text-slate-500">Loading workspace surface...</div>
      ) : null}
      <div className="flex-1 flex gap-4 min-h-0">
        <div className="flex-[2] relative min-h-[500px] rounded-lg border border-slate-200 bg-white overflow-hidden flex flex-col">
          <div className="absolute top-4 right-4 z-10 bg-white/80 backdrop-blur rounded p-1 shadow-sm">
            <Segmented
              options={['2D', '3D']}
              value={viewMode}
              onChange={(val) => { handleViewModeChange(val as '2D' | '3D'); }}
              size="small"
            />
          </div>
          <div className="flex-1 relative">
            {viewMode === '2D' ? (
              <HexGrid
                agents={agents}
                nodes={topology.nodes}
                edges={topology.edges}
                objectives={objectives}
                onSelectHex={handleSelectHex}
                onContextMenu={handleContextMenu}
              />
            ) : (
              <Suspense fallback={<div className="flex items-center justify-center h-full text-slate-500">Loading 3D View...</div>}>
                <HexCanvas3D
                  agents={agents}
                  nodes={topology.nodes}
                  edges={topology.edges}
                  objectives={objectives}
                  onSelectHex={handleSelectHex}
                  onContextMenu={handleContextMenu}
                />
              </Suspense>
            )}
            {contextMenu && (
              <HexContextMenu
                q={contextMenu.q}
                r={contextMenu.r}
                x={contextMenu.x}
                y={contextMenu.y}
                onClose={() => { setContextMenu(null); }}
                onAction={handleHexAction}
              />
            )}
          </div>
        </div>
        <div className="flex-1 space-y-4 overflow-y-auto">
          <Tabs
            defaultActiveKey="1"
            items={[
              {
                key: '1',
                label: 'Board',
                children: (
                  <div className="space-y-4">
                    <BlackboardPanel tenantId={tenantId} projectId={projectId} workspaceId={workspaceId} />
                    <TaskBoard workspaceId={workspaceId} />
                  </div>
                ),
              },
              {
                key: '2',
                label: 'Objectives',
                children: (
                  <ObjectiveList
                    objectives={objectives}
                    onDelete={(id) => { void deleteObjective(tenantId, projectId, workspaceId, id); }}
                    onCreate={() => { setShowCreateObjective(true); }}
                    loading={isLoading}
                  />
                ),
              },
              {
                key: '3',
                label: 'Genes',
                children: (
                  <GeneList
                    genes={genes}
                    onDelete={(id) => { void deleteGene(tenantId, projectId, workspaceId, id); }}
                    onToggleActive={(id, active) => { void updateGene(tenantId, projectId, workspaceId, id, { is_active: active }); }}
                    loading={isLoading}
                  />
                ),
              },
              {
                key: '4',
                label: 'Members',
                children: <MemberPanel tenantId={tenantId} projectId={projectId} workspaceId={workspaceId} />,
              },
              {
                key: '5',
                label: 'Chat',
                children: (
                  <div className="h-[500px]">
                    <ChatPanel tenantId={tenantId} projectId={projectId} workspaceId={workspaceId} />
                  </div>
                ),
              },
            ]}
          />
        </div>
      </div>
      <ObjectiveCreateModal
        open={showCreateObjective}
        onClose={() => { setShowCreateObjective(false); }}
        onSubmit={(data) => {
          const payload: {
            title: string;
            description?: string;
            obj_type?: CyberObjectiveType;
            parent_id?: string;
          } = { title: data.title, obj_type: data.obj_type };
          if (data.description !== undefined) payload.description = data.description;
          if (data.parent_id !== undefined) payload.parent_id = data.parent_id;
          void createObjective(tenantId, projectId, workspaceId, payload).then(() => {
            setShowCreateObjective(false);
          });
        }}
        parentObjectives={objectives}
      />
      <AddAgentModal
        open={hexAgentModal != null}
        onClose={() => { setHexAgentModal(null); }}
        onSubmit={handleAddAgentFromHex}
        hexCoords={hexAgentModal}
      />
    </div>
  );
}
