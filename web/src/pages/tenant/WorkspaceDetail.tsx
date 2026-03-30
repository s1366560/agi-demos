import { useCallback, useEffect, useMemo, useState, Suspense, lazy } from 'react';
import type { MouseEvent as ReactMouseEvent } from 'react';

import { useTranslation } from 'react-i18next';
import { Link, useParams } from 'react-router-dom';

import { Tabs, Segmented, Alert, Skeleton } from 'antd';

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
  useWorkspaceError,
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

import { WorkspaceSettingsPanel } from './WorkspaceSettings';

import type { CyberObjectiveType } from '@/types/workspace';

const HexCanvas3D = lazy(() => import('@/components/workspace/hex3d').then((m) => ({ default: m.HexCanvas3D })));

export function WorkspaceDetail() {
  const params = useParams<{ tenantId?: string; projectId?: string; workspaceId?: string }>();
  const currentTenant = useCurrentTenant();
  const currentProject = useCurrentProject();
  const currentWorkspace = useCurrentWorkspace();
  const isLoading = useWorkspaceLoading();
  const error = useWorkspaceError();
  const { t } = useTranslation();
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
      const payload: Parameters<typeof bindAgent>[3] = { ...data };
      if (hexAgentModal?.q !== undefined) payload.hex_q = hexAgentModal.q;
      if (hexAgentModal?.r !== undefined) payload.hex_r = hexAgentModal.r;
      await bindAgent(tenantId, projectId, workspaceId, payload);
    },
    [bindAgent, tenantId, projectId, workspaceId, hexAgentModal]
  );

  if (!tenantId || !projectId || !workspaceId) {
    return <div className="p-6 text-slate-500 dark:text-slate-400">{t('workspaceDetail.missingContext')}</div>;
  }

  return (
    <div className="flex flex-col h-full p-3 sm:p-4 md:p-6 space-y-3 sm:space-y-4">
      <header>
        <h1 className="text-2xl font-bold">{currentWorkspace?.name ?? t('workspaceDetail.title')}</h1>
        <p className="text-sm text-slate-500 dark:text-slate-400">{workspaceId}</p>
        <div className="mt-3">
          <Link
            to={`/tenant/${tenantId}/agent-workspace?projectId=${projectId}&workspaceId=${workspaceId}`}
            className="inline-flex items-center rounded-md bg-primary px-3 py-2 text-sm font-medium text-white hover:opacity-90 transition-colors duration-200"
          >
            {t('workspaceDetail.openInAgentWorkspace')}
          </Link>
        </div>
      </header>
      <PresenceBar workspaceId={workspaceId} />
      {error && (
        <Alert
          type="error"
          showIcon
          message={t('workspaceDetail.errorLoadingWorkspace')}
          closable
          className="mb-3"
        />
      )}
      {isLoading ? (
        <div className="space-y-3">
          <Skeleton active paragraph={{ rows: 1 }} />
          <Skeleton active paragraph={{ rows: 3 }} />
        </div>
      ) : null}
      {/* Ant Design Tabs lacks a native API to make the content area flex-1 and scrollable, requiring these deep overrides */}
      <div className="flex-1 min-h-0 flex flex-col [&_.ant-tabs-content-holder]:flex-1 [&_.ant-tabs-content-holder]:overflow-y-auto [&_.ant-tabs-content]:h-full [&_.ant-tabs-tabpane]:h-full">
        <Tabs
          defaultActiveKey="overview"
          destroyInactiveTabPane
          animated
          className="h-full flex flex-col"
          items={[
            {
              key: 'overview',
              label: t('workspaceDetail.tabs.overview'),
              children: (
                <div className="relative min-h-[500px] h-full rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 overflow-hidden flex flex-col transition-colors duration-200">
                  <div className="absolute top-4 right-4 z-10 bg-white/80 dark:bg-slate-800/80 backdrop-blur rounded p-1 shadow-sm transition-colors duration-200">
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
                        onContextMenu={handleContextMenu}
                      />
                    ) : (
                      <Suspense fallback={<div className="flex items-center justify-center h-full text-slate-500 dark:text-slate-400">{t('workspaceDetail.loading3DView')}</div>}>
                        <HexCanvas3D
                          agents={agents}
                          nodes={topology.nodes}
                          edges={topology.edges}
                          objectives={objectives}
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
              ),
            },
            {
              key: 'board',
              label: t('workspaceDetail.tabs.board'),
              children: (
                <div className="space-y-4">
                  <BlackboardPanel tenantId={tenantId} projectId={projectId} workspaceId={workspaceId} />
                  <TaskBoard workspaceId={workspaceId} />
                </div>
              ),
            },
            {
              key: 'objectives',
              label: t('workspaceDetail.tabs.objectives'),
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
              key: 'genes',
              label: t('workspaceDetail.tabs.genes'),
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
              key: 'members',
              label: t('workspaceDetail.tabs.members'),
              children: <MemberPanel tenantId={tenantId} projectId={projectId} workspaceId={workspaceId} />,
            },
            {
              key: 'chat',
              label: t('workspaceDetail.tabs.chat'),
              children: (
                <div className="h-full min-h-[300px] sm:min-h-[400px] md:min-h-[500px]">
                  <ChatPanel tenantId={tenantId} projectId={projectId} workspaceId={workspaceId} />
                </div>
              ),
            },
            {
              key: 'settings',
              label: t('workspaceDetail.tabs.settings'),
              children: (
                <div className="h-full overflow-y-auto">
                  <WorkspaceSettingsPanel tenantId={tenantId} projectId={projectId} workspaceId={workspaceId} />
                </div>
              ),
            },
          ]}
        />
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
