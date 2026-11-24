import React, { useState } from 'react';
import { useTranslation } from 'react-i18next';
export function RosterControls() {
  const { t } = useTranslation();
  const [unavailable, setUnavailable] = useState(false);
  return (
    <>
      <button
        type="button"
        onClick={async () => {
          try {
            await window.memstack.openPage('memstack-agent', 'chat');
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
