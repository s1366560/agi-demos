import React, { useState } from 'react';
import { useParams, useSearchParams } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
export function RosterControls({ conversationId }: { conversationId: string }) {
  const { tenantId } = useParams();
  const [search] = useSearchParams();
  const { t } = useTranslation();
  const [unavailable, setUnavailable] = useState(false);
  return (
    <>
      <button
        type="button"
        onClick={async () => {
          try {
            const query = new URLSearchParams();
            const workspace = search.get('workspaceId');
            if (workspace) query.set('workspaceId', workspace);
            const path =
              '/tenant/' +
              encodeURIComponent(tenantId!) +
              '/agent-workspace/' +
              encodeURIComponent(conversationId);
            await window.memstack.openPage(
              'memstack-agent',
              'chat',
              path + (query.size ? '?' + query : '')
            );
          } catch {
            setUnavailable(true);
          }
        }}
      >
        {t('blackboard.openInAgentWorkspace', 'Open in Agent Workspace')}
      </button>
      {unavailable && (
        <p role="alert">
          {t('blackboard.agentPageUnavailable', 'The Agent page is unavailable in this project.')}
        </p>
      )}
    </>
  );
}
