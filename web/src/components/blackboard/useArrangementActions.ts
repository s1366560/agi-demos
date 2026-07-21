import { useCallback, useState } from 'react';

import { useTranslation } from 'react-i18next';

import { useLazyMessage } from '@/components/ui/lazyAntd';
import { hexToPixel } from '@/components/workspace/hex/useHexLayout';

import {
  coordKey,
  DEFAULT_AGENT_COLOR,
  hasHex,
  HUMAN_SEAT_COLOR,
  RESERVED_CENTER_KEY,
} from './arrangementUtils';

import { getErrorMessage } from '@/types/common';
import type { TopologyNode, WorkspaceAgent } from '@/types/workspace';
import { confirmAction } from '@/utils/confirmAction';

import type { MoveMode, SelectionState } from './arrangementUtils';

type BindAgentData = {
  agent_id: string;
  display_name?: string;
  description?: string;
  hex_q?: number;
  hex_r?: number;
};

type UpdateAgentData = Partial<{
  display_name: string;
  description: string;
  config: Record<string, unknown>;
  is_active: boolean;
  hex_q: number;
  hex_r: number;
  theme_color: string;
  label: string;
}>;

type CreateNodeData = {
  node_type: TopologyNode['node_type'];
  title?: string;
  position_x?: number;
  position_y?: number;
  hex_q?: number;
  hex_r?: number;
  status?: string;
  data?: Record<string, unknown>;
};

type UpdateNodeData = Partial<{
  title: string;
  position_x: number;
  position_y: number;
  hex_q: number;
  hex_r: number;
  data: Record<string, unknown>;
}>;

interface UseArrangementActionsParams {
  tenantId: string;
  projectId: string;
  workspaceId: string;
  agents: WorkspaceAgent[];
  nodes: TopologyNode[];
  selection: SelectionState | null;
  moveMode: MoveMode;
  selectedAgent: WorkspaceAgent | null;
  selectedNode: TopologyNode | null;
  agentByCoord: Map<string, WorkspaceAgent>;
  nodeByCoord: Map<string, TopologyNode>;
  setSelection: (s: SelectionState | null) => void;
  setMoveMode: (m: MoveMode) => void;
  bindAgent: (
    tenantId: string,
    projectId: string,
    workspaceId: string,
    data: BindAgentData
  ) => Promise<WorkspaceAgent>;
  updateAgentBinding: (
    tenantId: string,
    projectId: string,
    workspaceId: string,
    workspaceAgentId: string,
    data: UpdateAgentData
  ) => Promise<WorkspaceAgent>;
  unbindAgent: (
    tenantId: string,
    projectId: string,
    workspaceId: string,
    workspaceAgentId: string
  ) => Promise<void>;
  moveAgent: (
    tenantId: string,
    projectId: string,
    workspaceId: string,
    workspaceAgentId: string,
    q: number,
    r: number
  ) => Promise<WorkspaceAgent>;
  createTopologyNode: (workspaceId: string, data: CreateNodeData) => Promise<TopologyNode>;
  updateTopologyNode: (
    workspaceId: string,
    nodeId: string,
    data: UpdateNodeData
  ) => Promise<TopologyNode>;
  deleteTopologyNode: (workspaceId: string, nodeId: string) => Promise<void>;
  onOpenBlackboard: () => void;
}

export interface ArrangementActions {
  pendingAction: string | null;
  labelDraft: string;
  colorDraft: string;
  addAgentOpen: boolean;
  setLabelDraft: (v: string) => void;
  setColorDraft: (v: string) => void;
  setAddAgentOpen: (v: boolean) => void;
  handleMoveSelection: (q: number, r: number) => Promise<void>;
  handleActivateHex: (q: number, r: number) => Promise<void>;
  handleCreateNode: (
    nodeType: TopologyNode['node_type'],
    targetHex?: { q: number; r: number }
  ) => Promise<void>;
  handleAddAgent: (data: {
    agent_id: string;
    display_name?: string;
    description?: string;
  }) => Promise<void>;
  handleSaveSelection: () => Promise<void>;
  handleDeleteSelection: () => Promise<void>;
  beginMoveMode: () => void;
}

export function useArrangementActions(params: UseArrangementActionsParams): ArrangementActions {
  const { t } = useTranslation();
  const message = useLazyMessage();

  const [pendingAction, setPendingAction] = useState<string | null>(null);
  const [labelDraft, setLabelDraft] = useState('');
  const [colorDraft, setColorDraft] = useState(DEFAULT_AGENT_COLOR);
  const [addAgentOpen, setAddAgentOpen] = useState(false);

  const occupiedByOther = useCallback(
    (q: number, r: number, currentKey?: string | null) => {
      const targetKey = coordKey(q, r);
      if (targetKey === RESERVED_CENTER_KEY) {
        return true;
      }
      if (targetKey === currentKey) {
        return false;
      }
      return params.agentByCoord.has(targetKey) || params.nodeByCoord.has(targetKey);
    },
    [params.agentByCoord, params.nodeByCoord]
  );

  const handleMoveSelection = useCallback(
    async (q: number, r: number) => {
      if (!params.moveMode) {
        return;
      }

      if (params.moveMode.kind === 'agent') {
        const movingAgentId = params.moveMode.agentId;
        const agent = params.agents.find((item) => item.id === movingAgentId);
        if (!agent) {
          return;
        }
        const currentKey =
          hasHex(agent.hex_q) && hasHex(agent.hex_r) ? coordKey(agent.hex_q, agent.hex_r) : null;
        if (occupiedByOther(q, r, currentKey)) {
          message?.warning(
            t(
              'blackboard.arrangement.messages.slotUnavailable',
              'That workstation is already occupied.'
            )
          );
          return;
        }

        setPendingAction('move-agent');
        try {
          const updatedAgent = await params.moveAgent(
            params.tenantId,
            params.projectId,
            params.workspaceId,
            agent.id,
            q,
            r
          );
          params.setSelection({ kind: 'agent', agentId: updatedAgent.id });
          params.setMoveMode(null);
        } catch (error) {
          message?.error(getErrorMessage(error));
        } finally {
          setPendingAction(null);
        }
        return;
      }

      const movingNodeId = params.moveMode.nodeId;
      const node = params.nodes.find((item) => item.id === movingNodeId);
      if (!node) {
        return;
      }
      const currentKey =
        hasHex(node.hex_q) && hasHex(node.hex_r) ? coordKey(node.hex_q, node.hex_r) : null;
      if (occupiedByOther(q, r, currentKey)) {
        message?.warning(
          t(
            'blackboard.arrangement.messages.slotUnavailable',
            'That workstation is already occupied.'
          )
        );
        return;
      }

      const logicalPosition = hexToPixel(q, r, 1);
      setPendingAction('move-node');
      try {
        const updatedNode = await params.updateTopologyNode(params.workspaceId, node.id, {
          hex_q: q,
          hex_r: r,
          position_x: logicalPosition.x,
          position_y: logicalPosition.y,
        });
        params.setSelection({ kind: 'node', nodeId: updatedNode.id });
        params.setMoveMode(null);
      } catch (error) {
        message?.error(getErrorMessage(error));
      } finally {
        setPendingAction(null);
      }
    },
    [message, occupiedByOther, params, t]
  );

  const handleActivateHex = useCallback(
    async (q: number, r: number) => {
      if (params.moveMode) {
        await handleMoveSelection(q, r);
        return;
      }

      const key = coordKey(q, r);
      if (key === RESERVED_CENTER_KEY) {
        params.setSelection({ kind: 'blackboard', q, r });
        params.onOpenBlackboard();
        return;
      }

      const agent = params.agentByCoord.get(key);
      if (agent) {
        params.setSelection({ kind: 'agent', agentId: agent.id });
        return;
      }

      const node = params.nodeByCoord.get(key);
      if (node) {
        params.setSelection({ kind: 'node', nodeId: node.id });
        return;
      }

      params.setSelection({ kind: 'empty', q, r });
    },
    [handleMoveSelection, params]
  );

  const handleCreateNode = useCallback(
    async (nodeType: TopologyNode['node_type'], targetHex?: { q: number; r: number }) => {
      const target =
        targetHex ??
        (params.selection?.kind === 'empty'
          ? { q: params.selection.q, r: params.selection.r }
          : null);

      if (!target) {
        return;
      }
      const logicalPosition = hexToPixel(target.q, target.r, 1);
      const defaultTitle =
        nodeType === 'human_seat'
          ? t('blackboard.arrangement.defaults.humanSeat', 'Human seat')
          : t('blackboard.arrangement.defaults.corridor', 'Corridor');

      setPendingAction(`create-${nodeType}`);
      try {
        const createdNode = await params.createTopologyNode(params.workspaceId, {
          node_type: nodeType,
          title: defaultTitle,
          hex_q: target.q,
          hex_r: target.r,
          position_x: logicalPosition.x,
          position_y: logicalPosition.y,
          status: 'active',
          data: nodeType === 'human_seat' ? { color: HUMAN_SEAT_COLOR } : {},
        });
        params.setSelection({ kind: 'node', nodeId: createdNode.id });
      } catch (error) {
        message?.error(getErrorMessage(error));
      } finally {
        setPendingAction(null);
      }
    },
    [message, params, t]
  );

  const handleAddAgent = useCallback(
    async (data: { agent_id: string; display_name?: string; description?: string }) => {
      if (params.selection?.kind !== 'empty') {
        return;
      }
      setPendingAction('add-agent');
      try {
        const agent = await params.bindAgent(
          params.tenantId,
          params.projectId,
          params.workspaceId,
          {
            ...data,
            hex_q: params.selection.q,
            hex_r: params.selection.r,
          }
        );
        params.setSelection({ kind: 'agent', agentId: agent.id });
        message?.success(
          t('blackboard.arrangement.messages.agentPlaced', 'Agent placed on the workstation.')
        );
      } catch (error) {
        message?.error(getErrorMessage(error));
      } finally {
        setPendingAction(null);
      }
    },
    [message, params, t]
  );

  const handleSaveSelection = useCallback(async () => {
    if (params.selection?.kind === 'agent' && params.selectedAgent) {
      setPendingAction('save-agent');
      try {
        const updatePayload: Parameters<typeof params.updateAgentBinding>[4] = {
          theme_color: colorDraft,
        };
        const nextLabel = labelDraft.trim();
        if (nextLabel.length > 0) {
          updatePayload.label = nextLabel;
        }
        await params.updateAgentBinding(
          params.tenantId,
          params.projectId,
          params.workspaceId,
          params.selectedAgent.id,
          updatePayload
        );
        message?.success(
          t('blackboard.arrangement.messages.agentUpdated', 'Agent styling updated.')
        );
      } catch (error) {
        message?.error(getErrorMessage(error));
      } finally {
        setPendingAction(null);
      }
      return;
    }

    if (params.selection?.kind === 'node' && params.selectedNode) {
      setPendingAction('save-node');
      try {
        const nextData =
          params.selectedNode.node_type === 'human_seat'
            ? { ...params.selectedNode.data, color: colorDraft }
            : params.selectedNode.data;
        await params.updateTopologyNode(params.workspaceId, params.selectedNode.id, {
          title: labelDraft.trim() || params.selectedNode.title,
          data: nextData,
        });
        message?.success(t('blackboard.arrangement.messages.nodeUpdated', 'Seat details updated.'));
      } catch (error) {
        message?.error(getErrorMessage(error));
      } finally {
        setPendingAction(null);
      }
    }
  }, [colorDraft, labelDraft, message, params, t]);

  const handleDeleteSelection = useCallback(async () => {
    if (params.selection?.kind === 'agent' && params.selectedAgent) {
      const confirmed = await confirmAction({
        title: t('blackboard.arrangement.confirm.removeAgentTitle', 'Remove this agent?'),
        content: t(
          'blackboard.arrangement.confirm.removeAgentContent',
          'The agent will be unbound from this workstation.'
        ),
        okText: t('common.delete', 'Delete'),
        cancelText: t('common.cancel', 'Cancel'),
        danger: true,
      });
      if (!confirmed) {
        return;
      }

      setPendingAction('delete-agent');
      try {
        await params.unbindAgent(
          params.tenantId,
          params.projectId,
          params.workspaceId,
          params.selectedAgent.id
        );
        params.setSelection(null);
        params.setMoveMode(null);
        message?.success(
          t('blackboard.arrangement.messages.agentRemoved', 'Agent removed from the workstation.')
        );
      } catch (error) {
        message?.error(getErrorMessage(error));
      } finally {
        setPendingAction(null);
      }
      return;
    }

    if (params.selection?.kind === 'node' && params.selectedNode) {
      const confirmed = await confirmAction({
        title: t('blackboard.arrangement.confirm.removeNodeTitle', 'Remove this seat?'),
        content: t(
          'blackboard.arrangement.confirm.removeNodeContent',
          'This node will be permanently removed from the topology.'
        ),
        okText: t('common.delete', 'Delete'),
        cancelText: t('common.cancel', 'Cancel'),
        danger: true,
      });
      if (!confirmed) {
        return;
      }

      setPendingAction('delete-node');
      try {
        await params.deleteTopologyNode(params.workspaceId, params.selectedNode.id);
        params.setSelection(null);
        params.setMoveMode(null);
        message?.success(
          t('blackboard.arrangement.messages.nodeRemoved', 'Seat removed from the workstation.')
        );
      } catch (error) {
        message?.error(getErrorMessage(error));
      } finally {
        setPendingAction(null);
      }
    }
  }, [message, params, t]);

  const beginMoveMode = useCallback(() => {
    if (params.selection?.kind === 'agent') {
      params.setMoveMode({ kind: 'agent', agentId: params.selection.agentId });
      return;
    }
    if (params.selection?.kind === 'node') {
      params.setMoveMode({ kind: 'node', nodeId: params.selection.nodeId });
    }
  }, [params]);

  return {
    pendingAction,
    labelDraft,
    colorDraft,
    addAgentOpen,
    setLabelDraft,
    setColorDraft,
    setAddAgentOpen,
    handleMoveSelection,
    handleActivateHex,
    handleCreateNode,
    handleAddAgent,
    handleSaveSelection,
    handleDeleteSelection,
    beginMoveMode,
  };
}
