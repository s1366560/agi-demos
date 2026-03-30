import { useCallback, useState } from 'react';
import type { FC } from 'react';

import { useTranslation } from 'react-i18next';

import { Button } from 'antd';
import { Plus, Trash2 } from 'lucide-react';

import {
  useWorkspaceAgents,
  useWorkspaceMembers,
  useWorkspaceActions,
} from '@/stores/workspace';

import { LazyPopconfirm, useLazyMessage } from '@/components/ui/lazyAntd';

import { AddAgentModal } from './AddAgentModal';


export interface MemberPanelProps {
  tenantId: string;
  projectId: string;
  workspaceId: string;
}

export const MemberPanel: FC<MemberPanelProps> = ({ tenantId, projectId, workspaceId }) => {
  const { t } = useTranslation();
  const message = useLazyMessage();
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
        message?.success(t('workspaceDetail.members.agentRemoved'));
      } catch {
        message?.error(t('workspaceDetail.members.removeAgentFailed'));
      }
    },
    [unbindAgent, tenantId, projectId, workspaceId, message, t]
  );

  return (
    <section className="rounded-lg border border-slate-200 dark:border-slate-700 p-4 bg-white dark:bg-slate-800 transition-colors duration-200">
      <h3 className="font-semibold text-slate-900 dark:text-white mb-3">{t('workspaceDetail.members.title')}</h3>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        <div>
          <h4 className="text-sm font-medium mb-2">{t('workspaceDetail.members.membersLabel')} ({members.length})</h4>
          <ul className="space-y-1">
            {members.map((member) => (
              <li key={member.id} className="text-sm border dark:border-slate-700 rounded px-2 py-1">
                {member.user_email ?? member.user_id} · {member.role}
              </li>
            ))}
          </ul>
        </div>
        <div>
          <div className="flex items-center justify-between mb-2">
            <h4 className="text-sm font-medium">{t('workspaceDetail.members.agentsLabel')} ({agents.length})</h4>
            <Button
              type="text"
              size="small"
              icon={<Plus size={16} />}
              onClick={() => { setShowAddAgent(true); }}
            >
              {t('workspaceDetail.members.add')}
            </Button>
          </div>
          <ul className="space-y-1">
            {agents.map((agent) => (
              <li
                key={agent.id}
                className="text-sm border dark:border-slate-700 rounded px-2 py-1 flex items-center justify-between group"
              >
                <span>{agent.display_name || agent.agent_id}</span>
                <LazyPopconfirm
                  title={t('workspaceDetail.members.removeAgentConfirm')}
                  onConfirm={() => { void handleRemoveAgent(agent.id); }}
                  okText={t('workspaceDetail.members.remove')}
                  cancelText={t('workspaceDetail.members.cancel')}
                >
                  <Button
                    type="text"
                    size="small"
                    danger
                    icon={<Trash2 size={16} />}
                    className="opacity-0 group-hover:opacity-100 transition-opacity"
                  />
                </LazyPopconfirm>
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

