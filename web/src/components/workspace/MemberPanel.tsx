import { useCallback, useState } from 'react';
import type { FC } from 'react';

import { PlusOutlined, DeleteOutlined } from '@ant-design/icons';
import { Button, Popconfirm, message } from 'antd';

import {
  useWorkspaceAgents,
  useWorkspaceMembers,
  useWorkspaceActions,
} from '@/stores/workspace';

import { AddAgentModal } from './AddAgentModal';


export interface MemberPanelProps {
  tenantId: string;
  projectId: string;
  workspaceId: string;
}

export const MemberPanel: FC<MemberPanelProps> = ({ tenantId, projectId, workspaceId }) => {
  const members = useWorkspaceMembers();
  const agents = useWorkspaceAgents();
  const { bindAgent, unbindAgent } = useWorkspaceActions();

  const [showAddAgent, setShowAddAgent] = useState(false);

  const handleAddAgent = useCallback(
    async (data: { agent_id: string; display_name?: string; description?: string }) => {
      await bindAgent(tenantId, projectId, workspaceId, data);
    },
    [bindAgent, tenantId, projectId, workspaceId]
  );

  const handleRemoveAgent = useCallback(
    async (workspaceAgentId: string) => {
      try {
        await unbindAgent(tenantId, projectId, workspaceId, workspaceAgentId);
        message.success('Agent removed');
      } catch {
        message.error('Failed to remove agent');
      }
    },
    [unbindAgent, tenantId, projectId, workspaceId]
  );

  return (
    <section className="rounded-lg border border-slate-200 p-4 bg-white">
      <h3 className="font-semibold text-slate-900 mb-3">Members & Agents</h3>
      <div className="grid grid-cols-2 gap-3">
        <div>
          <h4 className="text-sm font-medium mb-2">Members ({members.length})</h4>
          <ul className="space-y-1">
            {members.map((member) => (
              <li key={member.id} className="text-sm border rounded px-2 py-1">
                {member.user_email ?? member.user_id} · {member.role}
              </li>
            ))}
          </ul>
        </div>
        <div>
          <div className="flex items-center justify-between mb-2">
            <h4 className="text-sm font-medium">Agents ({agents.length})</h4>
            <Button
              type="text"
              size="small"
              icon={<PlusOutlined />}
              onClick={() => { setShowAddAgent(true); }}
            >
              Add
            </Button>
          </div>
          <ul className="space-y-1">
            {agents.map((agent) => (
              <li
                key={agent.id}
                className="text-sm border rounded px-2 py-1 flex items-center justify-between group"
              >
                <span>{agent.display_name || agent.agent_id}</span>
                <Popconfirm
                  title="Remove this agent?"
                  onConfirm={() => { void handleRemoveAgent(agent.id); }}
                  okText="Remove"
                  cancelText="Cancel"
                >
                  <Button
                    type="text"
                    size="small"
                    danger
                    icon={<DeleteOutlined />}
                    className="opacity-0 group-hover:opacity-100 transition-opacity"
                  />
                </Popconfirm>
              </li>
            ))}
          </ul>
        </div>
      </div>

      <AddAgentModal
        open={showAddAgent}
        onClose={() => { setShowAddAgent(false); }}
        onSubmit={handleAddAgent}
      />
    </section>
  );
};

