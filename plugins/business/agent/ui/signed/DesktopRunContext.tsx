import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { SessionContextRail } from '../desktop/chat/SessionContextRail';
import { I18nProvider } from '../../../../../agi-stack/apps/desktop/src/i18n';
import type { RunProjection } from './SelectedRunReview';

function duration(run: RunProjection) {
  const elapsed = Date.parse(run.completed_at || run.updated_at) - Date.parse(run.started_at || '');
  if (!Number.isFinite(elapsed) || elapsed < 0) return null;
  const seconds = Math.floor(elapsed / 1000);
  return [Math.floor(seconds / 3600), Math.floor(seconds / 60) % 60, seconds % 60]
    .map((part) => String(part).padStart(2, '0'))
    .join(':');
}
export function DesktopRunContext({ run }: { run: RunProjection }) {
  const [open, setOpen] = useState(false);
  const { i18n } = useTranslation();
  const zh = i18n.language.startsWith('zh');
  const title = zh ? '运行上下文' : 'Run context';
  return (
    <>
      <button type="button" aria-expanded={open} onClick={() => setOpen(!open)}>
        {title}
      </button>
      {open && (
        <I18nProvider>
          <SessionContextRail
            viewModel={{
              status: run.status,
              stage: 'unavailable',
              environmentLabel:
                run.local_root_label ||
                run.execution_environment_id ||
                run.execution_target ||
                null,
              elapsedLabel: duration(run),
              executionMode: 'unavailable',
              permissionLabel: run.permission_profile || null,
              observedToolActivityCount: null,
              observedFailedToolActivityCount: null,
              error: run.error || null,
            }}
          />
        </I18nProvider>
      )}
    </>
  );
}
