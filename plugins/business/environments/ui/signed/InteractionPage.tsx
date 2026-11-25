import { useCallback, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { Theme } from '@radix-ui/themes';
import { createInstance } from 'i18next';
import { I18nextProvider, useTranslation } from 'react-i18next';
import type { RichPageContext } from '../../../../../sdk/memstack-plugin-sdk/src/pageRuntime';
import { KasmVNCViewer } from '../web/components/sandbox/KasmVNCViewer';
import { SandboxTerminal } from '../web/components/sandbox/SandboxTerminal';
import { SandboxChannel } from './channel';
import en from '../web/locales/en-US.json';
import zh from '../web/locales/zh-CN.json';
import './interaction.css';

function Interaction({ ctx, sandbox }: { ctx: RichPageContext; sandbox: string }) {
  const { t } = useTranslation();
  const [tab, setTab] = useState<'terminal' | 'desktop'>('terminal');
  const [resolution, setResolution] = useState('1280x720');
  const terminalSocket = useCallback(() => {
    const query = new URLSearchParams(ctx.search);
    const runId = query.get('run_id');
    const run =
      runId !== null
        ? { run_id: runId, expected_run_revision: Number(query.get('revision')) }
        : undefined;
    return new SandboxChannel('project-terminal', undefined, run) as unknown as WebSocket;
  }, [ctx.search]);
  const openDesktop = useCallback(
    () => new SandboxChannel('project-desktop', resolution) as unknown as WebSocket,
    [resolution]
  );
  return (
    <main className="sandbox-interaction">
      <nav aria-label={t('project.settings.sandboxConnect')}>
        {(['terminal', 'desktop'] as const).map((key) => (
          <button key={key} type="button" aria-pressed={tab === key} onClick={() => setTab(key)}>
            {t('project.settings.' + key + 'Label')}
          </button>
        ))}
      </nav>
      {tab === 'terminal' ? (
        <SandboxTerminal
          sandboxId={sandbox}
          projectId={ctx.projectId!}
          openSocket={terminalSocket}
          height="100%"
        />
      ) : (
        <KasmVNCViewer
          projectId={ctx.projectId!}
          sandboxId={sandbox}
          wsUrl="signed:project-desktop"
          openSocket={openDesktop}
          resolution={resolution}
          onResolutionChange={setResolution}
        />
      )}
    </main>
  );
}

async function mount() {
  const ctx = await window.memstack.getContext();
  const i18n = createInstance();
  await i18n.init({
    lng: ctx.locale.startsWith('zh') ? 'zh' : 'en',
    resources: { en: { translation: en }, zh: { translation: zh } },
    interpolation: { escapeValue: false },
  });
  const root = createRoot(document.getElementById('root')!);
  try {
    const { sandbox } = (await window.memstack.invoke('sandbox-status')) as {
      sandbox: { sandbox_id: string } | null;
    };
    if (!sandbox) throw Error(i18n.t('project.settings.sandboxNotProvisioned'));
    root.render(
      <I18nextProvider i18n={i18n}>
        <Theme>
          <Interaction ctx={ctx} sandbox={sandbox.sandbox_id} />
        </Theme>
      </I18nextProvider>
    );
  } catch (error) {
    root.render(<p role="alert">{error instanceof Error ? error.message : String(error)}</p>);
  }
}
void mount();
