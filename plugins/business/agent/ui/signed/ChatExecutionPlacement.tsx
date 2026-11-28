import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { WebComposerExecutionPlacement } from '../../../../../web/src/components/execution-target/WebComposerExecutionPlacement';
import {
  publicDirectoryLabel,
  webComposerPlacement,
} from '../../../../../web/src/components/execution-target/webExecutionPlacement';
import type { Chat } from './useChat';

export function ChatExecutionPlacement({ chat }: { chat: Chat }) {
  const { t } = useTranslation();
  const { selectedRow, target, hasDevice, local } = chat;
  const selected = selectedRow?.execution_target ?? target;
  const [directory, setDirectory] = useState<string | null>(null);
  const [error, setError] = useState('');
  const [revision, setRevision] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    setDirectory(null);
    setError('');
    if (local && selected === 'local' && hasDevice) {
      void window.memstack
        .device('local_chat', { action: 'placement' }, { signal: controller.signal })
        .then((result) => {
          const label = (result as { local_root_label?: string })?.local_root_label;
          if (!controller.signal.aborted) setDirectory(publicDirectoryLabel(label));
        })
        .catch((cause) => {
          if (!controller.signal.aborted)
            setError(String(cause instanceof Error ? cause.message : cause));
        });
    }
    return () => controller.abort();
  }, [local, selected, hasDevice, revision]);

  if (!local)
    return (
      <WebComposerExecutionPlacement
        placement={webComposerPlacement(selectedRow && { ...selectedRow, status: 'active' })}
      />
    );
  const cloud = t('agent.executionTarget.cloud', 'Cloud');
  const device = t('agent.executionTarget.local', 'This computer');
  return (
    <div
      className="mb-2 flex min-w-0 flex-wrap items-center gap-2 text-xs [overflow-wrap:anywhere]"
      data-surface="desktop"
      role="group"
      aria-label={t('agent.executionPlacement.targetLabel', 'Execution location')}
    >
      <select
        className="h-7 rounded-full bg-slate-100 px-3 dark:bg-slate-800"
        aria-label={t('agent.executionPlacement.targetLabel', 'Execution location')}
        value={selected}
        disabled={!!selectedRow || chat.busy}
        onChange={(event) =>
          chat.setTarget(event.currentTarget.value === 'cloud' ? 'cloud' : 'local')
        }
      >
        <option value="cloud">{cloud}</option>
        <option value="local">{device}</option>
      </select>
      <span data-execution-resource={selected === 'cloud' ? 'default-environment' : 'directory'}>
        {selected === 'cloud'
          ? t('agent.executionTarget.defaultEnvironment', 'Default environment')
          : (directory ??
            publicDirectoryLabel(selectedRow?.local_root_label) ??
            t('agent.executionPlacement.directoryUnavailable', 'This directory is unavailable'))}
      </span>
      {selected === 'local' && window.memstack.reviewDevice && (
        <button
          type="button"
          className="rounded-full px-2 underline"
          onClick={() =>
            void window.memstack.reviewDevice!()
              .then(() => setRevision((n) => n + 1))
              .catch((cause) => setError(String(cause)))
          }
        >
          {t('agent.executionPlacement.reviewDevice', 'Device settings')}
        </button>
      )}
      {selected === 'local' && (!hasDevice || error) && (
        <span role="status">
          {t(
            'agent.executionPlacement.deviceApproval',
            'Choose a directory and approve this release in device settings.',
          )}
          {error && ' · ' + error}
        </span>
      )}
    </div>
  );
}
