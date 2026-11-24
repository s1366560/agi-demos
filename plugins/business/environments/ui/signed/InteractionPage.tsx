import { useCallback, useEffect, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { Theme } from '@radix-ui/themes';
import { createInstance } from 'i18next';
import { I18nextProvider, useTranslation } from 'react-i18next';
import type { RichPageContext } from '../../../../../sdk/memstack-plugin-sdk/src/pageRuntime';
import { RemoteDesktopSurface } from '../desktop/sandbox/RemoteDesktopSurface';
import { InteractiveTerminal } from '../desktop/sandbox/InteractiveTerminal';
import type { RemoteDesktopResolution } from '../desktop/sandbox/sandboxRuntimeSurfaceClient';
import { KasmVNCViewer } from '../web/components/sandbox/KasmVNCViewer';
import { SandboxTerminal } from '../web/components/sandbox/SandboxTerminal';
import { SandboxChannel } from './channel';
import { DesktopLocale } from './desktopI18n';
import en from '../web/locales/en-US.json';
import zh from '../web/locales/zh-CN.json';
import './interaction.css';

type TerminalSocket = () => WebSocket;

function NativeTerminal({ terminalSocket }: { terminalSocket: TerminalSocket }) {
  const { t } = useTranslation();
  const channel = useRef<WebSocket>(null);
  const [connected, setConnected] = useState(false);
  const [error, setError] = useState(false);
  const [output, setOutput] = useState<string[]>([]);
  const size = useRef({ cols: 80, rows: 24 });
  useEffect(() => {
    const socket = terminalSocket();
    channel.current = socket;
    socket.onmessage = (event) => {
      const packet = JSON.parse(event.data);
      if (packet.type === 'connected') {
        setConnected(true);
        socket.send(JSON.stringify({ type: 'resize', ...size.current }));
      } else if (packet.type === 'output') {
        setOutput((chunks) => [...chunks.slice(-512), packet.data]);
      } else if (packet.type === 'error') setError(true);
    };
    socket.onerror = () => setError(true);
    socket.onclose = () => setConnected(false);
    return () => {
      socket.onclose = null;
      socket.close();
    };
  }, [terminalSocket]);
  return (
    <>
      {error && <p role="alert">{t('components.sandboxTerminal.connectionError')}</p>}
      <InteractiveTerminal
        ariaLabel={t('project.settings.terminalLabel')}
        connected={connected}
        outputChunks={output}
        onInput={(data) => channel.current?.send(JSON.stringify({ type: 'input', data }))}
        onResize={(cols, rows) => {
          size.current = { cols, rows };
          if (connected) channel.current?.send(JSON.stringify({ type: 'resize', cols, rows }));
        }}
      />
    </>
  );
}

function Interaction({ ctx, sandbox }: { ctx: RichPageContext; sandbox: string }) {
  const { t } = useTranslation();
  const [tab, setTab] = useState<'terminal' | 'desktop'>('terminal');
  const [resolution, setResolution] = useState<RemoteDesktopResolution>('1280x720');
  const [revision, setRevision] = useState(0);
  const [state, setState] = useState<'loading' | 'ready' | 'error'>('loading');
  const desktop = ctx.target === 'desktop-renderer';
  const terminalSocket = useCallback(() => {
    const query = new URLSearchParams(ctx.search);
    const runId = query.get('run_id');
    const run =
      runId !== null
        ? { run_id: runId, expected_run_revision: Number(query.get('revision')) }
        : undefined;
    return new SandboxChannel('project-terminal', undefined, run) as unknown as WebSocket;
  }, [ctx.search]);
  const start = useCallback(async (value?: RemoteDesktopResolution) => {
    if (value) setResolution(value);
    setState('loading');
    setRevision((v) => v + 1);
  }, []);
  const stop = useCallback(async () => {
    setRevision(0);
  }, []);
  const openDesktop = useCallback(
    () => new SandboxChannel('project-desktop', resolution) as unknown as WebSocket,
    [resolution]
  );
  const viewer = (
    <KasmVNCViewer
      key={revision}
      projectId={ctx.projectId!}
      sandboxId={sandbox}
      wsUrl="signed:project-desktop"
      openSocket={openDesktop}
      resolution={resolution}
      showToolbar={!desktop}
      onConnect={() => setState('ready')}
      onError={() => setState('error')}
    />
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
        desktop ? (
          <NativeTerminal terminalSocket={terminalSocket} />
        ) : (
          <SandboxTerminal
            sandboxId={sandbox}
            projectId={ctx.projectId!}
            openSocket={terminalSocket}
            height="100%"
          />
        )
      ) : desktop ? (
        <RemoteDesktopSurface
          capability={{ availability: 'available', contract_version: 1, reason_code: null }}
          session={null}
          sessionRevision={revision}
          viewer={revision ? { state, content: viewer } : undefined}
          status={
            revision
              ? state === 'error'
                ? 'error'
                : state === 'ready'
                  ? 'ready'
                  : 'starting'
              : 'idle'
          }
          reasonCode={null}
          resolution={resolution}
          onResolutionChange={setResolution}
          onStart={start}
          onReconnect={start}
          onStop={stop}
        />
      ) : (
        viewer
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
        <DesktopLocale.Provider value={ctx.locale}>
          <Theme>
            <Interaction ctx={ctx} sandbox={sandbox.sandbox_id} />
          </Theme>
        </DesktopLocale.Provider>
      </I18nextProvider>
    );
  } catch (error) {
    root.render(<p role="alert">{error instanceof Error ? error.message : String(error)}</p>);
  }
}
void mount();
