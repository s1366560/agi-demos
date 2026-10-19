import {
  createContext,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from 'react';
import {
  createComputerUseClientV2,
  isComputerUseSnapshotForScope,
  type ComputerUseClientV2,
  type ComputerUseOperation,
  type ComputerUseSnapshot,
} from '../../api/computerUseClientV2';
import type { DesktopRuntimeConfig } from '../../types';
import { useI18n } from '../../i18n';
import { ComputerUseAppIdentity, ComputerUseTargetPreview } from './ComputerUseTargetPreview';
import { computerUsePhaseLabel, computerUseSessionView } from './computerUsePresentationModel';
import { createComputerUseManagement } from './computerUseManagement';
import { ComputerUseRecordings } from './ComputerUseRecordings';
import { computerUseRecordingIsPending } from '../../api/computerUseRecording';
import './ComputerUseSettingsPage.css';

type DeviceContext = {
  mode: DesktopRuntimeConfig['mode'];
  client: ComputerUseClientV2 | null;
  snapshot: ComputerUseSnapshot | null;
  busy: boolean;
  stopping: boolean;
  error: string | null;
  manage: (operation: ComputerUseOperation) => Promise<void>;
};
const DeviceContext = createContext<DeviceContext>({
  mode: 'local',
  client: null,
  snapshot: null,
  busy: false,
  stopping: false,
  error: null,
  manage: async () => {},
});
export const useComputerUseDevice = () => useContext(DeviceContext);

export function ComputerUseDeviceProvider({
  config,
  children,
}: {
  config: DesktopRuntimeConfig;
  children: ReactNode;
}) {
  const client = useMemo(
    () => createComputerUseClientV2(config),
    [config.mode, config.apiKey, config.tenantId, config.projectId]
  );
  const [state, setState] = useState<{
    client: ComputerUseClientV2;
    snapshot: ComputerUseSnapshot | null;
    error: string | null;
  }>({ client, snapshot: null, error: null });
  const [busy, setBusy] = useState(false);
  const [stopping, setStopping] = useState(false);
  const activeClient = useRef(client);
  activeClient.current = client;
  const management = useMemo(
    () =>
      createComputerUseManagement({
        run: (operation, signal) => client.manage(operation, signal),
        changed: (nextBusy, nextStopping) => {
          if (activeClient.current !== client) return;
          setBusy(nextBusy);
          setStopping(nextStopping);
        },
        completed: (snapshot) => {
          if (activeClient.current === client) setState({ client, snapshot, error: null });
        },
        failed: (error) => {
          if (activeClient.current === client) setState((current) => ({ ...current, error }));
        },
      }),
    [client]
  );
  useEffect(() => {
    setBusy(false);
    setStopping(false);
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout> | undefined;
    const refresh = async () => {
      const generation = management.generation();
      let delay = 30000;
      try {
        const snapshot = await client.snapshot(controller.signal);
        if (
          snapshot.sessions.length ||
          snapshot.pending.length ||
          snapshot.recordings?.some(computerUseRecordingIsPending) ||
          snapshot.accounts?.some((account) => account.status === 'authorizing')
        )
          delay = 5000;
        if (!controller.signal.aborted && management.acceptsRefresh(generation))
          setState({ client, snapshot, error: null });
      } catch (error) {
        if (!controller.signal.aborted && management.acceptsRefresh(generation))
          setState({
            client,
            snapshot: null,
            error: error instanceof Error ? error.message : 'cua_operation_failed',
          });
      }
      if (!controller.signal.aborted) timer = setTimeout(() => void refresh(), delay);
    };
    void refresh();
    const unsubscribe = window.__MEMSTACK_DESKTOP__?.events?.onComputerUseActivity?.((value) => {
      const event = value as { mode?: unknown; snapshot?: unknown };
      if (
        !controller.signal.aborted &&
        activeClient.current === client &&
        event?.mode === config.mode &&
        isComputerUseSnapshotForScope(event.snapshot, {
          tenantId: config.tenantId,
          projectId: config.projectId,
        })
      )
        setState({ client, snapshot: event.snapshot, error: null });
    });
    return () => {
      unsubscribe?.();
      controller.abort();
      management.dispose();
      if (timer) clearTimeout(timer);
    };
  }, [client, management]);
  return (
    <DeviceContext.Provider
      value={{
        mode: config.mode,
        client,
        snapshot: state.client === client ? state.snapshot : null,
        error: state.client === client ? state.error : null,
        busy,
        stopping,
        manage: management.manage,
      }}
    >
      {children}
    </DeviceContext.Provider>
  );
}

export function ComputerUseActivity({ conversationId, runId }: {
  conversationId: string | null;
  runId: string | null;
}) {
  const { t } = useI18n();
  const { snapshot, manage, busy, stopping, error, client } = useComputerUseDevice();
  const sessions = (snapshot?.sessions ?? []).filter((session) =>
    conversationId && runId && session.conversation_id === conversationId && session.run_id === runId);
  const pending = (snapshot?.pending ?? []).filter((request) =>
    sessions.some((session) => session.session_id === request.session_id));
  const recordings = (snapshot?.recordings ?? []).filter((recording) =>
    conversationId && recording.conversation_id === conversationId &&
    (runId ? recording.run_id === runId : !computerUseRecordingIsPending(recording)));
  if (!sessions.length && !pending.length && !recordings.length) return null;
  return (
    <aside className="computer-use-activity" aria-live="polite">
      <strong>{t('cua.title')}</strong>
      {error ? (
        <p role="alert">
          {t('cua.error')} <code>{error}</code>
        </p>
      ) : null}
      <ComputerUseRecordings recordings={recordings} client={client}
        manage={manage} stopping={stopping} />
      {sessions.map((session) => {
        const view = computerUseSessionView(snapshot!, session);
        return (
          <section key={session.session_id} className="computer-use-session-activity">
            <span className="computer-use-phase">{t(computerUsePhaseLabel(view.phase))}</span>
            {view.target ? <ComputerUseTargetPreview presentation={view} client={client} /> : null}
            <div className="computer-use-actions">
              {view.phase === 'paused' && view.can_resume ? (
                <button
                  type="button"
                  disabled={busy}
                  onClick={() =>
                    void manage({
                      action: 'resume',
                      session_id: session.session_id,
                    })
                  }
                >
                  {t('cua.resume')}
                </button>
              ) : null}
              {view.phase === 'paused' && !view.can_resume ? (
                <span>
                  {t('cua.resumeUnavailable')} <code>{view.resume_blocked_reason}</code>
                </span>
              ) : null}
              {!['paused', 'stopped'].includes(view.phase) ? (
                <button
                  type="button"
                  disabled={busy}
                  onClick={() =>
                    void manage({
                      action: 'pause',
                      session_id: session.session_id,
                    })
                  }
                >
                  {t('cua.pause')}
                </button>
              ) : null}
              {!session.stopped ? (
                <button
                  type="button"
                  disabled={stopping}
                  onClick={() =>
                    void manage({
                      action: 'stop',
                      session_id: session.session_id,
                    })
                  }
                >
                  {t('cua.stop')}
                </button>
              ) : null}
            </div>
          </section>
        );
      })}
      {pending.map((request) => (
        <div key={request.request_id}>
          <ComputerUseAppIdentity
            target={request.target}
            icon={request.app_icon}
            client={client}
            fallback={request.app}
          />
          <span>{t(`cua.capability.${request.capability}`)}</span>
          <span>{t('cua.waitingConsent')}</span>
        </div>
      ))}
    </aside>
  );
}
